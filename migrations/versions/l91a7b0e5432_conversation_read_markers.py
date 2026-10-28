"""Add private per-bot conversation read state and an arrival-time reply clock."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "l91a7b0e5432"
down_revision = "k80e6a9d4321"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("conversation_read_markers",
        sa.Column("workspace_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("agent_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("box_id", UUID(as_uuid=False), nullable=False),
        sa.Column("owner_id", UUID(as_uuid=False), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.Column("seen_at", sa.DateTime(timezone=True)),
        sa.Column("seen_id", sa.String(33)),
        sa.Column("manual_unread", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"], ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        sa.ForeignKeyConstraint(["agent_id", "box_id", "owner_id"], ["provider_bots.agent_id", "provider_bots.box_id", "provider_bots.owner_id"]),
        sa.CheckConstraint("(seen_at IS NULL) = (seen_id IS NULL)", name="ck_conversation_seen_pair"),
        sa.CheckConstraint("seen_id IS NULL OR seen_id ~ '^[a-z][0-9a-f]{32}$'", name="ck_conversation_seen_id"),
        sa.CheckConstraint("version >= 1", name="ck_conversation_marker_version"))
    op.execute("""
    CREATE FUNCTION guard_conversation_read_marker() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM principals WHERE id=NEW.owner_id AND box_id=NEW.box_id
          AND principal_type='human' AND state='active' AND tombstoned_at IS NULL) THEN
        RAISE EXCEPTION 'conversation reader must be an active human';
      END IF;
      IF TG_OP='UPDATE' AND (
          (NEW.workspace_id,NEW.agent_id,NEW.box_id,NEW.owner_id,NEW.opened_at)
            IS DISTINCT FROM (OLD.workspace_id,OLD.agent_id,OLD.box_id,OLD.owner_id,OLD.opened_at)
          OR NEW.version < OLD.version
          OR OLD.seen_at IS NOT NULL AND (NEW.seen_at IS NULL OR (NEW.seen_at,NEW.seen_id)<(OLD.seen_at,OLD.seen_id))) THEN
        RAISE EXCEPTION 'conversation read watermark cannot move backwards';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER conversation_read_marker_guard BEFORE INSERT OR UPDATE ON conversation_read_markers
      FOR EACH ROW EXECUTE FUNCTION guard_conversation_read_marker();
    """)
    # now() is transaction start, which can precede a slow model reply.
    op.alter_column("workspace_replies", "created_at", server_default=sa.text("clock_timestamp()"))


def downgrade():
    raise RuntimeError("Retain human read watermarks and reply arrival timestamps")
