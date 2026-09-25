"""Explicit, fenced execution of exact F-8 appointment operations.

The gated request route requires an exact human command and an explicitly
injected receiver; no worker, ambient credential or automatic retry activates
dispatch. The receiver's durable journal is required for same-operation retry.
"""

from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from cosmas_os.application import appointment_work as work
from cosmas_os.application import follow_up
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import (
    AppointmentExecution,
    AppointmentReceipt,
    AuditEvent,
    Decision,
    EncounterWorkspace,
    Operation,
)
from cosmas_os.ports.scheduling_actions import AppointmentOperation, AppointmentResult

LEASE_SECONDS = 60
MAX_SUBMISSIONS = 3


@dataclass(frozen=True)
class Attempt:
    box: str
    owner: str
    workspace_id: str
    ticket_id: str
    token: str
    generation: int
    mode: str
    operation: AppointmentOperation


def _now(s, clock):
    return work._clock(clock() if clock else s.scalar(select(func.clock_timestamp())))


def _approved(s, w, ticket, revision):
    decision = s.scalar(select(Decision.id).where(
        Decision.box_id == w.box_id, Decision.ticket_id == ticket.id,
        Decision.action_revision_id == revision.id, Decision.actor_principal_id == w.owner_id,
        Decision.kind == "approve"))
    audit = s.scalar(select(AuditEvent.id).where(
        AuditEvent.box_id == w.box_id, AuditEvent.aggregate_id == ticket.id,
        AuditEvent.event_type == "appointment.approved", AuditEvent.action_revision_id == revision.id,
        AuditEvent.approved_by_principal_id == w.owner_id, AuditEvent.payload_hash == revision.payload_hash,
        AuditEvent.policy_version == revision.policy_version, AuditEvent.charter_version == revision.charter_version,
        AuditEvent.config_version == revision.config_version))
    if ticket.state not in {"approved", "sent"} or not decision or not audit:
        raise ws.WorkspaceError("appointment_approval_required")


def _request(op, intent):
    return AppointmentOperation(operation_id=op.id, intent=intent, approved_payload_hash=intent.approval_hash())


def _latest(s, operation):
    return s.scalar(select(AppointmentReceipt).where(AppointmentReceipt.operation_id == str(operation.operation_id))
        .order_by(AppointmentReceipt.observed_at.desc(), AppointmentReceipt.created_at.desc(), AppointmentReceipt.id.desc()).limit(1))


def _checked_receipt(row, operation):
    try:
        result = AppointmentResult.model_validate(row.payload)
        result.require_operation(operation)
        if (row.operation_id != str(operation.operation_id) or row.request_hash != result.request_hash
            or row.response_hash != payload_hash(result.model_dump(mode="json")) or row.observed_at != result.observed_at):
            raise ValueError
        return result
    except (ValueError, TypeError, AttributeError):
        raise ws.WorkspaceError("appointment_receipt_unavailable", 503) from None


def outcome(s, op, intent):
    """A saved appointment requires a verified durable receipt, not a status bit."""
    result = None
    if op:
        operation = _request(op, intent)
        row = _latest(s, operation)
        if row:
            result = _checked_receipt(row, operation)
            if (row.box_id != op.box_id or row.ticket_id != op.ticket_id or op.status != "succeeded"
                or op.result_receipt_hash != row.response_hash
                or op.external_reference != "scheduling:" + str(result.appointment.id)):
                raise ws.WorkspaceError("appointment_receipt_unavailable", 503)
        elif op.status == "succeeded":
            raise ws.WorkspaceError("appointment_receipt_unavailable", 503)
    return {"appointment_saved": result is not None,
            "calendar_state": result.calendar_state if result else "unconfirmed",
            "result": result.model_dump(mode="json") if result else None,
            "execution_error": op.error_message if op else None,
            "dispatch_started": bool(op and op.started_at is not None)}


