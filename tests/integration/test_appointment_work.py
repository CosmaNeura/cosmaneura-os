from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from tests.integration.test_workspace import encounter
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace
from tests.unit.test_scheduling_actions import NOW, operation

from cosmas_os.application import appointment_work as work
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.domain.enums import DecisionKind
from cosmas_os.domain.rules import AuthorizationError, DomainError
from cosmas_os.models import (
    AppointmentWork,
    AuditEvent,
    Decision,
    ExternalIdentity,
    Operation,
    Principal,
    SchedulingAccount,
    SchedulingPatientAccount,
)
from cosmas_os.ports.scheduling_actions import AppointmentSelection

signed_workspace = _signed_workspace


def test_expired_authority_after_body_read_does_not_create_approval(session, signed_workspace, monkeypatch):
    from fastapi import HTTPException

    from cosmas_os.api import app as api

    signed = signed_workspace
    signed.configuration.workspace_scheduling_enabled = True
    signed.configuration.workspace_appointments_enabled = True
    case = prepare(session, {"box_id": signed.box, "owner_id": signed.actor}, existing=signed)
    item = propose(session, case)
    original_read = api.read_capture_request

    async def slow_body(request, schema):
        result = await original_read(request, schema)
        def expired(**kwargs):
            raise HTTPException(401, "authentication_required")
        monkeypatch.setattr(api, "_identity", expired)
        return result

    monkeypatch.setattr(api, "read_capture_request", slow_body)
    path = f"/workspaces/{case.wid}/appointments/{item['ticket_id']}/decide"
    response = signed.client.post(path, headers={"Authorization": "Bearer " + signed.token()},
        json={"revision_id": item["revision_id"], "payload_hash": item["payload_hash"], "choice": "approve"})
    assert response.status_code == 401
    assert not session.scalar(select(Operation.id).where(Operation.ticket_id == item["ticket_id"]))


def prepare(s, seeded, *, existing=None, patient_mapping=True):
    box, owner = seeded["box_id"], seeded["owner_id"]
    if existing is None:
        visit = encounter(s, box, owner)
        workspace = ws.create(s, box, owner, visit.id, "appointments-prepare")
        identity = ExternalIdentity(box_id=box, principal_id=owner, provider="clerk",
            issuer="https://clerk.example.invalid", subject="user_" + str(uuid4()),
            organization_id="org_invented", reviewed_by="Invented reviewer", evidence_ref="synthetic:w15")
        s.add(identity)
        s.flush()
    else:
        visit, workspace, identity = existing.appointment, existing.workspace, existing.binding
    account = SchedulingAccount(external_identity_id=identity.id,
        **{key: str(uuid4()) for key in ("practice_id", "actor_id", "practitioner_id", "location_id", "appointment_type_id")},
        label="Invented scheduling", reviewed_by="Invented reviewer", evidence_ref="synthetic:w15", reviewed_at=NOW)
    s.add(account)
    s.flush()
    patient = SchedulingPatientAccount(box_id=box, patient_link_id=visit.patient_link_id,
        practice_id=account.practice_id, patient_id=str(uuid4()), reviewed_by="Invented reviewer",
        evidence_ref="synthetic:w15-patient", reviewed_at=NOW)
    if patient_mapping:
        s.add(patient)
    s.commit()
    selected = AppointmentSelection.model_validate(dict(box_id=box, owner_id=owner, patient_link_id=patient.patient_link_id,
        practice_id=account.practice_id, expected_actor_id=account.actor_id, practitioner_id=account.practitioner_id,
        location_id=account.location_id, appointment_type_id=account.appointment_type_id, patient_id=patient.patient_id))
    return SimpleNamespace(box=box, owner=owner, wid=workspace["id"], selection=selected,
                           identity=identity.id, account=account.id, patient=patient.id if patient_mapping else None, link=patient.patient_link_id)


@pytest.fixture
def case(session, seeded):
    return prepare(session, seeded)


def propose(s, case, *, action="book", intent=None, **changes):
    return work.propose(s, case.box, case.owner, case.wid, **{
        "external_identity_id": case.identity, "intent": intent or operation(case.selection, action).intent,
        "key": "proposal", "share": True, "now": NOW, **changes,
    })


def decide(s, case, item, **changes):
    return work.decide(s, case.box, case.owner, case.wid, item["ticket_id"], **{
        "external_identity_id": case.identity, "revision_id": item["revision_id"],
        "digest": item["payload_hash"], "choice": "approve", "now": NOW, **changes,
    })


