"""Signed, synthetic calendar-file upload, recovery, review and source revocation."""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import NoReturn
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session
from tests.integration.test_handoff_review import isolate_http_request, request_sessions
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace

from cosmas_os.api import app as api_module
from cosmas_os.application import calendar_imports as imports
from cosmas_os.application import model_work, provider_team
from cosmas_os.application import workspace as ws
from cosmas_os.calendar_import_models import CalendarImportRequest, CalendarImportSourceReview
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import AppointmentObservation, ExternalIdentity, WorkspaceEntry

signed_workspace = _signed_workspace


def synthetic_ics(*, day=None, cancelled=False, title="Invented calendar visit", extra=""):
    day = day or datetime.now(UTC).date()
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:invented-file\r\n"
            "BEGIN:VEVENT\r\nUID:invented-calendar-event\r\n"
            f"DTSTART:{day:%Y%m%d}T130000Z\r\nDTEND:{day:%Y%m%d}T133000Z\r\n"
            f"SUMMARY:{title}\r\nSTATUS:{'CANCELLED' if cancelled else 'CONFIRMED'}\r\n"
            f"{extra}END:VEVENT\r\nEND:VCALENDAR\r\n").encode()


@pytest.fixture
def calendar_import_case(signed_workspace, session, monkeypatch):
    """Compact signed API fixture reusable by the parent's actual-UI bridge."""
    f = signed_workspace
    monkeypatch.setattr(f.configuration, "workspace_calendar_import_enabled", True)
    monkeypatch.setattr(provider_team, "runtime_settings", f.configuration)
    fresh = request_sessions(session)
    result = SimpleNamespace(client=f.client, token=f.token, workspace=f.workspace,
        box=f.box, owner=f.actor, actor=f.actor, account=f.binding.id, binding=f.binding,
        configuration=f.configuration, appointment=f.appointment, s=session, request_session=None)
    result.headers = lambda: {"Authorization": "Bearer " + f.token(), "X-Cosmas-Calendar-Import": "1"}
    result.ics = synthetic_ics
    result.starts_on = datetime.now(UTC).date()
    result.window = dict(starts_on=result.starts_on.isoformat(),
                         ends_on=(result.starts_on + timedelta(days=7)).isoformat(), timezone="UTC")

    def request_session():
        for owned in fresh():
            result.request_session = owned
            try:
                yield owned
            finally:
                result.request_session = None

    overrides = api_module.app.dependency_overrides
    previous = overrides[api_module.get_session]
    overrides[api_module.get_session] = request_session
    monkeypatch.setattr(f.client, "request", isolate_http_request(f.client, session))
    try:
        yield result
    finally:
        overrides[api_module.get_session] = previous


def upload_body(f, *, key="calendar-upload-1", raw=None, **changes):
    raw = raw if raw is not None else f.ics(day=f.starts_on)
    return dict(action="upload", idempotency_key=key, byte_sha256=hashlib.sha256(raw).hexdigest(),
                file_base64=base64.b64encode(raw).decode(), window=f.window,
                reported_source="atlas_md", **changes)


def action(f, body, *, wid=None):
    return f.client.post(f"/workspaces/{wid or f.workspace['id']}/calendar-imports", headers=f.headers(), json=body)


def uploaded(f, **kwargs):
    response = action(f, upload_body(f, **kwargs))
    assert response.status_code == 200, response.text
    return response.json()


def review_body(f, receipt, *, key="calendar-review-1", expected=None) -> dict[str, str | int | bool]:
    item = receipt["payload"]["items"][0]
    return dict(expected_revision=expected or f.workspace["revision"], idempotency_key=key,
        import_id=receipt["import_id"], source_sha256=receipt["source_sha256"], item_index=item["item_index"],
        item_sha256=imports.item_hash(item), reviewed_visit=True, reviewed_exact_summary=True, reviewed_untrusted_source=True)


def review(f, body):
    return f.client.post(f"/workspaces/{f.workspace['id']}/calendar-imports/review", headers=f.headers(), json=body)


