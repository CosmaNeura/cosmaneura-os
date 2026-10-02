"""Actual PostgreSQL calendar custody; only the bounded provider is synthetic."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, TypedDict
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration import test_google_calendar_model_work as lineage
from tests.integration.test_handoff_review import isolate_http_request, request_sessions
from tests.integration.test_note_review import prepare
from tests.integration.test_note_review import review as review_note
from tests.integration.test_note_review import save as save_note
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace

from cosmas_os.api import app as api_module
from cosmas_os.application import google_calendar as calendar
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.google_calendar_models import (
    GoogleCalendarObservationRequest,
    GoogleCalendarSnapshot,
    GoogleCalendarSourceReview,
)
from cosmas_os.google_connection_models import GoogleConnectionCredential
from cosmas_os.models import EncounterWorkspace, ExternalIdentity, ModelWorkAdmission
from cosmas_os.ports.google_calendar import (
    GoogleCalendarAccount,
    GoogleCalendarBinding,
    GoogleCalendarEvent,
    GoogleCalendarObservation,
    GoogleCalendarRead,
)

signed_workspace = _signed_workspace
google_case = lineage.google_case
calendar_case = lineage.calendar_case


@pytest.fixture
def isolated_calendar_case(calendar_case, monkeypatch):
    """Always close this committed fixture's work through the authority fence."""
    f = calendar_case
    try:
        yield f
    finally:
        before_io = (len(f.port.calls), len(f.calendar_port.calls))
        monkeypatch.setattr(lineage.work, "dispatch_claim", lambda *_args, **_kwargs: pytest.fail("cleanup must not dispatch a model"))
        with Session(f.engine) as s:
            credential = s.get(GoogleConnectionCredential, f.account)
            assert credential is not None
            credential.status, credential.sealed = "disconnected", None
            s.commit()
            reserved = list(s.scalars(select(ModelWorkAdmission.id).where(ModelWorkAdmission.box_id == f.box,
                ModelWorkAdmission.owner_id == f.owner, ModelWorkAdmission.workspace_id == f.wid,
                ModelWorkAdmission.state == "reserved")))
            for admission_id in reserved:
                assert lineage.work.claim(s, f.box, f.owner, admission_id) is None
                admission = s.get(ModelWorkAdmission, admission_id)
                assert admission is not None and admission.state in {"failed", "abandoned"}
            assert not list(s.scalars(select(ModelWorkAdmission.id).where(ModelWorkAdmission.box_id == f.box,
                ModelWorkAdmission.owner_id == f.owner, ModelWorkAdmission.workspace_id == f.wid,
                ModelWorkAdmission.state.in_({"reserved", "running"}))))
        assert (len(f.port.calls), len(f.calendar_port.calls)) == before_io


class CalendarReviewReceipt(TypedDict):
    entry_id: str
    entry_revision: int
    request_sha256: str
    source_withheld: bool
    workspace: dict[str, Any]
    source: dict[str, str]


def checked_review_receipt(value: object) -> CalendarReviewReceipt:
    assert isinstance(value, dict)
    assert isinstance(value["entry_id"], str) and type(value["entry_revision"]) is int
    assert isinstance(value["request_sha256"], str) and type(value["source_withheld"]) is bool
    assert isinstance(value["workspace"], dict) and isinstance(value["source"], dict)
    assert all(isinstance(item, str) for item in value["source"].values())
    return {"entry_id": value["entry_id"], "entry_revision": value["entry_revision"],
        "request_sha256": value["request_sha256"], "source_withheld": value["source_withheld"],
        "workspace": value["workspace"], "source": value["source"]}