def claim(s, box, owner, workspace_id, ticket_id, *, external_identity_id, reauthenticate,
          operation_id, revision_id, digest, mode, clock=None):
    """Commit a claim before I/O. Existing active claims never dispatch twice."""
    try:
        if mode not in {"submit", "reconcile", "retry"}:
            raise ws.WorkspaceError("appointment_command_invalid", 400)
        s.rollback()
        follow_up._local(s)
        reauthenticate()
        w = ws._workspace(s, box, owner, workspace_id, writing=True)
        source, ticket, revision, intent = work._bound(s, w, ticket_id)
        op = work._operation(s, ticket, revision)
        if not op:
            raise ws.WorkspaceError("appointment_approval_required")
        if op.id != operation_id or revision.id != revision_id or revision.payload_hash != digest:
            raise ws.WorkspaceError("appointment_approval_changed")
        _approved(s, w, ticket, revision)
        account, patient, selected = work._current(s, w, external_identity_id)
        if account.id != source.account_id or patient.id != source.patient_mapping_id or selected != intent.selection:
            raise ws.WorkspaceError("scheduling_context_changed")
        now = _now(s, clock)
        row = s.get(AppointmentExecution, op.id)
        if op.status not in {"pending", "running", "unknown", "succeeded"}:
            raise ws.WorkspaceError("appointment_operation_unavailable")
        if op.status == "pending" and (op.started_at is not None or op.attempt_count != 0 or row is not None):
            raise ws.WorkspaceError("appointment_dispatch_state_invalid")
        if mode == "reconcile" and op.started_at is None:
            raise ws.WorkspaceError("appointment_dispatch_required")
        if mode == "retry" and op.started_at is None:
            raise ws.WorkspaceError("appointment_retry_requires_dispatch")
        if row and row.lease_until is not None and row.lease_until > now:
            s.commit()
            return None
        if op.status == "succeeded" and mode != "reconcile":
            outcome(s, op, intent)
            s.commit()
            return None
        # Replaying a retained submit command can recover its state, but cannot
        # start a second attempt or turn into an implicit reconciliation read.
        if mode == "submit" and op.status != "pending":
            s.commit()
            return None
        dispatch_mode = "reconcile" if mode == "reconcile" else "submit"
        if dispatch_mode == "submit":
            if now >= intent.expires_at or op.attempt_count >= MAX_SUBMISSIONS:
                raise ws.WorkspaceError("appointment_resubmission_unavailable")
        token = str(uuid4())
        if row is None:
            row = AppointmentExecution(operation_id=op.id, ticket_id=ticket.id, box_id=box,
                                       generation=1, mode=dispatch_mode)
            s.add(row)
        else:
            if row.box_id != box or row.ticket_id != ticket.id:
                raise ws.WorkspaceError("appointment_approval_changed")
            row.generation += 1
        row.claim_token, row.lease_until, row.mode = token, now + timedelta(seconds=LEASE_SECONDS), dispatch_mode
        if dispatch_mode == "submit":
            op.attempt_count += 1
            op.started_at = op.started_at or now
        if op.status != "succeeded":
            op.status = "running"
        op.error_message = None
        attempt = Attempt(box, owner, workspace_id, ticket_id, token, row.generation, dispatch_mode, _request(op, intent))
        s.add(AuditEvent(box_id=box, aggregate_type="operation", aggregate_id=op.id,
            event_type="appointment.attempt_claimed", initiated_by_principal_id=owner,
            approved_by_principal_id=owner, action_revision_id=revision.id, payload_hash=revision.payload_hash,
            outcome=dispatch_mode, detail={"generation": row.generation}))
        s.commit()
        return attempt
    except Exception:
        s.rollback()
        raise


