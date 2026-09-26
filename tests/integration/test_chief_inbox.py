"""Actual migrated PostgreSQL and offline signed main-app Chief brief reads."""

import json
import os
from copy import deepcopy
from datetime import UTC, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from tests.integration import test_inbox_handoff as ih
from tests.integration import test_inbox_work as iw
from tests.integration.test_routines import configuration
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case
from tests.integration.test_workspace_auth import signed_workspace as signed_workspace

from cosmas_os.api import app as api
from cosmas_os.application import provider_team, routine_inbox, routines, shared_work
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import ExternalIdentity, Principal, RoutineRevision, RoutineRun


@pytest.fixture
def chief(signed_workspace, session, monkeypatch):
    f = signed_workspace
    f.configuration.workspace_routines_enabled = True
    f.configuration.inbox_work_enabled = True
    f.configuration.inbox_handoff_enabled = True
    f.configuration.database_url = os.environ["DATABASE_URL"]
    monkeypatch.setattr(routines, "settings", f.configuration)
    c = vendor_case.__wrapped__(session, {"box_id": f.box, "owner_id": f.actor})
    c = iw.inbox_case.__wrapped__(session, c)
    c = ih.case.__wrapped__(session, c)
    for actor, sub in [(c["staff"], "chief_staff"), (c["peer"], "chief_peer")]:
        session.add(ExternalIdentity(box_id=f.box, principal_id=actor, provider="clerk",
            issuer=f.configuration.clerk_issuer, subject=sub, organization_id="org_invented",
            reviewed_by="Invented reviewer", evidence_ref="test:chief-inbox"))
    session.commit()
    for actor in [f.actor, c["staff"], c["peer"]]:
        provider_team.save(session, f.box, actor, expected=0, key="chief-team-" + actor,
            configuration=provider_team.default_configuration())
        routines.save(session, f.box, actor, "chief", expected=0, team_revision=1,
            key="chief-schedule-" + actor, configuration=configuration())
    latest = session.scalar(select(func.max(RoutineRevision.created_at)).where(RoutineRevision.box_id == f.box))
    f.clock = [latest.astimezone(UTC).replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)]
    monkeypatch.setattr(routines, "_now", lambda _: f.clock[0])
    api.app.dependency_overrides[api._inbox_registry] = lambda: c["registry"]
    api.app.dependency_overrides[api._inbox_handoff_policy] = lambda: ih.ON
    f.c, f.session = c, session
    try:
        yield f
    finally:
        api.app.dependency_overrides.pop(api._inbox_registry, None)
        api.app.dependency_overrides.pop(api._inbox_handoff_policy, None)


def run(f, actor=None, *, legacy=False):
    out = routines.run_once(f.session, f.box, actor or f.actor, "chief",
        incoming_sources=None if legacy else api._routine_sources())
    assert out["status"] == "completed", out
    return out["run"]["id"]


def headers(f, actor=None):
    return {"Authorization": "Bearer " + f.token(sub="chief_staff" if actor == f.c["staff"] else
            "chief_peer" if actor == f.c["peer"] else "user_invented"),
        "X-Cosmas-Draft-Recovery": "2", "X-Cosmas-Routine-Contract": "2"}


def read(f, rid, actor=None):
    reply = f.client.get("/provider-team/routines/chief/runs/" + rid, headers=headers(f, actor))
    assert reply.status_code == 200, reply.text
    assert reply.headers["cache-control"] == "no-store" and len(reply.content) <= 32768
    return reply.json()


def export(name, body):
    root = Path(os.environ["ROUTINE_EVIDENCE_ROOT"]) / ("evidence-" + os.environ["ROUTINE_EVIDENCE_LABEL"])
    root.mkdir(exist_ok=True)
    (root / name).write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n")