def test_signed_upload_review_recovery_and_revoke(calendar_import_case):
    f = calendar_import_case
    status = action(f, {"action": "status"})
    assert status.status_code == 200 and status.json()["status"] == "available"
    receipt = uploaded(f)
    assert receipt["scope"] == status.json()["scope"]
    assert receipt["payload_sha256"] == payload_hash(receipt["payload"])
    assert receipt["payload"]["reported_source"] == "atlas_md"
    assert receipt["payload"]["coverage"] == "file_window_only"
    assert action(f, {"action": "inspect", "import_id": receipt["import_id"]}).json() == receipt
    assert action(f, {"action": "resolve", "idempotency_key": "calendar-upload-1"}).json() == receipt
    assert uploaded(f) == receipt
    saved = review(f, review_body(f, receipt))
    assert saved.status_code == 200, saved.text
    data = saved.json()
    entry = next(row for row in data["workspace"]["entries"] if row["id"] == data["entry_id"])
    assert entry["kind"] == "calendar_import_source" and entry["calendar_import_source_state"] == "current"
    assert entry["content"] == imports.source_content(receipt["payload"], receipt["payload"]["items"][0])
    assert "Source reported by user: Atlas.md" in entry["content"]
    assert review(f, review_body(f, receipt)).json()["entry_id"] == data["entry_id"]
    revoke = dict(action="revoke", expected_revision=data["workspace"]["revision"], idempotency_key="calendar-revoke-1",
                  import_id=receipt["import_id"], source_sha256=receipt["source_sha256"])
    removed = action(f, revoke)
    assert removed.status_code == 200, removed.text
    assert removed.json()["status"] == "revoked"
    assert action(f, revoke).json()["request_sha256"] == removed.json()["request_sha256"]
    withheld = action(f, {"action": "resolve", "idempotency_key": "calendar-upload-1"}).json()
    assert withheld["status"] == "withheld" and "payload" not in withheld and "payload_sha256" not in withheld
    replay = review(f, review_body(f, receipt)).json()
    assert replay["source_withheld"]
    source = next(row for row in replay["workspace"]["entries"] if row["id"] == data["entry_id"])
    assert source["content"] == "" and source["source_label"] == "Unavailable calendar import"
    assert f.s.scalar(select(func.count()).select_from(CalendarImportRequest)) == 1
    assert f.s.scalar(select(func.count()).select_from(CalendarImportSourceReview)) == 1


def test_resolve_and_exact_upload_replay_never_reparse(calendar_import_case, monkeypatch):
    f = calendar_import_case
    receipt = uploaded(f)

    def fail(*args, **kwargs) -> NoReturn:
        pytest.fail("Read-only recovery reparsed the file")

    monkeypatch.setattr(imports, "parse_calendar_file", fail)
    for body in ({"action": "status"}, {"action": "inspect", "import_id": receipt["import_id"]},
                 {"action": "resolve", "idempotency_key": "calendar-upload-1"}, upload_body(f)):
        assert action(f, body).status_code == 200


def test_bad_file_can_be_resolved_absent_then_corrected_explicitly(calendar_import_case):
    f = calendar_import_case
    failed = action(f, upload_body(f, raw=f.ics(extra="RRULE:FREQ=DAILY\r\n")))
    assert failed.status_code == 422 and failed.json()["detail"] == "calendar_recurrence_unsupported"
    assert action(f, {"action": "resolve", "idempotency_key": "calendar-upload-1"}).json()["status"] == "not_found"
    assert uploaded(f, key="calendar-corrected-1")["status"] == "imported"


def test_changed_metadata_cannot_reuse_retained_upload_key(calendar_import_case):
    f = calendar_import_case
    uploaded(f)
    body = upload_body(f)
    body["reported_source"] = "other_calendar"
    response = action(f, body)
    assert response.status_code == 409 and response.json()["detail"] == "idempotency_conflict"


