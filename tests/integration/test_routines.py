from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_shared_work import act, delivered, finish, people
from tests.integration.test_workspace_auth import signed_workspace as signed_workspace

from cosmas_os.api import app as api
from cosmas_os.application import provider_team as team
from cosmas_os.application import routines
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.models import AuditEvent, PatientLink, Principal, RoutineRevision, RoutineRun


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(api.settings, "workspace_enabled", True)
    monkeypatch.setattr(api.settings, "workspace_routines_enabled", True)


def configuration(**changes):
    return {**dict(enabled=True, timezone="UTC", at="08:00", weekdays=[1, 2, 3, 4, 5, 6, 7],
                quiet_start="20:00", quiet_end="07:00", max_runs_per_seven_days=5), **changes}


def save(s, box, owner, **changes):
    return routines.save(s, box, owner, "chief", **{**dict(expected=0, team_revision=1,
                        key="routine-first", configuration=configuration()), **changes})


@pytest.fixture
def scenario(session, seeded, monkeypatch):
    case, item = delivered(session, seeded)
    team.save(session, *case[:2], expected=0, key="team", configuration=team.default_configuration())
    first = save(session, case[0], case[1])
    row = session.scalar(select(RoutineRevision).where(RoutineRevision.agent_id == first["agent_id"]))
    due = row.created_at.astimezone(UTC).replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)
    clock = [due]
    monkeypatch.setattr(routines, "_now", lambda s: clock[0])
    return case, item, first, clock


def test_config_exact_retry_stale_edit_and_pause_do_not_reset_history(session, scenario):
    case, _, first, _ = scenario
    assert save(session, *case[:2])["revision"] == 1
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        save(session, *case[:2], configuration=configuration(at="09:00"))
    with pytest.raises(ws.WorkspaceError, match="routine_revision_conflict"):
        save(session, *case[:2], key="stale")
    disabled = configuration(enabled=False)
    paused = save(session, *case[:2], expected=1, key="pause", configuration=disabled)
    assert paused["status"] == "paused"
    assert save(session, *case[:2])["revision"] == first["revision"]
    assert routines.read(session, *case[:2], "chief")["revision"] == 2
    assert routines.run_once(session, *case[:2], "chief") == {"status": "paused"}


def test_report_reads_real_work_once_keeps_notebook_and_rechecks_sources(session, scenario):
    case, item, _, _ = scenario
    before = ws.read(session, *case[:2], case[2]["id"])["revision"]
    result = routines.run_once(session, *case[:2], "chief")
    assert result["status"] == "completed"
    run = routines.read_run(session, *case[:2], "chief", result["run"]["id"])
    assert run["items"][0]["ticket_id"] == item["ticket_id"] and run["counts"]["open"] == 1
    assert run["model_used"] is False and "Private invented agenda" not in str(run)
    assert routines.run_once(session, *case[:2], "chief")["status"] == "already_run"
    assert ws.read(session, *case[:2], case[2]["id"])["revision"] == before
    finish(session, case, item, case[1])
    # This is a dated observation, not an invented fresh completion claim.
    assert routines.read_run(session, *case[:2], "chief", run["id"])["counts"]["verified_complete"] == 0
    session.get(PatientLink, case[3]).revoked_at = datetime.now(UTC)
    session.commit()
    hidden = routines.read_run(session, *case[:2], "chief", run["id"])
    assert hidden["items"] == [] and hidden["withheld_sources"] and hidden["counts"]["open"] == 0


@pytest.mark.parametrize("change", ["owner", "box", "agent", "disabled"])
def test_private_config_and_history_deny_wrong_or_inactive_principals(session, scenario, change):
    case, _, first, _ = scenario
    run = routines.run_once(session, *case[:2], "chief")["run"]["id"]
    box, owner = case[:2]
    if change == "owner":
        owner = people(session, box)[0]
    elif change == "box":
        box = svc.provision_box(svc.Container(session), "Other invented practice")["box_id"]
    elif change == "agent":
        owner = first["agent_id"]
    else:
        session.get(Principal, owner).state = "disabled"
        session.commit()
    for action in [lambda: routines.read(session, box, owner, "chief"),
                   lambda: routines.read_run(session, box, owner, "chief", run),
                   lambda: routines.run_once(session, box, owner, "chief")]:
        with pytest.raises(ws.WorkspaceError):
            action()