class InventedCalendar:
    def __init__(self, session, account, connected):
        self.session, self.account, self.connected = session, account, connected
        self.grant, self.calls, self.fail = "b" * 64, [], False
        self.after = lambda: None
        self.change = lambda event: event

    def calendar_binding(self, identity, *, session=None):
        assert session is self.session and identity.external_identity_id == self.account
        return GoogleCalendarBinding(account_id=self.account, binding_digest="a" * 64,
            connected_at=self.connected, grant_sha256=self.grant)

    def calendar_status(self, identity, *, session=None):
        return dict(contract_version=1, state="connected", calendar_read=True,
            account={"label": "Invented café 🫀", "email": "owner@example.invalid"})

    def calendar_observation(self, identity, *, window):
        assert not self.session.in_transaction(), "bounded provider I/O must release the SQL transaction"
        self.calls.append(window)
        self.after()
        if self.fail:
            raise TimeoutError("invented uncertain provider response")
        event = GoogleCalendarEvent.model_validate(self.change(dict(id="invented-event", subject="Invented café 🫀 follow-up",
            starts_at=(window.starts_at + timedelta(hours=1)).isoformat(), ends_at=(window.starts_at + timedelta(hours=2)).isoformat(),
            all_day=False, cancelled=False)))
        return GoogleCalendarRead(custody=self.calendar_binding(identity, session=self.session),
            observation=GoogleCalendarObservation(kind="calendar", account=GoogleCalendarAccount(label="Invented café 🫀", email="owner@example.invalid"),
                items=(event,), more=True, observed_at=datetime.now(UTC), window=window))


@pytest.fixture
def case(session, seeded):
    box, owner, w, patient = prepare(session, seeded)
    account = ExternalIdentity(box_id=box, principal_id=owner, issuer=f"https://clerk-{uuid4()}.example.invalid",
        subject="invented-owner", organization_id="invented-org", reviewed_by="invented owner", evidence_ref="synthetic calendar")
    session.add(account)
    session.flush()
    now = datetime.now(UTC)
    session.add(GoogleConnectionCredential(account_id=account.id, binding_digest="a" * 64, status="ready",
        sealed=b"i" * 40, connected_at=now, expires_at=now + timedelta(hours=1)))
    session.commit()
    port = InventedCalendar(session, account.id, now)
    with calendar.install_binding_reader(lambda s, a: port.calendar_binding(calendar._scoped_identity(a), session=s)):
        yield SimpleNamespace(s=session, box=box, owner=owner, w=w, patient=patient, account=account.id, port=port)


def observe(f, **changes):
    return calendar.observe(f.s, f.box, f.owner, f.account, key=changes.pop("key", "observe-1"), port=f.port, **changes)


def select_event(f, receipt, **changes) -> CalendarReviewReceipt:
    event = receipt["observation"]["items"][0]
    return checked_review_receipt(calendar.select_review(f.s, f.box, f.owner, f.w["id"], **{
        "expected": f.w["revision"], "key": "review-1", "observation_id": receipt["observation_id"],
        "observation_sha256": receipt["source_sha256"], "event_id": event["id"], "event_sha256": calendar.event_hash(event),
        "reviewed_visit": True, "reviewed_exact_summary": True, "reviewed_untrusted_source": True,
        "port": f.port, "external_identity_id": f.account, **changes}))


def revoke(f):
    credential = f.s.get(GoogleConnectionCredential, f.account)
    credential.status, credential.sealed = "disconnected", None
    f.s.commit()


def scoped_count(f, model):
    predicate = model.account_id == f.account if model is GoogleCalendarObservationRequest else (
        model.workspace_id == f.w["id"] if model is GoogleCalendarSourceReview else model.observation_id.in_(
            select(GoogleCalendarObservationRequest.id).where(GoogleCalendarObservationRequest.account_id == f.account)))
    return f.s.scalar(select(func.count()).select_from(model).where(predicate))


def test_one_frozen_observation_exact_replay_resolve_and_inspect_without_provider_repeat(case):
    f = case
    receipt = observe(f)
    assert set(receipt) == {"contract_version", "observation_id", "observation_key", "source_sha256", "payload_sha256", "observation"}
    assert receipt["payload_sha256"] == calendar._payload_digest(receipt["observation"])
    assert observe(f) == receipt
    assert calendar.inspect_observation(f.s, f.box, f.owner, f.account, observation_id=receipt["observation_id"], port=f.port) == receipt
    assert calendar.resolve_observation(f.s, f.box, f.owner, f.account, key="observe-1", port=f.port) == receipt
    assert len(f.port.calls) == 1 and f.port.calls[0].ends_at - f.port.calls[0].starts_at == timedelta(hours=168)
    assert scoped_count(f, GoogleCalendarObservationRequest) == 1
    assert scoped_count(f, GoogleCalendarSnapshot) == 1


