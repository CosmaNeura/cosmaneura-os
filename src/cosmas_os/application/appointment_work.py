"""Persist reviewed appointment proposals and exact human decisions in F-8.

This layer performs no network I/O. Its caller must obtain fresh, qualified
Scheduling receipts before composing an intent; browser/model input is not a
receipt. No execution route is enabled here. The receiver extension, orchestration
and UI must be qualified before these pending operations can be dispatched.
"""

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from cosmas_os.application import follow_up
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import (
    ActionRevision,
    AppointmentWork,
    AuditEvent,
    Decision,
    ExternalIdentity,
    Operation,
    SchedulingAccount,
    SchedulingPatientAccount,
    Ticket,
)
from cosmas_os.ports.scheduling_actions import AppointmentIntent, AppointmentSelection

LANE = "scheduling_appointment"
ADAPTER = "scheduling_appointment_v1"


def _proposal_gate(s, configuration: Settings | None) -> None:
    """Explicit signed proposal capability; legacy callers remain local-only."""
    if configuration is None:
        follow_up._local(s)
    elif (not configuration.workspace_scheduling_available
          or not configuration.workspace_appointments_enabled):
        raise ws.WorkspaceError("appointment_proposals_unavailable", 403)


def _intent(value):
    try:
        if not isinstance(value, AppointmentIntent):
            raise ValueError
        return AppointmentIntent.model_validate(value.model_dump(warnings=False))
    except (ValueError, TypeError, AttributeError):
        raise ws.WorkspaceError("appointment_proposal_invalid", 400) from None


def _clock(value=None):
    value = datetime.now(UTC) if value is None else value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ws.WorkspaceError("appointment_clock_unavailable", 503)
    return value.astimezone(UTC)


def _current(s, w, identity_id, *, configuration: Settings | None = None):
    identity = s.scalar(select(ExternalIdentity).where(
        ExternalIdentity.id == identity_id, ExternalIdentity.box_id == w.box_id,
        ExternalIdentity.principal_id == w.owner_id, ExternalIdentity.active.is_(True),
    ).with_for_update(read=True))
    account = s.scalar(select(SchedulingAccount).where(
        SchedulingAccount.external_identity_id == identity_id, SchedulingAccount.revoked_at.is_(None),
    ).with_for_update(read=True))
    if identity is None or account is None:
        raise ws.WorkspaceError("scheduling_connection_required")
    if configuration is None:
        follow_up._local(s)
        patient = s.scalar(select(SchedulingPatientAccount).where(
            SchedulingPatientAccount.box_id == w.box_id,
            SchedulingPatientAccount.patient_link_id == w.patient_link_id,
            SchedulingPatientAccount.practice_id == account.practice_id,
            SchedulingPatientAccount.revoked_at.is_(None),
        ).with_for_update(read=True))
    else:
        from cosmas_os.application.scheduling_patient_setup import personal_mapping_for

        patient = personal_mapping_for(s, w, identity_id, account, configuration=configuration)
    if patient is None:
        raise ws.WorkspaceError("scheduling_patient_correspondence_required")
    return account, patient, AppointmentSelection(
        box_id=w.box_id, owner_id=w.owner_id, patient_link_id=w.patient_link_id,
        practice_id=account.practice_id, expected_actor_id=account.actor_id,
        practitioner_id=account.practitioner_id, location_id=account.location_id,
        appointment_type_id=account.appointment_type_id, patient_id=patient.patient_id,
    )


def _target(intent):
    if intent.expected:
        return "scheduling_appointment:" + str(intent.expected.id)
    return "scheduling_patient:" + str(intent.selection.patient_id)


def _content(intent):
    if intent.action == "cancel":
        return "Cancel the reviewed appointment."
    assert intent.slot is not None
    return ("Book" if intent.action == "book" else "Reschedule") + " appointment: " + (
        intent.slot.starts_at.isoformat() + " to " + intent.slot.ends_at.isoformat()
    )


def _bound(s, w, ticket_id):
    source = s.scalar(select(AppointmentWork).where(
        AppointmentWork.ticket_id == ticket_id, AppointmentWork.box_id == w.box_id,
        AppointmentWork.workspace_id == w.id, AppointmentWork.owner_id == w.owner_id,
    ))
    if source is None:
        raise ws.WorkspaceError("appointment_work_unavailable", 404)
    ticket = s.scalar(select(Ticket).where(Ticket.id == ticket_id).with_for_update().execution_options(populate_existing=True))
    revision = s.get(ActionRevision, source.action_revision_id)
    try:
        if ticket is None or revision is None:
            raise ValueError
        intent = AppointmentIntent.model_validate(revision.payload)
        if (ticket.box_id != w.box_id or ticket.lane != LANE
            or ticket.created_by_principal_id != w.owner_id
            or ticket.appointment_id != w.appointment_id or ticket.patient_link_id != w.patient_link_id
            or source.patient_link_id != w.patient_link_id or ticket.current_revision_id != revision.id
            or revision.invalidated or revision.ticket_id != ticket.id or revision.box_id != w.box_id
            or revision.created_by_principal_id != w.owner_id
            or revision.payload_hash != source.payload_hash or intent.approval_hash() != source.payload_hash
            or str(intent.selection.box_id) != w.box_id or str(intent.selection.owner_id) != w.owner_id
            or str(intent.selection.patient_link_id) != w.patient_link_id
            or revision.action_type != "scheduling." + intent.action
            or revision.automation_class != "hitl_required" or revision.content != _content(intent)
            or revision.target_ref != _target(intent)):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ws.WorkspaceError("appointment_approval_changed") from None
    return source, ticket, revision, intent


