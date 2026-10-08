"""Immutable owner-scoped device recording metadata and link receipts."""
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base


class PrivateRecording(Base):
    __tablename__ = "private_recordings"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"],
            ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["agent_id", "box_id", "owner_id"],
            ["provider_bots.agent_id", "provider_bots.box_id", "provider_bots.owner_id"]),
        ForeignKeyConstraint(["team_revision_id", "box_id", "owner_id"],
            ["provider_team_revisions.id", "provider_team_revisions.box_id", "provider_team_revisions.owner_id"]),
        UniqueConstraint("owner_id", "request_key", name="uq_private_recording_key"),
        UniqueConstraint("owner_id", "local_recording_id", name="uq_private_recording_local"),
        UniqueConstraint("id", "workspace_id", "box_id", "owner_id", name="uq_private_recording_scope"),
        CheckConstraint("workspace_revision >= 1 AND request_sha256 ~ '^[a-f0-9]{64}$' "
            "AND recovery_scope ~ '^[a-f0-9]{64}$'", name="ck_private_recording_binding"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    external_identity_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("external_identities.id"))
    agent_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    team_revision_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    workspace_revision: Mapped[int] = mapped_column(Integer)
    local_recording_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    request_key: Mapped[str] = mapped_column(UUID(as_uuid=False))
    request_sha256: Mapped[str] = mapped_column(String(64))
    recovery_scope: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PrivateRecordingFinish(Base):
    __tablename__ = "private_recording_finishes"
    __table_args__ = (
        UniqueConstraint("recording_id", name="uq_private_recording_finish"),
        UniqueConstraint("id", "recording_id", name="uq_private_recording_finish_scope"),
        CheckConstraint("request_sha256 ~ '^[a-f0-9]{64}$'", name="ck_private_recording_finish_hash"),
        CheckConstraint("((capture_state = 'unknown' AND manifest_sha256 IS NULL AND chunks IS NULL "
            "AND frames IS NULL AND ended_at IS NULL) OR (capture_state IN ('finished','interrupted') "
            "AND manifest_sha256 IS NOT NULL AND manifest_sha256 ~ '^[a-f0-9]{64}$' "
            "AND chunks BETWEEN 1 AND 1000 AND frames BETWEEN 1 AND 115200000 "
            "AND ended_at IS NOT NULL)) IS TRUE", name="ck_private_recording_finish_outcome"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    recording_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("private_recordings.id"))
    request_key: Mapped[str] = mapped_column(UUID(as_uuid=False))
    request_sha256: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSONB)
    capture_state: Mapped[str] = mapped_column(String(16))
    manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frames: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PrivateRecordingLink(Base):
    __tablename__ = "private_recording_links"
    __table_args__ = (
        ForeignKeyConstraint(["finish_id", "recording_id"],
            ["private_recording_finishes.id", "private_recording_finishes.recording_id"]),
        UniqueConstraint("recording_id", name="uq_private_recording_link"),
        CheckConstraint("request_sha256 ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$'",
                        name="ck_private_recording_link_hash"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    recording_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("private_recordings.id"))
    finish_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    workspace_link_receipt_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("workspace_appointment_links.id"))
    request_key: Mapped[str] = mapped_column(UUID(as_uuid=False))
    request_sha256: Mapped[str] = mapped_column(String(64))
    source_sha256: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
