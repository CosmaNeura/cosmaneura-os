"""Immutable local portal mapping revisions and exact owner command history."""

from datetime import datetime
from uuid import uuid4

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


class PortalSetup(OwnerScope, Base):
    __tablename__ = "portal_setups"
    __table_args__ = (
        ForeignKeyConstraint(["owner_id", "box_id"], ["principals.id", "principals.box_id"]),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_portal_setup_scope"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PortalSetupRevision(OwnerScope, Base):
    __tablename__ = "portal_setup_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connection_id", "box_id", "owner_id"],
            ["portal_setups.id", "portal_setups.box_id", "portal_setups.owner_id"],
        ),
        ForeignKeyConstraint(
            ["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]
        ),
        UniqueConstraint(
            "id", "connection_id", "box_id", "owner_id", name="uq_portal_setup_revision_scope"
        ),
        UniqueConstraint("connection_id", "revision", name="uq_portal_setup_revision"),
        CheckConstraint("revision BETWEEN 1 AND 100"),
        digest_check("profile_sha256", "configuration_sha256", "review_sha256", "mappings_sha256"),
        json_check("review", 8192),
    )
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    connection_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    installation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    portal_id: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    practice_mapping_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_mapping_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    recipient_mapping_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    mappings_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    review: Mapped[dict] = mapped_column(JSONB, nullable=False)
    review_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PortalSetupReceipt(OwnerScope, Base):
    __tablename__ = "portal_setup_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "connection_id", "box_id", "owner_id"],
            [
                "portal_setup_revisions.id",
                "portal_setup_revisions.connection_id",
                "portal_setup_revisions.box_id",
                "portal_setup_revisions.owner_id",
            ],
        ),
        UniqueConstraint("connection_id", "version", name="uq_portal_setup_version"),
        UniqueConstraint(
            "box_id", "owner_id", "idempotency_key", name="uq_portal_setup_command_key"
        ),
        CheckConstraint(
            "command_kind IN ('propose','activate','disable','revoke') AND version BETWEEN 1 AND 1000"
        ),
        CheckConstraint("state IN ('pending_review','active','disabled','revoked')"),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'"),
        digest_check("request_sha256", "receipt_sha256"),
        json_check("request", 8192),
        json_check("response", 4096),
    )
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    connection_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    command_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
