"""Associate saved recordings with existing visits without moving their origin."""
import sqlalchemy as sa
from alembic import op

revision = "f98d3e6f4579"
down_revision = "f97c2d5e3468"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("private_recording_visit_bindings",
        sa.Column("id", sa.UUID(), primary_key=True),
        *[sa.Column(name, sa.UUID(), nullable=False) for name in (
            "recording_id", "origin_workspace_id", "target_workspace_id", "box_id", "owner_id",
            "appointment_id", "patient_link_id", "finish_id", "request_key")],
        sa.Column("target_revision", sa.Integer(), nullable=False),
        *[sa.Column(name, sa.String(64), nullable=False) for name in (
            "request_sha256", "source_sha256", "appointment_sha256")],
        sa.Column("request", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["recording_id", "origin_workspace_id", "box_id", "owner_id"],
            ["private_recordings.id", "private_recordings.workspace_id", "private_recordings.box_id", "private_recordings.owner_id"]),
        sa.ForeignKeyConstraint(["target_workspace_id", "box_id", "owner_id"],
            ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        sa.ForeignKeyConstraint(["appointment_id", "box_id", "patient_link_id"],
            ["appointment_observations.id", "appointment_observations.box_id", "appointment_observations.patient_link_id"]),
        sa.ForeignKeyConstraint(["finish_id", "recording_id"],
            ["private_recording_finishes.id", "private_recording_finishes.recording_id"]),
        sa.UniqueConstraint("recording_id", name="uq_private_recording_visit_binding"),
        sa.CheckConstraint("target_revision >= 1 AND request_sha256 ~ '^[a-f0-9]{64}$' "
            "AND source_sha256 ~ '^[a-f0-9]{64}$' AND appointment_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_private_recording_visit_binding_hash"))
    op.execute("CREATE TRIGGER private_recording_visit_bindings_immutable BEFORE UPDATE OR DELETE "
        "ON public.private_recording_visit_bindings FOR EACH ROW "
        "EXECUTE FUNCTION public.reject_workspace_history_change()")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM private_recording_visit_bindings)")).scalar():
        raise RuntimeError("Recording visit association history cannot be erased")
    op.drop_table("private_recording_visit_bindings")
