"""Initial account connection attempts, separate from established credentials."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base


class SchedulingEnrollment(Base):
    __tablename__ = "scheduling_enrollments"
    __table_args__ = (
        Index(
            "uq_scheduling_enrollment_active",
            "external_identity_id",
            unique=True,
            postgresql_where=text("status IN ('pending','exchanging','review')"),
        ),
        CheckConstraint("status IN ('pending','exchanging','review','confirmed','failed')"),
        CheckConstraint("sealed IS NULL OR octet_length(sealed) BETWEEN 28 AND 32768"),
        CheckConstraint("state_digest ~ '^[a-f0-9]{64}$' AND binding_digest ~ '^[a-f0-9]{64}$'"),
        CheckConstraint("expires_at > created_at"),
        CheckConstraint(
            "(status = 'confirmed' AND sealed IS NULL AND account_id IS NOT NULL AND command_key IS NOT NULL AND command_sha256 IS NOT NULL) OR (status <> 'confirmed' AND account_id IS NULL AND command_key IS NULL AND command_sha256 IS NULL)"
        ),
        Index(
            "uq_scheduling_enrollment_command",
            "external_identity_id",
            "command_key",
            unique=True,
            postgresql_where=text("command_key IS NOT NULL"),
        ),
        CheckConstraint("command_sha256 IS NULL OR command_sha256 ~ '^[a-f0-9]{64}$'"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    external_identity_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("external_identities.id"), nullable=False, index=True
    )
    state_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    binding_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    sealed: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    account_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("scheduling_accounts.id")
    )
    command_key: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    command_sha256: Mapped[str | None] = mapped_column(String(64))