def test_uncertain_get_reservation_is_resolvable_and_never_automatically_repeated(case):
    f = case
    f.port.fail = True
    with pytest.raises(ws.WorkspaceError, match="google_calendar_observation_unconfirmed"):
        observe(f)
    assert calendar.resolve_observation(f.s, f.box, f.owner, f.account, key="observe-1", port=f.port)["status"] == "unconfirmed"
    f.port.fail = False
    with pytest.raises(ws.WorkspaceError, match="google_calendar_observation_unconfirmed"):
        observe(f)
    assert len(f.port.calls) == 1
    assert calendar.resolve_observation(f.s, f.box, f.owner, f.account, key="missing-key", port=f.port) == {
        "status": "not_found", "observation_id": None, "observation_key": "missing-key"}


def test_exact_human_source_does_not_replace_or_stale_existing_clinical_note(case):
    f = case
    note_case = (f.box, f.owner, f.w, f.patient)
    w = save_note(f.s, note_case)
    f.w = review_note(f.s, note_case, w)
    before_note = deepcopy(f.w["note"])
    receipt = observe(f)
    saved = select_event(f, receipt)
    assert saved["workspace"]["note"] == before_note
    entry = next(row for row in saved["workspace"]["entries"] if row["id"] == saved["entry_id"])
    assert entry["kind"] == "google_calendar" and entry["calendar_source_state"] == "current"
    assert entry["content"] == calendar.source_content(receipt["observation"], receipt["observation"]["items"][0])
    assert saved["source"]["content_sha256"] == hashlib.sha256(entry["content"].encode()).hexdigest()
    assert saved["source_withheld"] is False
    assert select_event(f, receipt)["entry_id"] == saved["entry_id"]
    assert scoped_count(f, GoogleCalendarSourceReview) == 1
    assert f.s.scalar(text("SELECT google_calendar_source_valid(:id)"), {"id": saved["entry_id"]}) is True
    assert f.s.scalar(text("SELECT google_calendar_source_current(:id)"), {"id": saved["entry_id"]}) is True


def test_lost_review_reply_after_revoke_returns_only_matching_masked_historical_receipt(case):
    f = case
    receipt = observe(f)
    saved = select_event(f, receipt)
    revoke(f)
    recovered = select_event(f, receipt)
    assert recovered["entry_id"] == saved["entry_id"] and recovered["request_sha256"] == saved["request_sha256"]
    assert recovered["source"] == saved["source"] and recovered["source_withheld"] is True
    entry = next(row for row in recovered["workspace"]["entries"] if row["id"] == recovered["entry_id"])
    assert entry["content"] == "" and entry["calendar_source_state"] == "unavailable" and "café" not in entry["source_label"]
    assert len(f.port.calls) == 1
    assert f.s.scalar(text("SELECT google_calendar_source_valid(:id)"), {"id": saved["entry_id"]}) is True
    assert f.s.scalar(text("SELECT google_calendar_source_current(:id)"), {"id": saved["entry_id"]}) is False
    with pytest.raises(ws.WorkspaceError, match="google_calendar_grant_unavailable"):
        calendar.inspect_observation(f.s, f.box, f.owner, f.account, observation_id=receipt["observation_id"], port=f.port)
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        select_event(f, receipt, event_sha256="c" * 64)


