"""Fresh PostgreSQL + signed offline JWT read-only activity qualification."""

import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from tests.integration.test_model_work_admission import another_workspace, command
from tests.integration.test_model_work_api import case as _model_case
from tests.integration.test_workspace_capture import capture_case as _capture_case

from cosmas_os.api import app as api
from cosmas_os.api import model_activity_routes as routes
from cosmas_os.api.model_activity_schemas import ActivityResponse
from cosmas_os.application import model_activity as activity
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    EncounterWorkspace,
    ExternalIdentity,
    ModelWorkAdmission,
    PatientLink,
    Principal,
)
from cosmas_os.ports.bot_capabilities import BotReply

model_case = _model_case
capture_case = _capture_case


@pytest.fixture
def current(model_case):
    f = model_case
    app = FastAPI()

    def sessions():
        with Session(f.engine) as s:
            yield s

    app.dependency_overrides[api.get_session] = sessions
    state = SimpleNamespace(enabled=True, before_return=None)

    def reauthenticate(request, session, identity):
        api._refresh_team_identity(request, session, identity)

    routes.register(
        app,
        sessions,
        api._identity,
        gate=api._workspace_gate,
        reauthenticate=reauthenticate,
        enabled=lambda: state.enabled,
    )
    f.activity_headers = {**f.headers, "X-Cosmas-Draft-Recovery": "2"}
    f.box, f.owner = f.binding.box_id, f.binding.principal_id
    f.activity_state = state
    with TestClient(app) as client:
        f.activity_client = client
        yield f


def reserve(f, *, at=None, fresh=False):
    wid = (
        another_workspace(f.engine, f.box, f.owner, f.workspace["id"])
        if fresh
        else f.workspace["id"]
    )
    with Session(f.engine) as s:
        aid, _ = work.reserve_conversation(
            s,
            f.box,
            f.owner,
            wid,
            external_identity_id=f.identity_id,
            clock=(lambda: at) if at else None,
            **command(),
        )
    return aid, wid


def inspect(f, view="attention", cursor=None, headers=None):
    path = "/provider-team/activity/" + view + ("/" + cursor if cursor else "")
    return f.activity_client.get(path, headers=headers or f.activity_headers)


def value(response):
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert len(response.content) <= 65536
    raw = response.json()
    ActivityResponse.model_validate(raw)
    return raw


def ledger(f):
    with Session(f.engine) as s:
        return {
            table: s.scalar(
                text(
                    "SELECT md5(COALESCE(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text),'')) FROM "
                    + table
                    + " t WHERE box_id=:box"
                ),
                {"box": f.box},
            )
            for table in [
                "model_work_admissions",
                "model_usage_observations",
                "workspace_entries",
                "workspace_replies",
                "audit_events",
            ]
        }


def export(name, obj):
    root = Path(os.environ["MODEL_ACTIVITY_EVIDENCE_ROOT"])
    root.mkdir(exist_ok=True)
    (root / name).write_text(json.dumps(obj, indent=2) + "\n")


def test_signed_empty_pending_completed_and_verified_usage_are_read_only(current):
    f = current
    empty = value(inspect(f))
    aid, wid = reserve(f)
    before = ledger(f)
    pending = value(inspect(f))
    assert pending["rows"][0]["admission"]["id"] == aid
    assert pending["rows"][0]["admission"]["state"] == "reserved"
    assert pending["rows"][0]["admission"]["usage"] == "unknown"
    assert pending["rows"][0]["admission"]["input_tokens"] is None
    assert before == ledger(f) and f.calls == []
    with Session(f.engine) as s:
        claim = work.claim(s, f.box, f.owner, aid)
        work.settle(
            s, claim, BotReply("PRIVATE INVENTED ANSWER NEVER IN ACTIVITY", (), "azure_gpt41", 0, 0)
        )
    before = ledger(f)
    recent = value(inspect(f, "recent"))
    row = recent["rows"][0]
    assert row["admission"]["state"] == "completed"
    assert row["admission"]["usage"] == "verified"
    assert row["admission"]["input_tokens"] == row["admission"]["output_tokens"] == 0
    assert recent["coverage"]["attention_total"] == 0
    assert recent["usage"]["usage_complete"] is True
    assert "PRIVATE INVENTED" not in json.dumps(recent)
    assert before == ledger(f) and f.calls == []
    export("actual-activity-pages.json", {"empty": empty, "pending": pending, "recent": recent})


