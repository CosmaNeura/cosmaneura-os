"""Reviewed human workspace enrollment; never an agent work queue."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base


class PracticeAccessRequest(Base):
    __tablename__ = "practice_access_requests"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", "request_key", name="uq_practice_access_retry"),
        Index("ix_practice_access_pending", "box_id", "state", "created_at"),
        CheckConstraint("state IN ('pending','approved','declined','cancelled')", name="ck_practice_access_state"),
        CheckConstraint("review_sha256 ~ '^[a-f0-9]{64}$'", name="ck_practice_access_hash"),
        CheckConstraint("expires_at > created_at", name="ck_practice_access_expiry"),
        CheckConstraint("(state='pending' AND decided_at IS NULL AND decided_by IS NULL) OR (state='cancelled' AND decided_at IS NOT NULL AND decided_by IS NULL) OR (state IN ('approved','declined') AND decided_at IS NOT NULL AND decided_by IS NOT NULL)", name="ck_practice_access_decision"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"))
    issuer: Mapped[str] = mapped_column(String(255))
    organization_id: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    request_key: Mapped[str] = mapped_column(UUID(as_uuid=False))
    display_name: Mapped[str] = mapped_column(String(120))
    review_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("principals.id"), nullable=True)
