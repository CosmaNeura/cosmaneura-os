from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_appointment_work import decide, prepare, propose
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace
from tests.unit.test_scheduling_actions import NOW

from cosmas_os.application import appointment_execution as execution
from cosmas_os.application import appointment_work as work
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    AppointmentReceipt,
    AuditEvent,
    Decision,
    EncounterWorkspace,
    ExternalIdentity,
    Operation,
    PatientLink,
    Principal,
    SchedulingAccount,
    SchedulingPatientAccount,
)
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling_actions import AppointmentResult, AppointmentSnapshot

signed_workspace = _signed_workspace


class Journal:
    """Invented receiver journal; no HTTP or Scheduling service is used."""
    def __init__(self):
        self.now = NOW
        self.calls = []
        self.effects = {}
        self.lose = False
        self.after = lambda: None
        self.calendar = "pending"
        self.fault = None

    def result(self, operation):
        identity = str(operation.operation_id)
        if identity not in self.effects:
            intent = operation.intent
            before = intent.expected
            slot = intent.slot or before
            assert slot
            self.effects[identity] = AppointmentSnapshot(
                id=before.id if before else uuid4(), version=before.version+1 if before else 1,
                status="cancelled" if intent.action == "cancel" else before.status if before else "booked",
                client_id=before.client_id if before else None, starts_at=slot.starts_at, ends_at=slot.ends_at,
                **{name: getattr(intent.selection, name) for name in ("patient_id", "practitioner_id", "location_id", "appointment_type_id")})
        value = AppointmentResult(operation_id=operation.operation_id, request_hash=operation.request_hash(),
            appointment=self.effects[identity], observed_at=self.now, calendar_state=self.calendar)
        if self.fault == "patient":
            value = value.model_copy(update={"appointment": value.appointment.model_copy(update={"patient_id": uuid4()})})
        elif self.fault == "hash":
            value = value.model_copy(update={"request_hash": "f"*64})
        elif self.fault == "stale":
            value = value.model_copy(update={"observed_at": self.now-timedelta(seconds=31)})
        elif self.fault == "future":
            value = value.model_copy(update={"observed_at": self.now+timedelta(seconds=6)})
        elif self.fault == "changed_effect":
            value = value.model_copy(update={"appointment": value.appointment.model_copy(update={"id": uuid4()})})
        return value

    def submit(self, operation):
        self.calls.append(("submit", operation))
        self.after()
        result = self.result(operation)
        if self.lose:
            raise ConnectorUnavailable("PRIVATE response lost")
        return result

    def reconcile(self, operation):
        self.calls.append(("reconcile", operation))
        self.after()
        if str(operation.operation_id) not in self.effects:
            raise ConnectorUnavailable("PRIVATE missing result")
        return self.result(operation)


def setup(s, seeded, action="book", approve=True, existing=None):
    case = prepare(s, seeded, existing=existing)
    case.item = propose(s, case, action=action)
    if approve:
        case.approved = decide(s, case, case.item)
    case.port = Journal()
    return case


@pytest.fixture
def case(session, seeded):
    return setup(session, seeded)


def command(s, case, **changes):
    op = s.scalar(select(Operation).where(Operation.ticket_id == case.item["ticket_id"]))
    mode = "reconcile" if changes.pop("refresh", False) or op and op.status in {"running", "unknown"} else "submit"
    if changes.pop("retry", False):
        mode = "retry"
    return {"operation_id": op.id if op else str(uuid4()), "revision_id": case.item["revision_id"],
            "digest": case.item["payload_hash"], "mode": mode, **changes}


def run(s, case, **changes):
    return execution.run(s, case.box, case.owner, case.wid, case.item["ticket_id"], external_identity_id=case.identity,
                         reauthenticate=lambda: None, port=case.port, clock=lambda: case.port.now, **command(s, case, **changes))


def claim(s, case, **changes):
    return execution.claim(s, case.box, case.owner, case.wid, case.item["ticket_id"], external_identity_id=case.identity,
                           reauthenticate=lambda: None, clock=lambda: case.port.now, **command(s, case, **changes))