def test_team_changes_require_review_and_custom_bots_need_work_skill(session, scenario):
    case, _, _, _ = scenario
    changed = deepcopy(team.current(session, *case[:2]).configuration)
    custom_id = str(uuid4())
    changed["bots"].append(dict(role="custom", name="Invented coordinator", enabled=True,
        instance_id=custom_id, job_focus="Review practice work", skills=[]))
    team.save(session, *case[:2], expected=1, key="add-custom", configuration=changed)
    assert routines.run_once(session, *case[:2], "chief")["status"] == "team_changed"
    with pytest.raises(ws.WorkspaceError, match="routine_skill_required"):
        routines.save(session, *case[:2], custom_id, expected=0, team_revision=2,
                      key="custom-routine", configuration=configuration())
    changed["bots"][-1]["skills"] = ["work_status"]
    team.save(session, *case[:2], expected=2, key="custom-skill", configuration=changed)
    configured = routines.save(session, *case[:2], custom_id, expected=0, team_revision=3,
                               key="custom-routine", configuration=configuration())
    assert configured["agent_id"] != routines.read(session, *case[:2], "chief")["agent_id"]


def test_rolling_limit_survives_revision_and_time_zone_changes(session, scenario):
    case, _, _, clock = scenario
    # First revision configured with five-run budget; stricter edits must count it.
    routines.run_once(session, *case[:2], "chief")
    save(session, *case[:2], expected=1, key="lower-limit",
         configuration=configuration(max_runs_per_seven_days=1, timezone="Etc/UTC"))
    clock[0] += timedelta(days=1)
    assert routines.run_once(session, *case[:2], "chief")["status"] == "run_limit"
    clock[0] += timedelta(days=6)
    assert routines.run_once(session, *case[:2], "chief")["status"] == "completed"


def test_kill_switch_during_reads_rolls_back_output_and_audit(session, scenario, monkeypatch):
    case, _, _, _ = scenario
    original = routines._snapshot
    def revoke(*args):
        result = original(*args)
        monkeypatch.setattr(api.settings, "workspace_routines_enabled", False)
        return result
    monkeypatch.setattr(routines, "_snapshot", revoke)
    with pytest.raises(ws.WorkspaceError, match="routines_unavailable"):
        routines.run_once(session, *case[:2], "chief")
    session.rollback()
    assert session.scalar(select(func.count()).select_from(RoutineRun).where(RoutineRun.box_id == case[0])) == 0
    assert session.scalar(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.event_type == "routine.brief_completed", AuditEvent.box_id == case[0])) == 0


def test_accepted_staff_handoff_is_visible_without_private_provider_notebook(session, scenario):
    case, item, _, clock = scenario
    staff = people(session, case[0])[0]
    offered = act(session, case, item, case[1], "offer", recipient=staff)
    act(session, case, offered, staff, "accept", offer_id=offered["pending_offer"]["id"])
    team.save(session, case[0], staff, expected=0, key="staff-team", configuration=team.default_configuration())
    save(session, case[0], staff)
    # Configuration happened after the injected clock's date? Use a later day.
    clock[0] += timedelta(days=1)
    result = routines.run_once(session, case[0], staff, "chief")
    report = routines.read_run(session, case[0], staff, "chief", result["run"]["id"])
    assert report["items"][0]["responsible"]["id"] == staff
    assert "Private invented agenda" not in str(report)
    with pytest.raises(ws.WorkspaceError):
        ws.read(session, case[0], staff, case[2]["id"])


def test_database_rejects_history_changes(session, scenario):
    case, _, _, _ = scenario
    result = routines.run_once(session, *case[:2], "chief")
    for statement in [
        "UPDATE routine_runs SET snapshot = '{}'::jsonb",
        "DELETE FROM routine_runs",
        "UPDATE routine_revisions SET configuration = '{}'::jsonb",
        "DELETE FROM routine_revisions",
    ]:
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(text(statement))
    assert routines.read_run(session, *case[:2], "chief", result["run"]["id"])["items"]


def test_signed_api_save_recovery_validation_and_default_off(request, session, monkeypatch):
    case = request.getfixturevalue("signed_workspace")
    monkeypatch.setattr(api.settings, "workspace_routines_enabled", True)
    headers = {"Authorization": "Bearer " + case.token()}
    endpoint = "/provider-team/routines/chief"
    body = {"expected_revision": 0, "team_revision": 1, "idempotency_key": "signed-routine",
            "configuration": configuration()}
    team.save(session, case.box, case.actor, expected=0, key="team", configuration=team.default_configuration())
    first = case.client.post(endpoint, headers=headers, json=body)
    assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
    assert case.client.post(endpoint, headers=headers, json=body).json()["revision"] == 1
    malformed = case.client.post(endpoint, headers=headers, json={**body, "send_messages": True})
    assert malformed.status_code == 422 and "send_messages" not in malformed.text
    assert case.client.get(endpoint).status_code == 401
    assert case.client.get("/provider-team/routines/not-an-id", headers=headers).status_code == 422
    monkeypatch.setattr(api.settings, "workspace_routines_enabled", False)
    assert case.client.get(endpoint, headers=headers).status_code == 404