def test_expired_claim_and_late_usage_remain_unconfirmed(current):
    f = current
    at = datetime.now(UTC) - timedelta(days=3)
    aid, _ = reserve(f, at=at)
    with Session(f.engine) as s:
        claimed = work.claim(s, f.box, f.owner, aid, clock=lambda: at + timedelta(seconds=1))
        work.settle(
            s,
            claimed,
            BotReply("LATE PRIVATE TEXT", (), "azure_gpt41", 25, 8),
            clock=lambda: at + timedelta(seconds=91),
        )
    before = ledger(f)
    page = value(inspect(f))
    row = page["rows"][0]
    assert row["admission"]["state"] == "unknown" and row["admission"]["dispatch"] == "unconfirmed"
    assert row["admission"]["usage"] == "verified" and row["admission"]["input_tokens"] == 25
    assert page["coverage"]["attention_total"] == 1 and page["usage"]["admitted_units"] == 0
    assert before == ledger(f) and f.calls == []
    export("actual-activity-unconfirmed.json", page)


def test_old_unknowns_have_independent_oldest_first_pages_not_newest50(current):
    f = current
    at = datetime.now(UTC) - timedelta(days=5)
    ids = []
    for i in range(23):
        stamp = at + timedelta(minutes=i)
        aid, _ = reserve(f, at=stamp, fresh=i > 0)
        with Session(f.engine) as s:
            assert work.claim(
                s, f.box, f.owner, aid, clock=lambda stamp=stamp: stamp + timedelta(seconds=1)
            )
        ids.append(aid)
    for _ in range(51):
        reserve(f, at=datetime.now(UTC) - timedelta(minutes=1), fresh=True)
    before = ledger(f)
    first = value(inspect(f))
    second = value(inspect(f, cursor=first["page"]["next_cursor"]))
    assert [r["admission"]["id"] for r in first["rows"]] == ids[:20]
    assert [r["admission"]["id"] for r in second["rows"]] == ids[20:]
    assert first["coverage"]["attention_total"] == 23 and first["coverage"]["recent_total"] == 51
    assert first["page"]["has_more"] is True and second["page"]["has_more"] is False
    recent = value(inspect(f, "recent"))
    assert len(recent["rows"]) == 20 and recent["page"]["has_more"]
    assert all(r["admission"]["state"] == "abandoned" for r in recent["rows"])
    assert before == ledger(f)
    bad = first["page"]["next_cursor"][:-1] + (
        "0" if first["page"]["next_cursor"][-1] != "0" else "1"
    )
    assert inspect(f, cursor=bad).status_code == 422
    assert inspect(f, "recent", cursor=first["page"]["next_cursor"]).status_code == 422
    export("actual-activity-paging.json", {"first": first, "second": second, "recent": recent})


def test_current_source_revocation_withholds_all_private_row_locators(current):
    f = current
    aid, wid = reserve(f)
    with Session(f.engine) as s:
        s.get(PatientLink, f.patient_link_id).revoked_at = datetime.now(UTC)
        s.commit()
    before = ledger(f)
    page = value(inspect(f))
    assert page["rows"] == [] and page["coverage"]["withheld_total"] == 1
    encoded = json.dumps(page)
    assert aid not in encoded and wid not in encoded
    assert before == ledger(f)
    export("actual-activity-withheld.json", page)


@pytest.mark.parametrize("target", ["identity", "human"])
def test_current_authority_revocation_denies_read(current, target):
    f = current
    reserve(f)
    with Session(f.engine) as s:
        if target == "identity":
            s.get(ExternalIdentity, f.identity_id).active = False
        else:
            s.get(Principal, f.owner).state = "disabled"
        s.commit()
    result = inspect(f)
    assert result.status_code == 403 and result.json() == {"detail": "activity_access_denied"}


