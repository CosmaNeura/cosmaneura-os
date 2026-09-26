"""Encrypted staff credentials and retained single-use sign-in attempts."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base


class GoogleConnectionAttempt(Base):
    __tablename__ = "google_connection_attempts"
    __table_args__ = (
        Index(
            "uq_google_connection_active",
            "account_id",
            unique=True,
            postgresql_where=text("status IN ('pending','exchanging')"),
        ),
        CheckConstraint("status IN ('pending','exchanging','ready','failed')"),
        CheckConstraint("sealed IS NULL OR octet_length(sealed) BETWEEN 28 AND 32768"),
        CheckConstraint("state_digest ~ '^[a-f0-9]{64}$' AND binding_digest ~ '^[a-f0-9]{64}$'"),
        CheckConstraint("expires_at > created_at"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("external_identities.id"), nullable=False, index=True
    )
    state_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    binding_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    sealed: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GoogleConnectionCredential(Base):
    __tablename__ = "google_connection_credentials"
    __table_args__ = (
        CheckConstraint("status IN ('ready','refreshing','failed','disconnected')"),
        CheckConstraint("sealed IS NULL OR octet_length(sealed) BETWEEN 28 AND 32768"),
        CheckConstraint("binding_digest ~ '^[a-f0-9]{64}$'"),
    )
    account_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("external_identities.id"), primary_key=True
    )
    binding_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    sealed: Mapped[bytes | None] = mapped_column(LargeBinary)
    refresh_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