def test_new_uncertain_observation_supersedes_old_source_without_repeating_or_erasing_history(case):
    f = case
    receipt = observe(f)
    saved = select_event(f, receipt)
    f.port.fail = True
    with pytest.raises(ws.WorkspaceError, match="google_calendar_observation_unconfirmed"):
        observe(f, key="observe-new")
    current = ws.read(f.s, f.box, f.owner, f.w["id"])
    entry = next(row for row in current["entries"] if row["id"] == saved["entry_id"])
    assert entry["content"] == "" and entry["calendar_source_state"] == "unavailable"
    assert select_event(f, receipt)["source_withheld"] is True
    assert len(f.port.calls) == 2
    with pytest.raises(ws.WorkspaceError, match="google_calendar_source_superseded"):
        calendar.inspect_observation(f.s, f.box, f.owner, f.account, observation_id=receipt["observation_id"], port=f.port)
    with pytest.raises(ws.WorkspaceError, match="google_calendar_source_superseded"):
        calendar.resolve_observation(f.s, f.box, f.owner, f.account, key="observe-1", port=f.port)
    with pytest.raises(ws.WorkspaceError, match="google_calendar_source_superseded"):
        observe(f)


@pytest.mark.parametrize("change", ["hash", "event", "event_hash", "visit_ack", "summary_ack", "untrusted_ack", "revision"])
def test_no_admission_for_changed_exact_event_revision_or_missing_review(case, change):
    f = case
    receipt = observe(f)
    changes = {"hash": {"observation_sha256": "d" * 64}, "event": {"event_id": "unobserved"},
        "event_hash": {"event_sha256": "d" * 64}, "visit_ack": {"reviewed_visit": False},
        "summary_ack": {"reviewed_exact_summary": False}, "untrusted_ack": {"reviewed_untrusted_source": False},
        "revision": {"expected": f.w["revision"] + 1}}[change]
    with pytest.raises(ws.WorkspaceError):
        select_event(f, receipt, **changes)
    assert scoped_count(f, GoogleCalendarSourceReview) == 0


def test_loss_during_provider_io_leaves_only_uncertain_reservation_and_no_public_snapshot(case):
    f = case
    f.port.after = lambda: revoke(f)
    with pytest.raises(ws.WorkspaceError, match="google_calendar_grant_unavailable"):
        observe(f)
    assert scoped_count(f, GoogleCalendarSnapshot) == 0
    assert scoped_count(f, GoogleCalendarObservationRequest) == 1


def test_current_semantic_grant_change_with_same_account_refuses_old_source(case):
    f = case
    receipt = observe(f)
    saved = select_event(f, receipt)
    f.port.grant = "c" * 64
    assert select_event(f, receipt)["source_withheld"] is True
    with pytest.raises(ws.WorkspaceError, match="google_calendar_grant_changed"):
        calendar.inspect_observation(f.s, f.box, f.owner, f.account, observation_id=receipt["observation_id"], port=f.port)
    assert calendar.historical_source(f.s, f.s.get(EncounterWorkspace, f.w["id"]), saved["entry_id"]).id == saved["entry_id"]


def test_withheld_receipt_reprojects_source_even_when_reader_recovers_during_final_read(case, monkeypatch):
    f = case
    receipt = observe(f)
    saved = select_event(f, receipt)
    original = calendar.ws.read
    reads = []

    def flip_after_projection(*args, **kwargs):
        reads.append(True)
        value = original(*args, **kwargs)
        if len(reads) == 1:
            f.port.grant = "c" * 64
        else:
            f.port.grant = "b" * 64
        return value

    monkeypatch.setattr(calendar.ws, "read", flip_after_projection)
    recovered = select_event(f, receipt)
    assert recovered["source_withheld"] is True and len(reads) == 2
    entry = next(row for row in recovered["workspace"]["entries"] if row["id"] == saved["entry_id"])
    assert entry["content"] == "" and entry["calendar_source_state"] == "unavailable"
    assert entry["source_label"] == "Unavailable calendar source"
    assert calendar._withheld_sources.get() == frozenset()


