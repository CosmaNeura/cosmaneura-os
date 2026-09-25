"""Private draft handoffs and bounded attempts.

Revision ID: b184d870ca62
Revises: aa7c429feb39
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "b184d870ca62"
down_revision = "aa7c429feb39"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_workspace_entry_kind", "workspace_entries", type_="check")
    op.create_check_constraint(
        "ck_workspace_entry_kind",
        "workspace_entries",
        "kind IN ('synthetic_source', 'scratchpad', 'conversation', 'evidence', 'work_link', 'handoff_result')",
    )
    op.create_table(
        "workspace_handoffs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=False), nullable=False),
        sa.Column("box_id", UUID(as_uuid=False), nullable=False),
        sa.Column("owner_id", UUID(as_uuid=False), nullable=False),
        sa.Column("origin_entry_id", UUID(as_uuid=False), nullable=False),
        sa.Column("issuer_agent_id", UUID(as_uuid=False), nullable=False),
        sa.Column("recipient_agent_id", UUID(as_uuid=False), nullable=False),
        sa.Column("recipient_role", sa.String(32), nullable=False),
        sa.Column("recipient_name", sa.String(40), nullable=False),
        sa.Column("team_revision_id", UUID(as_uuid=False), nullable=False),
        sa.Column("context_revision", sa.Integer, nullable=False),
        sa.Column("brief", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["origin_entry_id", "workspace_id", "box_id"],
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
            ["issuer_agent_id", "box_id", "owner_id"],
            ["provider_bots.agent_id", "provider_bots.box_id", "provider_bots.owner_id"],
        ),
        sa.ForeignKeyConstraint(
            ["recipient_agent_id", "box_id", "owner_id"],
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
        sa.UniqueConstraint("origin_entry_id", "recipient_role", name="uq_handoff_origin_role"),
        sa.UniqueConstraint("id", "workspace_id", "box_id", "owner_id", name="uq_handoff_scope"),
        sa.CheckConstraint(
            "recipient_role IN ('scribe', 'visit_prep', 'follow_up')", name="ck_handoff_role"
        ),
        sa.CheckConstraint(
            "char_length(brief) BETWEEN 1 AND 4000 AND context_revision >= 1",
            name="ck_handoff_brief",
        ),
    )
    op.create_table(
        "workspace_handoff_attempts",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("handoff_id", UUID(as_uuid=False), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=False), nullable=False),
        sa.Column("box_id", UUID(as_uuid=False), nullable=False),
        sa.Column("owner_id", UUID(as_uuid=False), nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result_entry_id", UUID(as_uuid=False), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["handoff_id", "workspace_id", "box_id", "owner_id"],
            [
                "workspace_handoffs.id",
                "workspace_handoffs.workspace_id",
                "workspace_handoffs.box_id",
                "workspace_handoffs.owner_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["result_entry_id", "workspace_id", "box_id"],
            ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"],
        ),
        sa.UniqueConstraint("handoff_id", "number", name="uq_handoff_attempt_number"),
        sa.UniqueConstraint("handoff_id", "idempotency_key", name="uq_handoff_attempt_key"),
        sa.UniqueConstraint("result_entry_id", name="uq_handoff_result"),
        sa.CheckConstraint("number BETWEEN 1 AND 3", name="ck_handoff_attempt_number"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'interrupted')",
            name="ck_handoff_attempt_status",
        ),
        sa.CheckConstraint(
            "(status = 'completed') = (result_entry_id IS NOT NULL)",
            name="ck_handoff_attempt_result",
        ),
        sa.CheckConstraint(
            "(status IN ('failed', 'interrupted')) = (error_code IS NOT NULL)",
            name="ck_handoff_attempt_error",
        ),
        sa.CheckConstraint(
            "(status = 'queued') = (started_at IS NULL) AND (status IN ('queued', 'running')) = (completed_at IS NULL)",
            name="ck_handoff_attempt_times",
        ),
    )
    op.create_index(
        "ix_workspace_handoff_attempts_status", "workspace_handoff_attempts", ["status"]
    )
    op.execute("""CREATE TRIGGER workspace_handoffs_immutable BEFORE UPDATE OR DELETE
        ON public.workspace_handoffs FOR EACH ROW EXECUTE FUNCTION public.reject_provider_history_change()""")
    op.execute("""CREATE FUNCTION public.guard_workspace_handoff_attempt() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'handoff attempts are retained'; END IF;
            IF OLD.status = 'queued' AND NEW.status = 'running' AND
                (to_jsonb(OLD) - ARRAY['status', 'started_at']) = (to_jsonb(NEW) - ARRAY['status', 'started_at']) THEN RETURN NEW; END IF;
            IF OLD.status = 'running' AND NEW.status IN ('completed', 'failed', 'interrupted') AND
                (to_jsonb(OLD) - ARRAY['status', 'completed_at', 'error_code', 'result_entry_id']) =
                (to_jsonb(NEW) - ARRAY['status', 'completed_at', 'error_code', 'result_entry_id']) THEN RETURN NEW; END IF;
            RAISE EXCEPTION 'invalid handoff attempt transition';
        END; $$""")
    op.execute("""CREATE TRIGGER workspace_handoff_attempts_lifecycle BEFORE UPDATE OR DELETE
        ON public.workspace_handoff_attempts FOR EACH ROW EXECUTE FUNCTION public.guard_workspace_handoff_attempt()""")


def downgrade():
    raise RuntimeError(
        "Disable WORKSPACE_ENABLED; destructive private handoff downgrade is not supported"
    )