def test_concurrent_ticks_and_new_session_recover_one_result(engine, monkeypatch):
    with Session(engine) as s:
        seeded = svc.provision_box(svc.Container(s), "Invented routine concurrency")
        case, item = delivered(s, seeded)
        team.save(s, *case[:2], expected=0, key="team", configuration=team.default_configuration())
        first = save(s, *case[:2])
        created = s.scalar(select(RoutineRevision.created_at).where(RoutineRevision.agent_id == first["agent_id"]))
    due = created.replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)
    monkeypatch.setattr(routines, "_now", lambda s: due)
    barrier = Barrier(2)
    def tick():
        with Session(engine) as s:
            barrier.wait(timeout=10)
            return routines.run_once(s, *case[:2], "chief")["status"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: tick(), range(2)))
    assert sorted(outcomes) == ["already_run", "completed"]
    with Session(engine) as s:
        runs = routines.read(s, *case[:2], "chief")["runs"]
        assert len(runs) == 1
        assert routines.read_run(s, *case[:2], "chief", runs[0]["id"])["items"][0]["ticket_id"] == item["ticket_id"]


def test_old_run_cannot_be_read_through_another_bot(session, scenario):
    case, _, _, _ = scenario
    result = routines.run_once(session, *case[:2], "chief")
    with pytest.raises(ws.WorkspaceError, match="routine_run_unavailable"):
        routines.read_run(session, *case[:2], "scribe", result["run"]["id"])


def test_private_computation_creates_no_extra_f8_action_or_notebook_event(session, scenario):
    from cosmas_os.models import Operation, Ticket, WorkspaceEntry
    case, _, _, _ = scenario
    models = [Ticket, Operation, WorkspaceEntry]
    before = [session.scalar(select(func.count()).select_from(model)) for model in models]
    routines.run_once(session, *case[:2], "chief")
    assert [session.scalar(select(func.count()).select_from(model)) for model in models] == before


def test_read_report_caps_details_but_counts_all_authorized_sources(session, scenario, monkeypatch):
    import json
    case, item, _, _ = scenario
    original = routines.shared_work.catalog
    def many(*args, **kwargs):
        page = original(*args, after=None)
        page["items"] = [dict(page["items"][0], body="示" * 4000,
                             responsible={**page["items"][0]["responsible"], "name": "例" * 200}) for _ in range(50)]
        page["next_cursor"] = item["ticket_id"]
        return page
    monkeypatch.setattr(routines.shared_work, "catalog", many)
    result = routines.run_once(session, *case[:2], "chief")
    report = routines.read_run(session, *case[:2], "chief", result["run"]["id"])
    assert report["matching_items"] == 200 and report["counts"]["open"] == 200
    assert len(report["items"]) == 10 and report["truncated"] is True
    assert len(json.dumps(report).encode()) < 32768


@pytest.mark.parametrize("change", ["binding", "switch"])
def test_slow_body_rechecks_identity_and_runtime_switch(request, session, monkeypatch, change):
    from cosmas_os.api import routine_schemas
    case = request.getfixturevalue("signed_workspace")
    monkeypatch.setattr(api.settings, "workspace_routines_enabled", True)
    team.save(session, case.box, case.actor, expected=0, key="team", configuration=team.default_configuration())
    original = api.read_capture_request
    async def revoke(request, schema):
        result = await original(request, schema)
        assert schema is routine_schemas.RoutineSave
        if change == "switch":
            monkeypatch.setattr(api.settings, "workspace_routines_enabled", False)
        else:
            case.binding.active = False
            session.commit()
        return result
    monkeypatch.setattr(api, "read_capture_request", revoke)
    response = case.client.post("/provider-team/routines/chief",
        headers={"Authorization": "Bearer " + case.token()},
        json={"expected_revision": 0, "team_revision": 1, "idempotency_key": "slow-body-once",
              "configuration": configuration()})
    assert response.status_code in {403, 404}
    assert session.scalar(select(func.count()).select_from(RoutineRevision).where(
        RoutineRevision.box_id == case.box)) == 0


@pytest.mark.parametrize("signed_workspace", ["apple", "desktop"], indirect=True)
def test_native_origins_read_and_pause_same_private_routine(signed_workspace, session, monkeypatch):
    case = signed_workspace
    monkeypatch.setattr(api.settings, "workspace_routines_enabled", True)
    team.save(session, case.box, case.actor, expected=0, key="native-team", configuration=team.default_configuration())
    headers = {"Authorization": "Bearer " + case.token(), "Origin": case.configuration.clerk_authorized_parties}
    endpoint = "/provider-team/routines/chief"
    body = {"expected_revision": 0, "team_revision": 1, "idempotency_key": "native-routine",
            "configuration": configuration()}
    first = case.client.post(endpoint, headers=headers, json=body)
    assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
    read = case.client.get(endpoint, headers=headers)
    assert read.status_code == 200 and read.json()["revision"] == 1
    paused = case.client.post(endpoint, headers=headers, json={**body, "expected_revision": 1,
        "idempotency_key": "native-pause", "configuration": configuration(enabled=False)})
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    case.binding.active = False
    session.commit()
    assert case.client.get(endpoint, headers=headers).status_code == 403
