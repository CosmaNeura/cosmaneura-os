"""Retained first-owner reservation and practice setup; no existing owner changes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e85f0a3c1246"
down_revision = "d74e9a2b0135"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("practice_owner_reservations",
        sa.Column("box_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("box_contexts.id"), primary_key=True),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("organization_id", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("reviewed_by", sa.String(200), nullable=False),
        sa.Column("evidence_ref", sa.String(255), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("issuer", "subject", name="uq_practice_owner_reservation_subject"))
    op.create_table("practice_setup_profiles",
        sa.Column("box_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("box_contexts.id"), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("owner_display_name", sa.String(120), nullable=False),
        sa.Column("specialty", sa.String(120), nullable=True),
        sa.Column("request_key", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_id", "box_id"], ["principals.id", "principals.box_id"]))
    op.execute("""CREATE FUNCTION public.guard_practice_owner_reservation() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN
      IF (NEW.box_id,NEW.issuer,NEW.organization_id,NEW.subject,NEW.reviewed_by,NEW.evidence_ref,
          NEW.manifest_sha256,NEW.expires_at,NEW.created_at)
        IS DISTINCT FROM (OLD.box_id,OLD.issuer,OLD.organization_id,OLD.subject,OLD.reviewed_by,OLD.evidence_ref,
          OLD.manifest_sha256,OLD.expires_at,OLD.created_at)
        OR OLD.consumed_at IS NOT NULL OR NEW.consumed_at IS NULL
      THEN RAISE EXCEPTION 'owner reservation is immutable except one consumption'; END IF;
      RETURN NEW; END; $$;
      CREATE TRIGGER practice_owner_reservation_consume BEFORE UPDATE ON public.practice_owner_reservations
        FOR EACH ROW EXECUTE FUNCTION public.guard_practice_owner_reservation();
      CREATE TRIGGER practice_owner_reservation_no_delete BEFORE DELETE ON public.practice_owner_reservations
        FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
      CREATE TRIGGER practice_setup_profile_immutable BEFORE UPDATE OR DELETE ON public.practice_setup_profiles
        FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
    """)


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM practice_setup_profiles) OR EXISTS (SELECT 1 FROM practice_owner_reservations)")).scalar():
        raise RuntimeError("Retained practice setup and owner reservation history cannot be erased.")
    op.drop_table("practice_setup_profiles")
    op.drop_table("practice_owner_reservations")
    op.execute("DROP FUNCTION public.guard_practice_owner_reservation()")
