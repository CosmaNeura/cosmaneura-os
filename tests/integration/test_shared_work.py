from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from cosmas_os.api import app as api
from cosmas_os.application import services as svc
from cosmas_os.application import shared_work as work
from cosmas_os.application import workspace as ws
from cosmas_os.models import AuditEvent, ExternalIdentity, FollowUpReceipt, PatientLink, Principal, WorkHandoff
from tests.integration.test_follow_up import complete, decide, prepare, propose
from tests.integration.test_workspace_auth import signed_workspace


@pytest.fixture(autouse=True)
def enable(monkeypatch):
    monkeypatch.setattr(api.settings, "workspace_enabled", True)


def people(s, box):
    values = [Principal(box_id=box, principal_type="human", display_name="Invented " + name,
        state="active", is_owner=False) for name in ["recipient", "colleague"]]
    s.add_all(values)
    s.commit()
    return [p.id for p in values]


def delivered(s, seed):
    case = prepare(s, seed)
    item = propose(s, case)["workspace"]["follow_ups"][0]
    decide(s, case, item)
    return case, work.read(s, case[0], case[1], item["ticket_id"])


@pytest.fixture
def scenario(session, seeded):
    case, item = delivered(session, seeded)
    staff, other = people(session, case[0])
    return case, item, staff, other


def act(s, case, item, actor, kind, **changes):
    return work.act(s, case[0], actor, item["ticket_id"], **{
        "expected": item["version"], "revision_id": item["revision_id"], "digest": item["payload_hash"],
        "key": str(uuid4()), "kind": kind, **changes})


def finish(s, case, item, actor, **changes):
    return work.complete(s, case[0], actor, item["ticket_id"], **{
        "revision_id": item["revision_id"], "digest": item["payload_hash"], "key": "verified-outcome",
        "evidence": "Invented recipient confirmed that the requested visit was arranged.", **changes})


def test_offer_keeps_provider_responsible_until_explicit_acceptance(session, scenario):
    case, item, staff, other = scenario
    assert work.catalog(session, case[0], staff)["items"] == []
    offered = act(session, case, item, case[1], "offer", recipient=staff, key="offer-once")
    assert offered["responsible"]["id"] == case[1]
    assert offered["pending_offer"]["to"]["id"] == staff
    with pytest.raises(ws.WorkspaceError, match="responsibility_required"):
        finish(session, case, offered, staff)
    assert act(session, case, item, case[1], "offer", recipient=staff, key="offer-once") == offered
    shared = work.read(session, case[0], staff, item["ticket_id"])
    assert "Private invented agenda" not in str(shared)
    assert not {"workspace_id", "note_id", "note_version", "source_fingerprint", "target_ref"} & set(shared)
    assert shared["body"] == item["body"]
    with pytest.raises(ws.WorkspaceError):
        ws.read(session, case[0], staff, case[2]["id"])
    with pytest.raises(ws.WorkspaceError, match="unavailable"):
        work.read(session, case[0], other, item["ticket_id"])
    accepted = act(session, case, offered, staff, "accept", offer_id=offered["pending_offer"]["id"], key="accept-once")
    assert accepted["responsible"]["id"] == staff and accepted["pending_offer"] is None
    assert act(session, case, offered, staff, "accept", offer_id=offered["pending_offer"]["id"], key="accept-once") == accepted
    with pytest.raises(ws.WorkspaceError, match="responsibility_required"):
        complete(session, case, item)
    closed = finish(session, case, accepted, staff)
    assert closed["state"] == "closed" and closed["receipts"][-1]["actor"]["id"] == staff
    assert finish(session, case, accepted, staff) == closed
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        finish(session, case, accepted, case[1])
    audit = session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == item["ticket_id"],
        AuditEvent.event_type == "follow_up.human_completion"))
    assert audit.actor_principal_id == staff


def test_exact_offer_recovery_after_recipient_revocation_returns_history_without_new_authority(session, scenario):
    case, item, staff, other = scenario
    offered = act(session, case, item, case[1], "offer", recipient=staff, key="lost-offer-reply")
    session.get(Principal, staff).state = "disabled"
    session.commit()
    recovered = act(session, case, item, case[1], "offer", recipient=staff, key="lost-offer-reply")
    assert recovered["pending_offer"]["id"] == offered["pending_offer"]["id"]
    assert not recovered["pending_offer"]["to"]["available"]
    assert recovered["responsible"]["id"] == case[1] and len(recovered["handoffs"]) == 1
    with pytest.raises(ws.WorkspaceError, match="recipient_unavailable"):
        act(session, case, recovered, case[1], "offer", recipient=staff, key="new-offer-for-revoked")
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        act(session, case, item, case[1], "offer", recipient=other, key="lost-offer-reply")
    session.get(Principal, case[1]).state = "disabled"
    session.commit()
    with pytest.raises(ws.WorkspaceError, match="access_denied"):
        act(session, case, item, case[1], "offer", recipient=staff, key="lost-offer-reply")


