"""Private multi-provider inbox custody around the existing F8 approval queue."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base
from cosmas_os.vendor_models import OwnerScope, digest_check, json_check


def _id():
    return str(uuid4())


def _owner():
    return ForeignKeyConstraint(["owner_id", "box_id"], ["principals.id", "principals.box_id"])


def _grant():
    return ForeignKeyConstraint(
        ["grant_id", "box_id", "owner_id"],
        ["fax_inbound_grants.id", "fax_inbound_grants.box_id", "fax_inbound_grants.owner_id"],
    )


class FaxInboundGrant(OwnerScope, Base):
    __tablename__ = "fax_inbound_grants"
    __table_args__ = (
        _owner(),
        UniqueConstraint("id", "box_id", "owner_id"),
        CheckConstraint("expires_at>reviewed_at AND expires_at<=reviewed_at+interval '1 day'"),
        CheckConstraint("char_length(label) BETWEEN 1 AND 80 AND reviewed_by=owner_id"),
        digest_check("installation_sha256", "account_sha256"),
        json_check("installation", 8192),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_id)
    installation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    installation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    account_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    image_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_by: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FaxInboundCommand(OwnerScope, Base):
    __tablename__ = "fax_inbound_commands"
    __table_args__ = (
        _owner(),
        UniqueConstraint("id", "box_id", "owner_id"),
        UniqueConstraint("box_id", "owner_id", "idempotency_key"),
        CheckConstraint("kind IN ('grant','revoke','observe','propose','decide','acquire')"),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'"),
        digest_check("request_sha256"),
        json_check("request", 8192),
        json_check("public_request", 8192),
        json_check("result", 8192),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_id)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    public_request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class FaxInboundObservation(OwnerScope, Base):
    __tablename__ = "fax_inbound_observations"
    __table_args__ = (
        _grant(),
        ForeignKeyConstraint(
            ["id", "box_id", "owner_id"],
            [
                "fax_inbound_commands.id",
                "fax_inbound_commands.box_id",
                "fax_inbound_commands.owner_id",
            ],
        ),
        UniqueConstraint("id", "box_id", "owner_id"),
        digest_check("source_sha256"),
        json_check("snapshot", 131072),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    grant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class FaxInboundImage(OwnerScope, Base):
    __tablename__ = "fax_inbound_images"
    __table_args__ = (
        _grant(),
        ForeignKeyConstraint(
            ["observation_id", "box_id", "owner_id"],
            [
                "fax_inbound_observations.id",
                "fax_inbound_observations.box_id",
                "fax_inbound_observations.owner_id",
            ],
        ),
        ForeignKeyConstraint(
            ["revision_id", "ticket_id", "box_id", "payload_sha256"],
            [
                "action_revisions.id",
                "action_revisions.ticket_id",
                "action_revisions.box_id",
                "action_revisions.payload_hash",
            ],
        ),
        UniqueConstraint("id", "box_id", "owner_id"),
        UniqueConstraint("revision_id"),
        UniqueConstraint("operation_id"),
        digest_check("source_sha256", "payload_sha256"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_id)
    grant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    observation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FaxInboundAttempt(OwnerScope, Base):
    __tablename__ = "fax_inbound_attempts"
    __table_args__ = (
        _owner(),
        ForeignKeyConstraint(
            ["image_id", "box_id", "owner_id"],
            ["fax_inbound_images.id", "fax_inbound_images.box_id", "fax_inbound_images.owner_id"],
        ),
        ForeignKeyConstraint(
            ["operation_id", "ticket_id", "box_id"],
            ["operations.id", "operations.ticket_id", "operations.box_id"],
        ),
        UniqueConstraint("operation_id", "box_id", "owner_id"),
        UniqueConstraint("account_sha256", "locator_sha256"),
        digest_check("account_sha256", "locator_sha256", "token_sha256", "approval_sha256"),
        CheckConstraint("deadline>created_at AND deadline<=created_at+interval '45 seconds'"),
    )
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    image_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    account_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    locator_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FaxInboundOutcome(OwnerScope, Base):
    __tablename__ = "fax_inbound_outcomes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["operation_id", "box_id", "owner_id"],
            [
                "fax_inbound_attempts.operation_id",
                "fax_inbound_attempts.box_id",
                "fax_inbound_attempts.owner_id",
            ],
        ),
        CheckConstraint("state IN ('acquired','outcome_unconfirmed')"),
        CheckConstraint(
            "(state='acquired' AND document IS NOT NULL AND octet_length(document)=document_byte_length+28 AND document_byte_length BETWEEN 1 AND 1048576 AND pages BETWEEN 1 AND 50 AND document_sha256 ~ '^[a-f0-9]{64}$' AND document_ciphertext_sha256 ~ '^[a-f0-9]{64}$' AND document_key_id ~ '^[A-Za-z0-9:_-]{1,80}$') OR (state='outcome_unconfirmed' AND document IS NULL AND document_sha256 IS NULL AND pages IS NULL AND document_byte_length IS NULL AND document_ciphertext_sha256 IS NULL AND document_key_id IS NULL)"
        ),
    )
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    document: Mapped[bytes | None] = mapped_column(LargeBinary)
    document_sha256: Mapped[str | None] = mapped_column(String(64))
    pages: Mapped[int | None] = mapped_column(Integer)
    document_byte_length: Mapped[int | None] = mapped_column(Integer)
    document_ciphertext_sha256: Mapped[str | None] = mapped_column(String(64))
    document_key_id: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class FaxInboundDispatch(OwnerScope, Base):
    __tablename__ = "fax_inbound_dispatches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["operation_id", "box_id", "owner_id"],
            [
                "fax_inbound_attempts.operation_id",
                "fax_inbound_attempts.box_id",
                "fax_inbound_attempts.owner_id",
            ],
        ),
    )
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
