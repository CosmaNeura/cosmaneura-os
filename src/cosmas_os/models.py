from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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
    __table_args__ = (
        UniqueConstraint("id", "box_id", name="uq_principal_id_box"),
    )

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


class ExternalIdentity(Base):
    """Reviewed binding from a verified IdP subject to one Box principal."""

    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("id", "box_id", "principal_id", name="uq_external_identity_scope"),
        ForeignKeyConstraint(
            ["principal_id", "box_id"],
            ["principals.id", "principals.box_id"],
            name="fk_external_identity_principal_box",
        ),
        UniqueConstraint("issuer", "subject", name="uq_external_identity_issuer_subject"),
        UniqueConstraint(
            "issuer",
            "organization_id",
            "principal_id",
            name="uq_external_identity_org_principal",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("box_contexts.id"), nullable=False
    )
    principal_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="clerk")
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reviewed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CoreCaptureAccount(Base):
    """Reviewed Core identity correspondence; not an encounter permission grant."""

    __tablename__ = "core_capture_accounts"
    __table_args__ = (
        Index("uq_core_capture_active_identity", "external_identity_id", unique=True,
              postgresql_where=text("revoked_at IS NULL")),
        CheckConstraint("core_actor_ref ~ '^authority_actor_[0-7][0-9a-hjkmnp-tv-z]{25}$'", name="ck_core_capture_actor"),
        CheckConstraint("core_tenant_ref ~ '^authority_tenant_[0-7][0-9a-hjkmnp-tv-z]{25}$'", name="ck_core_capture_tenant"),
        CheckConstraint("char_length(reviewed_by) > 0 AND char_length(evidence_ref) > 0", name="ck_core_capture_review"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    external_identity_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("external_identities.id"), nullable=False)
    core_actor_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    core_tenant_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SchedulingAccount(Base):
    """Reviewed private staff/practice correspondence; contains no credential."""

    __tablename__ = "scheduling_accounts"
    __table_args__ = (
        Index("uq_scheduling_active_identity", "external_identity_id", unique=True,
              postgresql_where=text("revoked_at IS NULL")),
        CheckConstraint("char_length(reviewed_by) > 0 AND char_length(evidence_ref) > 0", name="ck_scheduling_review"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    external_identity_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("external_identities.id"), nullable=False)
    practice_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    actor_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    practitioner_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    location_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    appointment_type_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SchedulingPatientAccount(Base):
    """Reviewed patient/practice correspondence; never inferred from a UUID/email."""

    __tablename__ = "scheduling_patient_accounts"
    __table_args__ = (
        ForeignKeyConstraint(["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]),
        UniqueConstraint("id", "box_id", "patient_link_id", name="uq_scheduling_patient_scope"),
        Index("uq_scheduling_patient_active_link", "box_id", "patient_link_id", "practice_id", unique=True,
              postgresql_where=text("revoked_at IS NULL")),
        Index("uq_scheduling_patient_active_remote", "box_id", "practice_id", "patient_id", unique=True,
              postgresql_where=text("revoked_at IS NULL")),
        CheckConstraint("char_length(reviewed_by) > 0 AND char_length(evidence_ref) > 0", name="ck_scheduling_patient_review"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    practice_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AppointmentWork(Base):
    """Private source binding for an existing F-8 appointment action revision."""

    __tablename__ = "appointment_work"
    __table_args__ = (
        ForeignKeyConstraint(["ticket_id", "box_id"], ["tickets.id", "tickets.box_id"]),
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"],
                             ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["action_revision_id", "ticket_id", "box_id", "payload_hash"],
                             ["action_revisions.id", "action_revisions.ticket_id", "action_revisions.box_id", "action_revisions.payload_hash"]),
        ForeignKeyConstraint(["patient_mapping_id", "box_id", "patient_link_id"],
                             ["scheduling_patient_accounts.id", "scheduling_patient_accounts.box_id", "scheduling_patient_accounts.patient_link_id"]),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_appointment_work_key"),
        CheckConstraint("char_length(idempotency_key) BETWEEN 1 AND 100", name="ck_appointment_work_key"),
    )
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("scheduling_accounts.id"), nullable=False)
    patient_mapping_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    action_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PatientLink(Base):
    __tablename__ = "patient_links"
    __table_args__ = (
        UniqueConstraint("id", "box_id", name="uq_patient_link_id_box"),
        UniqueConstraint("box_id", "source_pair_key", name="uq_patient_link_source_pair"),
        ForeignKeyConstraint(["source_owner_id", "box_id"], ["principals.id", "principals.box_id"], name="fk_patient_source_owner"),
        CheckConstraint("(source_owner_id IS NULL) = (source_account_id IS NULL)", name="ck_patient_source_scope"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"), nullable=False)
    source_pair_key: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    source_owner_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    source_account_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("core_capture_accounts.id"), nullable=True)
    confirmed_by_principal_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("principals.id"), nullable=True
    )
    attested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="unconfirmed")


class AppointmentObservation(Base):
    __tablename__ = "appointment_observations"
    __table_args__ = (
        UniqueConstraint("id", "box_id", "patient_link_id", name="uq_appointment_scope"),
        UniqueConstraint("source_owner_id", "source", "external_id", name="uq_private_source_appointment"),
        ForeignKeyConstraint(["source_owner_id", "box_id"], ["principals.id", "principals.box_id"], name="fk_appointment_source_owner"),
        CheckConstraint("(start_at IS NOT NULL) <> (source_local_start IS NOT NULL)", name="ck_appointment_source_time"),
        CheckConstraint("(source_owner_id IS NULL AND source_local_start IS NULL AND source_sha256 IS NULL) OR "
            "(source_owner_id IS NOT NULL AND source = 'cosmaneura_core' AND patient_link_id IS NOT NULL "
            "AND source_sha256 IS NOT NULL AND source_sha256 ~ '^[a-f0-9]{64}$')", name="ck_appointment_private_source"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_local_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    source_owner_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    patient_label: Mapped[str] = mapped_column(String(200), nullable=False)
    patient_link_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("patient_links.id"), nullable=True
    )
    coverage_status: Mapped[str] = mapped_column(String(32), default=CoverageStatus.MISSING.value)


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (UniqueConstraint("id", "box_id", name="uq_ticket_scope"),)

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
    __table_args__ = (UniqueConstraint("id", "ticket_id", "box_id", "payload_hash", name="uq_action_binding"),)

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
        UniqueConstraint("id", "ticket_id", "box_id", name="uq_operation_scope"),
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


class AppointmentExecution(Base):
    """A fenced attempt for the existing F-8 operation, not another queue."""

    __tablename__ = "appointment_executions"
    __table_args__ = (
        ForeignKeyConstraint(["operation_id", "ticket_id", "box_id"], ["operations.id", "operations.ticket_id", "operations.box_id"]),
        ForeignKeyConstraint(["ticket_id"], ["appointment_work.ticket_id"]),
        CheckConstraint("generation >= 1", name="ck_appointment_execution_generation"),
        CheckConstraint("mode IN ('submit', 'reconcile')", name="ck_appointment_execution_mode"),
        CheckConstraint("(claim_token IS NULL) = (lease_until IS NULL)", name="ck_appointment_execution_claim"),
    )
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    generation: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(16))
    claim_token: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AppointmentReceipt(Base):
    """Immutable verified observations of one appointment operation's result."""

    __tablename__ = "appointment_receipts"
    __table_args__ = (
        ForeignKeyConstraint(["operation_id", "ticket_id", "box_id"], ["operations.id", "operations.ticket_id", "operations.box_id"]),
        ForeignKeyConstraint(["ticket_id"], ["appointment_work.ticket_id"]),
        UniqueConstraint("operation_id", "response_hash", name="uq_appointment_receipt_response"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$' AND response_hash ~ '^[0-9a-f]{64}$'", name="ck_appointment_receipt_hashes"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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


class EncounterWorkspace(Base):
    __tablename__ = "encounter_workspaces"
    __table_args__ = (
        ForeignKeyConstraint(["owner_id", "box_id"], ["principals.id", "principals.box_id"]),
        ForeignKeyConstraint(["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]),
        ForeignKeyConstraint(["appointment_id", "box_id", "patient_link_id"],
                             ["appointment_observations.id", "appointment_observations.box_id", "appointment_observations.patient_link_id"]),
        UniqueConstraint("id", "box_id", name="uq_workspace_id_box"),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_workspace_owner_scope"),
        UniqueConstraint("owner_id", "appointment_id", name="uq_workspace_owner_encounter"),
        UniqueConstraint("owner_id", "create_key", name="uq_workspace_create_key"),
        CheckConstraint("revision >= 1", name="ck_workspace_revision"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    appointment_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    create_key: Mapped[str] = mapped_column(String(100))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceEntry(Base):
    __tablename__ = "workspace_entries"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "box_id", "actor_id"],
                             ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["actor_id", "box_id"], ["principals.id", "principals.box_id"]),
        UniqueConstraint("workspace_id", "revision", name="uq_workspace_entry_revision"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_workspace_entry_key"),
        UniqueConstraint("id", "workspace_id", "box_id", name="uq_workspace_entry_scope"),
        CheckConstraint("revision >= 1", name="ck_workspace_entry_revision"),
        CheckConstraint("kind IN ('synthetic_source', 'scratchpad', 'conversation', 'evidence', 'work_link', 'handoff_result', 'google_message')", name="ck_workspace_entry_kind"),
        CheckConstraint("char_length(content) <= 20000", name="ck_workspace_entry_content"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    actor_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    source_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    ticket_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("tickets.id"), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProviderBot(Base):
    """Stable, private ownership of an existing agent principal; no implicit grants."""

    __tablename__ = "provider_bots"
    __table_args__ = (
        ForeignKeyConstraint(["owner_id", "box_id"], ["principals.id", "principals.box_id"]),
        ForeignKeyConstraint(["agent_id", "box_id"], ["principals.id", "principals.box_id"]),
        Index("uq_provider_bot_default_role", "owner_id", "role", unique=True,
              postgresql_where=text("instance_id IS NULL")),
        UniqueConstraint("owner_id", "instance_id", name="uq_provider_bot_instance"),
        UniqueConstraint("agent_id", "box_id", "owner_id", name="uq_provider_bot_scope"),
        CheckConstraint("role IN ('scribe', 'visit_prep', 'follow_up', 'chief', 'custom', 'research')", name="ck_provider_bot_role"),
        CheckConstraint("role <> 'research' OR instance_id IS NOT NULL", name="ck_provider_bot_research_identity"),
        CheckConstraint("role <> 'custom' OR instance_id IS NOT NULL", name="ck_provider_bot_custom_identity"),
        CheckConstraint("instance_id IS NULL OR role <> 'chief'", name="ck_provider_bot_additional_template"),
    )

    agent_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    role: Mapped[str] = mapped_column(String(32))
    instance_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)


class ProviderTeamRevision(Base):
    __tablename__ = "provider_team_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["owner_id", "box_id"], ["principals.id", "principals.box_id"]),
        UniqueConstraint("owner_id", "revision", name="uq_provider_team_revision"),
        UniqueConstraint("owner_id", "idempotency_key", name="uq_provider_team_key"),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_provider_team_scope"),
        CheckConstraint("revision >= 1", name="ck_provider_team_revision"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    revision: Mapped[int] = mapped_column(Integer)
    template_version: Mapped[str] = mapped_column(String(64))
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RoutineRevision(Base):
    """Versioned owner configuration; no work queue or external action grants."""

    __tablename__ = "routine_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["agent_id", "box_id", "owner_id"],
                             ["provider_bots.agent_id", "provider_bots.box_id", "provider_bots.owner_id"]),
        ForeignKeyConstraint(["team_revision_id", "box_id", "owner_id"],
                             ["provider_team_revisions.id", "provider_team_revisions.box_id", "provider_team_revisions.owner_id"]),
        UniqueConstraint("agent_id", "revision", name="uq_routine_revision"),
        UniqueConstraint("agent_id", "idempotency_key", name="uq_routine_key"),
        UniqueConstraint("id", "agent_id", "box_id", "owner_id", name="uq_routine_scope"),
        CheckConstraint("revision BETWEEN 1 AND 100", name="ck_routine_revision"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="ck_routine_request_hash"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    team_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    revision: Mapped[int] = mapped_column(Integer)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class RoutineRun(Base):
    """Immutable local report committed once, atomically with its source reads."""

    __tablename__ = "routine_runs"
    __table_args__ = (
        ForeignKeyConstraint(["routine_revision_id", "agent_id", "box_id", "owner_id"],
                             ["routine_revisions.id", "routine_revisions.agent_id", "routine_revisions.box_id", "routine_revisions.owner_id"]),
        UniqueConstraint("agent_id", "local_date", name="uq_routine_occurrence"),
        CheckConstraint("completed_at >= scheduled_at", name="ck_routine_completion"),
        CheckConstraint("snapshot_hash ~ '^[0-9a-f]{64}$'", name="ck_routine_snapshot_hash"),
        Index("ix_routine_recent_runs", "agent_id", "completed_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    routine_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    local_date: Mapped[date] = mapped_column(Date)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    snapshot_hash: Mapped[str] = mapped_column(String(64))


class WorkspaceReply(Base):
    """Immutable assistant output bound to one human turn and its private context."""

    __tablename__ = "workspace_replies"
    __table_args__ = (
        ForeignKeyConstraint(["entry_id", "workspace_id", "box_id"],
                             ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"]),
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"],
                             ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["agent_id", "box_id", "owner_id"],
                             ["provider_bots.agent_id", "provider_bots.box_id", "provider_bots.owner_id"]),
        ForeignKeyConstraint(["team_revision_id", "box_id", "owner_id"],
                             ["provider_team_revisions.id", "provider_team_revisions.box_id", "provider_team_revisions.owner_id"]),
        CheckConstraint("char_length(content) <= 20000", name="ck_workspace_reply_content"),
    )

    entry_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    agent_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    team_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    agent_name: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(32))
    backend: Mapped[str] = mapped_column(String(64))
    context_revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceNote(Base):
    """Immutable private note version, with source and human-edit lineage."""

    __tablename__ = "workspace_notes"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"], ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["parent_id", "workspace_id", "box_id"], ["workspace_notes.id", "workspace_notes.workspace_id", "workspace_notes.box_id"]),
        ForeignKeyConstraint(["source_reply_id", "workspace_id", "box_id"], ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"]),
        UniqueConstraint("id", "workspace_id", "box_id", name="uq_workspace_note_scope"),
        UniqueConstraint("id", "workspace_id", "box_id", "owner_id", "content_hash", "source_fingerprint", name="uq_workspace_note_review_binding"),
        UniqueConstraint("workspace_id", "version", name="uq_workspace_note_version"),
        UniqueConstraint("workspace_id", "workspace_revision", name="uq_workspace_note_revision"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_workspace_note_key"),
        CheckConstraint("version BETWEEN 1 AND 50 AND source_revision >= 1 AND workspace_revision > source_revision", name="ck_workspace_note_revisions"),
        CheckConstraint("char_length(content) BETWEEN 1 AND 270336", name="ck_workspace_note_content"),
        CheckConstraint("(version = 1 AND parent_id IS NULL) OR (version > 1 AND parent_id IS NOT NULL)", name="ck_workspace_note_parent"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    version: Mapped[int] = mapped_column(Integer)
    workspace_revision: Mapped[int] = mapped_column(Integer)
    parent_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    source_reply_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    source_revision: Mapped[int] = mapped_column(Integer)
    source_fingerprint: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceCoreNoteSource(Base):
    """Immutable source/version reference for a private copy of a saved Core note."""

    __tablename__ = "workspace_core_note_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["note_id", "workspace_id", "box_id", "owner_id", "content_hash", "source_fingerprint"],
            ["workspace_notes.id", "workspace_notes.workspace_id", "workspace_notes.box_id",
             "workspace_notes.owner_id", "workspace_notes.content_hash", "workspace_notes.source_fingerprint"],
        ),
        CheckConstraint("source_sha256 ~ '^[a-f0-9]{64}$' AND note_sha256 ~ '^[a-f0-9]{64}$'", name="ck_workspace_core_note_digests"),
        CheckConstraint("capture_gap_review IS NULL OR COALESCE((jsonb_typeof(capture_gap_review) = 'object' AND capture_gap_review->>'recovery_sha256' ~ '^[a-f0-9]{64}$' AND capture_gap_review->'review_required' = 'true'::jsonb AND jsonb_typeof(capture_gap_review->'observations') = 'array' AND jsonb_array_length(capture_gap_review->'observations') BETWEEN 1 AND 1000 AND octet_length(capture_gap_review::text) <= 786432), false)", name="ck_workspace_core_gap_review"),
    )
    note_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    content_hash: Mapped[str] = mapped_column(String(64))
    source_fingerprint: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    scribe_source_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    source_sha256: Mapped[str] = mapped_column(String(64))
    schema_ref: Mapped[str] = mapped_column(String(160))
    transcript_ref: Mapped[str] = mapped_column(String(160))
    note_ref: Mapped[str] = mapped_column(String(160))
    note_sha256: Mapped[str] = mapped_column(String(64))
    note_type: Mapped[str] = mapped_column(String(160))
    capture_gap_review: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    notebook_source: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    reviewed_source: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceNoteReview(Base):
    """Exact human review receipt; grants no signature or external authority."""

    __tablename__ = "workspace_note_reviews"
    __table_args__ = (
        ForeignKeyConstraint(["note_id", "workspace_id", "box_id", "owner_id", "content_hash", "source_fingerprint"], ["workspace_notes.id", "workspace_notes.workspace_id", "workspace_notes.box_id", "workspace_notes.owner_id", "workspace_notes.content_hash", "workspace_notes.source_fingerprint"]),
        UniqueConstraint("note_id", name="uq_workspace_note_review"),
        UniqueConstraint("workspace_id", "workspace_revision", name="uq_workspace_note_review_revision"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_workspace_note_review_key"),
        CheckConstraint("workspace_revision >= 2", name="ck_workspace_note_review_revision"),
        CheckConstraint("capture_gap_review_sha256 IS NULL OR capture_gap_review_sha256 ~ '^[a-f0-9]{64}$'", name="ck_workspace_note_gap_acknowledgment"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    note_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    workspace_revision: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    source_fingerprint: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    capture_gap_review_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FollowUpSource(Base):
    """Private provenance for an existing F-8 ticket; never a second work queue."""

    __tablename__ = "follow_up_sources"
    __table_args__ = (
        ForeignKeyConstraint(["inbox_item_id", "box_id", "owner_id"], ["inbox_items.id", "inbox_items.box_id", "inbox_items.owner_id"], name="fk_incoming_item"),
        ForeignKeyConstraint(["inbox_source_id", "inbox_item_id"], ["inbox_sources.id", "inbox_sources.item_id"], name="fk_incoming_source"),
        ForeignKeyConstraint(["inbox_review_receipt_id"], ["inbox_events.id"], name="fk_incoming_review"),
        ForeignKeyConstraint(["ticket_id", "box_id"], ["tickets.id", "tickets.box_id"]),
        ForeignKeyConstraint(["action_revision_id", "ticket_id", "box_id", "payload_hash"], ["action_revisions.id", "action_revisions.ticket_id", "action_revisions.box_id", "action_revisions.payload_hash"]),
        ForeignKeyConstraint(["note_id", "workspace_id", "box_id", "owner_id", "content_hash", "source_fingerprint"], ["workspace_notes.id", "workspace_notes.workspace_id", "workspace_notes.box_id", "workspace_notes.owner_id", "workspace_notes.content_hash", "workspace_notes.source_fingerprint"]),
        ForeignKeyConstraint(["note_id"], ["workspace_note_reviews.note_id"]),
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"], ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        CheckConstraint("COALESCE((((source_kind IN ('reviewed_note','vendor_reviewed_note') AND note_id IS NOT NULL AND content_hash IS NOT NULL AND source_fingerprint IS NOT NULL AND prep_snapshot_sha256 IS NULL AND prep_receipt IS NULL) OR (source_kind = 'core_prep' AND note_id IS NULL AND content_hash IS NULL AND source_fingerprint IS NULL AND prep_snapshot_sha256 ~ '^[a-f0-9]{64}$' AND jsonb_typeof(prep_receipt) = 'object' AND prep_receipt->>'snapshot_sha256' = prep_snapshot_sha256 AND jsonb_typeof(prep_receipt->'sources') = 'array' AND jsonb_array_length(prep_receipt->'sources') <= 6 AND octet_length(prep_receipt::text) <= 262144)) AND inbox_item_id IS NULL AND inbox_source_id IS NULL AND inbox_review_receipt_id IS NULL AND inbox_source_sha256 IS NULL AND inbox_review_sha256 IS NULL) OR (source_kind = 'incoming_message' AND note_id IS NULL AND content_hash IS NULL AND source_fingerprint IS NULL AND prep_snapshot_sha256 IS NULL AND prep_receipt IS NULL AND inbox_item_id IS NOT NULL AND inbox_source_id IS NOT NULL AND inbox_review_receipt_id IS NOT NULL AND inbox_source_sha256 ~ '^[a-f0-9]{64}$' AND inbox_review_sha256 ~ '^[a-f0-9]{64}$'), false)", name="ck_follow_up_source_kind"),
        UniqueConstraint("ticket_id", "box_id", name="uq_follow_up_scope"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_follow_up_key"),
        Index("uq_follow_up_revision", "workspace_id", "workspace_revision", unique=True,
              postgresql_where=text("source_kind NOT IN ('vendor_reviewed_note','incoming_message')")),
    )
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    source_kind: Mapped[str] = mapped_column(String(32), default="reviewed_note", server_default="reviewed_note")
    note_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prep_snapshot_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prep_receipt: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    inbox_item_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    inbox_source_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    inbox_review_receipt_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    inbox_source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    inbox_review_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), unique=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    workspace_revision: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FollowUpReceipt(Base):
    """Immutable local delivery or human outcome evidence for an F-8 operation."""

    __tablename__ = "follow_up_receipts"
    __table_args__ = (
        ForeignKeyConstraint(["ticket_id", "box_id"], ["follow_up_sources.ticket_id", "follow_up_sources.box_id"]),
        ForeignKeyConstraint(["operation_id", "ticket_id", "box_id"], ["operations.id", "operations.ticket_id", "operations.box_id"]),
        ForeignKeyConstraint(["actor_id", "box_id"], ["principals.id", "principals.box_id"]),
        UniqueConstraint("ticket_id", "kind", name="uq_follow_up_receipt_kind"),
        CheckConstraint("kind IN ('local_delivery', 'human_completion', 'internal_publication', 'ready_for_review', 'provider_verification', 'incoming_verification')", name="ck_follow_up_receipt_kind"),
        CheckConstraint("char_length(content) BETWEEN 1 AND 2000", name="ck_follow_up_receipt_content"),
        CheckConstraint("COALESCE((kind <> 'provider_verification' AND source_snapshot_sha256 IS NULL AND source_proof IS NULL) OR (kind = 'provider_verification' AND source_snapshot_sha256 ~ '^[a-f0-9]{64}$' AND jsonb_typeof(source_proof) = 'object' AND source_proof->>'snapshot_sha256' = source_snapshot_sha256 AND jsonb_typeof(source_proof->'sources') = 'array' AND jsonb_array_length(source_proof->'sources') BETWEEN 1 AND 6 AND octet_length(source_proof::text) <= 262144), false)", name="ck_follow_up_receipt_proof"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    actor_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    kind: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    source_snapshot_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_proof: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkHandoff(Base):
    """Immutable responsibility offers/responses on existing F-8 work."""

    __tablename__ = "work_handoffs"
    __table_args__ = (
        ForeignKeyConstraint(["ticket_id", "box_id"], ["follow_up_sources.ticket_id", "follow_up_sources.box_id"]),
        ForeignKeyConstraint(["action_revision_id", "ticket_id", "box_id", "payload_hash"],
            ["action_revisions.id", "action_revisions.ticket_id", "action_revisions.box_id", "action_revisions.payload_hash"]),
        ForeignKeyConstraint(["actor_id", "box_id"], ["principals.id", "principals.box_id"]),
        ForeignKeyConstraint(["from_id", "box_id"], ["principals.id", "principals.box_id"]),
        ForeignKeyConstraint(["to_id", "box_id"], ["principals.id", "principals.box_id"]),
        UniqueConstraint("id", "ticket_id", "box_id", name="uq_work_handoff_scope"),
        ForeignKeyConstraint(["offer_id", "ticket_id", "box_id"],
            ["work_handoffs.id", "work_handoffs.ticket_id", "work_handoffs.box_id"]),
        UniqueConstraint("ticket_id", "sequence", name="uq_work_handoff_sequence"),
        UniqueConstraint("ticket_id", "actor_id", "idempotency_key", name="uq_work_handoff_key"),
        CheckConstraint("kind IN ('offer', 'accept', 'decline', 'recall', 'reclaim')", name="ck_work_handoff_kind"),
        CheckConstraint("sequence BETWEEN 1 AND 201 AND expected_version > 0", name="ck_work_handoff_version"),
        CheckConstraint("from_id <> to_id", name="ck_work_handoff_people"),
        CheckConstraint("(kind IN ('accept', 'decline', 'recall')) = (offer_id IS NOT NULL)", name="ck_work_handoff_offer"),
        CheckConstraint("(kind IN ('offer', 'recall') AND actor_id = from_id) OR "
            "(kind IN ('accept', 'decline', 'reclaim') AND actor_id = to_id)", name="ck_work_handoff_actor"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    action_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    payload_hash: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(Integer)
    expected_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    from_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    to_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    offer_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    vendor_publication_receipt_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceHandoff(Base):
    """Immutable private draft brief; never an external action or approval."""

    __tablename__ = "workspace_handoffs"
    __table_args__ = (
        ForeignKeyConstraint(["origin_entry_id", "workspace_id", "box_id"], ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"]),
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"], ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["issuer_agent_id", "box_id", "owner_id"], ["provider_bots.agent_id", "provider_bots.box_id", "provider_bots.owner_id"]),
        ForeignKeyConstraint(["recipient_agent_id", "box_id", "owner_id"], ["provider_bots.agent_id", "provider_bots.box_id", "provider_bots.owner_id"]),
        ForeignKeyConstraint(["team_revision_id", "box_id", "owner_id"], ["provider_team_revisions.id", "provider_team_revisions.box_id", "provider_team_revisions.owner_id"]),
        UniqueConstraint("origin_entry_id", "recipient_agent_id", name="uq_handoff_origin_recipient"),
        UniqueConstraint("id", "workspace_id", "box_id", "owner_id", name="uq_handoff_scope"),
        CheckConstraint("recipient_role IN ('scribe', 'visit_prep', 'follow_up', 'custom', 'research')", name="ck_handoff_role"),
        CheckConstraint("char_length(brief) BETWEEN 1 AND 4000 AND context_revision >= 1", name="ck_handoff_brief"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    origin_entry_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    issuer_agent_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    recipient_agent_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    recipient_role: Mapped[str] = mapped_column(String(32))
    recipient_name: Mapped[str] = mapped_column(String(40))
    team_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    context_revision: Mapped[int] = mapped_column(Integer)
    brief: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceHandoffAttempt(Base):
    """Bounded lifecycle: queued → running → immutable terminal receipt."""

    __tablename__ = "workspace_handoff_attempts"
    __table_args__ = (
        ForeignKeyConstraint(["handoff_id", "workspace_id", "box_id", "owner_id"], ["workspace_handoffs.id", "workspace_handoffs.workspace_id", "workspace_handoffs.box_id", "workspace_handoffs.owner_id"]),
        ForeignKeyConstraint(["result_entry_id", "workspace_id", "box_id"], ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"]),
        UniqueConstraint("handoff_id", "number", name="uq_handoff_attempt_number"),
        UniqueConstraint("handoff_id", "idempotency_key", name="uq_handoff_attempt_key"),
        UniqueConstraint("result_entry_id", name="uq_handoff_result"),
        UniqueConstraint("id", "workspace_id", "box_id", "owner_id", name="uq_handoff_attempt_scope"),
        CheckConstraint("number BETWEEN 1 AND 3", name="ck_handoff_attempt_number"),
        CheckConstraint("status IN ('queued', 'running', 'completed', 'failed', 'interrupted')", name="ck_handoff_attempt_status"),
        CheckConstraint("(status = 'completed') = (result_entry_id IS NOT NULL)", name="ck_handoff_attempt_result"),
        CheckConstraint("(status IN ('failed', 'interrupted')) = (error_code IS NOT NULL)", name="ck_handoff_attempt_error"),
        CheckConstraint("(status <> 'queued' OR started_at IS NULL) AND (status NOT IN ('running', 'completed') OR started_at IS NOT NULL) AND (status IN ('queued', 'running')) = (completed_at IS NULL)", name="ck_handoff_attempt_times"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    handoff_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    number: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    result_entry_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceHandoffReview(Base):
    """Immutable human feedback on one exact private draft and its saved inputs."""

    __tablename__ = "workspace_handoff_reviews"
    __table_args__ = (
        ForeignKeyConstraint(["handoff_id", "workspace_id", "box_id", "owner_id"], ["workspace_handoffs.id", "workspace_handoffs.workspace_id", "workspace_handoffs.box_id", "workspace_handoffs.owner_id"]),
        ForeignKeyConstraint(["attempt_id", "workspace_id", "box_id", "owner_id"], ["workspace_handoff_attempts.id", "workspace_handoff_attempts.workspace_id", "workspace_handoff_attempts.box_id", "workspace_handoff_attempts.owner_id"]),
        ForeignKeyConstraint(["result_entry_id", "workspace_id", "box_id"], ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"]),
        ForeignKeyConstraint(["agent_id", "box_id", "owner_id"], ["provider_bots.agent_id", "provider_bots.box_id", "provider_bots.owner_id"]),
        UniqueConstraint("attempt_id", name="uq_handoff_review_attempt"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_handoff_review_key"),
        UniqueConstraint("workspace_id", "workspace_revision", name="uq_handoff_review_revision"),
        CheckConstraint("decision IN ('accepted','changes_requested')", name="ck_handoff_review_decision"),
        CheckConstraint("char_length(feedback) <= 2000 AND (decision <> 'changes_requested' OR feedback !~ '^[[:space:]]*$')", name="ck_handoff_review_feedback"),
        CheckConstraint("result_sha256 ~ '^[0-9a-f]{64}$' AND source_sha256 ~ '^[0-9a-f]{64}$' AND request_hash ~ '^[0-9a-f]{64}$'", name="ck_handoff_review_hashes"),
        CheckConstraint("expected_revision >= 1 AND workspace_revision = expected_revision + 1", name="ck_handoff_review_revision"),
        CheckConstraint("jsonb_typeof(source_versions) = 'array' AND jsonb_array_length(source_versions) <= 12 AND octet_length(source_versions::text) <= 32768", name="ck_handoff_review_sources"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    handoff_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    attempt_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    result_entry_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    agent_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    result_sha256: Mapped[str] = mapped_column(String(64))
    source_sha256: Mapped[str] = mapped_column(String(64))
    source_versions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    expected_revision: Mapped[int] = mapped_column(Integer)
    workspace_revision: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(24))
    feedback: Mapped[str] = mapped_column(Text, default="")
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceHandoffRevision(Base):
    """One explicit human revision request linked to a fresh private assignment."""

    __tablename__ = "workspace_handoff_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["parent_handoff_id", "workspace_id", "box_id", "owner_id"], ["workspace_handoffs.id", "workspace_handoffs.workspace_id", "workspace_handoffs.box_id", "workspace_handoffs.owner_id"]),
        ForeignKeyConstraint(["revision_handoff_id", "workspace_id", "box_id", "owner_id"], ["workspace_handoffs.id", "workspace_handoffs.workspace_id", "workspace_handoffs.box_id", "workspace_handoffs.owner_id"]),
        ForeignKeyConstraint(["origin_entry_id", "workspace_id", "box_id"], ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"]),
        ForeignKeyConstraint(["review_id"], ["workspace_handoff_reviews.id"]),
        UniqueConstraint("review_id", name="uq_handoff_revision_review"),
        UniqueConstraint("revision_handoff_id", name="uq_handoff_revision_assignment"),
        UniqueConstraint("origin_entry_id", name="uq_handoff_revision_origin"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_handoff_revision_key"),
        CheckConstraint("parent_handoff_id <> revision_handoff_id", name="ck_handoff_revision_identity"),
        CheckConstraint("expected_revision >= 1 AND workspace_revision = expected_revision + 1", name="ck_handoff_revision_revision"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="ck_handoff_revision_hash"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    parent_handoff_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    review_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    revision_handoff_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    origin_entry_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    expected_revision: Mapped[int] = mapped_column(Integer)
    workspace_revision: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelWorkAdmission(Base):
    """One immutable private model input with a single durable dispatch fence."""

    __tablename__ = "model_work_admissions"
    __table_args__ = (
        ForeignKeyConstraint(["owner_id", "box_id"], ["principals.id", "principals.box_id"]),
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"], ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["agent_id", "box_id", "owner_id"], ["provider_bots.agent_id", "provider_bots.box_id", "provider_bots.owner_id"]),
        ForeignKeyConstraint(["team_revision_id", "box_id", "owner_id"], ["provider_team_revisions.id", "provider_team_revisions.box_id", "provider_team_revisions.owner_id"]),
        ForeignKeyConstraint(["external_identity_id", "box_id", "owner_id"], ["external_identities.id", "external_identities.box_id", "external_identities.principal_id"]),
        ForeignKeyConstraint(["handoff_attempt_id", "workspace_id", "box_id", "owner_id"], ["workspace_handoff_attempts.id", "workspace_handoff_attempts.workspace_id", "workspace_handoff_attempts.box_id", "workspace_handoff_attempts.owner_id"]),
        ForeignKeyConstraint(["request_entry_id", "workspace_id", "box_id"], ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"]),
        ForeignKeyConstraint(["result_entry_id", "workspace_id", "box_id"], ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"]),
        UniqueConstraint("id", "workspace_id", "box_id", "owner_id", name="uq_model_admission_scope"),
        UniqueConstraint("workspace_id", "request_key", name="uq_model_admission_request"),
        UniqueConstraint("request_entry_id", name="uq_model_admission_entry"),
        UniqueConstraint("handoff_attempt_id", name="uq_model_admission_handoff"),
        CheckConstraint("kind IN ('conversation','private_handoff') AND (kind='conversation') = (handoff_attempt_id IS NULL)", name="ck_model_admission_kind"),
        CheckConstraint("state IN ('reserved','running','completed','failed','unknown','abandoned')", name="ck_model_admission_state"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$' AND envelope_sha256 ~ '^[0-9a-f]{64}$' AND source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_model_admission_hashes"),
        CheckConstraint("expected_revision >= 1 AND context_revision >= 1", name="ck_model_admission_revisions"),
        CheckConstraint("jsonb_typeof(request_body)='object' AND octet_length(request_body::text) <= 131072 AND jsonb_typeof(prepared_envelope)='object' AND octet_length(prepared_envelope::text) <= 4194304", name="ck_model_admission_json"),
        CheckConstraint("reservation_expires_at > admitted_at AND (state IN ('reserved','running')) = (finalized_at IS NULL)", name="ck_model_admission_times"),
        CheckConstraint("(dispatch_id IS NULL) = (started_at IS NULL) AND (dispatch_id IS NULL) = (lease_ends_at IS NULL) AND (state NOT IN ('running','completed','unknown') OR dispatch_id IS NOT NULL) AND (state NOT IN ('reserved','abandoned') OR dispatch_id IS NULL)", name="ck_model_admission_dispatch"),
        CheckConstraint("result_entry_id IS NULL OR result_entry_id=request_entry_id", name="ck_model_admission_result_identity"),
        CheckConstraint("state <> 'completed' OR result_entry_id IS NOT NULL", name="ck_model_admission_completed"),
        Index("ix_model_owner_admitted", "box_id", "owner_id", "admitted_at"),
        Index("ix_model_owner_state", "box_id", "owner_id", "state"),
        Index("uq_model_active_conversation", "workspace_id", unique=True,
              postgresql_where=text("kind='conversation' AND state IN ('reserved','running')")),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    agent_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    team_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    external_identity_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))
    request_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    handoff_attempt_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    expected_revision: Mapped[int] = mapped_column(Integer)
    context_revision: Mapped[int] = mapped_column(Integer)
    request_body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    prepared_envelope: Mapped[dict[str, Any]] = mapped_column(JSONB)
    envelope_contract: Mapped[str] = mapped_column(String(64))
    envelope_sha256: Mapped[str] = mapped_column(String(64))
    source_sha256: Mapped[str] = mapped_column(String(64))
    admitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reservation_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16), default="reserved")
    dispatch_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_entry_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    result_entry_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ModelUsageObservation(Base):
    """Immutable bounded terminal/late-usage evidence, without generated text."""

    __tablename__ = "model_usage_observations"
    __table_args__ = (
        ForeignKeyConstraint(["admission_id", "workspace_id", "box_id", "owner_id"], ["model_work_admissions.id", "model_work_admissions.workspace_id", "model_work_admissions.box_id", "model_work_admissions.owner_id"]),
        UniqueConstraint("admission_id", "kind", name="uq_model_usage_kind"),
        CheckConstraint("kind IN ('terminal','late_usage')", name="ck_model_usage_kind"),
        CheckConstraint("dispatch IN ('not_dispatched','started_unconfirmed','response_received')", name="ck_model_usage_dispatch"),
        CheckConstraint("outcome IN ('valid_output','invalid_output','connector_failure','authority_withheld','source_withheld','interrupted','reservation_expired')", name="ck_model_usage_outcome"),
        CheckConstraint("usage IN ('unknown','verified') AND ((usage='unknown' AND input_tokens IS NULL AND output_tokens IS NULL) OR (usage='verified' AND input_tokens BETWEEN 0 AND 999999 AND output_tokens BETWEEN 0 AND 999999))", name="ck_model_usage_tokens"),
        CheckConstraint("receipt_hash ~ '^[0-9a-f]{64}$' AND envelope_sha256 ~ '^[0-9a-f]{64}$' AND (response_sha256 IS NULL OR response_sha256 ~ '^[0-9a-f]{64}$')", name="ck_model_usage_hashes"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    admission_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    kind: Mapped[str] = mapped_column(String(16))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dispatch: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(32))
    usage: Mapped[str] = mapped_column(String(16))
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str] = mapped_column(String(64))
    envelope_sha256: Mapped[str] = mapped_column(String(64))
    response_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64))
