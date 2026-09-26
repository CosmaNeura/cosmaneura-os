"""Exact negative admission receipts; no clinical, send or completion authority."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base
from cosmas_os.vendor_models import WorkspaceScope, digest_check, json_check


class VendorCommandRetirement(WorkspaceScope, Base):
    __tablename__ = "vendor_command_retirements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "box_id", "owner_id"],
            [
                "encounter_workspaces.id",
                "encounter_workspaces.box_id",
                "encounter_workspaces.owner_id",
            ],
        ),
        ForeignKeyConstraint(
            ["operation_id", "action_revision_id", "ticket_id", "box_id"],
            [
                "vendor_work_revisions.intended_operation_id",
                "vendor_work_revisions.action_revision_id",
                "vendor_work_revisions.ticket_id",
                "vendor_work_revisions.box_id",
            ],
        ),
        UniqueConstraint(
            "workspace_id", "actor_id", "idempotency_key", name="uq_vendor_retirement_key"
        ),
        CheckConstraint(
            "actor_id=owner_id AND command_kind IN ('decide','submit','verify') AND idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'",
            name="ck_vendor_retirement_command_kind",
        ),
        digest_check("request_sha256", "receipt_sha256", "payload_hash"),
        json_check("public_request", 4096),
        json_check("public_retirement", 4096),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    actor_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    action_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    command_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    public_request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    public_retirement: Mapped[dict] = mapped_column(JSONB, nullable=False)
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    retired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @property
    def scope_kind(self):
        return "workspace"

    @property
    def scope_id(self):
        return self.workspace_id


class VendorPreparationRetirement(WorkspaceScope, Base):
    """No-admission proof whose target need not have created vendor work."""

    __tablename__ = "vendor_preparation_retirements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "box_id", "owner_id"],
            ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"],
        ),
        UniqueConstraint("workspace_id", "actor_id", "idempotency_key", name="uq_vendor_preparation_retirement_key"),
        CheckConstraint("actor_id=owner_id AND command_kind IN ('propose','artifact_intent','artifact_content') AND idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'"),
        digest_check("request_sha256", "receipt_sha256"),
        json_check("public_request", 65536),
        json_check("public_retirement", 4096),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    actor_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    command_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    public_request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    public_retirement: Mapped[dict] = mapped_column(JSONB, nullable=False)
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    retired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @property
    def scope_kind(self):
        return "workspace"

    @property
    def scope_id(self):
        return self.workspace_id