def test_signed_owner_pending_and_recipient_published_briefs(chief):
    f, c = chief, chief.c
    tid = ih.propose(f.session, c)["effect"]["ticket_id"]
    rid = run(f)
    owner = read(f, rid)
    assert owner["incoming"]["counts"]["pending_approval"] == 1
    assert owner["incoming"]["items"][0]["body"] == c["q"].instructions
    assert owner["incoming"]["coverage"] == "complete"
    staff_id = run(f, c["staff"])
    staff = read(f, staff_id, c["staff"])
    assert staff["incoming"]["items"] == [] and staff["incoming"]["coverage"] == "unavailable"
    assert f.client.get("/provider-team/routines/chief/runs/" + rid,
        headers=headers(f, c["peer"])).status_code == 404
    text = json.dumps(owner)
    for secret in ["PRIVATE:", c["q"].selected_context, c["iid"], str(c["grant"].grant_id), c["q"].source_id]:
        assert secret not in text
    assert shared_work.catalog(f.session, f.box, f.actor, vendor=True)["items"] == []
    export("actual-chief-pending.json", {"owner": owner, "staff": staff, "ticket_id": tid})


@pytest.mark.parametrize("state", ["offered", "accepted", "result", "verified"])
def test_dated_incoming_state_and_receipt_meanings(chief, state):
    f, c = chief, chief.c
    tid = ih.published(f.session, c)
    offered, _ = ih.command(f.session, c, tid, "handoff", kind="offer", recipient_id=c["staff"])
    if state != "offered":
        ih.command(f.session, c, tid, "handoff", actor=c["staff"], kind="accept",
            offer_id=offered["effect"]["effect_id"])
    if state in {"result", "verified"}:
        ih.command(f.session, c, tid, "result", actor=c["staff"],
            evidence="Invented local administrative result, no patient reply claimed.", no_external_action_claimed=True)
    if state == "verified":
        d = ih.read(f.session, c, tid)
        ih.command(f.session, c, tid, "verify", result_receipt_id=d["result"]["receipt_id"],
            result_request_sha256=d["result"]["request_sha256"], reviewed_current_source=True,
            reviewed_result=True, local_handoff_only=True)
    rid = run(f)
    report = read(f, rid)
    counts = report["incoming"]["counts"]
    assert counts["awaiting_acceptance"] == int(state == "offered")
    assert counts["awaiting_review"] == int(state == "result")
    assert counts["verified_complete"] == int(state == "verified")
    assert counts["open"] == int(state != "verified")
    staff = read(f, run(f, c["staff"]), c["staff"])
    assert staff["incoming"]["items"][0]["ticket_id"] == tid
    export("actual-chief-" + state + ".json", {"owner": report, "staff": staff})


@pytest.mark.parametrize("change", ["registry", "source", "review", "responsible"])
def test_saved_brief_rechecks_current_authority_without_rewriting_history(chief, change):
    f, c = chief, chief.c
    ih.accepted(f.session, c)
    rid = run(f)
    before = deepcopy(f.session.get(RoutineRun, rid).snapshot)
    digest = f.session.get(RoutineRun, rid).snapshot_hash
    if change == "registry":
        c["registry_state"]["registry"] = iw.flow.InboxRegistry()
    elif change == "source":
        iw.ingest(f.session, c, iw.snapshot(c, 20, text_="PRIVATE: changed body"))
    elif change == "review":
        iw.review(f.session, c, c["iid"])
    else:
        f.session.get(Principal, c["staff"]).state = "inactive"
        f.session.commit()
    value = read(f, rid)["incoming"]
    if change == "responsible":
        assert value["counts"]["responsible_unavailable"] == 1
    else:
        assert value["coverage"] == "partial"
        assert value["counts"]["source_unavailable"] == 1
        assert value["items"][0]["body"] is None
        assert value["items"][0]["responsible"]["id"] == c["staff"]
        assert value["counts"]["verified_complete"] == 0
    row = f.session.get(RoutineRun, rid)
    assert row.snapshot == before and row.snapshot_hash == digest == payload_hash(before)


