"""Bind saved audio's immutable admission intent to one Scribe session."""
import sqlalchemy as sa
from alembic import op

revision = "f97c2d5e3468"
down_revision = "f96b1c4d2357"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("private_recording_transfers",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("recording_id", sa.UUID(), sa.ForeignKey("private_recordings.id"), nullable=False),
        sa.Column("workspace_id", sa.UUID(), sa.ForeignKey("encounter_workspaces.id"), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("request", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("recording_id", name="uq_private_transfer_recording"),
        sa.UniqueConstraint("workspace_id", name="uq_private_transfer_workspace"),
        sa.CheckConstraint("request_sha256 ~ '^[a-f0-9]{64}$'", name="ck_private_transfer_hash"))
    op.create_table("private_recording_transfer_sessions",
        sa.Column("transfer_id", sa.UUID(), sa.ForeignKey("private_recording_transfers.id"), primary_key=True),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("receipt", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("session_id", name="uq_private_transfer_session"))
    for table in ("private_recording_transfers", "private_recording_transfer_sessions"):
        op.execute("CREATE TRIGGER " + table + "_immutable BEFORE UPDATE OR DELETE ON public." + table +
            " FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change()")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM private_recording_transfers)")).scalar():
        raise RuntimeError("Saved recording transfer history cannot be erased")
    op.drop_table("private_recording_transfer_sessions")
    op.drop_table("private_recording_transfers")
