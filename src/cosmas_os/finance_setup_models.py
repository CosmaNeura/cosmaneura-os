"""Owner settings revisions around immutable financial connection/customer bindings."""

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
from cosmas_os.vendor_models import OwnerScope, digest_check, json_check


class FinanceSetup(OwnerScope, Base):
    __tablename__ = "finance_setups"
    __table_args__ = (
        ForeignKeyConstraint(["owner_id", "box_id"], ["principals.id", "principals.box_id"]),
        ForeignKeyConstraint(
            ["account_setup_id", "box_id", "owner_id"],
            ["finance_setups.id", "finance_setups.box_id", "finance_setups.owner_id"],
        ),
        ForeignKeyConstraint(
            ["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]
        ),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_finance_setup_scope"),
        UniqueConstraint(
            "box_id", "owner_id", "installation_id", name="uq_finance_setup_installation"
        ),
        UniqueConstraint(
            "box_id",
            "owner_id",
            "account_setup_id",
            "patient_link_id",
            name="uq_finance_setup_patient",
        ),
        CheckConstraint(
            "(kind='account' AND installation_id IS NOT NULL AND account_setup_id IS NULL AND patient_link_id IS NULL) OR (kind='customer' AND installation_id IS NULL AND account_setup_id IS NOT NULL AND patient_link_id IS NOT NULL)"
        ),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    installation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    account_setup_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    patient_link_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FinanceSetupRevision(OwnerScope, Base):
    __tablename__ = "finance_setup_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["setup_id", "box_id", "owner_id"],
            ["finance_setups.id", "finance_setups.box_id", "finance_setups.owner_id"],
        ),
        ForeignKeyConstraint(
            ["account_revision_id", "box_id", "owner_id"],
            [
                "finance_setup_revisions.id",
                "finance_setup_revisions.box_id",
                "finance_setup_revisions.owner_id",
            ],
        ),
        ForeignKeyConstraint(
            ["connection_version_id", "box_id", "owner_id"],
            [
                "finance_connection_versions.id",
                "finance_connection_versions.box_id",
                "finance_connection_versions.owner_id",
            ],
        ),
        ForeignKeyConstraint(
            [
                "customer_version_id",
                "connection_version_id",
                "patient_link_id",
                "box_id",
                "owner_id",
            ],
            [
                "finance_customer_versions.id",
                "finance_customer_versions.connection_version_id",
                "finance_customer_versions.patient_link_id",
                "finance_customer_versions.box_id",
                "finance_customer_versions.owner_id",
            ],
        ),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_finance_setup_revision_owner"),
        UniqueConstraint(
            "id", "setup_id", "box_id", "owner_id", name="uq_finance_setup_revision_scope"
        ),
        UniqueConstraint("setup_id", "revision", name="uq_finance_setup_revision"),
        UniqueConstraint("customer_version_id", name="uq_finance_setup_customer_binding"),
        CheckConstraint("revision BETWEEN 1 AND 20"),
        CheckConstraint(
            "(kind='account' AND customer_version_id IS NULL AND account_revision_id IS NULL AND patient_link_id IS NULL) OR (kind='customer' AND customer_version_id IS NOT NULL AND account_revision_id IS NOT NULL AND patient_link_id IS NOT NULL)"
        ),
        digest_check("installation_sha256", "review_sha256"),
        json_check("review", 8192),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    setup_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    installation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    installation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    connection_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    customer_version_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    account_revision_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    patient_link_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    review: Mapped[dict] = mapped_column(JSONB, nullable=False)
    review_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FinanceSetupReceipt(OwnerScope, Base):
    __tablename__ = "finance_setup_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "setup_id", "box_id", "owner_id"],
            [
                "finance_setup_revisions.id",
                "finance_setup_revisions.setup_id",
                "finance_setup_revisions.box_id",
                "finance_setup_revisions.owner_id",
            ],
        ),
        UniqueConstraint("setup_id", "version", name="uq_finance_setup_version"),
        UniqueConstraint("box_id", "owner_id", "idempotency_key", name="uq_finance_setup_command"),
        CheckConstraint(
            "version BETWEEN 1 AND 100 AND command_kind IN ('propose_account','propose_customer','activate','disable','revoke') AND state IN ('pending_review','active','disabled','revoked')"
        ),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'"),
        digest_check("request_sha256", "receipt_sha256"),
        json_check("request", 8192),
        json_check("response", 4096),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    setup_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    command_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
