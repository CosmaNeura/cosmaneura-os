"""Private owner notebooks and one-way, retained appointment linking."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "d74e9a2b0135"
down_revision = "h68e0c4f1239"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("encounter_workspaces", "appointment_id", nullable=True)
    op.alter_column("encounter_workspaces", "patient_link_id", nullable=True)
    op.add_column("encounter_workspaces", sa.Column("draft_title", sa.String(160), nullable=True))
    op.add_column("encounter_workspaces", sa.Column("create_request_hash", sa.String(64), nullable=True))
    op.create_check_constraint("ck_workspace_encounter_pair", "encounter_workspaces",
        "(appointment_id IS NULL) = (patient_link_id IS NULL)")
    op.create_check_constraint("ck_workspace_private_draft", "encounter_workspaces",
        "(draft_title IS NULL AND create_request_hash IS NULL AND appointment_id IS NOT NULL) OR "
        "(draft_title IS NOT NULL AND char_length(draft_title) BETWEEN 1 AND 160 "
        "AND create_request_hash IS NOT NULL AND create_request_hash ~ '^[0-9a-f]{64}$')")
    op.create_table("workspace_appointment_links",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=False), nullable=False),
        sa.Column("box_id", UUID(as_uuid=False), nullable=False),
        sa.Column("owner_id", UUID(as_uuid=False), nullable=False),
        sa.Column("appointment_id", UUID(as_uuid=False), nullable=False),
        sa.Column("patient_link_id", UUID(as_uuid=False), nullable=False),
        sa.Column("expected_revision", sa.Integer, nullable=False),
        sa.Column("workspace_revision", sa.Integer, nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("appointment_sha256", sa.String(64), nullable=False),
        sa.Column("draft_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"],
            ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        sa.ForeignKeyConstraint(["appointment_id", "box_id", "patient_link_id"],
            ["appointment_observations.id", "appointment_observations.box_id", "appointment_observations.patient_link_id"]),
        sa.UniqueConstraint("workspace_id", name="uq_workspace_appointment_link"),
        sa.CheckConstraint("expected_revision >= 1 AND workspace_revision = expected_revision + 1", name="ck_workspace_link_revision"),
        sa.CheckConstraint("request_hash ~ '^[0-9a-f]{64}$' AND appointment_sha256 ~ '^[0-9a-f]{64}$' "
            "AND draft_sha256 ~ '^[0-9a-f]{64}$'", name="ck_workspace_link_hashes"))
    op.execute(GUARDS)


def downgrade():
    raise RuntimeError("Retain private drafts, history and human appointment-link receipts")


GUARDS = r"""
CREATE FUNCTION public.guard_private_workspace_link() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE w public.encounter_workspaces;
BEGIN
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 IF w.id IS NULL OR w.box_id <> NEW.box_id OR w.owner_id <> NEW.owner_id
  OR w.draft_title IS NULL OR w.appointment_id IS NOT NULL OR w.patient_link_id IS NOT NULL
  OR w.revision <> NEW.expected_revision THEN RAISE EXCEPTION 'private draft link scope mismatch'; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER workspace_appointment_link_guard BEFORE INSERT ON public.workspace_appointment_links
 FOR EACH ROW EXECUTE FUNCTION public.guard_private_workspace_link();
CREATE TRIGGER workspace_appointment_link_immutable BEFORE UPDATE OR DELETE ON public.workspace_appointment_links
 FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE FUNCTION public.guard_workspace_association() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF (NEW.id,NEW.box_id,NEW.owner_id,NEW.create_key,NEW.draft_title,NEW.create_request_hash,NEW.created_at)
  IS DISTINCT FROM (OLD.id,OLD.box_id,OLD.owner_id,OLD.create_key,OLD.draft_title,OLD.create_request_hash,OLD.created_at)
 THEN RAISE EXCEPTION 'workspace ownership and origin are immutable'; END IF;
 IF (NEW.appointment_id,NEW.patient_link_id) IS DISTINCT FROM (OLD.appointment_id,OLD.patient_link_id) THEN
  IF OLD.appointment_id IS NOT NULL OR OLD.patient_link_id IS NOT NULL OR OLD.draft_title IS NULL
   OR NOT EXISTS(SELECT 1 FROM public.workspace_appointment_links r WHERE r.workspace_id=OLD.id
    AND r.box_id=OLD.box_id AND r.owner_id=OLD.owner_id AND r.appointment_id=NEW.appointment_id
    AND r.patient_link_id=NEW.patient_link_id AND r.expected_revision=OLD.revision
    AND r.workspace_revision=NEW.revision)
  THEN RAISE EXCEPTION 'exact private draft link receipt required'; END IF;
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER workspace_association_guard BEFORE UPDATE ON public.encounter_workspaces
 FOR EACH ROW EXECUTE FUNCTION public.guard_workspace_association();
"""