def test_final_source_recheck_rejects_independent_revocation(current, monkeypatch):
    f = current
    reserve(f)
    original = work.usage

    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        with Session(f.engine) as s:
            s.get(PatientLink, f.patient_link_id).revoked_at = datetime.now(UTC)
            s.commit()
        return result

    monkeypatch.setattr(work, "usage", revoke)
    result = inspect(f)
    assert result.status_code == 404 and "rows" not in result.json()


def test_application_read_runs_in_actual_read_only_transaction(current):
    f = current
    reserve(f)
    with f.engine.connect() as connection, connection.begin():
        connection.execute(text("SET TRANSACTION READ ONLY"))
        with Session(bind=connection) as s:
            page = activity.read(
                s, f.box, f.owner, view="attention", external_identity_id=f.identity_id
            )
            assert len(page["rows"]) == 1


def test_disabled_model_and_setup_keep_read_only_history_but_feature_off_denies(current):
    f = current
    reserve(f)
    f.configuration.workspace_llm_backend = "none"
    f.configuration.workspace_team_setup_enabled = False
    assert len(value(inspect(f))["rows"]) == 1
    f.activity_state.enabled = False
    result = inspect(f)
    assert result.status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        "query",
        "body",
        "encoding",
        "transfer",
        "wrongteam",
        "missingteam",
        "duplicateteam",
        "wrongrecovery",
        "duplicateauth",
        "cursor",
        "view",
        "post",
    ],
)
def test_exact_http_contract_rejects_without_admission(current, change):
    f = current
    headers = dict(f.activity_headers)
    path = "/provider-team/activity/attention"
    content = None
    method = "GET"
    if change == "query":
        path += "?after=anything"
    if change == "body":
        content = b"{}"
    if change == "encoding":
        headers["Content-Encoding"] = "gzip"
    if change == "transfer":
        headers["Transfer-Encoding"] = "chunked"
    if change == "wrongteam":
        headers["X-Cosmas-Team-Contract"] = "1"
    if change == "missingteam":
        del headers["X-Cosmas-Team-Contract"]
    if change == "duplicateteam":
        headers = list(headers.items()) + [("X-Cosmas-Team-Contract", "2")]
    if change == "wrongrecovery":
        headers["X-Cosmas-Draft-Recovery"] = "1"
    if change == "duplicateauth":
        headers = list(headers.items()) + [("Authorization", headers["Authorization"])]
    if change == "cursor":
        path += "/a1" + "0" * 128
    if change == "view":
        path = "/provider-team/activity/all"
    if change == "post":
        method = "POST"
    before = ledger(f)
    response = f.activity_client.request(method, path, headers=headers, content=content)
    assert response.status_code in {405, 422, 426}, response.text
    assert response.headers["cache-control"] == "no-store" and len(response.content) <= 1024
    assert set(response.json()) == {"detail"} and before == ledger(f) and f.calls == []


def test_peer_and_staff_are_scoped_to_their_own_rows_and_cursors(current):
    f = current
    reserve(f)
    with Session(f.engine) as s:
        people = {}
        for label in ["peer", "staff"]:
            person = Principal(
                box_id=f.box,
                principal_type="human",
                display_name="Invented " + label,
                is_owner=False,
            )
            s.add(person)
            s.flush()
            identity = ExternalIdentity(
                box_id=f.box,
                principal_id=person.id,
                provider="clerk",
                issuer=f.configuration.clerk_issuer,
                subject="user_activity_" + label,
                organization_id=f.configuration.clerk_organization_id,
                reviewed_by="Invented reviewer",
                evidence_ref="synthetic:activity",
            )
            s.add(identity)
            s.flush()
            people[label] = (person.id, identity.id)
        s.commit()
    for label, (actor, _) in people.items():
        headers = {
            **f.activity_headers,
            "Authorization": "Bearer " + f.token(sub="user_activity_" + label),
        }
        page = value(inspect(f, headers=headers))
        assert page["owner_id"] == actor and page["rows"] == []
        assert page["coverage"]["attention_total"] == 0 and f.owner not in json.dumps(page)
    staff, external = people["staff"]
    with Session(f.engine) as s:
        visit = s.get(EncounterWorkspace, f.workspace["id"]).appointment_id
        workspace = ws.create(s, f.box, staff, visit, "invented-staff-private-work")
        team.save(
            s,
            f.box,
            staff,
            expected=0,
            key="invented-staff-team",
            configuration=team.default_configuration(),
        )
        aid, _ = work.reserve_conversation(
            s, f.box, staff, workspace["id"], external_identity_id=external, **command()
        )
    headers = {
        **f.activity_headers,
        "Authorization": "Bearer " + f.token(sub="user_activity_staff"),
    }
    own = value(inspect(f, headers=headers))
    assert [r["admission"]["id"] for r in own["rows"]] == [aid]
    owner = value(inspect(f))
    assert aid not in json.dumps(owner)
    export("actual-activity-private-scopes.json", {"owner": owner, "staff": own})


