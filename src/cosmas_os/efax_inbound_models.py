"""Private eFax account custody and one-shot F8 image acquisition sidecars."""

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


def _scope():
    return ForeignKeyConstraint(["owner_id", "box_id"], ["principals.id", "principals.box_id"])


class EFaxInboundGrant(OwnerScope, Base):
    __tablename__ = "efax_inbound_grants"
    __table_args__ = (
        _scope(),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_efax_inbound_grant_scope"),
        CheckConstraint(
            "metadata_enabled AND expires_at>reviewed_at AND expires_at<=reviewed_at+interval '30 days'"
        ),
        CheckConstraint("char_length(label) BETWEEN 1 AND 80 AND reviewed_by=owner_id"),
        digest_check("account_sha256", "selection_sha256", "request_sha256"),
        json_check("selection", 4096),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_id)
    connection_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    account_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    selection: Mapped[dict] = mapped_column(JSONB, nullable=False)
    selection_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    metadata_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    image_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_by: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class EFaxInboundReceipt(OwnerScope, Base):
    __tablename__ = "efax_inbound_receipts"
    __table_args__ = (
        _scope(),
        UniqueConstraint(
            "box_id", "owner_id", "idempotency_key", name="uq_efax_inbound_receipt_key"
        ),
        CheckConstraint("kind IN ('grant','revoke','observe','propose','decide','acquire')"),
        CheckConstraint("char_length(idempotency_key) BETWEEN 8 AND 100"),
        digest_check("request_sha256"),
        json_check("request", 8192),
        json_check("result", 8192),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_id)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class EFaxInboundObservationRequest(OwnerScope, Base):
    __tablename__ = "efax_inbound_observation_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["grant_id", "box_id", "owner_id"],
            [
                "efax_inbound_grants.id",
                "efax_inbound_grants.box_id",
                "efax_inbound_grants.owner_id",
            ],
        ),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_efax_inbound_observe_scope"),
        digest_check("request_sha256"),
        json_check("request", 8192),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_id)
    grant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class EFaxInboundObservation(OwnerScope, Base):
    __tablename__ = "efax_inbound_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "box_id", "owner_id"],
            [
                "efax_inbound_observation_requests.id",
                "efax_inbound_observation_requests.box_id",
                "efax_inbound_observation_requests.owner_id",
            ],
        ),
        UniqueConstraint("request_id", name="uq_efax_inbound_observation_request"),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_efax_inbound_observation_scope"),
        digest_check("payload_sha256", "source_sha256"),
        json_check("payload", 65536),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_id)
    request_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class EFaxInboundImageRevision(OwnerScope, Base):
    __tablename__ = "efax_inbound_image_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["action_revision_id", "ticket_id", "box_id", "action_sha256"],
            [
                "action_revisions.id",
                "action_revisions.ticket_id",
                "action_revisions.box_id",
                "action_revisions.payload_hash",
            ],
        ),
        ForeignKeyConstraint(
            ["grant_id", "box_id", "owner_id"],
            [
                "efax_inbound_grants.id",
                "efax_inbound_grants.box_id",
                "efax_inbound_grants.owner_id",
            ],
        ),
        ForeignKeyConstraint(
            ["observation_id", "box_id", "owner_id"],
            [
                "efax_inbound_observation_requests.id",
                "efax_inbound_observation_requests.box_id",
                "efax_inbound_observation_requests.owner_id",
            ],
        ),
        UniqueConstraint(
            "action_revision_id", "box_id", "owner_id", name="uq_efax_inbound_revision_scope"
        ),
        UniqueConstraint("ticket_id", name="uq_efax_inbound_revision_ticket"),
        UniqueConstraint("operation_id", name="uq_efax_inbound_revision_operation"),
        digest_check("action_sha256", "command_sha256", "fax_sha256"),
        json_check("command", 8192),
    )
    action_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    grant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    observation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    fax_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    fax_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    action_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    command: Mapped[dict] = mapped_column(JSONB, nullable=False)
    command_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class EFaxInboundAcquisition(OwnerScope, Base):
    __tablename__ = "efax_inbound_acquisitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["operation_id", "ticket_id", "box_id"],
            ["operations.id", "operations.ticket_id", "operations.box_id"],
        ),
        ForeignKeyConstraint(
            ["action_revision_id", "box_id", "owner_id"],
            [
                "efax_inbound_image_revisions.action_revision_id",
                "efax_inbound_image_revisions.box_id",
                "efax_inbound_image_revisions.owner_id",
            ],
        ),
        UniqueConstraint(
            "operation_id", "box_id", "owner_id", name="uq_efax_inbound_acquisition_scope"
        ),
        UniqueConstraint(
            "box_id", "account_sha256", "fax_id", name="uq_efax_inbound_acquisition_resource"
        ),
        CheckConstraint("deadline>claimed_at AND deadline<=claimed_at+interval '45 seconds'"),
        digest_check("account_sha256", "token_sha256", "approval_sha256"),
        json_check("approval", 8192),
    )
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    action_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    account_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    fax_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    approval: Mapped[dict] = mapped_column(JSONB, nullable=False)
    approval_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EFaxInboundInvocation(OwnerScope, Base):
    __tablename__ = "efax_inbound_invocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["operation_id", "box_id", "owner_id"],
            [
                "efax_inbound_acquisitions.operation_id",
                "efax_inbound_acquisitions.box_id",
                "efax_inbound_acquisitions.owner_id",
            ],
        ),
    )
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EFaxInboundOutcome(OwnerScope, Base):
    __tablename__ = "efax_inbound_outcomes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["operation_id", "box_id", "owner_id"],
            [
                "efax_inbound_acquisitions.operation_id",
                "efax_inbound_acquisitions.box_id",
                "efax_inbound_acquisitions.owner_id",
            ],
        ),
        CheckConstraint(
            "state IN ('not_attempted','outcome_unconfirmed','acquired','needs_human')"
        ),
        CheckConstraint(
            "(state='acquired' AND document IS NOT NULL AND document_sha256 IS NOT NULL AND byte_length IS NOT NULL AND pages IS NOT NULL AND octet_length(document) BETWEEN 1 AND 1048576 AND byte_length=octet_length(document) AND pages BETWEEN 1 AND 50 AND document_sha256=encode(sha256(document),'hex')) OR (state<>'acquired' AND document IS NULL AND document_sha256 IS NULL AND byte_length IS NULL AND pages IS NULL)"
        ),
        digest_check("receipt_sha256"),
        json_check("receipt", 8192),
    )
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    receipt: Mapped[dict] = mapped_column(JSONB, nullable=False)
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document: Mapped[bytes | None] = mapped_column(LargeBinary)
    document_sha256: Mapped[str | None] = mapped_column(String(64))
    byte_length: Mapped[int | None] = mapped_column(Integer)
    pages: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
