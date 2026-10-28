"""Immutable calendar observation and exact human selected-summary custody."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base
from cosmas_os.vendor_models import OwnerScope, WorkspaceScope, digest_check, json_check


class GoogleCalendarObservationRequest(OwnerScope, Base):
    __tablename__ = "google_calendar_observation_requests"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "box_id", "owner_id"],
            ["external_identities.id", "external_identities.box_id", "external_identities.principal_id"]),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_google_calendar_observation_scope"),
        UniqueConstraint("account_id", "ordinal", name="uq_google_calendar_observation_ordinal"),
        UniqueConstraint("box_id", "owner_id", "idempotency_key", name="uq_google_calendar_observation_key"),
        CheckConstraint("ordinal>=1 AND char_length(idempotency_key) BETWEEN 8 AND 100", name="ck_google_calendar_observation_key"),
        CheckConstraint("window_end=window_start+interval '168 hours'", name="ck_google_calendar_observation_window"),
        digest_check("request_hash", "binding_digest", "grant_sha256"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    grant_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())


class GoogleCalendarSnapshot(OwnerScope, Base):
    __tablename__ = "google_calendar_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(["observation_id", "box_id", "owner_id"],
            ["google_calendar_observation_requests.id", "google_calendar_observation_requests.box_id", "google_calendar_observation_requests.owner_id"]),
        UniqueConstraint("observation_id", name="uq_google_calendar_snapshot_observation"),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_google_calendar_snapshot_scope"),
        digest_check("payload_sha256", "source_sha256"), json_check("payload", 65536),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    observation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())


class GoogleCalendarSourceReview(WorkspaceScope, Base):
    __tablename__ = "google_calendar_source_reviews"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"],
            ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["entry_id", "workspace_id", "box_id"],
            ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"]),
        ForeignKeyConstraint(["snapshot_id", "box_id", "owner_id"],
            ["google_calendar_snapshots.id", "google_calendar_snapshots.box_id", "google_calendar_snapshots.owner_id"]),
        ForeignKeyConstraint(["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]),
        UniqueConstraint("entry_id", name="uq_google_calendar_review_entry"),
        UniqueConstraint("workspace_id", "snapshot_id", "event_id", name="uq_google_calendar_review_event"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_google_calendar_review_key"),
        CheckConstraint("expected_revision>=1 AND workspace_revision=expected_revision+1", name="ck_google_calendar_review_revision"),
        CheckConstraint("reviewed_visit AND reviewed_exact_summary AND reviewed_untrusted_source", name="ck_google_calendar_review_checks"),
        CheckConstraint("event_id ~ '^[A-Za-z0-9_-]+$' AND char_length(event_id) BETWEEN 1 AND 1024", name="ck_google_calendar_review_event"),
        digest_check("request_hash", "observation_sha256", "event_sha256", "source_sha256", "content_sha256"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    entry_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    workspace_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    event_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_visit: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_exact_summary: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_untrusted_source: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())


class GoogleCalendarPrivateSourceReview(WorkspaceScope, Base):
    __tablename__ = "google_calendar_private_source_reviews"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"],
            ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["entry_id", "workspace_id", "box_id"],
            ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"]),
        ForeignKeyConstraint(["snapshot_id", "box_id", "owner_id"],
            ["google_calendar_snapshots.id", "google_calendar_snapshots.box_id", "google_calendar_snapshots.owner_id"]),
        UniqueConstraint("entry_id", name="uq_google_calendar_private_review_entry"),
        UniqueConstraint("workspace_id", "snapshot_id", "event_id", name="uq_google_calendar_private_review_event"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_google_calendar_private_review_key"),
        CheckConstraint("expected_revision>=1 AND workspace_revision=expected_revision+1", name="ck_google_calendar_private_review_revision"),
        CheckConstraint("reviewed_private_notebook AND reviewed_exact_summary AND reviewed_untrusted_source", name="ck_google_calendar_private_review_checks"),
        CheckConstraint("event_id ~ '^[A-Za-z0-9_-]+$' AND char_length(event_id) BETWEEN 1 AND 1024", name="ck_google_calendar_private_review_event"),
        digest_check("request_hash", "observation_sha256", "event_sha256", "source_sha256", "content_sha256"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    entry_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    workspace_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    event_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_private_notebook: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_exact_summary: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_untrusted_source: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())
