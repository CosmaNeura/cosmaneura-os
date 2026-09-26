"""Private financial bindings/evidence around existing F8 tickets and operations.

No membership state, stored card data, processor client secret, or automatic
financial action belongs in these records. The additive migration freezes DDL
and guards independently of these runtime model definitions.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base
from cosmas_os.vendor_models import (
    NoteScope,
    OwnerScope,
    WorkspaceScope,
    digest_check,
    json_check,
    note_fk,
)


def uid():
    return str(uuid4())


def workspace_fk():
    return ForeignKeyConstraint(
        ["workspace_id", "box_id", "owner_id"],
        ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"],
    )


class FinanceConnectionVersion(OwnerScope, Base):
    __tablename__ = "finance_connection_versions"
    __table_args__ = (
        ForeignKeyConstraint(["owner_id", "box_id"], ["principals.id", "principals.box_id"]),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_finance_connection_scope"),
        UniqueConstraint("family_id", "revision", name="uq_finance_connection_revision"),
        Index(
            "uq_finance_connection_current",
            "box_id",
            "owner_id",
            "family_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        CheckConstraint(
            "revision > 0 AND reviewed_by = owner_id AND environment IN ('production','sandbox')"
        ),
        digest_check("private_sha256", "public_sha256"),
        json_check("private_selection", 8192),
        json_check("public_view", 4096),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=uid)
    family_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    private_selection: Mapped[dict] = mapped_column(JSONB, nullable=False)
    private_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    public_view: Mapped[dict] = mapped_column(JSONB, nullable=False)
    public_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    write_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    read_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FinanceCustomerVersion(OwnerScope, Base):
    __tablename__ = "finance_customer_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connection_version_id", "box_id", "owner_id"],
            [
                "finance_connection_versions.id",
                "finance_connection_versions.box_id",
                "finance_connection_versions.owner_id",
            ],
        ),
        ForeignKeyConstraint(
            ["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]
        ),
        UniqueConstraint(
            "id",
            "connection_version_id",
            "patient_link_id",
            "box_id",
            "owner_id",
            name="uq_finance_customer_scope",
        ),
        UniqueConstraint("family_id", "revision", name="uq_finance_customer_revision"),
        Index(
            "uq_finance_customer_current",
            "box_id",
            "owner_id",
            "family_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        CheckConstraint(
            "revision > 0 AND reviewed_by = owner_id AND customer_id ~ '^cus_[A-Za-z0-9]+$'"
        ),
        digest_check("mapping_sha256", "public_sha256"),
        json_check("public_view", 4096),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=uid)
    family_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    connection_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    mapping_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    public_view: Mapped[dict] = mapped_column(JSONB, nullable=False)
    public_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FinanceWorkRevision(NoteScope, Base):
    __tablename__ = "finance_work_revisions"
    __table_args__ = (
        workspace_fk(),
        note_fk(),
        ForeignKeyConstraint(["note_id"], ["workspace_note_reviews.note_id"]),
        ForeignKeyConstraint(
            ["action_revision_id", "ticket_id", "box_id", "payload_hash"],
            [
                "action_revisions.id",
                "action_revisions.ticket_id",
                "action_revisions.box_id",
                "action_revisions.payload_hash",
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
        UniqueConstraint("intended_operation_id", name="uq_finance_intended_operation"),
        UniqueConstraint("ticket_id", "revision_number", name="uq_finance_ticket_revision"),
        UniqueConstraint(
            "action_revision_id", "ticket_id", "box_id", name="uq_finance_revision_scope"
        ),
        UniqueConstraint(
            "intended_operation_id",
            "action_revision_id",
            "ticket_id",
            "box_id",
            name="uq_finance_operation_revision",
        ),
        CheckConstraint(
            "revision_number BETWEEN 1 AND 20 AND source_workspace_revision > 0 AND amount BETWEEN 50 AND 99999999 AND currency='usd'"
        ),
        digest_check(
            "payload_hash",
            "request_sha256",
            "review_sha256",
            "private_command_sha256",
            "content_hash",
            "source_fingerprint",
        ),
        json_check("private_command", 16384),
        json_check("public_proposal", 16384),
        json_check("public_review", 16384),
    )
    action_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_workspace_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    intended_operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    connection_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    customer_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    review_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    private_command_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    private_command: Mapped[dict] = mapped_column(JSONB, nullable=False)
    public_proposal: Mapped[dict] = mapped_column(JSONB, nullable=False)
    public_review: Mapped[dict] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def revision_fk():
    return ForeignKeyConstraint(
        ["operation_id", "action_revision_id", "ticket_id", "box_id"],
        [
            "finance_work_revisions.intended_operation_id",
            "finance_work_revisions.action_revision_id",
            "finance_work_revisions.ticket_id",
            "finance_work_revisions.box_id",
        ],
    )


class FinanceReceipt(WorkspaceScope, Base):
    __tablename__ = "finance_command_receipts"
    __table_args__ = (
        revision_fk(),
        ForeignKeyConstraint(
            ["result_receipt_id", "ticket_id", "action_revision_id", "box_id"],
            [
                "finance_command_receipts.id",
                "finance_command_receipts.ticket_id",
                "finance_command_receipts.action_revision_id",
                "finance_command_receipts.box_id",
            ],
        ),
        ForeignKeyConstraint(["actor_id", "box_id"], ["principals.id", "principals.box_id"]),
        UniqueConstraint(
            "workspace_id", "actor_id", "idempotency_key", name="uq_finance_command_key"
        ),
        UniqueConstraint(
            "id", "ticket_id", "action_revision_id", "box_id", name="uq_finance_receipt_scope"
        ),
        CheckConstraint(
            "actor_id=owner_id AND command_kind IN ('propose','decide','withdraw','submit','reconcile','result','verify') AND effect_version>0 AND idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'"
        ),
        digest_check("request_sha256", "receipt_sha256"),
        json_check("public_request", 16384),
        json_check("effect", 8192),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=uid)
    actor_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    action_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    command_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    public_request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    effect_version: Mapped[int] = mapped_column(Integer, nullable=False)
    effect: Mapped[dict] = mapped_column(JSONB, nullable=False)
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_payload: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    result_receipt_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    observation_head_sha256: Mapped[str | None] = mapped_column(String(64))
    evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClaimScope(WorkspaceScope):
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    action_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    actor_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    command_receipt_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    claim_token: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    admitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def claim_fks():
    return (
        revision_fk(),
        ForeignKeyConstraint(
            ["operation_id", "ticket_id", "box_id"],
            ["operations.id", "operations.ticket_id", "operations.box_id"],
        ),
        ForeignKeyConstraint(
            ["command_receipt_id", "ticket_id", "action_revision_id", "box_id"],
            [
                "finance_command_receipts.id",
                "finance_command_receipts.ticket_id",
                "finance_command_receipts.action_revision_id",
                "finance_command_receipts.box_id",
            ],
        ),
        CheckConstraint("actor_id=owner_id AND deadline > admitted_at"),
    )


class FinanceSubmitClaim(ClaimScope, Base):
    __tablename__ = "finance_submit_claims"
    __table_args__ = (
        *claim_fks(),
        ForeignKeyConstraint(
            ["approval_receipt_id", "ticket_id", "action_revision_id", "box_id"],
            [
                "finance_command_receipts.id",
                "finance_command_receipts.ticket_id",
                "finance_command_receipts.action_revision_id",
                "finance_command_receipts.box_id",
            ],
        ),
        CheckConstraint(
            "dispatch IN ('not_started','invocation_started','proved_not_dispatched','unconfirmed','response_observed')"
        ),
        digest_check("command_sha256"),
    )
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    approval_receipt_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    command_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    dispatch: Mapped[str] = mapped_column(String(32), nullable=False, default="not_started")
    invocation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_error: Mapped[str | None] = mapped_column(String(64))


class FinanceReadClaim(ClaimScope, Base):
    __tablename__ = "finance_read_claims"
    __table_args__ = (
        *claim_fks(),
        UniqueConstraint("command_receipt_id", name="uq_finance_read_receipt"),
        json_check("private_reference", 4096),
        CheckConstraint("state IN ('admitted','settled','unknown')"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=uid)
    private_reference: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="admitted")


class FinanceEventCandidate(OwnerScope, Base):
    __tablename__ = "finance_event_candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connection_version_id", "box_id", "owner_id"],
            [
                "finance_connection_versions.id",
                "finance_connection_versions.box_id",
                "finance_connection_versions.owner_id",
            ],
        ),
        UniqueConstraint("connection_version_id", "body_sha256", name="uq_finance_event_candidate"),
        digest_check("body_sha256"),
        json_check("correlation", 4096),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=uid)
    connection_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    route_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FinanceObservation(WorkspaceScope, Base):
    __tablename__ = "finance_provider_observations"
    __table_args__ = (
        revision_fk(),
        ForeignKeyConstraint(["submit_claim_id"], ["finance_submit_claims.operation_id"]),
        ForeignKeyConstraint(["read_claim_id"], ["finance_read_claims.id"]),
        UniqueConstraint("operation_id", "sequence", name="uq_finance_observation_sequence"),
        CheckConstraint(
            "sequence > 0 AND kind IN ('dispatch','creation','payment') AND ((submit_claim_id=operation_id AND read_claim_id IS NULL) OR (submit_claim_id IS NULL AND read_claim_id IS NOT NULL))"
        ),
        digest_check("public_sha256", "head_sha256"),
        json_check("public_observation", 4096),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=uid)
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    action_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    submit_claim_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    read_claim_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    private_reference: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    public_observation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    public_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    head_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FinanceReopenFact(WorkspaceScope, Base):
    __tablename__ = "finance_reopen_facts"
    __table_args__ = (
        revision_fk(),
        ForeignKeyConstraint(["observation_id"], ["finance_provider_observations.id"]),
        UniqueConstraint("operation_id", "observation_id", name="uq_finance_reopen_fact"),
        digest_check("observation_sha256"),
        CheckConstraint("effect_version > 0"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=uid)
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    action_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    observation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    observation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    effect_version: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