def test_legacy_report_and_old_client_negotiation(chief):
    f = chief
    rid = run(f, legacy=True)
    row = f.session.get(RoutineRun, rid)
    before = deepcopy(row.snapshot), row.snapshot_hash
    assert read(f, rid)["incoming"]["coverage"] == "not_included"
    old = headers(f)
    old.pop("X-Cosmas-Routine-Contract")
    assert f.client.get("/provider-team/routines/chief/runs/" + rid, headers=old).status_code == 200
    assert (row.snapshot, row.snapshot_hash) == before
    f.clock[0] += timedelta(days=1)
    v2 = run(f)
    assert f.client.get("/provider-team/routines/chief/runs/" + v2, headers=old).status_code == 426
    path = "/provider-team/routines/chief/runs/" + v2
    for bad in ["1", "3", "2,2", "", " 2"]:
        assert f.client.get(path, headers={**headers(f), "X-Cosmas-Routine-Contract": bad}).status_code == 426
    assert f.client.get(path, headers=[*old.items(), ("X-Cosmas-Routine-Contract", "2"),
        ("X-Cosmas-Routine-Contract", "2")]).status_code == 426
    assert f.client.get(path + "?unexpected=1", headers=headers(f)).status_code == 422


def test_saved_read_final_signed_identity_revocation_withholds_everything(chief, monkeypatch):
    f = chief
    ih.accepted(f.session, f.c)
    rid = run(f)
    original = routine_inbox.reauthorize
    def revoked(*args, **kwargs):
        out = original(*args, **kwargs)
        f.binding.active = False
        f.session.commit()
        return out
    monkeypatch.setattr(routine_inbox, "reauthorize", revoked)
    response = f.client.get("/provider-team/routines/chief/runs/" + rid, headers=headers(f))
    assert response.status_code == 403 and "Please review" not in response.text


@pytest.mark.parametrize("change", ["registry", "policy"])
def test_saved_read_final_source_fence_rejects_revocation_after_projection(chief, monkeypatch, change):
    f = chief
    ih.accepted(f.session, f.c)
    rid = run(f)
    original = routine_inbox.reauthorize
    def revoke_after_projection(*args, **kwargs):
        value = original(*args, **kwargs)
        if change == "registry":
            f.c["registry_state"]["registry"] = iw.flow.InboxRegistry()
        else:
            api.app.dependency_overrides[api._inbox_handoff_policy] = ih.flow.Policy
        return value
    monkeypatch.setattr(routine_inbox, "reauthorize", revoke_after_projection)
    response = f.client.get("/provider-team/routines/chief/runs/" + rid, headers=headers(f))
    assert response.status_code == 409 and "Please review" not in response.text and "incoming" not in response.json()


def test_duplicate_tick_preserves_one_immutable_version2_run(chief):
    f = chief
    ih.accepted(f.session, f.c)
    rid = run(f)
    snapshot = deepcopy(f.session.get(RoutineRun, rid).snapshot)
    assert routines.run_once(f.session, f.box, f.actor, "chief", incoming_sources=api._routine_sources())["status"] == "already_run"
    assert f.session.scalar(select(func.count()).select_from(RoutineRun).where(RoutineRun.owner_id == f.actor)) == 1
    assert f.session.get(RoutineRun, rid).snapshot == snapshot


def test_real_catalog_limit_is_unknown_not_zero(chief):
    f, c = chief, chief.c
    # Each originator is capped at100 proposals; an authorized recipient can
    # legitimately accumulate more than100 offers across multiple originators.
    for number in range(100):
        tid = ih.propose(f.session, c, q=c["q"].model_copy(update={"idempotency_key": "chief-limit-" + str(number)}))["effect"]["ticket_id"]
        ih.command(f.session, c, tid, "decide", choice="approve", publish_selected_context=True)
        ih.command(f.session, c, tid, "handoff", kind="offer", recipient_id=c["staff"])
    person = Principal(box_id=f.box, principal_type="human", display_name="Invented second originator", state="active", is_owner=True)
    f.session.add(person)
    f.session.commit()
    second = vendor_case.__wrapped__(f.session, {"box_id": f.box, "owner_id": person.id})
    second = ih.case.__wrapped__(f.session, iw.inbox_case.__wrapped__(f.session, second))
    tid = ih.published(f.session, second)
    ih.command(f.session, second, tid, "handoff", kind="offer", recipient_id=c["staff"])
    report = read(f, run(f, c["staff"]), c["staff"])
    assert report["incoming"] == {"coverage": "unavailable", "reason": "collection_limit", "items": [],
        "matching_items": 0, "counts": None, "withheld_sources": True}


