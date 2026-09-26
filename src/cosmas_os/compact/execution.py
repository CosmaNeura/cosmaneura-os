from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from cosmas_os.compact.models import ClaimRecord, SyntheticReceipt
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.domain.rules import DomainError
from cosmas_os.models import (
    ActionRevision,
    AppointmentObservation,
    AuditEvent,
    Decision,
    Operation,
    PatientLink,
    Principal,
    Ticket,
)

ADAPTER = "compact_fake"


class LostClaim(RuntimeError):
    """No authority to act: a claim expired, completed, or was replaced."""


@dataclass(frozen=True)
class Lease:
    operation_id: str
    box_id: str
    token: str


def database_now(session: Session) -> datetime:
    return session.execute(select(func.clock_timestamp())).scalar_one()


def _event(session: Session, op: Operation, event: str) -> None:
    session.add(
        AuditEvent(
            box_id=op.box_id,
            aggregate_type="operation",
            aggregate_id=op.id,
            event_type=event,
            action_revision_id=op.action_revision_id,
            outcome=op.status,
            detail={"execution_profile": "postgres_local"},
        )
    )


def _approved_request(session: Session, op: Operation, *, for_effect: bool) -> str:
    """Return the exact approved request digest, validating before any effect.

    These locks also serialize the local fake effect against revocation/editing.
    Reconciliation records an already-proven outcome, not new send authority.
    """
    rev = session.scalar(
        select(ActionRevision).where(ActionRevision.id == op.action_revision_id).with_for_update()
    )
    ticket = session.scalar(select(Ticket).where(Ticket.id == op.ticket_id).with_for_update())
    if (
        not rev
        or not ticket
        or (
            op.adapter != ADAPTER
            or op.box_id != rev.box_id
            or op.box_id != ticket.box_id
            or rev.ticket_id != ticket.id
            or ticket.current_revision_id != rev.id
            or rev.invalidated
            or ticket.state != "approved"
            or rev.payload_hash != payload_hash(rev.payload)
            or rev.content != rev.payload.get("body")
            or rev.target_ref != rev.payload.get("target_ref")
            or rev.action_type != rev.payload.get("action")
            or rev.action_type != "notify.patient_insurance_request"
            or rev.payload.get("channel") != "fake_secure_link"
            or rev.automation_class != "hitl_required"
        )
    ):
        raise DomainError("compact approval binding is invalid")
    decision = session.scalar(
        select(Decision).where(
            Decision.box_id == op.box_id,
            Decision.ticket_id == ticket.id,
            Decision.action_revision_id == rev.id,
            Decision.kind == "approve",
        )
    )
    if not decision:
        raise DomainError("compact human approval is missing")
    human = session.scalar(
        select(Principal).where(Principal.id == decision.actor_principal_id).with_for_update()
    )
    if (
        not human
        or human.box_id != op.box_id
        or human.principal_type != "human"
        or (for_effect and human.state != "active")
    ):
        raise DomainError("compact human authority is invalid")
    approved = session.scalar(
        select(AuditEvent.id).where(
            AuditEvent.box_id == op.box_id,
            AuditEvent.aggregate_id == ticket.id,
            AuditEvent.event_type == "decision.approved",
            AuditEvent.action_revision_id == rev.id,
            AuditEvent.approved_by_principal_id == human.id,
            AuditEvent.payload_hash == rev.payload_hash,
            AuditEvent.policy_version == rev.policy_version,
            AuditEvent.charter_version == rev.charter_version,
            AuditEvent.config_version == rev.config_version,
        )
    )
    if not approved:
        raise DomainError("compact approval snapshot is invalid")
    if for_effect:
        link = session.scalar(
            select(PatientLink).where(PatientLink.id == ticket.patient_link_id).with_for_update()
        )
        appointment = session.get(AppointmentObservation, ticket.appointment_id)
        if (
            not link
            or not appointment
            or (
                link.box_id != op.box_id
                or appointment.box_id != op.box_id
                or link.state != "confirmed"
                or link.revoked_at is not None
                or link.source_owner_id is not None
                or appointment.source_owner_id is not None
                or rev.target_ref != f"patient_link:{link.id}"
                or rev.payload.get("appointment_ref") != appointment.external_id
            )
        ):
            raise DomainError("compact target authority is invalid")
    return payload_hash({"box_id": op.box_id, "operation_id": op.id, "payload": rev.payload})


