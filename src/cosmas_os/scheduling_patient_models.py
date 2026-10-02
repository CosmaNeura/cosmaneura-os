"""Durable personal patient correspondence. No credential or clinical-note writes."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base
from cosmas_os.vendor_models import WorkspaceScope, digest_check, json_check


def identifier():
    return str(uuid4())


class SchedulingPatientSetupRequest(WorkspaceScope, Base):
    __tablename__ = "scheduling_patient_setup_requests"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"],
            ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["external_identity_id", "box_id", "owner_id"],
            ["external_identities.id", "external_identities.box_id", "external_identities.principal_id"]),
        ForeignKeyConstraint(["account_id"], ["scheduling_accounts.id"]),
        ForeignKeyConstraint(["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]),
        ForeignKeyConstraint(["preview_request_id", "workspace_id", "box_id", "owner_id"],
            ["scheduling_patient_setup_requests.id", "scheduling_patient_setup_requests.workspace_id",
             "scheduling_patient_setup_requests.box_id", "scheduling_patient_setup_requests.owner_id"]),
        UniqueConstraint("id", "workspace_id", "box_id", "owner_id", name="uq_patient_setup_request_scope"),
        UniqueConstraint("workspace_id", "owner_id", "kind", "idempotency_key", name="uq_patient_setup_request_key"),
        UniqueConstraint("account_id", "workspace_id", "ordinal", name="uq_patient_setup_request_ordinal"),
        CheckConstraint("kind IN ('preview','confirm') AND ordinal BETWEEN 1 AND 500 AND expected_revision>=1", name="ck_patient_setup_request_bounds"),
        CheckConstraint("(kind='preview' AND preview_request_id IS NULL) OR (kind='confirm' AND preview_request_id IS NOT NULL)", name="ck_patient_setup_request_parent"),
        CheckConstraint("isfinite(connected_at) AND isfinite(created_at)", name="ck_patient_setup_request_time"),
        digest_check("request_sha256", "binding_sha256", "grant_sha256", "source_context_sha256"),
        json_check("command", 4096), json_check("selection", 2048), json_check("source_context", 4096),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=identifier)
    external_identity_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    request_nonce: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, default=identifier)
    preview_request_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    command: Mapped[dict] = mapped_column(JSONB, nullable=False)
    selection: Mapped[dict] = mapped_column(JSONB, nullable=False)
    binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    grant_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_context: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_context_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())


class SchedulingPatientSetupSnapshot(WorkspaceScope, Base):
    __tablename__ = "scheduling_patient_setup_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(["request_id", "workspace_id", "box_id", "owner_id"],
            ["scheduling_patient_setup_requests.id", "scheduling_patient_setup_requests.workspace_id",
             "scheduling_patient_setup_requests.box_id", "scheduling_patient_setup_requests.owner_id"]),
        UniqueConstraint("request_id", name="uq_patient_setup_snapshot_request"),
        UniqueConstraint("id", "workspace_id", "box_id", "owner_id", name="uq_patient_setup_snapshot_scope"),
        digest_check("payload_sha256", "source_sha256"), json_check("payload", 12288),
        CheckConstraint("isfinite(created_at)", name="ck_patient_setup_snapshot_time"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=identifier)
    request_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())


class SchedulingPatientMappingReview(WorkspaceScope, Base):
    __tablename__ = "scheduling_patient_mapping_reviews"
    __table_args__ = (
        ForeignKeyConstraint(["request_id", "workspace_id", "box_id", "owner_id"],
            ["scheduling_patient_setup_requests.id", "scheduling_patient_setup_requests.workspace_id",
             "scheduling_patient_setup_requests.box_id", "scheduling_patient_setup_requests.owner_id"]),
        ForeignKeyConstraint(["snapshot_id", "workspace_id", "box_id", "owner_id"],
            ["scheduling_patient_setup_snapshots.id", "scheduling_patient_setup_snapshots.workspace_id",
             "scheduling_patient_setup_snapshots.box_id", "scheduling_patient_setup_snapshots.owner_id"]),
        ForeignKeyConstraint(["mapping_id", "box_id", "patient_link_id"],
            ["scheduling_patient_accounts.id", "scheduling_patient_accounts.box_id", "scheduling_patient_accounts.patient_link_id"]),
        UniqueConstraint("request_id", name="uq_patient_mapping_review_request"),
        UniqueConstraint("snapshot_id", name="uq_patient_mapping_review_snapshot"),
        UniqueConstraint("mapping_id", name="uq_patient_mapping_review_mapping"),
        CheckConstraint("reviewed_same_patient AND reviewed_exact_identity", name="ck_patient_mapping_review_human"),
        digest_check("mapping_sha256"),
        CheckConstraint("isfinite(created_at)", name="ck_patient_mapping_review_time"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=identifier)
    request_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    mapping_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    reviewed_same_patient: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_exact_identity: Mapped[bool] = mapped_column(Boolean, nullable=False)
    mapping_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())