@pytest.mark.parametrize("action", ["book", "reschedule", "cancel"])
def test_exact_shared_proposal_approval_is_durable_but_performs_no_effect(session, case, action):
    original = ws.read(session, case.box, case.owner, case.wid)
    intent = operation(case.selection, action).intent
    first = propose(session, case, intent=intent)
    replay = propose(session, case, intent=intent, now=NOW + timedelta(days=1))
    assert first == replay and first["state"] == "pending_approval"
    approved = decide(session, case, first)
    assert approved["state"] == "approved" and approved["operation_status"] == "pending"
    assert approved["appointment_saved"] is False and approved["calendar_state"] == "unconfirmed"
    assert decide(session, case, first, now=NOW + timedelta(days=1)) == approved
    assert work.read(session, case.box, case.owner, case.wid, first["ticket_id"]) == approved
    assert session.scalar(select(func.count()).select_from(Operation).where(Operation.ticket_id == first["ticket_id"])) == 1
    assert session.scalar(select(func.count()).select_from(Decision).where(Decision.ticket_id == first["ticket_id"])) == 1
    op = session.get(Operation, approved["operation_id"])
    assert op.started_at is None and op.attempt_count == 0 and op.external_reference is None
    assert op.idempotency_key == "os-appointment:" + op.id
    current = ws.read(session, case.box, case.owner, case.wid)
    assert current["revision"] == original["revision"] and current["entries"] == original["entries"]
    events = list(session.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == first["ticket_id"])))
    assert {e.event_type for e in events} == {"appointment.proposed", "appointment.approved"}
    assert all(set(e.detail) == {"action"} for e in events)
    assert [e.approved_by_principal_id for e in events if e.event_type == "appointment.approved"] == [case.owner]


@pytest.mark.parametrize("fault", ["share", "owner", "box", "patient", "actor", "expired", "stale_google", "missing_mapping"])
def test_invalid_proposal_cannot_create_work(session, case, fault):
    intent = operation(case.selection).intent
    args = {}
    if fault == "share":
        args["share"] = False
    elif fault in {"owner", "box", "patient", "actor"}:
        key = {"owner": "owner_id", "box": "box_id", "patient": "patient_id", "actor": "expected_actor_id"}[fault]
        intent = intent.model_copy(update={"selection": case.selection.model_copy(update={key: uuid4()})})
    elif fault == "expired":
        args["now"] = NOW + timedelta(minutes=4)
    elif fault == "stale_google":
        args["now"] = NOW + timedelta(seconds=31)
    else:
        session.get(SchedulingPatientAccount, case.patient).revoked_at = NOW
        session.commit()
    with pytest.raises(ws.WorkspaceError):
        propose(session, case, intent=intent, **args)
    assert not session.scalar(select(AppointmentWork.ticket_id).where(AppointmentWork.workspace_id == case.wid))


def test_same_key_changed_payload_is_conflict_not_an_edit(session, case):
    first = propose(session, case)
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        propose(session, case, action="cancel")
    assert work.read(session, case.box, case.owner, case.wid, first["ticket_id"]) == first


@pytest.mark.parametrize("fault", ["hash", "revision", "identity", "account", "patient", "expired"])
def test_stale_or_revoked_authority_cannot_approve(session, case, fault):
    item = propose(session, case)
    args = {}
    if fault == "hash":
        args["digest"] = "0" * 64
    elif fault == "revision":
        args["revision_id"] = str(uuid4())
    elif fault == "identity":
        session.get(ExternalIdentity, case.identity).active = False
    elif fault == "account":
        session.get(SchedulingAccount, case.account).revoked_at = NOW
    elif fault == "patient":
        session.get(SchedulingPatientAccount, case.patient).revoked_at = NOW
    else:
        args["now"] = NOW + timedelta(minutes=3)
    session.commit()
    with pytest.raises(ws.WorkspaceError):
        decide(session, case, item, **args)
    assert not session.scalar(select(Operation.id).where(Operation.ticket_id == item["ticket_id"]))


def test_same_remote_patient_rebound_requires_new_approval_source(session, case):
    item = propose(session, case)
    old = session.get(SchedulingPatientAccount, case.patient)
    old.revoked_at = NOW
    session.flush()
    replacement = SchedulingPatientAccount(box_id=case.box, patient_link_id=case.link,
        practice_id=old.practice_id, patient_id=old.patient_id, reviewed_by="Invented replacement",
        evidence_ref="synthetic:re-reviewed", reviewed_at=NOW)
    session.add(replacement)
    session.commit()
    with pytest.raises(ws.WorkspaceError, match="scheduling_context_changed"):
        decide(session, case, item)