def _operation(s, ticket, revision):
    op = s.scalar(select(Operation).where(Operation.action_revision_id == revision.id)
                  .with_for_update().execution_options(populate_existing=True))
    if op and (op.ticket_id != ticket.id or op.box_id != ticket.box_id or op.adapter != ADAPTER
               or op.idempotency_key != "os-appointment:" + op.id):
        raise ws.WorkspaceError("appointment_approval_changed")
    return op


def _event(s, w, ticket, revision, kind, *, approved=False):
    s.add(AuditEvent(box_id=w.box_id, aggregate_type="ticket", aggregate_id=ticket.id,
        event_type=kind, actor_principal_id=w.owner_id,
        approved_by_principal_id=w.owner_id if approved else None,
        action_revision_id=revision.id, payload_hash=revision.payload_hash,
        policy_version=revision.policy_version, charter_version=revision.charter_version,
        config_version=revision.config_version, outcome=ticket.state,
        detail={"action": revision.action_type}))


def _read_bound(s, source, ticket, revision, intent):
    from cosmas_os.application.appointment_execution import outcome

    op = _operation(s, ticket, revision)
    return {"workspace_id": source.workspace_id, "ticket_id": ticket.id, "ticket_version": ticket.version, "state": ticket.state,
            "revision_id": revision.id, "payload_hash": revision.payload_hash,
            "intent": intent.model_dump(mode="json"), "owner_id": source.owner_id,
            "operation_id": op.id if op else None, "operation_status": op.status if op else None,
            **outcome(s, op, intent)}


def read(s, box, actor, workspace_id, ticket_id, *, configuration: Settings | None = None):
    _proposal_gate(s, configuration)
    w = ws._workspace(s, box, actor, workspace_id)
    return _read_bound(s, *_bound(s, w, ticket_id))


def catalog(s, box, actor, workspace_id, *, cursor=None, configuration: Settings | None = None):
    _proposal_gate(s, configuration)
    w = ws._workspace(s, box, actor, workspace_id)
    query = select(AppointmentWork.ticket_id).where(AppointmentWork.workspace_id == w.id,
        AppointmentWork.box_id == box, AppointmentWork.owner_id == actor)
    if cursor:
        query = query.where(AppointmentWork.ticket_id > cursor)
    ids = list(s.scalars(query.order_by(AppointmentWork.ticket_id).limit(21)))
    items = []
    for tid in ids[:20]:
        _, ticket, _, intent = _bound(s, w, tid)
        window = intent.slot or intent.expected
        assert window is not None
        items.append({"ticket_id": tid, "state": ticket.state, "action": intent.action,
                      "appointment_window": {"starts_at": window.starts_at.isoformat(), "ends_at": window.ends_at.isoformat()},
                      "expires_at": intent.expires_at.isoformat()})
    return {"workspace_id": w.id, "items": items, "next_cursor": ids[19] if len(ids) > 20 else None}