class PostgresExecutor:
    """Bounded local experiment. Every effect is a durable invented DB receipt.

    All mutation paths lock Operation first. A fresh token is a fencing value,
    not a claim of exactly-once delivery to any external service.
    """

    def __init__(self, engine: Engine, *, lease_seconds: int = 10, max_attempts: int = 5):
        if not 1 <= lease_seconds <= 60 or not 1 <= max_attempts <= 5:
            raise ValueError("invalid bounded worker configuration")
        from cosmas_os.compact.schema import require_local_engine

        require_local_engine(engine)
        self.sessions = sessionmaker(engine, expire_on_commit=False)
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    def claim_next(self, box_id: str) -> Lease | None:
        with self.sessions.begin() as session:
            now = database_now(session)
            op = session.scalar(
                select(Operation)
                .outerjoin(ClaimRecord, ClaimRecord.operation_id == Operation.id)
                .where(
                    Operation.box_id == box_id,
                    Operation.adapter == ADAPTER,
                    or_(
                        and_(
                            Operation.status == "pending",
                            or_(
                                ClaimRecord.operation_id.is_(None),
                                ClaimRecord.next_attempt_at <= now,
                            ),
                        ),
                        and_(Operation.status == "running", ClaimRecord.lease_until <= now),
                    ),
                )
                .order_by(Operation.created_at, Operation.id)
                .with_for_update(of=Operation, skip_locked=True)
                .limit(1)
            )
            if not op:
                return None
            row = session.get(ClaimRecord, op.id)
            if op.status == "running" and row and row.phase == "dispatching":
                # Lease expiry cannot prove whether dispatch delivered anything.
                self._unknown(session, op, row)
                self._reconcile(session, op, row)
                return None
            if op.status == "running" and (not row or row.phase != "claimed"):
                raise DomainError("invalid compact claim state")
            if op.attempt_count >= self.max_attempts:
                self._failed(session, op, row, "pre-dispatch retry budget exhausted")
                return None
            token = str(uuid4())
            if row is None:
                row = ClaimRecord(operation_id=op.id)
                session.add(row)
            row.token = token
            row.phase = "claimed"
            row.lease_until = now + timedelta(seconds=self.lease_seconds)
            row.next_attempt_at = now
            op.status = "running"
            op.started_at = now
            op.attempt_count += 1
            op.error_message = None
            _event(session, op, "operation.claimed")
            return Lease(op.id, op.box_id, token)

    def _owned(self, session: Session, lease: Lease, phase: str) -> tuple[Operation, ClaimRecord]:
        op = session.scalar(
            select(Operation).where(Operation.id == lease.operation_id).with_for_update()
        )
        row = session.get(ClaimRecord, lease.operation_id)
        if (
            not op
            or not row
            or (
                op.box_id != lease.box_id
                or op.adapter != ADAPTER
                or op.status != "running"
                or row.token != lease.token
                or row.phase != phase
                or row.lease_until <= database_now(session)
            )
        ):
            raise LostClaim("compact claim is no longer current")
        return op, row

    def begin_dispatch(self, lease: Lease) -> None:
        with self.sessions.begin() as session:
            op, row = self._owned(session, lease, "claimed")
            _approved_request(session, op, for_effect=True)
            row.phase = "dispatching"
            _event(session, op, "operation.dispatch_started")

    def record_fake_effect(self, lease: Lease) -> None:
        """Only effect adapter in this profile; no network/vendor implementation."""
        with self.sessions.begin() as session:
            op, _ = self._owned(session, lease, "dispatching")
            digest = _approved_request(session, op, for_effect=True)
            prior = session.get(SyntheticReceipt, op.id)
            if prior:
                if prior.box_id != op.box_id or prior.request_hash != digest:
                    raise DomainError("compact receipt binding mismatch")
                return
            session.add(
                SyntheticReceipt(
                    operation_id=op.id,
                    box_id=op.box_id,
                    request_hash=digest,
                    external_reference=f"fake-{op.id}",
                    created_at=database_now(session),
                )
            )

    def _reconcile(self, session: Session, op: Operation, row: ClaimRecord) -> bool:
        receipt = session.get(SyntheticReceipt, op.id)
        if not receipt:
            return False
        try:
            digest = _approved_request(session, op, for_effect=False)
        except DomainError:
            return False
        if (
            receipt.box_id != op.box_id
            or receipt.request_hash != digest
            or receipt.external_reference != f"fake-{op.id}"
        ):
            return False
        op.status = "succeeded"
        op.external_reference = receipt.external_reference
        op.result_receipt_hash = payload_hash(
            {"ref": receipt.external_reference, "status": "succeeded"}
        )
        op.completed_at = database_now(session)
        op.error_message = None
        row.phase = "done"
        ticket = session.get(Ticket, op.ticket_id)
        assert ticket is not None
        ticket.state = "sent"
        _event(session, op, "operation.reconciled")
        return True

    def finish(self, lease: Lease) -> None:
        with self.sessions.begin() as session:
            op, row = self._owned(session, lease, "dispatching")
            if not self._reconcile(session, op, row):
                self._unknown(session, op, row)

    def _unknown(self, session: Session, op: Operation, row: ClaimRecord) -> None:
        op.status = "unknown"
        op.error_message = "unconfirmed synthetic outcome; reconciliation required"
        row.phase = "uncertain"
        _event(session, op, "operation.unknown")

    def _failed(
        self, session: Session, op: Operation, row: ClaimRecord | None, reason: str
    ) -> None:
        op.status = "failed"
        op.error_message = reason
        op.completed_at = database_now(session)
        if row:
            row.phase = "done"
        ticket = session.get(Ticket, op.ticket_id)
        if ticket and ticket.box_id == op.box_id and ticket.state == "approved":
            ticket.state = "failed"
        _event(session, op, "operation.failed")

    def fail_before_dispatch(self, lease: Lease) -> None:
        with self.sessions.begin() as session:
            op, row = self._owned(session, lease, "claimed")
            self._failed(session, op, row, "approval or target validation failed")

    def retry_before_dispatch(self, lease: Lease) -> None:
        """Only a provably pre-dispatch failure is eligible for bounded retry."""
        with self.sessions.begin() as session:
            op, row = self._owned(session, lease, "claimed")
            if op.attempt_count >= self.max_attempts:
                self._failed(session, op, row, "pre-dispatch retry budget exhausted")
            else:
                op.status = "pending"
                row.phase = "waiting"
                row.next_attempt_at = database_now(session) + timedelta(
                    seconds=min(2**op.attempt_count, 30)
                )
                _event(session, op, "operation.retry_scheduled")

    def uncertain(self, lease: Lease) -> None:
        with self.sessions.begin() as session:
            op, row = self._owned(session, lease, "dispatching")
            self._unknown(session, op, row)

    def reconcile_known(self, box_id: str) -> None:
        with self.sessions.begin() as session:
            operations = session.scalars(
                select(Operation)
                .join(SyntheticReceipt, SyntheticReceipt.operation_id == Operation.id)
                .where(
                    Operation.box_id == box_id,
                    Operation.adapter == ADAPTER,
                    Operation.status == "unknown",
                )
                .order_by(Operation.created_at, Operation.id)
                .with_for_update(of=Operation, skip_locked=True)
                .limit(10)
            ).all()
            for op in operations:
                row = session.get(ClaimRecord, op.id)
                if row:
                    self._reconcile(session, op, row)

    def tick(self, box_id: str) -> bool:
        self.reconcile_known(box_id)
        lease = self.claim_next(box_id)
        if not lease:
            return False
        try:
            self.begin_dispatch(lease)
        except DomainError:
            self.fail_before_dispatch(lease)
            return True
        try:
            self.record_fake_effect(lease)
            self.finish(lease)
        except LostClaim:
            # Recovery belongs to the current claimant/scanner, never this worker.
            raise
        except Exception:
            # Never infer a safe retry from a generic exception after dispatch.
            self.uncertain(lease)
        return True
