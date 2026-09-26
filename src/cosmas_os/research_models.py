"""Private public-source lookup receipts; clinical material remains in its existing store."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base
from cosmas_os.models import _uuid


class ResearchRun(Base):
    __tablename__ = "research_runs"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"],
                             ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["agent_id", "box_id", "owner_id"],
                             ["provider_bots.agent_id", "provider_bots.box_id", "provider_bots.owner_id"]),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_research_run_key"),
        UniqueConstraint("id", "workspace_id", name="uq_research_run_workspace"),
        CheckConstraint("state IN ('running','completed','partial','unavailable')", name="ck_research_state"),
        CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'", name="ck_research_request_hash"),
        CheckConstraint("jsonb_typeof(request)='object' AND octet_length(request::text)<=8192", name="ck_research_request"),
        CheckConstraint("jsonb_typeof(results)='array' AND jsonb_array_length(results)<=15 AND octet_length(results::text)<=131072", name="ck_research_results"),
        CheckConstraint("jsonb_typeof(errors)='array' AND jsonb_array_length(errors)<=3", name="ck_research_errors"),
        CheckConstraint("(state='running')=(finished_at IS NULL)", name="ck_research_finish"),
        Index("ix_research_recent", "workspace_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    agent_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    request_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20), default="running")
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResearchSave(Base):
    __tablename__ = "research_saves"
    __table_args__ = (
        ForeignKeyConstraint(["run_id", "workspace_id"], ["research_runs.id", "research_runs.workspace_id"]),
        ForeignKeyConstraint(["entry_id", "workspace_id", "box_id"],
                             ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"]),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_research_save_key"),
        CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'", name="ck_research_save_hash"),
        CheckConstraint("jsonb_typeof(request)='object' AND octet_length(request::text)<=8192", name="ck_research_save_request"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    entry_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    request_sha256: Mapped[str] = mapped_column(String(64))