def test_two_imports_can_revisit_and_withdraw_first_without_hiding_second(calendar_import_case):
    f = calendar_import_case
    first = uploaded(f)
    second = uploaded(f, key="calendar-upload-2", raw=f.ics(title="Another invented calendar visit"))
    listing = action(f, {"action": "list"})
    assert listing.status_code == 200, listing.text
    rows = listing.json()["imports"]
    assert len(rows) == 2 and listing.json()["more"] is False
    assert "Invented calendar visit" not in listing.text and "Another invented" not in listing.text
    assert all(set(row) == {"status", "import_id", "idempotency_key", "byte_sha256", "request_sha256",
                           "source_sha256", "reported_source", "window", "imported_at", "reviewed_item_indices"} for row in rows)
    assert all(row["reviewed_item_indices"] == [] for row in rows)
    earlier = next(row for row in rows if row["import_id"] == first["import_id"])
    assert earlier["request_sha256"] == payload_hash(imports.upload_body(f.workspace["id"],
        earlier["idempotency_key"], earlier["byte_sha256"], earlier["reported_source"], earlier["window"]))
    assert action(f, {"action": "inspect", "import_id": earlier["import_id"]}).json() == first
    saved = review(f, review_body(f, first))
    assert saved.status_code == 200, saved.text
    reviewed = {row["import_id"]: row["reviewed_item_indices"] for row in action(f, {"action": "list"}).json()["imports"]}
    assert reviewed == {first["import_id"]: [0], second["import_id"]: []}
    revoke = dict(action="revoke", expected_revision=saved.json()["workspace"]["revision"], idempotency_key="calendar-withdraw-earlier",
                  import_id=first["import_id"], source_sha256=first["source_sha256"])
    assert action(f, revoke).status_code == 200
    states = {row["import_id"]: row["status"] for row in action(f, {"action": "list"}).json()["imports"]}
    assert states == {first["import_id"]: "withheld", second["import_id"]: "imported"}
    assert action(f, {"action": "inspect", "import_id": second["import_id"]}).json() == second


def test_only_explicitly_reviewed_current_import_enters_chief_context(calendar_import_case, monkeypatch):
    f = calendar_import_case
    receipt = uploaded(f)
    settings = dict(role="chief", include_evidence=True)
    w = ws._workspace(f.s, f.box, f.owner, f.workspace["id"])
    assert model_work._selected_connector_passages(f.s, w, settings) == ()
    saved = review(f, review_body(f, receipt))
    assert saved.status_code == 200, saved.text
    data = saved.json()
    w = ws._workspace(f.s, f.box, f.owner, f.workspace["id"])
    passages = model_work._selected_connector_passages(f.s, w, settings)
    assert [row.entry_id for row in passages] == [data["entry_id"]]
    assert any("does not verify patient or chart identity" in row.content for row in passages)
    assert model_work._selected_connector_passages(f.s, w, {**settings, "include_evidence": False}) == ()
    monkeypatch.setattr(f.configuration, "workspace_calendar_import_enabled", False)
    assert model_work._selected_connector_passages(f.s, w, settings) == ()
    monkeypatch.setattr(f.configuration, "workspace_calendar_import_enabled", True)
    assert action(f, dict(action="revoke", expected_revision=data["workspace"]["revision"],
        idempotency_key="calendar-context-revoke", import_id=receipt["import_id"],
        source_sha256=receipt["source_sha256"])).status_code == 200
    w = ws._workspace(f.s, f.box, f.owner, f.workspace["id"])
    assert model_work._selected_connector_passages(f.s, w, settings) == ()


@pytest.mark.parametrize("collision", ["upload_review", "upload_revoke", "review_upload", "review_revoke", "revoke_upload", "revoke_review"])
def test_cross_kind_keys_fail_as_conflicts_without_duplicate_commits(calendar_import_case, collision):
    f = calendar_import_case
    receipt = uploaded(f)
    expected = f.workspace["revision"]
    if collision.startswith("upload"):
        key = "calendar-upload-1"
    else:
        saved = review(f, review_body(f, receipt))
        assert saved.status_code == 200, saved.text
        expected = saved.json()["workspace"]["revision"]
        key = "calendar-review-1"
        if collision.startswith("revoke"):
            key = "calendar-revoke-1"
            assert action(f, dict(action="revoke", expected_revision=expected, idempotency_key=key,
                import_id=receipt["import_id"], source_sha256=receipt["source_sha256"])).status_code == 200
    if collision.endswith("upload"):
        response = action(f, upload_body(f, key=key))
    elif collision.endswith("review"):
        response = review(f, review_body(f, receipt, key=key, expected=expected))
    else:
        response = action(f, dict(action="revoke", expected_revision=expected, idempotency_key=key,
            import_id=receipt["import_id"], source_sha256=receipt["source_sha256"]))
    assert response.status_code == 409 and response.json()["detail"] == "idempotency_conflict"
    assert f.s.scalar(select(func.count()).select_from(CalendarImportRequest)) == 1