@pytest.mark.parametrize("action", ["book", "reschedule", "cancel"])
def test_exact_approved_action_saves_one_effect_and_never_claims_visit_completion(session, seeded, action):
    case = setup(session, seeded, action)
    revision = session.get(EncounterWorkspace, case.wid).revision
    result = run(session, case)
    assert result["state"] == "sent" and result["operation_status"] == "succeeded"
    assert result["appointment_saved"] is True and result["calendar_state"] == "pending" and result["dispatch_started"] is True
    assert result["result"]["operation_id"] == result["operation_id"]
    assert run(session, case) == result and len(case.port.calls) == 1 and len(case.port.effects) == 1
    assert session.scalar(select(func.count()).select_from(AppointmentReceipt).where(AppointmentReceipt.operation_id == result["operation_id"])) == 1
    assert session.get(EncounterWorkspace, case.wid).revision == revision
    assert decide(session, case, case.item) == result
    with pytest.raises(ws.WorkspaceError, match="operation_in_progress"):
        work.decide(session, case.box, case.owner, case.wid, case.item["ticket_id"], external_identity_id=case.identity,
            revision_id=case.item["revision_id"], digest=case.item["payload_hash"], choice="reject", now=NOW)


@pytest.mark.parametrize("fault", ["unapproved", "decision", "audit", "identity", "owner", "patient", "account", "mapping", "expired"])
def test_missing_or_revoked_authority_prevents_any_receiver_call(session, seeded, fault):
    case = setup(session, seeded, approve=fault != "unapproved")
    if fault == "decision":
        session.scalar(select(Decision).where(Decision.ticket_id == case.item["ticket_id"])).kind = "reject"
    elif fault == "audit":
        session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == case.item["ticket_id"], AuditEvent.event_type == "appointment.approved")).payload_hash = "f"*64
    elif fault == "identity":
        session.get(ExternalIdentity, case.identity).active = False
    elif fault == "owner":
        session.get(Principal, case.owner).state = "disabled"
    elif fault == "patient":
        session.get(PatientLink, case.link).revoked_at = NOW
    elif fault == "account":
        session.get(SchedulingAccount, case.account).revoked_at = NOW
    elif fault == "mapping":
        session.get(SchedulingPatientAccount, case.patient).revoked_at = NOW
    elif fault == "expired":
        case.port.now = NOW+timedelta(minutes=4)
    session.commit()
    with pytest.raises(ws.WorkspaceError):
        run(session, case)
    assert not case.port.calls and not case.port.effects


def test_lost_response_reconciles_same_operation_after_expiry(session, case):
    case.port.lose = True
    unknown = run(session, case)
    assert unknown["operation_status"] == "unknown" and not unknown["appointment_saved"]
    assert unknown["execution_error"] == "appointment_outcome_unconfirmed" and "PRIVATE" not in str(unknown)
    case.port.now += timedelta(minutes=6)
    saved = run(session, case)
    assert saved["appointment_saved"] and saved["operation_id"] == unknown["operation_id"]
    assert [kind for kind,_ in case.port.calls] == ["submit", "reconcile"]
    assert case.port.calls[0][1] == case.port.calls[1][1] and len(case.port.effects) == 1


def test_crash_before_io_can_only_reconcile_or_explicitly_retry_the_same_unexpired_operation(session, case):
    first = claim(session, case)
    assert first and first.mode == "submit"
    case.port.now += timedelta(seconds=61)
    unknown = run(session, case)
    assert unknown["operation_status"] == "unknown" and case.port.calls[0][0] == "reconcile" and not case.port.effects
    saved = run(session, case, retry=True)
    assert saved["appointment_saved"] and case.port.calls[-1][1] == first.operation
    assert session.get(Operation, saved["operation_id"]).attempt_count == 2


def test_explicit_retry_is_bounded_and_keeps_one_receiver_identity(session, case):
    case.port.lose = True
    for index in range(3):
        assert run(session, case, retry=index > 0)["operation_status"] == "unknown"
    with pytest.raises(ws.WorkspaceError, match="resubmission_unavailable"):
        run(session, case, retry=True)
    assert len(case.port.calls) == 3 and len(case.port.effects) == 1
    assert all(op == case.port.calls[0][1] for _,op in case.port.calls)
    assert run(session, case)["appointment_saved"]


def test_expired_retry_cannot_submit_but_can_reconcile(session, case):
    case.port.lose = True
    run(session, case)
    case.port.now += timedelta(minutes=4)
    with pytest.raises(ws.WorkspaceError, match="resubmission_unavailable"):
        run(session, case, retry=True)
    assert len(case.port.calls) == 1
    assert run(session, case)["appointment_saved"] and case.port.calls[-1][0] == "reconcile"


@pytest.mark.parametrize("fault", ["patient", "hash", "stale", "future"])
def test_invalid_receipt_never_becomes_a_saved_appointment(session, case, fault):
    case.port.fault = fault
    result = run(session, case)
    assert result["operation_status"] == "unknown" and result["result"] is None
    assert not session.scalar(select(AppointmentReceipt.id).where(AppointmentReceipt.operation_id == result["operation_id"]))


