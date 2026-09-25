from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmas_os.adapters.local import (
    CsvScheduleAdapter,
    FakeAuthAdapter,
    FakeNotifyAdapter,
    InjectableClock,
    LocalBlobAdapter,
    SystemClock,
)
from cosmas_os.config import settings
from cosmas_os.domain.enums import (
    AutomationClass,
    CapabilityKey,
    CoverageStatus,
    DecisionKind,
    OperationStatus,
    PrincipalState,
    PrincipalType,
    TicketState,
)
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.domain.work_lanes import PRIVATE_CONNECTOR_LANES
from cosmas_os.domain.rules import (
    AuthorizationError,
    DomainError,
    PolicyDenied,
    enforce_automation_send,
    enforce_capability,
    resolve_policy,
    transition_ticket,
)
from cosmas_os.models import (
    ActionRevision,
    AppointmentObservation,
    Artifact,
    AuditEvent,
    BoxContext,
    CapabilityConfig,
    Decision,
    FollowUpSource,
    Operation,
    PatientLink,
    Principal,
    Ticket,
)
from cosmas_os.ports import AuthSubject, NotifyRequest

NEUTRAL_MESSAGE = (
    "Please use the secure link to share insurance information before your visit. "
    "This message contains no clinical details."
)


class Container:
    def __init__(self, session: Session, *, clock=None, notify=None, blob=None, auth=None) -> None:
        self.session = session
        self.clock = clock or (
            InjectableClock(datetime.fromisoformat(settings.cosmas_clock_now))
            if settings.cosmas_clock_now
            else SystemClock()
        )
        self.notify = notify or FakeNotifyAdapter()
        self.blob = blob if blob is not None else _default_blob_adapter()
        self.auth = auth or FakeAuthAdapter()
        self.schedule = CsvScheduleAdapter()


