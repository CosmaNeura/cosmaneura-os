"""provider_team_conversation

Revision ID: aa7c429feb39
Revises: 9a3f3197e5e7
Create Date: 2026-09-16 14:11:00.889762

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "aa7c429feb39"
down_revision = "9a3f3197e5e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_workspace_entry_scope", "workspace_entries", ["id", "workspace_id", "box_id"]
    )
    op.create_table(
        "provider_bots",
        sa.Column("agent_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("box_id", UUID(as_uuid=False), nullable=False),
        sa.Column("owner_id", UUID(as_uuid=False), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["owner_id", "box_id"], ["principals.id", "principals.box_id"]),
        sa.ForeignKeyConstraint(["agent_id", "box_id"], ["principals.id", "principals.box_id"]),
        sa.UniqueConstraint("owner_id", "role", name="uq_provider_bot_role"),
        sa.UniqueConstraint("agent_id", "box_id", "owner_id", name="uq_provider_bot_scope"),
        sa.CheckConstraint(
            "role IN ('scribe', 'visit_prep', 'follow_up', 'chief')", name="ck_provider_bot_role"
        ),
    )
    op.create_table(
        "provider_team_revisions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("box_id", UUID(as_uuid=False), nullable=False),
        sa.Column("owner_id", UUID(as_uuid=False), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("template_version", sa.String(64), nullable=False),
        sa.Column("configuration", JSONB, nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["owner_id", "box_id"], ["principals.id", "principals.box_id"]),
        sa.UniqueConstraint("owner_id", "revision", name="uq_provider_team_revision"),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_provider_team_key"),
        sa.UniqueConstraint("id", "box_id", "owner_id", name="uq_provider_team_scope"),
        sa.CheckConstraint("revision >= 1", name="ck_provider_team_revision"),
    )
    op.create_table(
        "workspace_replies",
        sa.Column("entry_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=False), nullable=False),
        sa.Column("box_id", UUID(as_uuid=False), nullable=False),
        sa.Column("owner_id", UUID(as_uuid=False), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=False), nullable=False),
        sa.Column("team_revision_id", UUID(as_uuid=False), nullable=False),
        sa.Column("agent_name", sa.String(40), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("backend", sa.String(64), nullable=False),
        sa.Column("context_revision", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("citations", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["entry_id", "workspace_id", "box_id"],
            ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "box_id", "owner_id"],
            [
                "encounter_workspaces.id",
                "encounter_workspaces.box_id",
                "encounter_workspaces.owner_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "box_id", "owner_id"],
            ["provider_bots.agent_id", "provider_bots.box_id", "provider_bots.owner_id"],
        ),
        sa.ForeignKeyConstraint(
            ["team_revision_id", "box_id", "owner_id"],
            [
                "provider_team_revisions.id",
                "provider_team_revisions.box_id",
                "provider_team_revisions.owner_id",
            ],
        ),
        sa.CheckConstraint("char_length(content) <= 20000", name="ck_workspace_reply_content"),
    )
    op.execute("""CREATE FUNCTION public.reject_provider_history_change() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN RAISE EXCEPTION 'provider history is immutable'; END; $$""")
    for table in ("provider_bots", "provider_team_revisions", "workspace_replies"):
        # These names are fixed migration constants, never input.
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.reject_provider_history_change()"
        )


def downgrade() -> None:
    raise RuntimeError(
        "Disable WORKSPACE_ENABLED; destructive Provider Team downgrade is not supported"
    )