def test_withdrawal_after_approval_survives_lost_reply_and_account_revocation(session, case):
    item = decide(session, case, propose(session, case))
    session.get(SchedulingAccount, case.account).revoked_at = NOW
    session.commit()
    rejected = decide(session, case, item, choice="reject", now=NOW + timedelta(days=1))
    assert rejected["state"] == "rejected" and rejected["operation_status"] == "failed"
    assert decide(session, case, item, choice="reject") == rejected
    op = session.get(Operation, rejected["operation_id"])
    assert op.started_at is None and op.error_message == "withdrawn_before_dispatch"
    with pytest.raises(ws.WorkspaceError):
        decide(session, case, item)


def test_dispatch_started_cannot_be_locally_misrepresented_as_cancelled(session, case):
    item = decide(session, case, propose(session, case))
    session.get(Operation, item["operation_id"]).started_at = NOW
    session.commit()
    with pytest.raises(ws.WorkspaceError, match="appointment_operation_in_progress"):
        decide(session, case, item, choice="reject")


def test_other_human_and_agent_cannot_review_private_appointment_work(session, case):
    item = propose(session, case)
    for kind in ["human", "agent"]:
        principal = Principal(box_id=case.box, principal_type=kind, display_name="Invented other", state="active")
        session.add(principal)
        session.commit()
        with pytest.raises(ws.WorkspaceError):
            work.read(session, case.box, principal.id, case.wid, item["ticket_id"])
        with pytest.raises(ws.WorkspaceError):
            work.decide(session, case.box, principal.id, case.wid, item["ticket_id"], external_identity_id=case.identity,
                        revision_id=item["revision_id"], digest=item["payload_hash"], choice="approve", now=NOW)


def test_generic_queue_mutations_and_notify_worker_cannot_bypass_exact_path(session, case):
    item = propose(session, case)
    c = svc.Container(session)
    with pytest.raises(AuthorizationError, match="private workspace"):
        svc.edit_revision(c, item["ticket_id"], case.owner, "Changed")
    with pytest.raises(AuthorizationError, match="private workspace"):
        svc.close_ticket(c, item["ticket_id"], case.owner)
    with pytest.raises(AuthorizationError, match="private workspace"):
        svc.decide(c, item["ticket_id"], case.owner, DecisionKind.APPROVE,
                   expected_revision_id=item["revision_id"])
    approved = decide(session, case, item)
    with pytest.raises(DomainError, match="configured execution backend"):
        svc.execute_operation(c, approved["operation_id"])


@pytest.mark.parametrize("statement", [
    "UPDATE appointment_work SET request_hash = 'changed' WHERE ticket_id = :id",
    "DELETE FROM appointment_work WHERE ticket_id = :id",
])
def test_private_approval_source_is_immutable(session, case, statement):
    item = propose(session, case)
    with pytest.raises(DBAPIError):
        with session.begin_nested():
            session.execute(text(statement), {"id": item["ticket_id"]})


def test_patient_mapping_is_scoped_immutable_and_revocation_cannot_be_undone(session, case):
    for statement in ["UPDATE scheduling_patient_accounts SET patient_id = :new WHERE id = :id",
                      "DELETE FROM scheduling_patient_accounts WHERE id = :id"]:
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(text(statement), {"id": case.patient, "new": str(uuid4())})
    session.get(SchedulingPatientAccount, case.patient).revoked_at = NOW
    session.commit()
    with pytest.raises(DBAPIError):
        with session.begin_nested():
            session.execute(text("UPDATE scheduling_patient_accounts SET revoked_at=NULL WHERE id=:id"), {"id": case.patient})
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(SchedulingPatientAccount(box_id=str(uuid4()), patient_link_id=case.link,
                practice_id=str(case.selection.practice_id), patient_id=str(uuid4()), reviewed_by="Invented",
                evidence_ref="synthetic:wrong-box", reviewed_at=NOW))
            session.flush()