def propose(s, box, actor, workspace_id, *, external_identity_id, intent, key, share, now=None,
            request_fingerprint=None, configuration: Settings | None = None):
    """Caller supplies a freshly composed receiver-backed intent, never raw UI data."""
    _proposal_gate(s, configuration)
    w = ws._workspace(s, box, actor, workspace_id, writing=True)
    checked = _intent(intent)
    if share is not True or not isinstance(key, str) or not 1 <= len(key) <= 100:
        raise ws.WorkspaceError("appointment_proposal_invalid", 400)
    if request_fingerprint is not None and (not isinstance(request_fingerprint, str)
            or not re.fullmatch(r"[0-9a-f]{64}", request_fingerprint)):
        raise ws.WorkspaceError("appointment_proposal_invalid", 400)
    # The orchestration layer fingerprints the exact human command before I/O.
    # Fresh receiver timestamps may differ on a retry of that same command.
    request_hash = request_fingerprint or payload_hash({"intent": checked.model_dump(mode="json"), "share": True})
    prior = s.scalar(select(AppointmentWork).where(
        AppointmentWork.workspace_id == w.id, AppointmentWork.idempotency_key == key,
    ))
    if prior:
        if prior.request_hash != request_hash:
            raise ws.WorkspaceError("idempotency_conflict")
        return _read_bound(s, *_bound(s, w, prior.ticket_id))
    account, patient, selection = _current(s, w, external_identity_id, configuration=configuration)
    current = _clock(now)
    if checked.selection != selection:
        raise ws.WorkspaceError("scheduling_context_changed")
    if not current < checked.expires_at <= current + timedelta(minutes=5):
        raise ws.WorkspaceError("appointment_proposal_expired")
    if checked.google and not current - timedelta(seconds=30) <= checked.google.checked_at <= current + timedelta(seconds=5):
        raise ws.WorkspaceError("appointment_proposal_expired")
    ticket = Ticket(box_id=box, lane=LANE, state="pending_approval", created_by_principal_id=actor,
                    appointment_id=w.appointment_id, patient_link_id=w.patient_link_id)
    s.add(ticket)
    s.flush()
    revision = ActionRevision(ticket_id=ticket.id, box_id=box, revision_number=1,
        action_type="scheduling." + checked.action, target_ref=_target(checked), content=_content(checked),
        payload=checked.model_dump(mode="json"), payload_hash=checked.approval_hash(),
        automation_class="hitl_required", policy_version="appointment-exact-v1",
        charter_version="human-selected-v1", config_version=("authenticated-proposal-v1"
            if configuration is not None else "local-disconnected-v1"),
        created_by_principal_id=actor)
    s.add(revision)
    s.flush()
    ticket.current_revision_id = revision.id
    s.add(AppointmentWork(ticket_id=ticket.id, box_id=box, workspace_id=w.id, owner_id=actor,
        patient_link_id=w.patient_link_id, account_id=account.id, patient_mapping_id=patient.id,
        action_revision_id=revision.id, payload_hash=revision.payload_hash, idempotency_key=key,
        request_hash=request_hash))
    _event(s, w, ticket, revision, "appointment.proposed")
    s.flush()
    _proposal_gate(s, configuration)
    s.commit()
    return read(s, box, actor, workspace_id, ticket.id, configuration=configuration)


def decide(s, box, actor, workspace_id, ticket_id, *, external_identity_id,
           revision_id, digest, choice, now=None, configuration: Settings | None = None):
    _proposal_gate(s, configuration)
    w = ws._workspace(s, box, actor, workspace_id, writing=True)
    source, ticket, revision, intent = _bound(s, w, ticket_id)
    if revision.id != revision_id or revision.payload_hash != digest:
        raise ws.WorkspaceError("appointment_approval_changed")
    op = _operation(s, ticket, revision)
    if choice == "reject":
        if ticket.state == "rejected":
            return _read_bound(s, source, ticket, revision, intent)
        if ticket.state not in {"pending_approval", "approved"} or op and (op.status != "pending" or op.started_at is not None):
            raise ws.WorkspaceError("appointment_operation_in_progress")
        if op:
            op.status = "failed"
            op.error_message = "withdrawn_before_dispatch"
        ticket.state = "rejected"
        ticket.version += 1
        s.add(Decision(box_id=box, ticket_id=ticket.id, action_revision_id=revision.id,
                       actor_principal_id=actor, kind="reject"))
        _event(s, w, ticket, revision, "appointment.rejected")
        s.flush()
        _proposal_gate(s, configuration)
        s.commit()
        return read(s, box, actor, workspace_id, ticket_id, configuration=configuration)
    if choice != "approve":
        raise ws.WorkspaceError("appointment_decision_invalid", 400)
    account, patient, selection = _current(s, w, external_identity_id, configuration=configuration)
    if (account.id != source.account_id or patient.id != source.patient_mapping_id
        or selection != intent.selection):
        raise ws.WorkspaceError("scheduling_context_changed")
    if ticket.state in {"approved", "sent"} and op is not None:
        approval = s.scalar(select(Decision.id).where(Decision.ticket_id == ticket.id,
            Decision.action_revision_id == revision.id, Decision.box_id == box,
            Decision.actor_principal_id == actor, Decision.kind == "approve"))
        if not approval:
            raise ws.WorkspaceError("appointment_approval_required")
        return _read_bound(s, source, ticket, revision, intent)
    if ticket.state != "pending_approval" or op is not None:
        raise ws.WorkspaceError("appointment_not_pending")
    if _clock(now) >= intent.expires_at:
        raise ws.WorkspaceError("appointment_proposal_expired")
    s.add(Decision(box_id=box, ticket_id=ticket.id, action_revision_id=revision.id,
                   actor_principal_id=actor, kind="approve"))
    operation_id = str(uuid4())
    op = Operation(id=operation_id, box_id=box, ticket_id=ticket.id, action_revision_id=revision.id,
                   idempotency_key="os-appointment:" + operation_id, adapter=ADAPTER, status="pending")
    s.add(op)
    ticket.state = "approved"
    ticket.version += 1
    _event(s, w, ticket, revision, "appointment.approved", approved=True)
    s.flush()
    _proposal_gate(s, configuration)
    s.commit()
    return read(s, box, actor, workspace_id, ticket_id, configuration=configuration)
