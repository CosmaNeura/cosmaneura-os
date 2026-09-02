from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cosmas_os.db import Base
from cosmas_os.domain.enums import (
    AutomationClass,
    CoverageStatus,
    OperationStatus,
    PrincipalState,
    TicketState,
)


def _uuid() -> str:
    return str(uuid4())


class BoxContext(Base):
    __tablename__ = "box_contexts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Principal(Base):
    __tablename__ = "principals"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default=PrincipalState.ACTIVE.value)
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    charter_version: Mapped[str] = mapped_column(String(64), default="charter-v1")
    config_version: Mapped[str] = mapped_column(String(64), default="config-v1")
    policy_version: Mapped[str] = mapped_column(String(64), default="policy-v1")
    tombstoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PatientLink(Base):
    __tablename__ = "patient_links"
    __table_args__ = (
        UniqueConstraint("box_id", "source_pair_key", name="uq_patient_link_source_pair"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"), nullable=False)
    source_pair_key: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    confirmed_by_principal_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("principals.id"), nullable=True
    )
    attested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="unconfirmed")


class AppointmentObservation(Base):
    __tablename__ = "appointment_observations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    patient_label: Mapped[str] = mapped_column(String(200), nullable=False)
    patient_link_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("patient_links.id"), nullable=True
    )
    coverage_status: Mapped[str] = mapped_column(String(32), default=CoverageStatus.MISSING.value)


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"), nullable=False)
    lane: Mapped[str] = mapped_column(String(64), default="artifact_chase")
    state: Mapped[str] = mapped_column(String(32), default=TicketState.DRAFT.value)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by_principal_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("principals.id"))
    appointment_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("appointment_observations.id"), nullable=True
    )
    patient_link_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("patient_links.id"), nullable=True
    )
    current_revision_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    revisions: Mapped[list[ActionRevision]] = relationship(back_populates="ticket")


class ActionRevision(Base):
    __tablename__ = "action_revisions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("tickets.id"), nullable=False)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    automation_class: Mapped[str] = mapped_column(
        String(32), default=AutomationClass.HITL_REQUIRED.value
    )
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    charter_version: Mapped[str] = mapped_column(String(64), nullable=False)
    config_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_principal_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("principals.id"))
    invalidated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="revisions")


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"), nullable=False)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("tickets.id"), nullable=False)
    action_revision_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("action_revisions.id"), nullable=False
    )
    actor_principal_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("principals.id"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Operation(Base):
    __tablename__ = "operations"
    __table_args__ = (
        UniqueConstraint("action_revision_id", name="uq_operation_action_revision"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"), nullable=False)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("tickets.id"), nullable=False)
    action_revision_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("action_revisions.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    adapter: Mapped[str] = mapped_column(String(64), default="notify")
    status: Mapped[str] = mapped_column(String(32), default=OperationStatus.PENDING.value)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    external_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    result_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_principal_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    initiated_by_principal_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    approved_by_principal_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    action_revision_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    charter_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"), nullable=False)
    ticket_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("tickets.id"), nullable=True)
    classification: Mapped[str] = mapped_column(String(64), default="insurance_working_copy")
    side: Mapped[str] = mapped_column(String(16), nullable=False)  # front|back
    blob_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    content_type: Mapped[str] = mapped_column(String(100), default="image/png")
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purge_receipt: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CapabilityConfig(Base):
    __tablename__ = "capability_configs"
    __table_args__ = (UniqueConstraint("box_id", "key", name="uq_capability_box_key"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
