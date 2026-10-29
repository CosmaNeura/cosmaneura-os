"""Human read state for one bot within one private workspace."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base


class ConversationReadMarker(Base):
    __tablename__ = "conversation_read_markers"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"],
            ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["agent_id", "box_id", "owner_id"],
            ["provider_bots.agent_id", "provider_bots.box_id", "provider_bots.owner_id"]),
        CheckConstraint("(seen_at IS NULL) = (seen_id IS NULL)", name="ck_conversation_seen_pair"),
        CheckConstraint("seen_id IS NULL OR seen_id ~ '^[a-z][0-9a-f]{32}$'", name="ck_conversation_seen_id"),
        CheckConstraint("version >= 1", name="ck_conversation_marker_version"),
    )
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    agent_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    box_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    seen_id: Mapped[str | None] = mapped_column(String(33), nullable=True)
    manual_unread: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