def test_fair_display_uses_real_private_and_published_lanes(chief):
    from tests.integration.test_routine_lane_integration import approved_vendor

    f, c = chief, chief.c
    for number in range(7):
        ih.propose(f.session, c, q=c["q"].model_copy(update={"idempotency_key": "chief-fair-" + str(number)}))
        approved_vendor(f, c, "Invented shared delivery " + str(number))
    report = read(f, run(f))
    assert len(report["incoming"]["items"]) == len(report["generic"]["items"]) == 5
    assert report["incoming"]["matching_items"] == report["generic"]["matching_items"] == 7
    assert report["incoming"]["counts"]["pending_approval"] == 7
    assert report["generic"]["counts"]["open"] == 7
    export("actual-chief-fair.json", {"owner": report})


def test_later_human_result_is_work_change_not_false_source_revocation(chief):
    f, c = chief, chief.c
    tid = ih.accepted(f.session, c)
    rid = run(f)
    ih.command(f.session, c, tid, "result", actor=c["staff"],
        evidence="Invented subsequent local result", no_external_action_claimed=True)
    report = read(f, rid)
    section = report["incoming"]
    assert section["reason"] == "work_changed" and section["counts"]["work_changed"] == 1
    assert section["counts"]["source_unavailable"] == 0
    assert section["items"][0]["state"] == "work_changed" and section["items"][0]["body"] is None
    assert not section["items"][0]["requires_owner_attention"]
    export("actual-chief-changed.json", {"owner": report})


def test_expired_grant_never_retains_verified_completion(chief, monkeypatch):
    f, c = chief, chief.c
    tid = ih.accepted(f.session, c)
    ih.command(f.session, c, tid, "result", actor=c["staff"], evidence="Invented finished task", no_external_action_claimed=True)
    d = ih.read(f.session, c, tid)
    ih.command(f.session, c, tid, "verify", result_receipt_id=d["result"]["receipt_id"],
        result_request_sha256=d["result"]["request_sha256"], reviewed_current_source=True,
        reviewed_result=True, local_handoff_only=True)
    rid = run(f)
    assert read(f, rid)["incoming"]["counts"]["verified_complete"] == 1
    monkeypatch.setattr(iw.flow.common, "_clock", lambda _: c["grant"].expires_at)
    value = read(f, rid)["incoming"]
    assert value["counts"]["verified_complete"] == 0 and value["counts"]["source_unavailable"] == 1
    assert value["items"][0]["verification_receipt_id"] is None
    export("actual-chief-unavailable.json", {"owner": read(f, rid)})


@pytest.mark.parametrize("reason", ["registry", "feature"])
def test_preexisting_unavailable_source_saves_an_honest_partial_brief(chief, reason):
    f, c = chief, chief.c
    ih.accepted(f.session, c)
    if reason == "registry":
        c["registry_state"]["registry"] = iw.flow.InboxRegistry()
    else:
        api.app.dependency_overrides[api._inbox_handoff_policy] = ih.flow.Policy
    rid = run(f)
    row = f.session.get(RoutineRun, rid)
    assert row.snapshot["incoming"]["coverage"] == "partial"
    report = read(f, rid)["incoming"]
    assert report["items"][0]["body"] is None and report["counts"]["source_unavailable"] == 1
    assert report["items"][0]["changed_since_report"] is False


def test_server_supplier_refreshes_and_commit_rechecks_scope(chief, monkeypatch):
    f, c = chief, chief.c
    ih.accepted(f.session, c)
    sources = api._routine_sources()
    assert sources.policy().enabled and sources.registry().grants
    api.app.dependency_overrides[api._inbox_registry] = lambda: iw.flow.no_registry
    assert not sources.registry().grants
    api.app.dependency_overrides[api._inbox_registry] = lambda: c["registry"]
    original = routine_inbox.snapshot
    def revoke_after_observation(*args, **kwargs):
        value = original(*args, **kwargs)
        c["registry_state"]["registry"] = iw.flow.InboxRegistry()
        return value
    monkeypatch.setattr(routine_inbox, "snapshot", revoke_after_observation)
    with pytest.raises(ws.WorkspaceError, match="routine_sources_changed"):
        routines.run_once(f.session, f.box, f.actor, "chief", incoming_sources=sources)
    assert f.session.scalar(select(func.count()).select_from(RoutineRun).where(RoutineRun.owner_id == f.actor)) == 0