@pytest.mark.parametrize("response", ["decline", "recall"])
def test_closed_offer_cannot_be_accepted_late_and_can_be_offered_again(session, scenario, response):
    case, item, staff, _ = scenario
    offered = act(session, case, item, case[1], "offer", recipient=staff)
    oid = offered["pending_offer"]["id"]
    responded = act(session, case, offered, staff if response == "decline" else case[1], response, offer_id=oid)
    assert responded["pending_offer"] is None and responded["responsible"]["id"] == case[1]
    with pytest.raises(ws.WorkspaceError, match="offer_changed"):
        act(session, case, responded, staff, "accept", offer_id=oid)
    repeated = act(session, case, responded, case[1], "offer", recipient=staff)
    assert repeated["pending_offer"]["id"] != oid


def test_reclaim_from_revoked_staff_preserves_payload_and_closes_pending_offer(session, scenario):
    case, item, staff, other = scenario
    offered = act(session, case, item, case[1], "offer", recipient=staff)
    accepted = act(session, case, offered, staff, "accept", offer_id=offered["pending_offer"]["id"])
    onward = act(session, case, accepted, staff, "offer", recipient=other)
    session.get(Principal, staff).state = "disabled"
    session.commit()
    with pytest.raises(ws.WorkspaceError, match="access_denied"):
        finish(session, case, onward, staff)
    assert not work.read(session, case[0], case[1], item["ticket_id"])["responsible"]["available"]
    reclaimed = act(session, case, onward, case[1], "reclaim")
    assert reclaimed["responsible"]["id"] == case[1] and reclaimed["pending_offer"] is None
    assert reclaimed["revision_id"] == item["revision_id"] and reclaimed["payload_hash"] == item["payload_hash"]
    with pytest.raises(ws.WorkspaceError, match="offer_changed"):
        act(session, case, reclaimed, other, "accept", offer_id=onward["pending_offer"]["id"])
    assert finish(session, case, reclaimed, case[1])["state"] == "closed"


def test_completion_expires_pending_offer_without_transferring_responsibility(session, scenario):
    case, item, staff, _ = scenario
    offered = act(session, case, item, case[1], "offer", recipient=staff)
    closed = finish(session, case, offered, case[1])
    assert closed["pending_offer"] is None
    with pytest.raises(ws.WorkspaceError, match="delivery_required"):
        act(session, case, closed, staff, "accept", offer_id=offered["pending_offer"]["id"])


@pytest.mark.parametrize("change", ["revision", "hash", "version", "key", "agent", "other_box", "patient", "staff"])
def test_stale_or_unauthorized_handoff_cannot_change_work(session, scenario, change):
    case, item, staff, _ = scenario
    altered = dict(item)
    args = {"recipient": staff, "key": "stable-offer"}
    if change == "revision": altered["revision_id"] = str(uuid4())
    if change == "hash": altered["payload_hash"] = "0" * 64
    if change == "version": altered["version"] += 1
    if change == "key":
        act(session, case, item, case[1], "offer", **args)
        altered["version"] += 1
    if change == "agent": session.get(Principal, staff).principal_type = "agent"
    if change == "staff": session.get(Principal, staff).tombstoned_at = datetime.now(UTC)
    if change == "other_box": args["recipient"] = svc.provision_box(svc.Container(session), "Other invented Box")["owner_id"]
    if change == "patient": session.get(PatientLink, case[3]).revoked_at = datetime.now(UTC)
    session.commit()
    before = session.scalar(select(func.count()).select_from(WorkHandoff).where(WorkHandoff.ticket_id == item["ticket_id"]))
    with pytest.raises(ws.WorkspaceError) as error:
        act(session, case, altered, case[1], "offer", **args)
    if change in {"staff", "agent", "other_box"}:
        assert error.value.status == 409 and error.value.code == "shared_work_recipient_unavailable"
    assert session.scalar(select(func.count()).select_from(WorkHandoff).where(WorkHandoff.ticket_id == item["ticket_id"])) == before


def test_only_delivered_work_can_be_offered(session, seeded):
    case = prepare(session, seeded)
    item = propose(session, case)["workspace"]["follow_ups"][0]
    staff, _ = people(session, case[0])
    pending = work.read(session, case[0], case[1], item["ticket_id"])
    with pytest.raises(ws.WorkspaceError, match="delivery_required"):
        act(session, case, pending, case[1], "offer", recipient=staff)


def test_handoff_history_rejects_update_and_delete(session, scenario):
    case, item, staff, _ = scenario
    offered = act(session, case, item, case[1], "offer", recipient=staff)
    for statement in ["UPDATE work_handoffs SET kind = 'recall' WHERE id = :id", "DELETE FROM work_handoffs WHERE id = :id"]:
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(text(statement), {"id": offered["pending_offer"]["id"]})