def record(s, attempt, value, *, clock=None):
    """Retain proven effects even if local access was revoked while I/O ran.

    This grants no read or new write authority. The caller reauthenticates before
    returning private data. A late valid receipt cannot overwrite a newer one.
    """
    try:
        s.rollback()
        follow_up._local(s)
        if not isinstance(value, AppointmentResult):
            raise ValueError("unqualified receipt")
        result = AppointmentResult.model_validate(value.model_dump(warnings=False))
        result.require_operation(attempt.operation)
        now = _now(s, clock)
        if not now - timedelta(seconds=30) <= result.observed_at <= now + timedelta(seconds=5):
            raise ValueError("stale receipt")
        w = s.get(EncounterWorkspace, attempt.workspace_id)
        if not w or w.box_id != attempt.box or w.owner_id != attempt.owner:
            raise ws.WorkspaceError("appointment_approval_changed")
        _, ticket, revision, intent = work._bound(s, w, attempt.ticket_id)
        op = work._operation(s, ticket, revision)
        if op is None or _request(op, intent) != attempt.operation or op.started_at is None:
            raise ws.WorkspaceError("appointment_approval_changed")
        _approved(s, w, ticket, revision)
        row = s.get(AppointmentExecution, op.id)
        if row is None or row.claim_token != attempt.token or row.generation != attempt.generation:
            raise ws.WorkspaceError("appointment_claim_unavailable")
        previous = _latest(s, attempt.operation)
        if previous:
            old = _checked_receipt(previous, attempt.operation)
            if (old.appointment != result.appointment
                or old.observed_at == result.observed_at and old.calendar_state != result.calendar_state):
                raise ValueError("receipt conflicts with the saved effect")
        payload = result.model_dump(mode="json")
        digest = payload_hash(payload)
        exists = s.scalar(select(AppointmentReceipt.id).where(
            AppointmentReceipt.operation_id == op.id, AppointmentReceipt.response_hash == digest))
        if not exists:
            s.add(AppointmentReceipt(operation_id=op.id, ticket_id=ticket.id, box_id=op.box_id,
                request_hash=result.request_hash, response_hash=digest, payload=payload, observed_at=result.observed_at))
        if previous is None or previous.observed_at <= result.observed_at:
            op.status = "succeeded"
            op.completed_at = op.completed_at or now
            op.external_reference = "scheduling:" + str(result.appointment.id)
            op.result_receipt_hash = digest
            op.error_message = None
            if ticket.state == "approved":
                ticket.state = "sent"
                ticket.version += 1
        if row.claim_token == attempt.token and row.generation == attempt.generation:
            row.claim_token = row.lease_until = None
        if not exists:
            s.add(AuditEvent(box_id=op.box_id, aggregate_type="operation", aggregate_id=op.id,
                event_type="appointment.result_verified", initiated_by_principal_id=attempt.owner,
                approved_by_principal_id=attempt.owner, action_revision_id=revision.id,
                payload_hash=revision.payload_hash, outcome="appointment_saved",
                detail={"receipt_sha256": digest, "calendar_state": result.calendar_state}))
        s.commit()
    except Exception:
        s.rollback()
        raise


def uncertain(s, attempt):
    s.rollback()
    op = s.scalar(select(Operation).where(Operation.id == str(attempt.operation.operation_id)).with_for_update())
    row = s.get(AppointmentExecution, str(attempt.operation.operation_id))
    if (op and row and op.box_id == attempt.box and op.ticket_id == attempt.ticket_id
        and row.claim_token == attempt.token and row.generation == attempt.generation):
        row.claim_token = row.lease_until = None
        op.error_message = "appointment_outcome_unconfirmed"
        if op.status != "succeeded":
            op.status = "unknown"
    s.commit()


def run(s, box, owner, workspace_id, ticket_id, *, external_identity_id, reauthenticate,
        port, operation_id, revision_id, digest, mode, clock=None):
    attempt = claim(s, box, owner, workspace_id, ticket_id, external_identity_id=external_identity_id,
                    reauthenticate=reauthenticate, operation_id=operation_id, revision_id=revision_id,
                    digest=digest, mode=mode, clock=clock)
    if attempt:
        try:
            value = port.submit(attempt.operation) if attempt.mode == "submit" else port.reconcile(attempt.operation)
            record(s, attempt, value, clock=clock)
        except Exception:
            uncertain(s, attempt)
    # Recording an already-proven effect must not return data to a revoked caller.
    reauthenticate()
    work._current(s, ws._workspace(s, box, owner, workspace_id), external_identity_id)
    return work.read(s, box, owner, workspace_id, ticket_id)
