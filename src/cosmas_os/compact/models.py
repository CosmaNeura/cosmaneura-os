from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from cosmas_os.models import BoxContext, Operation


class CompactBase(DeclarativeBase):
    """Separate experiment metadata: never included in the beta migration head."""


class ClaimRecord(CompactBase):
    __tablename__ = "compact_claims"

    operation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey(Operation.id), primary_key=True
    )
    token: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    phase: Mapped[str] = mapped_column(String(24), nullable=False)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SyntheticReceipt(CompactBase):
    __tablename__ = "compact_synthetic_receipts"

    operation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey(Operation.id), primary_key=True
    )
    box_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey(BoxContext.id), nullable=False
    )
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    external_reference: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkerHeartbeat(CompactBase):
    __tablename__ = "compact_worker_heartbeats"

    box_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey(BoxContext.id), primary_key=True
    )
    worker_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SchemaVersion(CompactBase):
    __tablename__ = "compact_schema_version"

    singleton: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