def _default_blob_adapter():
    if settings.blob_backend == "local":
        return LocalBlobAdapter(settings.blob_root)
    if settings.blob_backend != "azure":
        raise RuntimeError("unsupported BlobPort backend")

    account_url = settings.azure_storage_account_url
    container_name = settings.azure_blob_container
    box_id = settings.beta_box_id
    missing = [
        name
        for name, value in (
            ("AZURE_STORAGE_ACCOUNT_URL", account_url),
            ("AZURE_BLOB_CONTAINER", container_name),
            ("BETA_BOX_ID", box_id),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("Azure BlobPort configuration missing: " + ", ".join(missing))
    assert account_url is not None
    assert container_name is not None
    assert box_id is not None

    from cosmas_os.adapters.azure import AzureBlobAdapter

    return AzureBlobAdapter.from_managed_identity(
        account_url=account_url,
        container_name=container_name,
        box_id=box_id,
    )


def _require_active_human(
    principal: Principal | None,
    *,
    box_id: str,
    owner_required: bool = False,
) -> Principal:
    if principal is None:
        raise DomainError("missing principal")
    if principal.principal_type != PrincipalType.HUMAN.value:
        raise AuthorizationError("human authority required")
    if principal.state != PrincipalState.ACTIVE.value:
        raise AuthorizationError("active human authority required")
    if principal.box_id != box_id:
        raise AuthorizationError("principal is outside the Box")
    if owner_required and not principal.is_owner:
        raise AuthorizationError("owner authority required")
    return principal


def _require_operation_scope(
    op: Operation,
    rev: ActionRevision | None,
    ticket: Ticket | None,
) -> tuple[ActionRevision, Ticket]:
    if rev is None or ticket is None:
        raise DomainError("missing revision/ticket")
    if (
        op.ticket_id != ticket.id
        or op.action_revision_id != rev.id
        or rev.ticket_id != ticket.id
        or op.box_id != ticket.box_id
        or rev.box_id != ticket.box_id
        or ticket.current_revision_id != rev.id
    ):
        raise DomainError("operation scope mismatch")
    return rev, ticket


def _lock_ticket(c: Container, ticket_id: str) -> Ticket | None:
    """Load the current ticket row under a transaction-scoped write lock.

    Editing and deciding both replace or bind ``current_revision_id``.  They
    must therefore serialize on the ticket row so an approval can never be
    committed for a revision that a concurrent edit has just invalidated.
    ``populate_existing`` matters when a long-lived session already has the
    ticket in its identity map: after waiting for the lock, the decision must
    use the row state committed by the lock holder rather than cached state.
    """

    return c.session.scalar(
        select(Ticket)
        .where(Ticket.id == ticket_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _audit(
    c: Container,
    *,
    box_id: str,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    actor: str | None = None,
    initiated_by: str | None = None,
    approved_by: str | None = None,
    action_revision_id: str | None = None,
    payload_hash_value: str | None = None,
    policy_version: str | None = None,
    charter_version: str | None = None,
    config_version: str | None = None,
    outcome: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    ev = AuditEvent(
        box_id=box_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        actor_principal_id=actor,
        initiated_by_principal_id=initiated_by,
        approved_by_principal_id=approved_by,
        action_revision_id=action_revision_id,
        payload_hash=payload_hash_value,
        policy_version=policy_version,
        charter_version=charter_version,
        config_version=config_version,
        correlation_id=str(uuid4()),
        outcome=outcome,
        detail=detail or {},
        created_at=c.clock.now(),
    )
    c.session.add(ev)
    return ev


def provision_box(c: Container, display_name: str = "Synth Family Practice") -> dict[str, Any]:
    box = BoxContext(display_name=display_name)
    c.session.add(box)
    c.session.flush()

    owner = Principal(
        box_id=box.id,
        principal_type=PrincipalType.HUMAN.value,
        display_name="Alex Owner",
        is_owner=True,
        state=PrincipalState.ACTIVE.value,
    )
    c.session.add(owner)
    c.session.flush()

    agents = {}
    for key, name in (("scribe", "Scribe"), ("chief", "Chief"), ("chaser", "Chaser")):
        p = Principal(
            box_id=box.id,
            principal_type=PrincipalType.AGENT.value,
            display_name=name,
            agent_key=key,
            is_owner=False,
        )
        c.session.add(p)
        c.session.flush()
        agents[key] = p

    c.auth.register(
        AuthSubject(
            principal_id=owner.id,
            principal_type=PrincipalType.HUMAN.value,
            display_name=owner.display_name,
            is_owner=True,
        )
    )

    _audit(
        c,
        box_id=box.id,
        aggregate_type="box",
        aggregate_id=box.id,
        event_type="box.provisioned",
        actor=owner.id,
        outcome="ok",
    )
    c.session.commit()
    return {
        "box_id": box.id,
        "owner_id": owner.id,
        "agents": {k: v.id for k, v in agents.items()},
    }


def transfer_owner(c: Container, box_id: str, current_owner_id: str, successor_id: str) -> None:
    current = c.session.get(Principal, current_owner_id)
    successor = c.session.get(Principal, successor_id)
    if not current or not successor:
        raise DomainError("invalid owner transfer principals")
    _require_active_human(current, box_id=box_id, owner_required=True)
    _require_active_human(successor, box_id=box_id)
    current.is_owner = False
    successor.is_owner = True
    _audit(
        c,
        box_id=box_id,
        aggregate_type="principal",
        aggregate_id=successor_id,
        event_type="owner.transferred",
        actor=current_owner_id,
        outcome="ok",
    )
    c.session.commit()


def remove_principal(c: Container, actor_id: str, target_id: str) -> None:
    actor = c.session.get(Principal, actor_id)
    target = c.session.get(Principal, target_id)
    if not target:
        raise DomainError("invalid remove")
    _require_active_human(actor, box_id=target.box_id, owner_required=True)
    if target.is_owner:
        owners = c.session.scalars(
            select(Principal).where(
                Principal.box_id == target.box_id,
                Principal.is_owner.is_(True),
                Principal.state == PrincipalState.ACTIVE.value,
            )
        ).all()
        if len(owners) <= 1:
            raise DomainError("cannot remove last active owner without successor")
    target.state = PrincipalState.TOMBSTONED.value
    target.tombstoned_at = c.clock.now()
    _audit(
        c,
        box_id=target.box_id,
        aggregate_type="principal",
        aggregate_id=target.id,
        event_type="principal.tombstoned",
        actor=actor_id,
        outcome="ok",
        detail={"display_name": target.display_name, "agent_key": target.agent_key},
    )
    c.session.commit()


def disable_agent(c: Container, actor_id: str, agent_id: str) -> None:
    actor = c.session.get(Principal, actor_id)
    agent = c.session.get(Principal, agent_id)
    if not agent:
        raise DomainError("missing principal")
    if agent.principal_type != PrincipalType.AGENT.value:
        raise DomainError("not an agent")
    _require_active_human(actor, box_id=agent.box_id, owner_required=True)
    agent.state = PrincipalState.DISABLED.value
    _audit(
        c,
        box_id=agent.box_id,
        aggregate_type="principal",
        aggregate_id=agent.id,
        event_type="agent.disabled",
        actor=actor_id,
        outcome="ok",
    )
    c.session.commit()


def import_schedule(c: Container, box_id: str, csv_text: str) -> list[str]:
    rows = c.schedule.import_appointments(csv_text)
    ids = []
    for row in rows:
        appt = AppointmentObservation(
            box_id=box_id,
            external_id=row.external_id,
            source=row.source,
            start_at=row.start_at,
            patient_label=row.patient_label,
            coverage_status=CoverageStatus.MISSING.value,
        )
        c.session.add(appt)
        c.session.flush()
        ids.append(appt.id)
    c.session.commit()
    return ids


def attest_patient_link(
    c: Container,
    box_id: str,
    human_id: str,
    source_pair_key: str,
    label: str,
) -> PatientLink:
    human = c.session.get(Principal, human_id)
    _require_active_human(human, box_id=box_id)
    if source_pair_key.startswith("core-private:"):
        raise DomainError("private patient reference cannot be attested as shared")
    existing = c.session.scalar(
        select(PatientLink).where(
            PatientLink.box_id == box_id,
            PatientLink.source_pair_key == source_pair_key,
            PatientLink.revoked_at.is_(None),
        )
    )
    if existing and existing.source_owner_id is not None:
        raise DomainError("private patient reference unavailable")
    if existing and existing.state == "confirmed":
        return existing
    if existing:
        link = existing
    else:
        link = PatientLink(box_id=box_id, source_pair_key=source_pair_key, label=label)
        c.session.add(link)
        c.session.flush()
    link.confirmed_by_principal_id = human_id
    link.attested_at = c.clock.now()
    link.state = "confirmed"
    _audit(
        c,
        box_id=box_id,
        aggregate_type="patient_link",
        aggregate_id=link.id,
        event_type="patient_link.attested",
        actor=human_id,
        outcome="ok",
    )
    c.session.commit()
    return link


def revoke_patient_link(c: Container, link_id: str, human_id: str) -> None:
    link = c.session.get(PatientLink, link_id)
    human = c.session.get(Principal, human_id)
    if not link:
        raise DomainError("patient link missing")
    _require_active_human(human, box_id=link.box_id, owner_required=True)
    link.revoked_at = c.clock.now()
    link.state = "revoked"
    c.session.commit()


def detect_and_open_chase(
    c: Container,
    box_id: str,
    chaser_id: str,
    appointment_id: str,
    patient_link_id: str,
) -> Ticket:
    chaser = c.session.get(Principal, chaser_id)
    appt = c.session.get(AppointmentObservation, appointment_id)
    link = c.session.get(PatientLink, patient_link_id)
    if (
        not chaser
        or chaser.principal_type != PrincipalType.AGENT.value
        or chaser.agent_key != "chaser"
    ):
        raise DomainError("chaser agent required")
    if chaser.state != PrincipalState.ACTIVE.value:
        raise DomainError("chaser disabled")
    if chaser.box_id != box_id:
        raise AuthorizationError("chaser is outside the Box")
    if not appt or appt.box_id != box_id:
        raise DomainError("appointment missing")
    if not link or link.box_id != box_id or link.state != "confirmed" or link.revoked_at is not None:
        raise DomainError("unconfirmed PatientLink blocks chase")
    if appt.source_owner_id is not None or link.source_owner_id is not None:
        raise DomainError("private appointment cannot enter shared artifact chase")
    if appt.coverage_status not in {
        CoverageStatus.MISSING.value,
        CoverageStatus.STALE.value,
        CoverageStatus.UNKNOWN.value,
    }:
        raise DomainError("no missing/stale artifact")

    appt.patient_link_id = link.id
    ticket = Ticket(
        box_id=box_id,
        lane="artifact_chase",
        state=TicketState.DRAFT.value,
        created_by_principal_id=chaser_id,
        appointment_id=appt.id,
        patient_link_id=link.id,
    )
    c.session.add(ticket)
    c.session.flush()

    payload = {
        "action": "notify.patient_insurance_request",
        "channel": "fake_secure_link",
        "body": NEUTRAL_MESSAGE,
        "target_ref": f"patient_link:{link.id}",
        "appointment_ref": appt.external_id,
    }
    rev = ActionRevision(
        ticket_id=ticket.id,
        box_id=box_id,
        revision_number=1,
        action_type="notify.patient_insurance_request",
        target_ref=payload["target_ref"],
        content=NEUTRAL_MESSAGE,
        payload=payload,
        payload_hash=payload_hash(payload),
        automation_class=AutomationClass.HITL_REQUIRED.value,
        policy_version=chaser.policy_version,
        charter_version=chaser.charter_version,
        config_version=chaser.config_version,
        created_by_principal_id=chaser_id,
    )
    c.session.add(rev)
    c.session.flush()
    ticket.current_revision_id = rev.id
    ticket.state = transition_ticket(TicketState.DRAFT, TicketState.PENDING_APPROVAL).value
    _audit(
        c,
        box_id=box_id,
        aggregate_type="ticket",
        aggregate_id=ticket.id,
        event_type="ticket.opened",
        actor=chaser_id,
        initiated_by=chaser_id,
        action_revision_id=rev.id,
        payload_hash_value=rev.payload_hash,
        policy_version=rev.policy_version,
        charter_version=rev.charter_version,
        config_version=rev.config_version,
        outcome="pending_approval",
    )
    c.session.commit()
    return ticket


def _require_legacy_work_path(c: Container, ticket: Ticket) -> None:
    from cosmas_os.models import AppointmentWork

    appointment = c.session.get(AppointmentObservation, ticket.appointment_id) if ticket.appointment_id else None
    link = c.session.get(PatientLink, ticket.patient_link_id) if ticket.patient_link_id else None
    if appointment is not None and appointment.source_owner_id is not None or link is not None and link.source_owner_id is not None:
        raise AuthorizationError("private reference requires its workspace review path")
    if ticket.lane == "scheduling_appointment" or c.session.get(AppointmentWork, ticket.id):
        raise AuthorizationError("appointment actions require their private workspace review path")
    if ticket.lane in {"encounter_follow_up", "visit_preparation"} | PRIVATE_CONNECTOR_LANES or c.session.get(FollowUpSource, ticket.id):
        raise AuthorizationError("follow-up requires its private workspace review path")


def edit_revision(c: Container, ticket_id: str, human_id: str, new_body: str) -> ActionRevision:
    ticket = _lock_ticket(c, ticket_id)
    human = c.session.get(Principal, human_id)
    if not ticket or not human:
        raise DomainError("missing")
    _require_legacy_work_path(c, ticket)
    _require_active_human(human, box_id=ticket.box_id)
    if ticket.state != TicketState.PENDING_APPROVAL.value:
        raise DomainError("edit only while pending approval")
    old = c.session.get(ActionRevision, ticket.current_revision_id)
    if not old:
        raise DomainError("no revision")
    if old.ticket_id != ticket.id or old.box_id != ticket.box_id:
        raise DomainError("revision scope mismatch")
    old.invalidated = True
    payload = dict(old.payload)
    payload["body"] = new_body
    rev = ActionRevision(
        ticket_id=ticket.id,
        box_id=ticket.box_id,
        revision_number=old.revision_number + 1,
        action_type=old.action_type,
        target_ref=old.target_ref,
        content=new_body,
        payload=payload,
        payload_hash=payload_hash(payload),
        automation_class=old.automation_class,
        policy_version=old.policy_version,
        charter_version=old.charter_version,
        config_version=old.config_version,
        created_by_principal_id=human_id,
    )
    c.session.add(rev)
    c.session.flush()
    ticket.current_revision_id = rev.id
    ticket.version += 1
    c.session.add(
        Decision(
            box_id=ticket.box_id,
            ticket_id=ticket.id,
            action_revision_id=rev.id,
            actor_principal_id=human_id,
            kind=DecisionKind.EDIT.value,
            note="edited content; prior approval invalidated",
        )
    )
    _audit(
        c,
        box_id=ticket.box_id,
        aggregate_type="ticket",
        aggregate_id=ticket.id,
        event_type="revision.edited",
        actor=human_id,
        action_revision_id=rev.id,
        payload_hash_value=rev.payload_hash,
        outcome="pending_approval",
    )
    c.session.commit()
    return rev


def decide(
    c: Container,
    ticket_id: str,
    human_id: str,
    kind: DecisionKind,
    *,
    expected_revision_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    ticket = _lock_ticket(c, ticket_id)
    human = c.session.get(Principal, human_id)
    if not ticket or not human:
        raise DomainError("missing")
    _require_legacy_work_path(c, ticket)
    _require_active_human(human, box_id=ticket.box_id)

    if kind == DecisionKind.APPROVE and not resolve_policy(
        platform_allows=True,
        charter_allows=True,
        specialty_allows=True,
        org_allows=True,
    ):
        raise PolicyDenied("policy denied")

    rev = c.session.get(ActionRevision, ticket.current_revision_id)
    if not rev or rev.invalidated:
        raise DomainError("no current revision")
    if rev.ticket_id != ticket.id or rev.box_id != ticket.box_id:
        raise DomainError("revision scope mismatch")
    if expected_revision_id and expected_revision_id != rev.id:
        raise DomainError("stale revision")

    # Concurrent double-approve / retry: return existing decision+operation
    existing_op = c.session.scalar(
        select(Operation).where(Operation.action_revision_id == rev.id)
    )
    if kind == DecisionKind.APPROVE and existing_op is not None:
        _require_operation_scope(existing_op, rev, ticket)
        if existing_op.status == OperationStatus.PENDING.value:
            _dispatch_operation(c, existing_op)
        return {"decision": "already_approved", "operation_id": existing_op.id}
    if kind == DecisionKind.APPROVE and ticket.state in {
        TicketState.APPROVED.value,
        TicketState.SENT.value,
        TicketState.CONFIRMED.value,
        TicketState.CLOSED.value,
    }:
        return {"decision": "already_approved", "operation_id": existing_op.id if existing_op else None}

    if ticket.state != TicketState.PENDING_APPROVAL.value and kind != DecisionKind.APPROVE:
        # reject/escalate from pending only
        if ticket.state != TicketState.PENDING_APPROVAL.value:
            raise DomainError("ticket not pending approval")

    enforce_automation_send(AutomationClass(rev.automation_class))

    c.session.add(
        Decision(
            box_id=ticket.box_id,
            ticket_id=ticket.id,
            action_revision_id=rev.id,
            actor_principal_id=human_id,
            kind=kind.value,
            note=note,
        )
    )

    if kind == DecisionKind.REJECT:
        ticket.state = transition_ticket(TicketState.PENDING_APPROVAL, TicketState.REJECTED).value
        ticket.version += 1
        _audit(
            c,
            box_id=ticket.box_id,
            aggregate_type="ticket",
            aggregate_id=ticket.id,
            event_type="decision.rejected",
            actor=human_id,
            approved_by=human_id,
            action_revision_id=rev.id,
            outcome="rejected",
        )
        c.session.commit()
        return {"decision": "rejected", "operation_id": None}

    if kind == DecisionKind.ESCALATE:
        ticket.state = transition_ticket(TicketState.PENDING_APPROVAL, TicketState.ESCALATED).value
        ticket.version += 1
        _audit(
            c,
            box_id=ticket.box_id,
            aggregate_type="ticket",
            aggregate_id=ticket.id,
            event_type="decision.escalated",
            actor=human_id,
            action_revision_id=rev.id,
            outcome="escalated",
        )
        c.session.commit()
        return {"decision": "escalated", "operation_id": None}

    if kind != DecisionKind.APPROVE:
        raise DomainError("unsupported decision")

    # Approve + create operation atomically
    ticket.state = transition_ticket(TicketState.PENDING_APPROVAL, TicketState.APPROVED).value
    ticket.version += 1
    op = Operation(
        box_id=ticket.box_id,
        ticket_id=ticket.id,
        action_revision_id=rev.id,
        idempotency_key=f"op:{rev.id}",
        adapter="compact_fake" if settings.execution_backend == "postgres_local" else "notify",
        status=OperationStatus.PENDING.value,
    )
    c.session.add(op)
    c.session.flush()
    _audit(
        c,
        box_id=ticket.box_id,
        aggregate_type="ticket",
        aggregate_id=ticket.id,
        event_type="decision.approved",
        actor=human_id,
        approved_by=human_id,
        action_revision_id=rev.id,
        payload_hash_value=rev.payload_hash,
        policy_version=rev.policy_version,
        charter_version=rev.charter_version,
        config_version=rev.config_version,
        outcome="approved",
        detail={"operation_bound": True},
    )
    c.session.commit()

    _dispatch_operation(c, op)

    return {"decision": "approved", "operation_id": op.id}


def _dispatch_operation(c: Container, operation: Operation) -> None:
    """Dispatch one durable pending operation without creating a replacement."""

    if settings.execution_backend == "postgres_local":
        settings.validate_runtime_configuration()
        # Approval already committed the intent. The independent DB worker
        # discovers it even if the API exits immediately: no publish gap.
        return

    if settings.sync_worker:
        execute_operation(c, operation.id)
        c.session.refresh(operation)
        return

    from cosmas_os.worker.tasks import execute_operation_task

    execute_operation_task.delay(operation.id)


def execute_operation(c: Container, operation_id: str) -> Operation:
    op = c.session.get(Operation, operation_id)
    if not op:
        raise DomainError("operation missing")
    if settings.execution_backend == "postgres_local" or op.adapter != "notify":
        raise DomainError("operation requires its configured execution backend")

    rev = c.session.get(ActionRevision, op.action_revision_id)
    ticket = c.session.get(Ticket, op.ticket_id)
    rev, ticket = _require_operation_scope(op, rev, ticket)

    _require_legacy_work_path(c, ticket)

    if op.status in {OperationStatus.SUCCEEDED.value}:
        return op
    if op.status == OperationStatus.UNKNOWN.value:
        return reconcile_unknown(c, operation_id)

    op.status = OperationStatus.RUNNING.value
    op.attempt_count += 1
    op.started_at = c.clock.now()
    c.session.commit()

    try:
        receipt = c.notify.send(
            NotifyRequest(
                operation_id=op.id,
                channel=str(rev.payload.get("channel", "fake")),
                body=rev.content,
                target_ref=rev.target_ref,
            )
        )
        if receipt.status == "unknown":
            op.status = OperationStatus.UNKNOWN.value
            op.external_reference = receipt.external_reference
            op.error_message = "unconfirmed external outcome"
            c.session.commit()
            return op
        if receipt.status != "succeeded":
            op.status = OperationStatus.FAILED.value
            op.error_message = receipt.status
            ticket.state = TicketState.FAILED.value
            c.session.commit()
            return op

        # Verify executed payload still matches approval
        if payload_hash(rev.payload) != rev.payload_hash:
            raise DomainError("payload hash mismatch")

        op.status = OperationStatus.SUCCEEDED.value
        op.external_reference = receipt.external_reference
        op.result_receipt_hash = payload_hash({"ref": receipt.external_reference, "status": receipt.status})
        op.completed_at = c.clock.now()
        ticket.state = transition_ticket(TicketState.APPROVED, TicketState.SENT).value
        _audit(
            c,
            box_id=op.box_id,
            aggregate_type="operation",
            aggregate_id=op.id,
            event_type="operation.succeeded",
            action_revision_id=rev.id,
            payload_hash_value=rev.payload_hash,
            outcome="succeeded",
            detail={"external_reference": receipt.external_reference},
        )
        c.session.commit()
        return op
    except Exception as exc:  # noqa: BLE001 — ledger must capture crash path
        # Crash-before-ack: if notify already recorded success for this op, reconcile
        prior = c.notify.sent.get(op.id)
        if prior and prior.status == "succeeded":
            op.status = OperationStatus.UNKNOWN.value
            op.external_reference = prior.external_reference
            op.error_message = f"crash after possible success: {exc}"
            c.session.commit()
            return reconcile_unknown(c, op.id)
        op.status = OperationStatus.PENDING.value
        op.error_message = str(exc)
        c.session.commit()
        raise


def reconcile_unknown(c: Container, operation_id: str) -> Operation:
    op = c.session.get(Operation, operation_id)
    if not op:
        raise DomainError("missing op")
    if settings.execution_backend == "postgres_local" or op.adapter != "notify":
        raise DomainError("operation requires its configured execution backend")
    prior = c.notify.sent.get(op.id)
    ticket = c.session.get(Ticket, op.ticket_id)
    rev = c.session.get(ActionRevision, op.action_revision_id)
    rev, ticket = _require_operation_scope(op, rev, ticket)
    _require_legacy_work_path(c, ticket)
    if prior and prior.status == "succeeded" and ticket and rev:
        op.status = OperationStatus.SUCCEEDED.value
        op.external_reference = prior.external_reference
        op.result_receipt_hash = payload_hash({"ref": prior.external_reference, "status": prior.status})
        op.completed_at = c.clock.now()
        if ticket.state == TicketState.APPROVED.value:
            ticket.state = TicketState.SENT.value
        _audit(
            c,
            box_id=op.box_id,
            aggregate_type="operation",
            aggregate_id=op.id,
            event_type="operation.reconciled",
            action_revision_id=rev.id,
            outcome="succeeded",
        )
        c.session.commit()
        return op
    # Do not blind retry when unknown without receipt
    return op


def simulate_upload_and_verify(
    c: Container,
    ticket_id: str,
    human_id: str,
    front_bytes: bytes,
    back_bytes: bytes,
) -> dict[str, Any]:
    ticket = c.session.get(Ticket, ticket_id)
    human = c.session.get(Principal, human_id)
    if not ticket:
        raise DomainError("ticket missing")
    _require_legacy_work_path(c, ticket)
    _require_active_human(human, box_id=ticket.box_id)
    appt = c.session.get(AppointmentObservation, ticket.appointment_id) if ticket.appointment_id else None
    if appt and appt.box_id != ticket.box_id:
        raise DomainError("appointment scope mismatch")
    arts = []
    for side, data in (("front", front_bytes), ("back", back_bytes)):
        art = Artifact(
            box_id=ticket.box_id,
            ticket_id=ticket.id,
            side=side,
            classification="insurance_working_copy",
        )
        c.session.add(art)
        c.session.flush()
        token = c.blob.issue_upload_token(art.id)
        artifact_id = c.blob.consume_upload_token(token)
        key = f"{ticket.box_id}/{artifact_id}/{side}.png"
        c.blob.put_bytes(key, data, "image/png")
        art.blob_key = key
        arts.append(art.id)

    if appt:
        appt.coverage_status = CoverageStatus.IMAGE_ON_FILE.value
    ticket.state = TicketState.CONFIRMED.value
    _audit(
        c,
        box_id=ticket.box_id,
        aggregate_type="ticket",
        aggregate_id=ticket.id,
        event_type="artifact.verified",
        actor=human_id,
        outcome="image_on_file",
    )
    c.session.commit()
    return {"artifact_ids": arts, "coverage_status": CoverageStatus.IMAGE_ON_FILE.value}


def close_ticket(c: Container, ticket_id: str, human_id: str) -> Ticket:
    ticket = c.session.get(Ticket, ticket_id)
    human = c.session.get(Principal, human_id)
    if not ticket or not human:
        raise DomainError("missing")
    _require_legacy_work_path(c, ticket)
    _require_active_human(human, box_id=ticket.box_id)
    current = TicketState(ticket.state)
    if current not in {TicketState.CONFIRMED, TicketState.REJECTED, TicketState.ESCALATED, TicketState.FAILED}:
        # allow close from confirmed primarily
        if current == TicketState.SENT:
            ticket.state = TicketState.CONFIRMED.value
            current = TicketState.CONFIRMED
    ticket.state = transition_ticket(TicketState(ticket.state), TicketState.CLOSED).value
    ticket.closed_at = c.clock.now()
    _audit(
        c,
        box_id=ticket.box_id,
        aggregate_type="ticket",
        aggregate_id=ticket.id,
        event_type="ticket.closed",
        actor=human_id,
        outcome="closed",
    )
    c.session.commit()
    return ticket


def purge_due_artifacts(
    c: Container,
    box_id: str,
    actor_id: str,
    *,
    retain_days: int = 7,
) -> list[dict[str, Any]]:
    from datetime import timedelta

    actor = c.session.scalar(
        select(Principal).where(Principal.id == actor_id).with_for_update()
    )
    _require_active_human(actor, box_id=box_id, owner_required=True)
    now = c.clock.now()
    tickets = c.session.scalars(
        select(Ticket).where(
            Ticket.box_id == box_id,
            Ticket.state == TicketState.CLOSED.value,
            Ticket.closed_at.is_not(None),
        )
    ).all()
    receipts = []
    for ticket in tickets:
        assert ticket.closed_at is not None
        if ticket.closed_at + timedelta(days=retain_days) > now:
            continue
        arts = c.session.scalars(
            select(Artifact).where(
                Artifact.ticket_id == ticket.id,
                Artifact.box_id == box_id,
                Artifact.purged_at.is_(None),
            )
        ).all()
        for art in arts:
            if art.blob_key:
                c.blob.delete(art.blob_key)
            art.blob_key = None
            art.purged_at = now
            receipt = {
                "artifact_id": art.id,
                "retention_rule": f"closed_plus_{retain_days}d",
                "deleted_at": now.isoformat(),
                "outcome": "purged",
            }
            art.purge_receipt = receipt
            receipts.append(receipt)
            _audit(
                c,
                box_id=box_id,
                aggregate_type="artifact",
                aggregate_id=art.id,
                event_type="artifact.purged",
                actor=actor_id,
                outcome="purged",
                detail={
                    "retention_rule": receipt["retention_rule"],
                    "owner_authorized": True,
                },
            )
    c.session.commit()
    return receipts


def list_queue(c: Container, box_id: str) -> list[dict[str, Any]]:
    tickets = c.session.scalars(
        select(Ticket).where(Ticket.box_id == box_id, Ticket.lane.not_in(PRIVATE_CONNECTOR_LANES),
            ~select(FollowUpSource.ticket_id).where(FollowUpSource.ticket_id == Ticket.id,
                FollowUpSource.source_kind == "vendor_reviewed_note").exists()).order_by(Ticket.created_at.desc())
    ).all()
    out = []
    for t in tickets:
        rev = c.session.get(ActionRevision, t.current_revision_id) if t.current_revision_id else None
        if rev and (rev.ticket_id != t.id or rev.box_id != box_id):
            raise DomainError("revision scope mismatch")
        out.append(
            {
                "id": t.id,
                "lane": t.lane,
                "state": t.state,
                "proposed_message": rev.content if rev else None,
                "revision_id": rev.id if rev else None,
                "patient_link_id": t.patient_link_id,
            }
        )
    return out


def audit_timeline(c: Container, box_id: str, ticket_id: str) -> list[dict[str, Any]]:
    ticket = c.session.get(Ticket, ticket_id)
    if not ticket:
        raise DomainError("ticket missing")
    if ticket.box_id != box_id:
        raise AuthorizationError("ticket is outside the Box")
    source = c.session.get(FollowUpSource, ticket_id)
    if ticket.lane in PRIVATE_CONNECTOR_LANES or source and source.source_kind == "vendor_reviewed_note":
        raise AuthorizationError("connector work requires its private or published review path")
    events = c.session.scalars(
        select(AuditEvent)
        .where(AuditEvent.box_id == box_id, AuditEvent.aggregate_type == "ticket",
            AuditEvent.aggregate_id == ticket_id)
        .order_by(AuditEvent.created_at.asc())
    ).all()
    ops = c.session.scalars(
        select(Operation)
        .join(ActionRevision, Operation.action_revision_id == ActionRevision.id)
        .where(
            Operation.ticket_id == ticket_id,
            Operation.box_id == box_id,
            ActionRevision.ticket_id == ticket_id,
            ActionRevision.box_id == box_id,
        )
    ).all()
    op_ids = {o.id for o in ops}
    more = c.session.scalars(
        select(AuditEvent)
        .where(AuditEvent.box_id == box_id, AuditEvent.aggregate_type == "operation")
        .order_by(AuditEvent.created_at.asc())
    ).all()
    merged: list[AuditEvent] = list(events)
    for ev in more:
        if ev.aggregate_id in op_ids:
            merged.append(ev)
    merged = sorted(merged, key=lambda e: e.created_at or c.clock.now())
    return [
        {
            "event_type": e.event_type,
            "actor_principal_id": e.actor_principal_id,
            "approved_by_principal_id": e.approved_by_principal_id,
            "action_revision_id": e.action_revision_id,
            "payload_hash": e.payload_hash,
            "outcome": e.outcome,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in merged
    ]


def reject_dark_capability(c: Container, box_id: str, key: CapabilityKey) -> None:
    enabled = {
        row.key
        for row in c.session.scalars(
            select(CapabilityConfig).where(CapabilityConfig.box_id == box_id, CapabilityConfig.enabled.is_(True))
        )
    }
    enforce_capability(enabled, key)
