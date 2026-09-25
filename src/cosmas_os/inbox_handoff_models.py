"""Private request receipts subordinate to the existing F8 effects and responsibility."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base
from cosmas_os.vendor_models import OwnerScope, digest_check, json_check


class InboxHandoffReceipt(OwnerScope, Base):
    __tablename__ = "inbox_handoff_receipts"
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
            ["ticket_id", "box_id"], ["follow_up_sources.ticket_id", "follow_up_sources.box_id"]
        ),
        UniqueConstraint(
            "workspace_id", "actor_id", "idempotency_key", name="uq_inbox_handoff_receipt_key"
        ),
        digest_check("request_sha256", "receipt_sha256"),
        json_check("request", 16384),
        json_check("response", 16384),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    actor_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    ticket_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    command_kind: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request: Mapped[dict] = mapped_column(JSONB)
    request_sha256: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    receipt_sha256: Mapped[str] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