def test_calendar_reconciliation_retains_immutable_effect_and_observation_history(session, case):
    first = run(session, case)
    case.port.now += timedelta(seconds=10)
    case.port.calendar = "synced"
    second = run(session, case, refresh=True)
    assert second["calendar_state"] == "synced" and second["result"]["appointment"] == first["result"]["appointment"]
    rows = list(session.scalars(select(AppointmentReceipt).where(AppointmentReceipt.operation_id == first["operation_id"])))
    assert len(rows) == 2
    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(text("UPDATE appointment_receipts SET payload = '{}'::jsonb WHERE id = :id"), {"id": rows[0].id})
    case.port.now += timedelta(seconds=10)
    case.port.fault = "changed_effect"
    conflicted = run(session, case, refresh=True)
    assert conflicted["result"] == second["result"] and conflicted["execution_error"] == "appointment_outcome_unconfirmed"
    assert session.scalar(select(func.count()).select_from(AppointmentReceipt).where(AppointmentReceipt.operation_id == first["operation_id"])) == 2


def test_stale_claim_cannot_overwrite_newer_receipt_or_clear_its_claim(session, case):
    first = claim(session, case)
    assert first
    case.port.now += timedelta(seconds=61)
    second = claim(session, case)
    assert second and second.generation == 2 and second.mode == "reconcile"
    receipt = case.port.result(first.operation)
    with pytest.raises(ws.WorkspaceError, match="claim_unavailable"):
        execution.record(session, first, receipt, clock=lambda: case.port.now)
    execution.record(session, second, receipt, clock=lambda: case.port.now)
    execution.uncertain(session, first)
    assert work.read(session, case.box, case.owner, case.wid, case.item["ticket_id"])["appointment_saved"]


def test_active_claim_serializes_concurrent_worker_without_holding_local_locks_during_io(engine):
    with Session(engine) as session:
        case = setup(session, svc.provision_box(svc.Container(session), "Invented execution race"))
        seen = []
        def concurrent():
            with Session(engine) as other:
                other.execute(text("SET LOCAL lock_timeout = '1s'"))
                seen.append(run(other, case))
        case.port.after = concurrent
        saved = run(session, case)
        assert saved["appointment_saved"] and seen[0]["operation_status"] == "running"
        assert len(case.port.calls) == 1


def test_revocation_during_io_retains_proven_effect_without_disclosing_it(engine):
    with Session(engine) as session:
        case = setup(session, svc.provision_box(svc.Container(session), "Invented late result"))
        def revoke():
            with Session(engine) as other:
                other.execute(text("SET LOCAL lock_timeout = '1s'"))
                other.get(ExternalIdentity, case.identity).active = False
                other.commit()
        case.port.after = revoke
        with pytest.raises(ws.WorkspaceError, match="connection_required"):
            run(session, case)
        with Session(engine) as reader:
            operation = reader.scalar(select(Operation).where(Operation.ticket_id == case.item["ticket_id"]))
            assert operation.status == "succeeded" and operation.attempt_count == 1
            assert reader.scalar(select(AppointmentReceipt.id).where(AppointmentReceipt.operation_id == operation.id))
        with pytest.raises(ws.WorkspaceError):
            run(session, case, refresh=True)
        assert len(case.port.calls) == 1


@pytest.mark.parametrize("signed_workspace", ["apple", "desktop"], indirect=True)
def test_signed_native_read_returns_verified_result_and_execution_requires_exact_command(session, signed_workspace):
    signed = signed_workspace
    signed.configuration.workspace_scheduling_enabled = True
    signed.configuration.workspace_appointments_enabled = True
    case = setup(session, {"box_id": signed.box, "owner_id": signed.actor}, existing=signed)
    saved = run(session, case)
    path = f"/workspaces/{case.wid}/appointments/{case.item['ticket_id']}"
    headers = {"Authorization": "Bearer " + signed.token()}
    response = signed.client.get(path, headers=headers)
    assert response.status_code == 200 and response.json() == saved
    assert signed.client.post(path + "/execute", headers=headers, json={}).status_code == 422


def test_late_calendar_observation_cannot_regress_newer_verified_state(session, case):
    run(session, case)
    case.port.now += timedelta(seconds=10)
    case.port.calendar = "synced"
    latest = run(session, case, refresh=True)
    case.port.now += timedelta(seconds=5)
    attempt = claim(session, case, refresh=True)
    case.port.calendar = "pending"
    older = case.port.result(attempt.operation).model_copy(update={"observed_at": NOW+timedelta(seconds=5)})
    execution.record(session, attempt, older, clock=lambda: case.port.now)
    assert work.read(session, case.box, case.owner, case.wid, case.item["ticket_id"])["result"] == latest["result"]