def test_routine_switch_revocation_during_last_source_pass_prevents_commit(chief, monkeypatch):
    f = chief
    ih.accepted(f.session, f.c)
    original = routine_inbox.reauthorize
    def revoke_last(*args, **kwargs):
        value = original(*args, **kwargs)
        f.configuration.workspace_routines_enabled = False
        return value
    monkeypatch.setattr(routine_inbox, "reauthorize", revoke_last)
    with pytest.raises(ws.WorkspaceError, match="routines_unavailable"):
        routines.run_once(f.session, f.box, f.actor, "chief", incoming_sources=api._routine_sources())
    assert f.session.scalar(select(func.count()).select_from(RoutineRun).where(RoutineRun.owner_id == f.actor)) == 0


def test_main_app_exact_header_cors_and_body_boundary(chief):
    f = chief
    rid = run(f)
    path = "/provider-team/routines/chief/runs/" + rid
    origin = f.configuration.allowed_origins[0]
    preflight = f.client.options(path, headers={"Origin": origin, "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization,x-cosmas-draft-recovery,x-cosmas-routine-contract"})
    assert preflight.status_code == 200
    assert "x-cosmas-routine-contract" in preflight.headers["access-control-allow-headers"].lower()
    response = f.client.get(path, headers={**headers(f), "Origin": origin})
    assert response.status_code == 200 and response.headers["access-control-allow-origin"] == origin
    for extra in [{"Content-Encoding": "gzip"}, {"Content-Encoding": ""}, {"Content-Length": "1"},
            {"Transfer-Encoding": "chunked"}]:
        assert f.client.get(path, headers={**headers(f), **extra}).status_code == 422
    for other in ["/provider-team", "/provider-team/routines/chief", "/practice-work"]:
        denied = f.client.get(other, headers={**headers(f), "Origin": origin})
        assert denied.status_code == 426 and denied.headers["cache-control"] == "no-store"
        assert denied.headers["access-control-allow-origin"] == origin
    assert f.client.post(path, headers=headers(f), json={}).status_code == 426
    bad_origin = f.client.options(path, headers={"Origin": "https://unapproved.invalid",
        "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "x-cosmas-routine-contract"})
    assert bad_origin.status_code == 400 and "access-control-allow-origin" not in bad_origin.headers


def test_actual_independent_sessions_and_worker_keep_one_version2_run(engine, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.orm import Session

    from cosmas_os.application import services

    monkeypatch.setattr(routines.settings, "workspace_routines_enabled", True)
    with Session(engine) as s:
        seed = services.provision_box(services.Container(s), "Invented Chief concurrency")
        c = vendor_case.__wrapped__(s, seed)
        c = ih.case.__wrapped__(s, iw.inbox_case.__wrapped__(s, c))
        ih.accepted(s, c)
        provider_team.save(s, c["box"], c["actor"], expected=0, key="worker-team",
            configuration=provider_team.default_configuration())
        saved = routines.save(s, c["box"], c["actor"], "chief", expected=0, team_revision=1,
            key="worker-routine", configuration=configuration())
        created = s.scalar(select(RoutineRevision.created_at).where(RoutineRevision.agent_id == saved["agent_id"]))
    due = created.replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)
    monkeypatch.setattr(routines, "_now", lambda _: due)
    sources = routine_inbox.Sources(c["registry"], lambda: ih.ON)
    barrier = Barrier(2)
    def tick(_):
        with Session(engine) as s:
            barrier.wait(timeout=10)
            return routines.run_once(s, c["box"], c["actor"], "chief", incoming_sources=sources)["status"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(tick, range(2))) == ["already_run", "completed"]
    routines.process_batch(lambda: Session(engine), incoming_sources=sources)
    with Session(engine) as s:
        runs = list(s.scalars(select(RoutineRun).where(RoutineRun.owner_id == c["actor"])))
        assert len(runs) == 1 and runs[0].snapshot["snapshot_version"] == 2
        readback = routines.read_run(s, c["box"], c["actor"], "chief", runs[0].id, contract=2, incoming_sources=sources)
        assert readback["incoming"]["counts"]["open"] == 1
