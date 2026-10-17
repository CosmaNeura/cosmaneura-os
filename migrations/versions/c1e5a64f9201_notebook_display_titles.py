"""Append-only notebook display title revisions."""

import sqlalchemy as sa
from alembic import op

revision = "c1e5a64f9201"
down_revision = "bfdb4a6487c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "workspace_title_revisions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("box_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"],
            ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        sa.UniqueConstraint("workspace_id", "version", name="uq_workspace_title_version"),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_workspace_title_key"),
        sa.CheckConstraint("version >= 1 AND char_length(title) BETWEEN 1 AND 160 AND request_hash ~ '^[a-f0-9]{64}$'",
            name="ck_workspace_title_revision"),
    )
    op.execute("CREATE TRIGGER workspace_title_revisions_immutable BEFORE UPDATE OR DELETE ON public.workspace_title_revisions "
        "FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change()")


def downgrade() -> None:
    raise RuntimeError("Disable notebook renaming and retain title history.")
