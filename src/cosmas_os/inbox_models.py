"""Private incoming source versions and immutable human/read receipts."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
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
from cosmas_os.vendor_models import OwnerScope, digest_check, json_check


class InboxItem(OwnerScope, Base):
    __tablename__ = "inbox_items"
    __table_args__ = (
        ForeignKeyConstraint(["owner_id", "box_id"], ["principals.id", "principals.box_id"]),
        ForeignKeyConstraint(
            ["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]
        ),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_inbox_item_scope"),
        UniqueConstraint("box_id", "owner_id", "grant_id", name="uq_inbox_grant_item"),
        ForeignKeyConstraint(
            ["current_source_id", "id"],
            ["inbox_sources.id", "inbox_sources.item_id"],
            name="fk_inbox_current_source",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("version BETWEEN 1 AND 100"),
        digest_check("grant_sha256"),
        json_check("grant_payload", 16384),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    grant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    grant_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    grant: Mapped[dict] = mapped_column("grant_payload", JSONB, nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_source_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    source_conflict: Mapped[bool] = mapped_column(Boolean, nullable=False)
    read_issue: Mapped[str | None] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InboxSource(OwnerScope, Base):
    __tablename__ = "inbox_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["item_id", "box_id", "owner_id"],
            ["inbox_items.id", "inbox_items.box_id", "inbox_items.owner_id"],
        ),
        UniqueConstraint("id", "item_id", name="uq_inbox_source_identity"),
        UniqueConstraint("item_id", "sequence", name="uq_inbox_source_sequence"),
        UniqueConstraint("item_id", "source_sha256", name="uq_inbox_source_content"),
        CheckConstraint("sequence BETWEEN 1 AND 50"),
        digest_check("source_sha256", "snapshot_sha256"),
        json_check("snapshot", 131072),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    item_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InboxEvent(OwnerScope, Base):
    __tablename__ = "inbox_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["item_id", "box_id", "owner_id"],
            ["inbox_items.id", "inbox_items.box_id", "inbox_items.owner_id"],
        ),
        ForeignKeyConstraint(
            ["source_id", "item_id"], ["inbox_sources.id", "inbox_sources.item_id"]
        ),
        UniqueConstraint("item_id", "version", name="uq_inbox_event_version"),
        UniqueConstraint("item_id", "origin", "idempotency_key", name="uq_inbox_event_key"),
        CheckConstraint("version BETWEEN 1 AND 100"),
        CheckConstraint(
            "(origin='read' AND kind IN ('ingest','read_failed')) OR (origin='human' AND kind IN ('review','triage','result','verify'))"
        ),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'"),
        digest_check("request_sha256", "receipt_sha256"),
        json_check("request", 16384),
        json_check("response", 16384),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    item_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String(8), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
