"""Private evidence for existing F8 portal actions, never a second work queue."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base
from cosmas_os.vendor_models import NoteScope, WorkspaceScope, digest_check, json_check, note_fk


def uid():
    return str(uuid4())


class PortalWork(NoteScope, Base):
    __tablename__ = "portal_work"
    __table_args__ = (
        note_fk(),
        ForeignKeyConstraint(
            ["workspace_id", "box_id", "owner_id"],
            [
                "encounter_workspaces.id",
                "encounter_workspaces.box_id",
                "encounter_workspaces.owner_id",
            ],
        ),
        ForeignKeyConstraint(
            ["action_revision_id", "ticket_id", "box_id", "payload_hash"],
            [
                "action_revisions.id",
                "action_revisions.ticket_id",
                "action_revisions.box_id",
                "action_revisions.payload_hash",
            ],
        ),
        ForeignKeyConstraint(
            ["setup_revision_id", "setup_connection_id", "box_id", "owner_id"],
            [
                "portal_setup_revisions.id",
                "portal_setup_revisions.connection_id",
                "portal_setup_revisions.box_id",
                "portal_setup_revisions.owner_id",
            ],
        ),
        ForeignKeyConstraint(
            ["artifact_id", "workspace_id", "box_id", "owner_id"],
            [
                "vendor_artifacts.artifact_id",
                "vendor_artifacts.workspace_id",
                "vendor_artifacts.box_id",
                "vendor_artifacts.owner_id",
            ],
        ),
        UniqueConstraint("operation_id", name="uq_portal_work_operation"),
        UniqueConstraint(
            "operation_id", "workspace_id", "box_id", "owner_id", name="uq_portal_work_op_scope"
        ),
        UniqueConstraint(
            "ticket_id", "workspace_id", "box_id", "owner_id", name="uq_portal_work_scope"
        ),
        UniqueConstraint("action_revision_id", name="uq_portal_work_revision"),
        ForeignKeyConstraint(
            ["uploaded_operation_id", "workspace_id", "box_id", "owner_id"],
            [
                "portal_work.operation_id",
                "portal_work.workspace_id",
                "portal_work.box_id",
                "portal_work.owner_id",
            ],
        ),
        CheckConstraint("action IN ('document.upload','referral.submit') AND setup_version>0"),
        CheckConstraint(
            "(action='document.upload' AND uploaded_operation_id IS NULL) OR (action='referral.submit' AND uploaded_operation_id IS NOT NULL)"
        ),
        digest_check("payload_hash", "command_sha256", "review_sha256", "request_sha256"),
        json_check("private_command", 32768),
        json_check("proposal", 16384),
        json_check("review", 16384),
    )
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    action_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    setup_connection_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    setup_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    setup_version: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    uploaded_operation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    private_command: Mapped[dict] = mapped_column(JSONB, nullable=False)
    command_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    review: Mapped[dict] = mapped_column(JSONB, nullable=False)
    review_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def work_fk():
    return ForeignKeyConstraint(
        ["ticket_id", "workspace_id", "box_id", "owner_id"],
        [
            "portal_work.ticket_id",
            "portal_work.workspace_id",
            "portal_work.box_id",
            "portal_work.owner_id",
        ],
    )


class PortalWorkReceipt(WorkspaceScope, Base):
    __tablename__ = "portal_work_receipts"
    __table_args__ = (
        work_fk(),
        UniqueConstraint(
            "workspace_id", "owner_id", "idempotency_key", name="uq_portal_work_receipt_key"
        ),
        UniqueConstraint("ticket_id", "version", name="uq_portal_work_receipt_version"),
        CheckConstraint(
            "command_kind IN ('propose','decide','withdraw','submit','status','result','verify') AND version>0"
        ),
        digest_check("request_sha256", "receipt_sha256"),
        json_check("request", 16384),
        json_check("response", 8192),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=uid)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    command_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PortalWorkClaim(WorkspaceScope, Base):
    __tablename__ = "portal_work_claims"
    __table_args__ = (
        work_fk(),
        ForeignKeyConstraint(
            ["operation_id", "ticket_id", "box_id"],
            ["operations.id", "operations.ticket_id", "operations.box_id"],
        ),
        ForeignKeyConstraint(["receipt_id"], ["portal_work_receipts.id"]),
        Index(
            "uq_portal_work_once_submit",
            "operation_id",
            unique=True,
            postgresql_where=text("mode='submit'"),
        ),
        CheckConstraint(
            "mode IN ('submit','status') AND dispatch IN ('claimed','invoking','settled') AND deadline>claimed_at"
        ),
        CheckConstraint("(dispatch='settled')=(completed_at IS NOT NULL)"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=uid)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    receipt_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    dispatch: Mapped[str] = mapped_column(String(16), nullable=False, default="claimed")
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PortalWorkObservation(WorkspaceScope, Base):
    __tablename__ = "portal_work_observations"
    __table_args__ = (
        work_fk(),
        ForeignKeyConstraint(["claim_id"], ["portal_work_claims.id"]),
        UniqueConstraint("ticket_id", "sequence", name="uq_portal_work_observation_sequence"),
        UniqueConstraint("claim_id", name="uq_portal_work_claim_observation"),
        CheckConstraint(
            "sequence BETWEEN 1 AND 1000 AND kind IN ('submission','status','failure')"
        ),
        digest_check("public_sha256", "head_sha256"),
        json_check("public_observation", 4096),
        json_check("private_observation", 32768),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=uid)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    claim_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    private_observation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    public_observation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    public_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    head_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PortalWorkReopen(WorkspaceScope, Base):
    __tablename__ = "portal_work_reopens"
    __table_args__ = (
        work_fk(),
        ForeignKeyConstraint(["observation_id"], ["portal_work_observations.id"]),
        UniqueConstraint("observation_id", name="uq_portal_work_reopen_observation"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=uid)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    observation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