def test_initial_unavailable_projection_stays_masked_when_final_reader_recovers(case, monkeypatch):
    f = case
    receipt = observe(f)
    saved = select_event(f, receipt)
    f.port.grant = "c" * 64
    original = calendar.ws.read
    reads = []

    def recover_after_initial_projection(*args, **kwargs):
        reads.append(True)
        value = original(*args, **kwargs)
        f.port.grant = "b" * 64
        return value

    monkeypatch.setattr(calendar.ws, "read", recover_after_initial_projection)
    recovered = select_event(f, receipt)
    assert recovered["source_withheld"] is True and len(reads) == 2
    entry = next(row for row in recovered["workspace"]["entries"] if row["id"] == saved["entry_id"])
    assert entry["content"] == "" and entry["calendar_source_state"] == "unavailable"
    assert entry["source_label"] == "Unavailable calendar source"
    assert calendar._withheld_sources.get() == frozenset()


def test_final_receipt_source_race_withholds_uncited_drafts_review_feedback_and_revised_brief(isolated_calendar_case, monkeypatch):
    f = isolated_calendar_case
    command, handoff = lineage.finish_handoff(f, cited=False)
    with Session(f.engine) as s:
        saved = lineage.reviews.review(s, f.box, f.owner, f.wid, handoff["id"], **command)
        review = next(h for h in saved["workspace"]["handoffs"] if h["id"] == handoff["id"])["review"]
        lineage.revisions.reserve(s, f.box, f.owner, f.wid, handoff["id"], expected=saved["workspace"]["revision"],
            key="calendar-race-revision", review_id=review["id"])
        source_review = s.scalar(select(GoogleCalendarSourceReview).where(GoogleCalendarSourceReview.entry_id == f.calendar_selected["entry_id"]))
        assert source_review is not None
        snapshot = s.get(GoogleCalendarSnapshot, source_review.snapshot_id)
        assert snapshot is not None
        original = calendar.ws.read
        reads = []

        def flip_after_projection(*args, **kwargs):
            reads.append(True)
            value = original(*args, **kwargs)
            f.calendar_port.grant = "c" * 64 if len(reads) == 1 else "b" * 64
            return value

        monkeypatch.setattr(calendar.ws, "read", flip_after_projection)
        recovered = checked_review_receipt(calendar.select_review(s, f.box, f.owner, f.wid, expected=source_review.expected_revision,
            key=source_review.idempotency_key, observation_id=snapshot.observation_id,
            observation_sha256=source_review.observation_sha256, event_id=source_review.event_id, event_sha256=source_review.event_sha256,
            reviewed_visit=True, reviewed_exact_summary=True, reviewed_untrusted_source=True, external_identity_id=f.account))
        assert recovered["source_withheld"] is True and len(reads) == 2
        assert lineage.gmail.private_fact_paths(recovered, ["calendar café", "Google calendar: Invented calendar"]) == []
        assert recovered["workspace"]["note"]["latest"] == f.note_before
        assert calendar._withheld_sources.get() == frozenset()
        # This fixture commits its isolated workspace for real model/tool
        # sessions. Close its intentionally queued revision before legacy
        # global worker tests run; use the normal authority fence, not a state
        # rewrite or a global cleanup of another fixture's work.
        reserved = list(s.scalars(select(ModelWorkAdmission.id).where(ModelWorkAdmission.box_id == f.box,
            ModelWorkAdmission.owner_id == f.owner, ModelWorkAdmission.workspace_id == f.wid,
            ModelWorkAdmission.state == "reserved")))
        assert len(reserved) == 1


def test_a_new_reservation_during_get_prevents_superseded_snapshot_return(case):
    f = case

    def reserve_newer_without_repeating_io():
        # This is a separate explicit synthetic request while the first bounded
        # GET is in flight; its own uncertain reservation remains durable.
        f.port.after = lambda: None
        f.port.fail = True
        with pytest.raises(ws.WorkspaceError, match="google_calendar_observation_unconfirmed"):
            observe(f, key="observe-new")
        f.port.fail = False

    f.port.after = reserve_newer_without_repeating_io
    with pytest.raises(ws.WorkspaceError, match="google_calendar_source_superseded"):
        observe(f)
    assert scoped_count(f, GoogleCalendarSnapshot) == 0
    assert scoped_count(f, GoogleCalendarObservationRequest) == 2
    assert len(f.port.calls) == 2