def test_historical_bot_label_does_not_follow_current_rename(current):
    f = current
    reserve(f)
    old = value(inspect(f))["rows"][0]["bot"]
    with Session(f.engine) as s:
        config = deepcopy(team.current(s, f.box, f.owner).configuration)
        next(b for b in config["bots"] if b["role"] == "visit_prep")["name"] = "New current name"
        team.save(s, f.box, f.owner, expected=1, key="invented-rename", configuration=config)
    page = value(inspect(f))
    assert page["rows"][0]["bot"] == old
    assert page["usage"]["team_revision"] == 2


def test_final_identity_recheck_blocks_stale_signed_session(current, monkeypatch):
    f = current
    reserve(f)
    original = work.usage

    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        with Session(f.engine) as s:
            s.get(ExternalIdentity, f.identity_id).active = False
            s.commit()
        return result

    monkeypatch.setattr(work, "usage", revoke)
    response = inspect(f)
    assert response.status_code == 403 and response.json() == {"detail": "activity_access_denied"}


def test_closed_response_budget_and_whole_request_deadline(current, monkeypatch):
    import time

    f = current
    monkeypatch.setattr(activity, "read", lambda *a, **kw: {"private_untrusted_text": "x" * 65537})
    response = inspect(f)
    assert response.status_code == 503 and "private_untrusted_text" not in response.text

    def delayed(*args, **kwargs):
        time.sleep(0.06)
        return {"private_untrusted_text": "must never disclose late"}

    monkeypatch.setattr(routes, "DEADLINE_SECONDS", 0.01)
    monkeypatch.setattr(activity, "read", delayed)
    response = inspect(f)
    assert response.status_code == 504 and response.json() == {"detail": "activity_timeout"}


def test_scoped_cursor_rejects_cross_owner_without_exposing_anchor(current):
    f = current
    at = datetime.now(UTC) - timedelta(days=1)
    aid, _ = reserve(f, at=at)
    with Session(f.engine) as s:
        row = s.get(ModelWorkAdmission, aid)
        foreign = activity._cursor(f.box, str(uuid4()), "attention", datetime.now(UTC), row)
    response = inspect(f, cursor=foreign)
    assert response.status_code == 422 and aid not in response.text


@pytest.mark.parametrize("character", ["😀", "\u0001"])
def test_maximum_closed_page_text_fits_bounded_utf8_envelope(current, monkeypatch, character):
    f = current
    reserve(f)
    page = value(inspect(f))
    row = page["rows"][0]
    rows = []
    for _ in range(20):
        item = deepcopy(row)
        item["admission"]["id"] = str(uuid4())
        item["bot"]["name"] = character * 40
        item["encounter"]["label"] = character * 200
        rows.append(item)
    page["rows"] = rows
    closed = ActivityResponse.model_validate(page).model_dump(mode="json")
    monkeypatch.setattr(activity, "read", lambda *args, **kwargs: closed)
    response = inspect(f)
    assert response.status_code == 200 and len(response.content) <= 65536
    assert response.json()["rows"][0]["encounter"]["label"] == character * 200