@pytest.mark.parametrize("competing", ["approve", "reject"])
def test_concurrent_human_decisions_produce_one_durable_operation(engine, competing):
    with Session(engine) as s:
        case = prepare(s, svc.provision_box(svc.Container(s), "Invented appointment race"))
        item = propose(s, case)
    barrier = Barrier(2)
    def run(index):
        with Session(engine) as s:
            barrier.wait(timeout=10)
            try:
                return decide(s, case, item, choice="approve" if index == 0 else competing)["state"]
            except ws.WorkspaceError:
                return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, [0, 1]))
    with Session(engine) as s:
        current = work.read(s, case.box, case.owner, case.wid, item["ticket_id"])
        assert (s.scalar(select(func.count()).select_from(Operation).where(Operation.ticket_id == item["ticket_id"])) or 0) <= 1
        assert (s.scalar(select(func.count()).select_from(Decision).where(Decision.ticket_id == item["ticket_id"], Decision.kind == "approve")) or 0) <= 1
        if competing == "approve":
            assert outcomes == ["approved", "approved"] and current["state"] == "approved"
        else:
            assert current["state"] == "rejected" and "rejected" in outcomes


@pytest.mark.parametrize("signed_workspace", ["apple", "desktop"], indirect=True)
def test_signed_native_origins_review_reopen_and_withdraw_same_operation(session, signed_workspace, monkeypatch):
    signed = signed_workspace
    signed.configuration.workspace_scheduling_enabled = True
    signed.configuration.workspace_appointments_enabled = True
    monkeypatch.setattr(work, "_clock", lambda value=None: NOW)
    signed.configuration.workspace_scheduling_login_enabled = True
    signed.configuration.workspace_scheduling_patient_setup_enabled = True
    case = prepare(session, {"box_id": signed.box, "owner_id": signed.actor}, existing=signed, patient_mapping=False)
    from tests.integration.test_scheduling_patient_setup import install_personal_fixture

    account = session.get(SchedulingAccount, case.account)
    assert account is not None
    with install_personal_fixture(session, box=case.box, owner=case.owner, wid=case.wid,
            identity_id=case.identity, account=account, configuration=signed.configuration,
            patient_id=str(case.selection.patient_id)) as mapping_receipt:
        case.patient = mapping_receipt["mapping"]["mapping_id"]
        item = propose(session, case)
        path = f"/workspaces/{case.wid}/appointments/{item['ticket_id']}"
        headers = {"Authorization": "Bearer " + signed.token()}
        readback = signed.client.get(path, headers=headers)
        assert readback.status_code == 200 and readback.json() == item
        body = {"revision_id": item["revision_id"], "payload_hash": item["payload_hash"], "choice": "approve"}
        approved = signed.client.post(path + "/decide", headers=headers, json=body)
        assert approved.status_code == 200, approved.text
        assert approved.json()["operation_status"] == "pending" and approved.json()["appointment_saved"] is False
        assert approved.headers["cache-control"] == "no-store"
        second = {"Authorization": "Bearer " + signed.token(sid="session_reopened")}
        assert signed.client.get(path, headers=second).json() == approved.json()
        malformed = signed.client.post(path + "/decide", headers=second, json={**body, "patient_id": "PRIVATE"})
        assert malformed.status_code == 422 and "PRIVATE" not in malformed.text
        rejected = signed.client.post(path + "/decide", headers=second, json={**body, "choice": "reject"})
        assert rejected.status_code == 200 and rejected.json()["state"] == "rejected"
        assert signed.client.get(path).status_code == 401
        assert signed.client.get(path, headers={"Authorization": "Bearer " + signed.token(sub="user_foreign")}).status_code == 403


def test_signed_route_is_default_off_and_rechecks_identity_revocation(session, signed_workspace, monkeypatch):
    signed = signed_workspace
    signed.configuration.workspace_scheduling_enabled = True
    monkeypatch.setattr(work, "_clock", lambda value=None: NOW)
    case = prepare(session, {"box_id": signed.box, "owner_id": signed.actor}, existing=signed)
    item = propose(session, case)
    path = f"/workspaces/{case.wid}/appointments/{item['ticket_id']}"
    headers = {"Authorization": "Bearer " + signed.token()}
    assert signed.client.get(path, headers=headers).status_code == 404
    signed.configuration.workspace_appointments_enabled = True
    assert signed.client.get(path, headers=headers).status_code == 200
    session.get(ExternalIdentity, case.identity).active = False
    session.commit()
    response = signed.client.post(path + "/decide", headers=headers, json={
        "revision_id": item["revision_id"], "payload_hash": item["payload_hash"], "choice": "approve"})
    assert response.status_code == 403
    assert not session.scalar(select(Operation.id).where(Operation.ticket_id == item["ticket_id"]))
