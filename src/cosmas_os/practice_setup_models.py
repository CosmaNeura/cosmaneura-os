"""Explicit first-owner reservation and private practice setup receipt."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base


class PracticeOwnerReservation(Base):
    __tablename__ = "practice_owner_reservations"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_practice_owner_reservation_subject"),)

    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"), primary_key=True)
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PracticeSetupProfile(Base):
    __tablename__ = "practice_setup_profiles"
    __table_args__ = (ForeignKeyConstraint(["owner_id", "box_id"], ["principals.id", "principals.box_id"]),)

    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("box_contexts.id"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    specialty: Mapped[str | None] = mapped_column(String(120), nullable=True)
    request_key: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