@pytest.mark.parametrize("reserved_kind", ["upload", "revoke"])
@pytest.mark.parametrize("entry_path", ["entries", "conversation", "team_admission"])
def test_reserved_import_keys_cannot_become_ordinary_entry_commands(calendar_import_case, reserved_kind, entry_path):
    f = calendar_import_case
    receipt = uploaded(f)
    key = "calendar-upload-1"
    if reserved_kind == "revoke":
        key = "calendar-reserved-revoke"
        response = action(f, dict(action="revoke", expected_revision=f.workspace["revision"],
            idempotency_key=key, import_id=receipt["import_id"], source_sha256=receipt["source_sha256"]))
        assert response.status_code == 200, response.text
    if entry_path == "team_admission":
        w = ws._workspace(f.s, f.box, f.owner, f.workspace["id"], writing=True)
        # Admission must refuse before consulting or generating a model context.
        with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
            model_work._new_admission(f.s, w, None, None, None, {"idempotency_key": key}, None, None, None, f.account)
    else:
        body = dict(expected_revision=f.workspace["revision"], idempotency_key=key, content="Invented follow-up")
        body |= {"kind": "scratchpad"} if entry_path == "entries" else {"team_revision": 1, "role": "chief"}
        response = f.client.post(f"/workspaces/{f.workspace['id']}/{entry_path}", headers=f.headers(), json=body)
        assert response.status_code == 409 and response.json()["detail"] == "idempotency_conflict"
    assert f.s.scalar(select(func.count()).select_from(WorkspaceEntry).where(WorkspaceEntry.idempotency_key == key)) == 0


def test_sha_claim_is_verified_and_raw_properties_never_persist(calendar_import_case):
    f = calendar_import_case
    secret = "https://example.invalid/private-feed/invented-secret"
    raw = f.ics(extra=f"URL:{secret}\r\nDESCRIPTION:{secret}\r\nATTACH:{secret}\r\n")
    body = upload_body(f, raw=raw)
    body["byte_sha256"] = "0" * 64
    assert action(f, body).status_code == 422
    receipt = uploaded(f, raw=raw)
    assert receipt["byte_sha256"] == hashlib.sha256(raw).hexdigest()
    for table in ("calendar_import_requests", "calendar_import_snapshots"):
        retained = json.dumps(list(f.s.scalars(text(f"SELECT row_to_json(t) FROM {table} t"))), default=str)
        assert secret not in retained and "invented-calendar-event" not in retained
        assert base64.b64encode(raw).decode() not in retained
        assert "file_base64" not in retained and "UID" not in retained


@pytest.mark.parametrize("change", ["hash", "index", "revision", "confirmation", "cancelled"])
def test_review_requires_current_revision_exact_item_and_human_checks(calendar_import_case, change):
    f = calendar_import_case
    receipt = uploaded(f, raw=f.ics(cancelled=change == "cancelled"))
    body = review_body(f, receipt)
    if change == "hash":
        body["item_sha256"] = "0" * 64
    elif change == "index":
        body["item_index"] = 499
    elif change == "revision":
        body["expected_revision"] = f.workspace["revision"] + 1
    elif change == "confirmation":
        body["reviewed_visit"] = False
    response = review(f, body)
    assert response.status_code in (409, 422), response.text
    assert f.s.scalar(select(func.count()).select_from(CalendarImportSourceReview)) == 0


def test_other_workspace_cannot_inspect_or_review_same_import(calendar_import_case):
    f = calendar_import_case
    receipt = uploaded(f)
    appt = AppointmentObservation(box_id=f.box, external_id="invented-" + str(uuid4()), source="synthetic",
        start_at=datetime.now(UTC), patient_label="Invented other visit", patient_link_id=f.appointment.patient_link_id)
    f.s.add(appt)
    f.s.commit()
    other = ws.create(f.s, f.box, f.owner, appt.id, "calendar-other-visit")
    response = action(f, {"action": "inspect", "import_id": receipt["import_id"]}, wid=other["id"])
    assert response.status_code == 404 and "Invented calendar visit" not in response.text


