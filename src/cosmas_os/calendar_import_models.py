"""Immutable calendar-file projection custody; raw file bytes are never retained."""

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
from cosmas_os.vendor_models import WorkspaceScope, digest_check, json_check


def _uuid():
    return str(uuid4())


def _workspace_fk():
    return ForeignKeyConstraint(
        ["workspace_id", "box_id", "owner_id"],
        ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"],
    )


def _import_fk():
    return ForeignKeyConstraint(
        ["import_id", "workspace_id", "box_id", "owner_id"],
        [
            "calendar_import_requests.id",
            "calendar_import_requests.workspace_id",
            "calendar_import_requests.box_id",
            "calendar_import_requests.owner_id",
        ],
    )


class CalendarImportRequest(WorkspaceScope, Base):
    __tablename__ = "calendar_import_requests"
    __table_args__ = (
        _workspace_fk(),
        ForeignKeyConstraint(
            ["account_id", "box_id", "owner_id"],
            [
                "external_identities.id",
                "external_identities.box_id",
                "external_identities.principal_id",
            ],
        ),
        ForeignKeyConstraint(
            ["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]
        ),
        UniqueConstraint(
            "id", "workspace_id", "box_id", "owner_id", name="uq_calendar_import_scope"
        ),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_calendar_import_key"),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'", name="ck_calendar_import_key"
        ),
        CheckConstraint(
            "reported_source IN ('atlas_md','other_calendar')", name="ck_calendar_import_reported"
        ),
        CheckConstraint(
            "window_end=window_start+7 AND window_start>=date '1900-01-01' AND window_end<date '2101-01-01'",
            name="ck_calendar_import_window",
        ),
        CheckConstraint(
            "char_length(timezone) BETWEEN 1 AND 128", name="ck_calendar_import_timezone"
        ),
        digest_check("request_hash", "byte_sha256"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reported_source: Mapped[str] = mapped_column(String(20), nullable=False)
    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    window_end: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class CalendarImportSnapshot(WorkspaceScope, Base):
    __tablename__ = "calendar_import_snapshots"
    __table_args__ = (
        _workspace_fk(),
        _import_fk(),
        UniqueConstraint(
            "id", "workspace_id", "box_id", "owner_id", name="uq_calendar_snapshot_scope"
        ),
        UniqueConstraint("import_id", name="uq_calendar_snapshot_import"),
        digest_check("payload_sha256", "source_sha256"),
        json_check("payload", 65536),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    import_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class CalendarImportSourceReview(WorkspaceScope, Base):
    __tablename__ = "calendar_import_source_reviews"
    __table_args__ = (
        _workspace_fk(),
        ForeignKeyConstraint(
            ["entry_id", "workspace_id", "box_id"],
            ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"],
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "workspace_id", "box_id", "owner_id"],
            [
                "calendar_import_snapshots.id",
                "calendar_import_snapshots.workspace_id",
                "calendar_import_snapshots.box_id",
                "calendar_import_snapshots.owner_id",
            ],
        ),
        ForeignKeyConstraint(
            ["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]
        ),
        UniqueConstraint("entry_id", name="uq_calendar_source_entry"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_calendar_source_key"),
        UniqueConstraint(
            "workspace_id", "snapshot_id", "item_index", name="uq_calendar_source_item"
        ),
        CheckConstraint(
            "expected_revision>=1 AND workspace_revision=expected_revision+1",
            name="ck_calendar_source_revision",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$' AND item_index BETWEEN 0 AND 499",
            name="ck_calendar_source_key",
        ),
        CheckConstraint(
            "reviewed_visit AND reviewed_exact_summary AND reviewed_untrusted_source",
            name="ck_calendar_source_review",
        ),
        digest_check(
            "request_hash", "import_sha256", "item_sha256", "source_sha256", "content_sha256"
        ),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    entry_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    workspace_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    import_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    item_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_visit: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_exact_summary: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_untrusted_source: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class CalendarImportRevocation(WorkspaceScope, Base):
    __tablename__ = "calendar_import_revocations"
    __table_args__ = (
        _workspace_fk(),
        _import_fk(),
        UniqueConstraint("import_id", name="uq_calendar_revoke_import"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_calendar_revoke_key"),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$' AND expected_revision>=1",
            name="ck_calendar_revoke_revision",
        ),
        digest_check("request_hash", "import_sha256"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    import_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    import_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
