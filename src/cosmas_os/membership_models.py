"""Private immutable membership review and exact human command receipts on F8."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base
from cosmas_os.vendor_models import NoteScope, WorkspaceScope, digest_check, json_check, note_fk


class MembershipWork(NoteScope, Base):
    __tablename__ = "membership_work"
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
            ["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]
        ),
        ForeignKeyConstraint(
            ["revision_id", "ticket_id", "box_id", "payload_hash"],
            [
                "action_revisions.id",
                "action_revisions.ticket_id",
                "action_revisions.box_id",
                "action_revisions.payload_hash",
            ],
        ),
        note_fk(),
        ForeignKeyConstraint(["note_id"], ["workspace_note_reviews.note_id"]),
        UniqueConstraint(
            "ticket_id", "workspace_id", "box_id", "owner_id", name="uq_membership_work_scope"
        ),
        CheckConstraint("source_workspace_revision > 0"),
        digest_check(
            "payload_hash", "request_sha256", "review_sha256", "content_hash", "source_fingerprint"
        ),
        json_check("proposal", 8192),
        json_check("review", 16384),
    )
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, unique=True)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    source_workspace_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    review_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal: Mapped[dict] = mapped_column(JSONB, nullable=False)
    review: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MembershipReceipt(WorkspaceScope, Base):
    __tablename__ = "membership_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ticket_id", "workspace_id", "box_id", "owner_id"],
            [
                "membership_work.ticket_id",
                "membership_work.workspace_id",
                "membership_work.box_id",
                "membership_work.owner_id",
            ],
        ),
        ForeignKeyConstraint(["result_receipt_id"], ["membership_receipts.id"]),
        UniqueConstraint(
            "workspace_id", "owner_id", "idempotency_key", name="uq_membership_command"
        ),
        UniqueConstraint("ticket_id", "version", name="uq_membership_receipt_version"),
        CheckConstraint(
            "version BETWEEN 1 AND 100 AND command_kind IN ('propose','decide','result','verify','withdraw')"
        ),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'"),
        digest_check("request_sha256", "receipt_sha256"),
        json_check("request", 8192),
        json_check("response", 8192),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    command_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_receipt_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MembershipCommandRetirement(WorkspaceScope, Base):
    """Immutable proof that one exact rejected local request cannot be admitted."""

    __tablename__ = "membership_command_retirements"
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
            ["ticket_id", "workspace_id", "box_id", "owner_id"],
            [
                "membership_work.ticket_id",
                "membership_work.workspace_id",
                "membership_work.box_id",
                "membership_work.owner_id",
            ],
        ),
        UniqueConstraint(
            "workspace_id", "owner_id", "idempotency_key", name="uq_membership_retirement_key"
        ),
        CheckConstraint(
            "command_kind IN ('propose','decide','result','verify','withdraw') AND (ticket_id IS NULL)=(command_kind='propose')"
        ),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'"),
        CheckConstraint(
            "reason IN ('membership_source_changed','membership_revision_changed','membership_result_changed','membership_exception_unresolved','membership_evidence_changed','membership_history_limit')"
        ),
        digest_check("request_sha256", "receipt_sha256"),
        json_check("request", 16384),
        json_check("response", 8192),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    ticket_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    command_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(48), nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    retired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