def test_bounded_handoff_history_keeps_provider_reclaim_and_completion_available(session, scenario):
    case, item, staff, other = scenario
    offered = act(session, case, item, case[1], "offer", recipient=staff)
    current = act(session, case, offered, staff, "accept", offer_id=offered["pending_offer"]["id"])
    for _ in range(99):
        offered = act(session, case, current, staff, "offer", recipient=other)
        current = act(session, case, offered, other, "decline", offer_id=offered["pending_offer"]["id"])
    assert len(current["handoffs"]) == 200
    with pytest.raises(ws.WorkspaceError, match="history_limit"):
        act(session, case, current, staff, "offer", recipient=other)
    session.get(Principal, staff).state = "disabled"
    session.commit()
    reclaimed = act(session, case, current, case[1], "reclaim")
    assert len(reclaimed["handoffs"]) == 201 and reclaimed["responsible"]["id"] == case[1]
    assert finish(session, case, reclaimed, case[1])["state"] == "closed"


@pytest.mark.parametrize("competing", ["accept", "recall", "complete"])
def test_concurrent_acceptance_retries_and_competing_actions_are_serialized(engine, competing):
    with Session(engine) as s:
        case, item = delivered(s, svc.provision_box(svc.Container(s), "Invented handoff race"))
        staff, _ = people(s, case[0])
        offered = act(s, case, item, case[1], "offer", recipient=staff)
        oid = offered["pending_offer"]["id"]
    barrier = Barrier(2)
    def run(index):
        with Session(engine) as s:
            barrier.wait(timeout=10)
            try:
                if index == 0 or competing == "accept":
                    return act(s, case, offered, staff, "accept", offer_id=oid, key="race-accept")["state"]
                if competing == "recall":
                    return act(s, case, offered, case[1], "recall", offer_id=oid)["state"]
                return finish(s, case, offered, case[1])["state"]
            except ws.WorkspaceError:
                return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(run, [0, 1]))
    assert result == ["sent", "sent"] if competing == "accept" else result.count("conflict") == 1
    with Session(engine) as s:
        current = work.read(s, case[0], case[1], item["ticket_id"])
        assert len(current["handoffs"]) == (1 if current["state"] == "closed" else 2)
        assert s.scalar(select(func.count()).select_from(FollowUpReceipt).where(
            FollowUpReceipt.ticket_id == item["ticket_id"], FollowUpReceipt.kind == "human_completion")) <= 1


@pytest.mark.parametrize("signed_workspace", ["apple", "desktop"], indirect=True)
def test_two_signed_humans_share_work_without_private_workspace_access(session, signed_workspace):
    signed = signed_workspace
    case, item = delivered(session, {"box_id": signed.box, "owner_id": signed.actor})
    staff, _ = people(session, signed.box)
    binding = ExternalIdentity(box_id=signed.box, principal_id=staff, provider="clerk",
        issuer=signed.configuration.clerk_issuer, subject="user_w14_staff", organization_id="org_invented",
        reviewed_by="Invented reviewer", evidence_ref="test:w14-synthetic-binding")
    session.add(binding)
    session.commit()
    headers = {"Authorization": "Bearer " + signed.token(), "Origin": signed.configuration.authorized_parties[0]}
    staff_headers = {**headers, "Authorization": "Bearer " + signed.token(sub="user_w14_staff")}
    endpoint = "/practice-work/" + item["ticket_id"]
    assert signed.client.get(endpoint, headers=staff_headers).status_code == 404
    offer_body = {"expected_version": item["version"], "revision_id": item["revision_id"],
        "payload_hash": item["payload_hash"], "idempotency_key": "signed-offer", "kind": "offer", "recipient_id": staff}
    result = signed.client.post(endpoint + "/handoffs", headers=headers, json=offer_body)
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    offer = result.json()
    assert signed.client.post(endpoint + "/handoffs", headers=headers, json=offer_body).json() == offer
    page = signed.client.get("/practice-work", headers=staff_headers)
    assert page.status_code == 200 and page.json()["items"][0]["ticket_id"] == item["ticket_id"]
    assert "Private invented agenda" not in page.text and "workspace_id" not in page.text
    assert signed.client.get("/workspaces/" + case[2]["id"], headers=staff_headers).status_code == 404
    accepted = signed.client.post(endpoint + "/handoffs", headers=staff_headers, json={
        **offer_body, "expected_version": offer["version"], "kind": "accept", "recipient_id": None,
        "offer_id": offer["pending_offer"]["id"], "idempotency_key": "signed-accept"})
    assert accepted.status_code == 200 and accepted.json()["responsible"]["id"] == staff
    done = {"revision_id": item["revision_id"], "payload_hash": item["payload_hash"],
        "idempotency_key": "signed-complete", "evidence": "Invented status confirmed directly."}
    assert signed.client.post(endpoint + "/complete", headers=headers, json=done).status_code == 409
    invalid = signed.client.post(endpoint + "/complete", headers=staff_headers, json={**done, "private_note": "Must not reflect this text"})
    assert invalid.status_code == 422 and "Must not reflect" not in invalid.text
    assert invalid.headers["cache-control"] == "no-store"
    finished = signed.client.post(endpoint + "/complete", headers=staff_headers, json=done)
    assert finished.status_code == 200 and finished.json()["state"] == "closed"
    binding.active = False
    session.commit()
    revoked = signed.client.get(endpoint, headers=staff_headers)
    assert revoked.status_code == 403 and revoked.headers["cache-control"] == "no-store"
