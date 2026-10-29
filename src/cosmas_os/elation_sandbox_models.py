"""Local sandbox installation receipts and aggregate credential request budgets."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base
from cosmas_os.vendor_models import OwnerScope, digest_check


class ElationSandboxInstallationReceipt(OwnerScope, Base):
    __tablename__ = "elation_sandbox_installation_receipts"
    __table_args__ = (
        ForeignKeyConstraint(["binding_id", "box_id", "owner_id", "account_id"],
            ["ehr_read_bindings.id", "ehr_read_bindings.box_id", "ehr_read_bindings.owner_id", "ehr_read_bindings.account_id"]),
        UniqueConstraint("box_id", "owner_id", "idempotency_key", name="uq_elation_install_key"),
        UniqueConstraint("binding_id", name="uq_elation_install_binding"),
        UniqueConstraint("box_id", "owner_id", "installation_id", "installation_sha256", name="uq_elation_install_version"),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'", name="ck_elation_install_key"),
        digest_check("installation_sha256", "request_sha256"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    binding_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    installation_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    installation_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class ElationSandboxQuota(Base):
    __tablename__ = "elation_sandbox_quotas"
    __table_args__ = (digest_check("credential_key"),)
    credential_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_permitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ElationSandboxQuotaMinute(Base):
    __tablename__ = "elation_sandbox_quota_minutes"
    __table_args__ = (CheckConstraint("requests BETWEEN 1 AND 149999 AND isfinite(minute)", name="ck_elation_quota_minute"),)
    credential_key: Mapped[str] = mapped_column(String(64), ForeignKey("elation_sandbox_quotas.credential_key"), primary_key=True)
    minute: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    requests: Mapped[int] = mapped_column(Integer)
