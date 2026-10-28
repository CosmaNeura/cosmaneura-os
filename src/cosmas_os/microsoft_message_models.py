"""Private immutable Microsoft observations, selected reads, and human source reviews."""

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
from cosmas_os.vendor_models import OwnerScope, WorkspaceScope, digest_check, json_check


class MicrosoftMessageReadRequest(OwnerScope, Base):
    __tablename__ = "microsoft_message_read_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "box_id", "owner_id"],
            [
                "external_identities.id",
                "external_identities.box_id",
                "external_identities.principal_id",
            ],
        ),
        ForeignKeyConstraint(
            ["observation_id", "box_id", "owner_id"],
            [
                "microsoft_message_read_requests.id",
                "microsoft_message_read_requests.box_id",
                "microsoft_message_read_requests.owner_id",
            ],
        ),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_microsoft_message_read_scope"),
        UniqueConstraint("account_id", "ordinal", name="uq_microsoft_message_read_ordinal"),
        UniqueConstraint(
            "box_id", "owner_id", "idempotency_key", name="uq_microsoft_message_read_key"
        ),
        CheckConstraint(
            "kind IN ('list','message') AND ordinal >= 1", name="ck_microsoft_message_read_kind"
        ),
        CheckConstraint(
            "char_length(idempotency_key) BETWEEN 1 AND 100", name="ck_microsoft_message_read_key"
        ),
        CheckConstraint(
            "(kind='list' AND observation_id IS NULL AND observation_sha256 IS NULL AND message_id IS NULL AND thread_id IS NULL) OR (kind='message' AND observation_id IS NOT NULL AND observation_sha256 ~ '^[0-9a-f]{64}$' AND message_id ~ '^[A-Za-z0-9_+/=-]+$' AND (thread_id IS NULL OR thread_id ~ '^[A-Za-z0-9_+/=-]+$'))",
            name="ck_microsoft_message_read_selection",
        ),
        digest_check("request_hash", "binding_digest", "grant_sha256"),
    )
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    grant_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    observation_sha256: Mapped[str | None] = mapped_column(String(64))
    message_id: Mapped[str | None] = mapped_column(String(2048))
    thread_id: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MicrosoftMessageSnapshot(OwnerScope, Base):
    __tablename__ = "microsoft_message_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["read_id", "box_id", "owner_id"],
            [
                "microsoft_message_read_requests.id",
                "microsoft_message_read_requests.box_id",
                "microsoft_message_read_requests.owner_id",
            ],
        ),
        UniqueConstraint("read_id", name="uq_microsoft_message_snapshot_read"),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_microsoft_message_snapshot_scope"),
        digest_check("payload_sha256", "source_sha256"),
        json_check("payload", 65536),
    )
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    read_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MicrosoftMessageSourceReview(WorkspaceScope, Base):
    __tablename__ = "microsoft_message_source_reviews"
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
            ["entry_id", "workspace_id", "box_id"],
            ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"],
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "box_id", "owner_id"],
            [
                "microsoft_message_snapshots.id",
                "microsoft_message_snapshots.box_id",
                "microsoft_message_snapshots.owner_id",
            ],
        ),
        ForeignKeyConstraint(
            ["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]
        ),
        UniqueConstraint("entry_id", name="uq_microsoft_message_review_entry"),
        UniqueConstraint("workspace_id", "snapshot_id", name="uq_microsoft_message_review_snapshot"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_microsoft_message_review_key"),
        CheckConstraint(
            "expected_revision >= 1 AND workspace_revision=expected_revision+1",
            name="ck_microsoft_message_review_revision",
        ),
        CheckConstraint(
            "reviewed_patient AND reviewed_exact_message AND reviewed_untrusted_source",
            name="ck_microsoft_message_review_checks",
        ),
        digest_check("request_hash", "source_sha256", "content_sha256"),
    )
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    entry_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    workspace_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_patient: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_exact_message: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_untrusted_source: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