def test_sql_non_ascii_event_hash_content_and_private_custody_commitment_match_python(case):
    f = case
    receipt = observe(f)
    event = receipt["observation"]["items"][0]
    assert f.s.scalar(text("SELECT google_calendar_json_digest(CAST(:value AS jsonb))"), {"value": json.dumps(event)}) == calendar.event_hash(event)
    saved = select_event(f, receipt)
    assert saved["request_sha256"] == payload_hash(calendar._review_body(f.w["id"], f.w["revision"], "review-1", receipt["observation_id"],
        receipt["source_sha256"], event["id"], calendar.event_hash(event), True, True, True))


@pytest.mark.parametrize("identifier", ["valid-id", "x" * 1024])
def test_sql_payload_validator_accepts_bounded_ids_without_invalid_regex_interval(case, identifier):
    f = case
    f.port.change = lambda event: {**event, "id": identifier}
    receipt = observe(f)
    payload = receipt["observation"]
    assert f.s.scalar(text("SELECT google_calendar_payload_valid(CAST(:p AS jsonb),:a,:b)"),
        {"p": json.dumps(payload), "a": f.port.calls[0].starts_at, "b": f.port.calls[0].ends_at}) is True
    select_event(f, receipt)


def test_inspect_resolve_and_replay_refuse_expired_window_while_saved_review_remains_recoverable(case, monkeypatch):
    f = case
    receipt = observe(f)
    saved = select_event(f, receipt)
    # A test-only DB clock reader overrides runtime checks without editing any
    # immutable custody record. SQL has separate current-expiry qualification.
    monkeypatch.setattr(calendar.model_work, "now", lambda s: f.port.calls[0].ends_at)
    for command in (lambda: observe(f),
        lambda: calendar.inspect_observation(f.s, f.box, f.owner, f.account, observation_id=receipt["observation_id"], port=f.port),
        lambda: calendar.resolve_observation(f.s, f.box, f.owner, f.account, key="observe-1", port=f.port)):
        with pytest.raises(ws.WorkspaceError, match="google_calendar_grant_unavailable|google_calendar_source_expired"):
            command()
    assert select_event(f, receipt)["entry_id"] == saved["entry_id"]


@pytest.mark.parametrize("table", ["google_calendar_observation_requests", "google_calendar_snapshots", "google_calendar_source_reviews"])
@pytest.mark.parametrize("action", ["UPDATE", "DELETE"])
def test_custody_and_review_records_are_immutable(case, table, action):
    f = case
    select_event(f, observe(f))
    clause = "SET created_at=clock_timestamp()" if action == "UPDATE" else ""
    with pytest.raises(DBAPIError), f.s.begin_nested():
        f.s.execute(text(f"{action} {'' if action == 'UPDATE' else 'FROM '}{table} {clause} WHERE box_id=:box AND owner_id=:owner"),
            {"box": f.box, "owner": f.owner})


@pytest.fixture
def http_case(signed_workspace, session, monkeypatch):
    f = signed_workspace
    monkeypatch.setattr(f.configuration, "workspace_google_calendar_enabled", True)
    monkeypatch.setattr(f.configuration, "workspace_google_connection_enabled", True)
    now = datetime.now(UTC)
    session.add(GoogleConnectionCredential(account_id=f.binding.id, binding_digest="a" * 64, status="ready", sealed=b"i" * 40,
        connected_at=now, expires_at=now + timedelta(hours=1)))
    session.commit()
    port = InventedCalendar(session, f.binding.id, now)
    original = port.calendar_binding

    def binding(identity, *, session=None):
        assert session is not None
        port.session = session
        return original(identity, session=session)

    port.calendar_binding = binding
    monkeypatch.setattr(api_module.app.state, "google_connection", port, raising=False)
    monkeypatch.setitem(api_module.app.dependency_overrides, api_module.get_session, request_sessions(session))
    monkeypatch.setattr(f.client, "request", isolate_http_request(f.client, session))
    f.port, f.s = port, session
    f.headers = {"Authorization": "Bearer " + f.token(), "X-Cosmas-Google-Calendar": "1"}
    with calendar.install_binding_reader(lambda s, a: binding(calendar._scoped_identity(a), session=s)):
        yield f


