"""Retained connector bindings and evidence around F8, never a second work queue.

The migration adds deferred cross-row guards as well as these declared bounds.
Private JSON is deliberately absent from generic Ticket/ActionRevision content.
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


def _uuid():
    return str(uuid4())


def digest_check(*names):
    return CheckConstraint(" AND ".join(f"{name} ~ '^[a-f0-9]{{64}}$'" for name in names))


def json_check(name, maximum):
    return CheckConstraint(
        f"jsonb_typeof({name}) = 'object' AND octet_length({name}::text) <= {maximum}"
    )


class OwnerScope:
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)


class WorkspaceScope(OwnerScope):
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)


class VendorConnectionVersion(OwnerScope, Base):
    __tablename__ = "vendor_connection_versions"
    __table_args__ = (
        ForeignKeyConstraint(["owner_id", "box_id"], ["principals.id", "principals.box_id"]),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_vendor_connection_scope"),
        UniqueConstraint("family_id", "revision", name="uq_vendor_connection_revision"),
        Index(
            "uq_vendor_connection_current",
            "box_id",
            "owner_id",
            "family_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        CheckConstraint("revision > 0 AND reviewed_by = owner_id"),
        CheckConstraint(
            "vendor IN ('spruce','srfax','documo') AND (environment = 'production' OR (vendor = 'documo' AND environment = 'sandbox'))"
        ),
        digest_check("private_sha256", "public_sha256"),
        json_check("private_selection", 32768),
        json_check("routing", 32768),
        json_check("public_view", 4096),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    family_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    vendor: Mapped[str] = mapped_column(String(16), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    private_selection: Mapped[dict] = mapped_column(JSONB, nullable=False)
    routing: Mapped[dict] = mapped_column(JSONB, nullable=False)
    private_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    public_view: Mapped[dict] = mapped_column(JSONB, nullable=False)
    public_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    read_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    write_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VendorCorrespondenceVersion(OwnerScope, Base):
    __tablename__ = "vendor_correspondence_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connection_version_id", "box_id", "owner_id"],
            [
                "vendor_connection_versions.id",
                "vendor_connection_versions.box_id",
                "vendor_connection_versions.owner_id",
            ],
        ),
        ForeignKeyConstraint(
            ["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]
        ),
        UniqueConstraint(
            "id",
            "connection_version_id",
            "box_id",
            "owner_id",
            "patient_link_id",
            name="uq_vendor_correspondence_scope",
        ),
        UniqueConstraint("family_id", "revision", name="uq_vendor_correspondence_revision"),
        Index(
            "uq_vendor_correspondence_current",
            "box_id",
            "owner_id",
            "family_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        CheckConstraint("revision > 0 AND reviewed_by = owner_id AND expires_at > reviewed_at"),
        digest_check("private_sha256", "public_sha256"),
        json_check("private_proof", 32768),
        json_check("public_view", 4096),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    family_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    connection_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    private_proof: Mapped[dict] = mapped_column(JSONB, nullable=False)
    private_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    public_view: Mapped[dict] = mapped_column(JSONB, nullable=False)
    public_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NoteScope(WorkspaceScope):
    note_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


def note_fk():
    return ForeignKeyConstraint(
        ["note_id", "workspace_id", "box_id", "owner_id", "content_hash", "source_fingerprint"],
        [
            "workspace_notes.id",
            "workspace_notes.workspace_id",
            "workspace_notes.box_id",
            "workspace_notes.owner_id",
            "workspace_notes.content_hash",
            "workspace_notes.source_fingerprint",
        ],
    )


class VendorArtifact(NoteScope, Base):
    __tablename__ = "vendor_artifacts"
    __table_args__ = (
        note_fk(),
        ForeignKeyConstraint(["note_id"], ["workspace_note_reviews.note_id"]),
        ForeignKeyConstraint(
            ["workspace_id", "box_id", "owner_id"],
            [
                "encounter_workspaces.id",
                "encounter_workspaces.box_id",
                "encounter_workspaces.owner_id",
            ],
        ),
        UniqueConstraint(
            "artifact_id", "workspace_id", "box_id", "owner_id", name="uq_vendor_artifact_scope"
        ),
        digest_check("intent_sha256", "sha256", "content_hash", "source_fingerprint"),
        CheckConstraint(
            "byte_length BETWEEN 5 AND 8388608 AND media_type = 'application/pdf' AND scope_version = 1"
        ),
        CheckConstraint(
            "state IN ('empty','receiving','ready','quarantined') AND version >= 1 AND active_generation >= 0"
        ),
        CheckConstraint("(state = 'empty') = (active_generation = 0)"),
    )
    artifact_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    intent_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_length: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="empty")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VendorArtifactAttempt(WorkspaceScope, Base):
    __tablename__ = "vendor_artifact_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["artifact_id", "workspace_id", "box_id", "owner_id"],
            [
                "vendor_artifacts.artifact_id",
                "vendor_artifacts.workspace_id",
                "vendor_artifacts.box_id",
                "vendor_artifacts.owner_id",
            ],
        ),
        ForeignKeyConstraint(["actor_id", "box_id"], ["principals.id", "principals.box_id"]),
        UniqueConstraint("artifact_id", "generation", name="uq_vendor_artifact_generation"),
        UniqueConstraint(
            "artifact_id", "idempotency_key", "generation", name="uq_vendor_artifact_key_generation"
        ),
        CheckConstraint("generation >= 1 AND actor_id = owner_id AND lease_until > admitted_at"),
        CheckConstraint("state IN ('receiving','ready','failed','unknown')"),
        digest_check("request_sha256"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    artifact_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    actor_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    fence_token: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, default=_uuid)
    admitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="receiving")
    safe_error: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VendorWork(WorkspaceScope, Base):
    __tablename__ = "vendor_work"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ticket_id", "box_id"],
            ["follow_up_sources.ticket_id", "follow_up_sources.box_id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "box_id", "owner_id"],
            [
                "encounter_workspaces.id",
                "encounter_workspaces.box_id",
                "encounter_workspaces.owner_id",
            ],
        ),
        ForeignKeyConstraint(
            ["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]
        ),
        UniqueConstraint(
            "ticket_id",
            "workspace_id",
            "box_id",
            "owner_id",
            "patient_link_id",
            name="uq_vendor_work_scope",
        ),
        UniqueConstraint(
            "origin_operation_id",
            "workspace_id",
            "box_id",
            "owner_id",
            "patient_link_id",
            name="uq_vendor_work_origin_scope",
        ),
    )
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    origin_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    origin_operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    supersedes_operation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VendorWorkRevision(NoteScope, Base):
    __tablename__ = "vendor_work_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ticket_id", "workspace_id", "box_id", "owner_id", "patient_link_id"],
            [
                "vendor_work.ticket_id",
                "vendor_work.workspace_id",
                "vendor_work.box_id",
                "vendor_work.owner_id",
                "vendor_work.patient_link_id",
            ],
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["action_revision_id", "ticket_id", "box_id", "payload_hash"],
            [
                "action_revisions.id",
                "action_revisions.ticket_id",
                "action_revisions.box_id",
                "action_revisions.payload_hash",
            ],
        ),
        note_fk(),
        ForeignKeyConstraint(["note_id"], ["workspace_note_reviews.note_id"]),
        ForeignKeyConstraint(
            ["connection_version_id", "box_id", "owner_id"],
            [
                "vendor_connection_versions.id",
                "vendor_connection_versions.box_id",
                "vendor_connection_versions.owner_id",
            ],
        ),
        ForeignKeyConstraint(
            [
                "correspondence_version_id",
                "connection_version_id",
                "box_id",
                "owner_id",
                "patient_link_id",
            ],
            [
                "vendor_correspondence_versions.id",
                "vendor_correspondence_versions.connection_version_id",
                "vendor_correspondence_versions.box_id",
                "vendor_correspondence_versions.owner_id",
                "vendor_correspondence_versions.patient_link_id",
            ],
        ),
        ForeignKeyConstraint(
            ["artifact_id", "workspace_id", "box_id", "owner_id"],
            [
                "vendor_artifacts.artifact_id",
                "vendor_artifacts.workspace_id",
                "vendor_artifacts.box_id",
                "vendor_artifacts.owner_id",
            ],
        ),
        UniqueConstraint("ticket_id", "revision_number", name="uq_vendor_work_revision"),
        UniqueConstraint("intended_operation_id", name="uq_vendor_intended_operation"),
        UniqueConstraint(
            "intended_operation_id",
            "action_revision_id",
            "ticket_id",
            "box_id",
            name="uq_vendor_operation_revision",
        ),
        UniqueConstraint(
            "intended_operation_id",
            "workspace_id",
            "box_id",
            "owner_id",
            "patient_link_id",
            name="uq_vendor_operation_owner",
        ),
        CheckConstraint("revision_number BETWEEN 1 AND 20 AND source_workspace_revision >= 1"),
        CheckConstraint(
            "action IN ('spruce_secure_message','spruce_fax','spruce_media_upload','srfax_fax','documo_fax')"
        ),
        CheckConstraint(
            "(action = 'spruce_media_upload' AND artifact_id IS NOT NULL AND correspondence_version_id IS NULL AND uploaded_media_operation_id IS NULL) OR (action IN ('srfax_fax','documo_fax') AND artifact_id IS NOT NULL AND correspondence_version_id IS NOT NULL AND uploaded_media_operation_id IS NULL) OR (action = 'spruce_secure_message' AND artifact_id IS NULL AND correspondence_version_id IS NOT NULL) OR (action = 'spruce_fax' AND artifact_id IS NULL AND correspondence_version_id IS NOT NULL AND uploaded_media_operation_id IS NOT NULL)"
        ),
        digest_check(
            "payload_hash",
            "private_command_sha256",
            "source_proof_sha256",
            "request_sha256",
            "review_sha256",
        ),
        json_check("private_command", 65536),
        json_check("source_proof", 1048576),
        json_check("public_proposal", 65536),
        json_check("public_review", 65536),
    )
    action_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    intended_operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    source_workspace_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    connection_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    correspondence_version_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    artifact_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    uploaded_media_operation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    private_command: Mapped[dict] = mapped_column(JSONB, nullable=False)
    private_command_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_proof: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_proof_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    public_proposal: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    public_review: Mapped[dict] = mapped_column(JSONB, nullable=False)
    review_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VendorCommandReceipt(WorkspaceScope, Base):
    __tablename__ = "vendor_command_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "box_id", "owner_id"],
            [
                "encounter_workspaces.id",
                "encounter_workspaces.box_id",
                "encounter_workspaces.owner_id",
            ],
        ),
        ForeignKeyConstraint(["actor_id", "box_id"], ["principals.id", "principals.box_id"]),
        ForeignKeyConstraint(
            ["operation_id", "action_revision_id", "ticket_id", "box_id"],
            [
                "vendor_work_revisions.intended_operation_id",
                "vendor_work_revisions.action_revision_id",
                "vendor_work_revisions.ticket_id",
                "vendor_work_revisions.box_id",
            ],
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "workspace_id", "box_id", "owner_id"],
            [
                "vendor_artifacts.artifact_id",
                "vendor_artifacts.workspace_id",
                "vendor_artifacts.box_id",
                "vendor_artifacts.owner_id",
            ],
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "id", "ticket_id", "action_revision_id", "box_id", name="uq_vendor_receipt_revision"
        ),
        Index(
            "uq_vendor_command_user_key",
            "workspace_id",
            "actor_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("origin = 'user'"),
        ),
        Index(
            "uq_vendor_system_fact",
            "workspace_id",
            "fact_key",
            unique=True,
            postgresql_where=text("origin = 'system'"),
        ),
        Index(
            "uq_vendor_publication",
            "action_revision_id",
            unique=True,
            postgresql_where=text("publication_projection IS NOT NULL"),
        ),
        Index(
            "uq_vendor_verification",
            "action_revision_id",
            "result_receipt_id",
            "evidence_sha256",
            unique=True,
            postgresql_where=text("command_kind = 'verify'"),
        ),
        CheckConstraint(
            "scope_kind IN ('workspace','practice_work') AND origin IN ('user','system') AND effect_version > 0"
        ),
        CheckConstraint(
            "(origin = 'user' AND actor_id IS NOT NULL AND idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$' AND fact_key IS NULL) OR (origin = 'system' AND actor_id IS NULL AND idempotency_key IS NULL AND fact_key IS NOT NULL)"
        ),
        CheckConstraint(
            "(artifact_id IS NULL AND ticket_id IS NOT NULL AND action_revision_id IS NOT NULL AND operation_id IS NOT NULL) OR (artifact_id IS NOT NULL AND ticket_id IS NULL AND action_revision_id IS NULL AND operation_id IS NULL)"
        ),
        CheckConstraint(
            "command_kind IN ('propose','decide','withdraw','publish','submit','reconcile','result','verify','handoff','artifact_intent','artifact_content','reopen')"
        ),
        digest_check("request_sha256", "receipt_sha256"),
        json_check("public_request", 65536),
        json_check("effect", 8192),
        CheckConstraint(
            "publication_projection IS NULL OR (jsonb_typeof(publication_projection) = 'object' AND octet_length(publication_projection::text) <= 16384)"
        ),
        CheckConstraint(
            "result_payload IS NULL OR (jsonb_typeof(result_payload) = 'object' AND octet_length(result_payload::text) <= 16384)"
        ),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    actor_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    command_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    fact_key: Mapped[str | None] = mapped_column(String(200))
    public_request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    action_revision_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    operation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    artifact_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    effect_version: Mapped[int] = mapped_column(Integer, nullable=False)
    effect: Mapped[dict] = mapped_column(JSONB, nullable=False)
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_receipt_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    observation_head_sha256: Mapped[str | None] = mapped_column(String(64))
    evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    publication_projection: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    publication_sha256: Mapped[str | None] = mapped_column(String(64))
    result_payload: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperationScope(WorkspaceScope):
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    ticket_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    action_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)


def operation_fk():
    return ForeignKeyConstraint(
        ["operation_id", "ticket_id", "box_id"],
        ["operations.id", "operations.ticket_id", "operations.box_id"],
    )


def revision_fk():
    return ForeignKeyConstraint(
        ["operation_id", "action_revision_id", "ticket_id", "box_id"],
        [
            "vendor_work_revisions.intended_operation_id",
            "vendor_work_revisions.action_revision_id",
            "vendor_work_revisions.ticket_id",
            "vendor_work_revisions.box_id",
        ],
    )


class VendorSubmitClaim(OperationScope, Base):
    __tablename__ = "vendor_submit_claims"
    __table_args__ = (
        operation_fk(),
        revision_fk(),
        ForeignKeyConstraint(
            ["approval_receipt_id", "ticket_id", "action_revision_id", "box_id"],
            [
                "vendor_command_receipts.id",
                "vendor_command_receipts.ticket_id",
                "vendor_command_receipts.action_revision_id",
                "vendor_command_receipts.box_id",
            ],
        ),
        ForeignKeyConstraint(
            ["command_receipt_id", "ticket_id", "action_revision_id", "box_id"],
            [
                "vendor_command_receipts.id",
                "vendor_command_receipts.ticket_id",
                "vendor_command_receipts.action_revision_id",
                "vendor_command_receipts.box_id",
            ],
        ),
        CheckConstraint("actor_id = owner_id AND deadline > claimed_at"),
        CheckConstraint(
            "dispatch IN ('not_started','invocation_started','proved_not_dispatched','unconfirmed','response_observed')"
        ),
        digest_check("command_sha256", "source_sha256", "selection_sha256", "request_sha256"),
    )
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    actor_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    approval_receipt_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    command_receipt_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    command_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    selection_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    correspondence_sha256: Mapped[str | None] = mapped_column(String(64))
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_token: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, default=_uuid)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dispatch: Mapped[str] = mapped_column(String(32), nullable=False, default="not_started")
    invocation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_error: Mapped[str | None] = mapped_column(String(64))


class VendorReadClaim(OperationScope, Base):
    __tablename__ = "vendor_read_claims"
    __table_args__ = (
        operation_fk(),
        revision_fk(),
        ForeignKeyConstraint(
            ["connection_version_id", "box_id", "owner_id"],
            [
                "vendor_connection_versions.id",
                "vendor_connection_versions.box_id",
                "vendor_connection_versions.owner_id",
            ],
        ),
        ForeignKeyConstraint(
            ["command_receipt_id", "ticket_id", "action_revision_id", "box_id"],
            [
                "vendor_command_receipts.id",
                "vendor_command_receipts.ticket_id",
                "vendor_command_receipts.action_revision_id",
                "vendor_command_receipts.box_id",
            ],
        ),
        UniqueConstraint("operation_id", "actor_id", "idempotency_key", name="uq_vendor_read_key"),
        CheckConstraint(
            "actor_id = owner_id AND deadline > admitted_at AND state IN ('admitted','settled','unknown')"
        ),
        digest_check("reference_sha256", "request_sha256"),
        json_check("private_reference", 8192),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    actor_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    command_receipt_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    connection_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    private_reference: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reference_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_token: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, default=_uuid)
    admitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="admitted")


class VendorEventCandidate(OwnerScope, Base):
    __tablename__ = "vendor_event_candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connection_version_id", "box_id", "owner_id"],
            [
                "vendor_connection_versions.id",
                "vendor_connection_versions.box_id",
                "vendor_connection_versions.owner_id",
            ],
        ),
        UniqueConstraint(
            "connection_version_id",
            "vendor",
            "authenticity",
            "body_sha256",
            name="uq_vendor_event_candidate",
        ),
        CheckConstraint(
            "vendor IN ('spruce','srfax','documo') AND authenticity IN ('signed','untrusted_hint')"
        ),
        CheckConstraint("authenticity <> 'signed' OR vendor = 'spruce'"),
        digest_check("body_sha256"),
        json_check("correlation", 8192),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    route_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    connection_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    vendor: Mapped[str] = mapped_column(String(16), nullable=False)
    authenticity: Mapped[str] = mapped_column(String(16), nullable=False)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VendorProviderObservation(OperationScope, Base):
    __tablename__ = "vendor_provider_observations"
    __table_args__ = (
        operation_fk(),
        revision_fk(),
        ForeignKeyConstraint(
            ["connection_version_id", "box_id", "owner_id"],
            [
                "vendor_connection_versions.id",
                "vendor_connection_versions.box_id",
                "vendor_connection_versions.owner_id",
            ],
        ),
        ForeignKeyConstraint(["submit_claim_id"], ["vendor_submit_claims.operation_id"]),
        ForeignKeyConstraint(["read_claim_id"], ["vendor_read_claims.id"]),
        ForeignKeyConstraint(["event_candidate_id"], ["vendor_event_candidates.id"]),
        UniqueConstraint("operation_id", "sequence", name="uq_vendor_observation_sequence"),
        UniqueConstraint(
            "operation_id",
            "source",
            "source_id",
            "kind",
            "canonical_sha256",
            name="uq_vendor_observation_fact",
        ),
        CheckConstraint(
            "sequence >= 1 AND source IN ('submit','read','event','internal_dispatch') AND kind IN ('submission','transport','dispatch')"
        ),
        CheckConstraint(
            "(source IN ('submit','internal_dispatch') AND submit_claim_id IS NOT NULL AND read_claim_id IS NULL AND event_candidate_id IS NULL AND source_id = submit_claim_id) OR (source = 'read' AND read_claim_id IS NOT NULL AND submit_claim_id IS NULL AND event_candidate_id IS NULL AND source_id = read_claim_id) OR (source = 'event' AND event_candidate_id IS NOT NULL AND submit_claim_id IS NULL AND read_claim_id IS NULL AND source_id = event_candidate_id)"
        ),
        digest_check("canonical_sha256", "public_sha256", "head_sha256"),
        json_check("public_observation", 4096),
        CheckConstraint(
            "private_reference IS NULL OR (jsonb_typeof(private_reference) = 'object' AND octet_length(private_reference::text) <= 8192)"
        ),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    connection_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    submit_claim_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    read_claim_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    event_candidate_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    body_sha256: Mapped[str | None] = mapped_column(String(64))
    canonical_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    private_reference: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    public_observation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    public_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    head_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