def test_preflight_releases_sql_transaction_before_streaming_body(calendar_import_case):
    f = calendar_import_case
    payload = json.dumps(upload_body(f)).encode()
    checked = []

    def chunks():
        assert f.request_session is not None
        checked.append(not f.request_session.in_transaction())
        yield payload[:100]
        yield payload[100:]

    response = f.client.post(f"/workspaces/{f.workspace['id']}/calendar-imports",
        headers={**f.headers(), "Content-Type": "application/json"}, content=chunks())
    assert response.status_code == 200, response.text
    assert checked == [True]


def test_default_off_and_auth_failure_never_parse(calendar_import_case, monkeypatch):
    f = calendar_import_case

    def fail(*args, **kwargs) -> NoReturn:
        pytest.fail("unauthorized or disabled parser call")

    monkeypatch.setattr(imports, "parse_calendar_file", fail)
    monkeypatch.setattr(f.configuration, "workspace_calendar_import_enabled", False)
    assert action(f, {"action": "status"}).json()["status"] == "unavailable"
    assert action(f, upload_body(f)).status_code == 404
    endpoint = f"/workspaces/{f.workspace['id']}/calendar-imports"
    assert f.client.post(endpoint, json=upload_body(f)).status_code == 401
    assert f.client.post(endpoint, headers={"Authorization": "Bearer " + f.token()}, json=upload_body(f)).status_code == 422


def test_unauthorized_request_does_not_consume_file_body(calendar_import_case):
    f = calendar_import_case
    consumed = []

    def chunks():
        consumed.append(True)
        yield b"invented-private-file-body"

    response = f.client.post(f"/workspaces/{f.workspace['id']}/calendar-imports",
                            headers={"Content-Type": "application/json"}, content=chunks())
    assert response.status_code == 401
    assert consumed == []


@pytest.mark.parametrize("fault", ["duplicate_json", "unknown_metadata", "compressed", "query"])
def test_route_refuses_ambiguous_or_extra_wire_data(calendar_import_case, fault):
    f = calendar_import_case
    endpoint = f"/workspaces/{f.workspace['id']}/calendar-imports"
    body = json.dumps(upload_body(f))
    headers = {**f.headers(), "Content-Type": "application/json"}
    if fault == "duplicate_json":
        body = '{"action":"status",' + body[1:]
    elif fault == "unknown_metadata":
        body = '{"filename":"invented.ics",' + body[1:]
    elif fault == "compressed":
        headers["Content-Encoding"] = "gzip"
    else:
        endpoint += "?feed=https://example.invalid/private"
    response = f.client.post(endpoint, headers=headers, content=body)
    assert response.status_code == 422 and "invented.ics" not in response.text


@pytest.mark.parametrize("signed_workspace", ["apple", "desktop"], indirect=True)
def test_signed_native_origin_profiles_use_the_same_import_contract(calendar_import_case):
    f = calendar_import_case
    receipt = uploaded(f)
    assert receipt["scope"]["workspace_id"] == f.workspace["id"]
    assert action(f, {"action": "inspect", "import_id": receipt["import_id"]}).json() == receipt


def test_account_loss_after_commit_withholds_upload_response(calendar_import_case, monkeypatch):
    f = calendar_import_case
    original = Session.commit
    parse = imports.parse_calendar_file
    admitted = []

    def parsed(*args, **kwargs):
        result = parse(*args, **kwargs)
        admitted.append(True)
        return result

    def commit(owned):
        original(owned)
        if admitted:
            admitted.clear()
            owned.execute(update(ExternalIdentity).where(ExternalIdentity.id == f.account).values(active=False))
            original(owned)

    monkeypatch.setattr(imports, "parse_calendar_file", parsed)
    monkeypatch.setattr(Session, "commit", commit)
    response = action(f, upload_body(f))
    assert response.status_code == 403, response.text
    assert "Invented calendar visit" not in response.text