def test_signed_http_observe_inspect_review_reopen_and_exact_replay_use_actual_routes(http_case):
    f = http_case
    path = "/connections/google/calendar-summaries"
    first = f.client.post(path, headers=f.headers, json={"action": "observe", "idempotency_key": "http-observe"})
    assert first.status_code == 200, first.text
    receipt = first.json()
    inspected = f.client.post(path, headers=f.headers, json={"action": "inspect", "observation_id": receipt["observation_id"]})
    assert inspected.status_code == 200 and inspected.json() == receipt
    event = receipt["observation"]["items"][0]
    body = dict(expected_revision=f.workspace["revision"], idempotency_key="http-review", observation_id=receipt["observation_id"],
        observation_sha256=receipt["source_sha256"], event_id=event["id"], event_sha256=calendar.event_hash(event),
        reviewed_visit=True, reviewed_exact_summary=True, reviewed_untrusted_source=True)
    review_path = f"/workspaces/{f.workspace['id']}/google-calendar/review"
    saved = f.client.post(review_path, headers=f.headers, json=body)
    assert saved.status_code == 200, saved.text
    replay = f.client.post(review_path, headers=f.headers, json=body)
    assert replay.status_code == 200 and replay.json()["entry_id"] == saved.json()["entry_id"]
    assert len(f.port.calls) == 1
    for response in (first, inspected, saved, replay):
        assert response.headers["cache-control"] == "no-store"


def test_signed_http_does_not_return_calendar_content_when_feature_is_disabled_during_get(http_case):
    f = http_case
    f.port.after = lambda: setattr(f.configuration, "workspace_google_calendar_enabled", False)
    response = f.client.post("/connections/google/calendar-summaries", headers=f.headers,
        json={"action": "observe", "idempotency_key": "http-flag-race"})
    assert response.status_code == 404 and response.json() == {"detail": "google_calendar_unavailable"}
    assert "café" not in response.text and "observation" not in response.text
    assert len(f.port.calls) == 1


@pytest.mark.parametrize("action", ["inspect", "resolve"])
def test_signed_http_final_gate_withholds_db_only_observation_reply_on_feature_loss(http_case, monkeypatch, action):
    f = http_case
    path = "/connections/google/calendar-summaries"
    initial = f.client.post(path, headers=f.headers, json={"action": "observe", "idempotency_key": "http-before-race"})
    assert initial.status_code == 200, initial.text
    method = "inspect_observation" if action == "inspect" else "resolve_observation"
    original = getattr(calendar, method)

    def lose_flag_after_read(*args, **kwargs):
        result = original(*args, **kwargs)
        f.configuration.workspace_google_calendar_enabled = False
        return result

    monkeypatch.setattr(calendar, method, lose_flag_after_read)
    body = {"action": action, "observation_id": initial.json()["observation_id"]} if action == "inspect" else {
        "action": "resolve", "idempotency_key": "http-before-race"}
    response = f.client.post(path, headers=f.headers, json=body)
    assert response.status_code == 404 and response.json() == {"detail": "google_calendar_unavailable"}
    assert "café" not in response.text and len(f.port.calls) == 1


@pytest.mark.parametrize("extra", [{"account_id": str(uuid4())}, {"timeMin": "2027-01-01T00:00:00Z"},
    {"calendar_id": "shared"}, {"maxResults": 100}, {"pageToken": "invented"}])
def test_signed_http_cannot_broaden_read_or_choose_provider_scope(http_case, extra):
    f = http_case
    response = f.client.post("/connections/google/calendar-summaries", headers=f.headers,
        json={"action": "observe", "idempotency_key": "http-invalid", **extra})
    assert response.status_code == 422 and f.port.calls == []
