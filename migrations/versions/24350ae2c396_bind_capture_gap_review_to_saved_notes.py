"""bind_capture_gap_review_to_saved_notes"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "24350ae2c396"
down_revision = "e4450ca5d524"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '60s'")
    # Generated from the two affected models against the synthetic OS database.
    op.add_column(
        "workspace_core_note_sources",
        sa.Column(
            "capture_gap_review",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_workspace_core_gap_review",
        "workspace_core_note_sources",
        "capture_gap_review IS NULL OR COALESCE((jsonb_typeof(capture_gap_review) = 'object' AND capture_gap_review->>'recovery_sha256' ~ '^[a-f0-9]{64}$' AND capture_gap_review->'review_required' = 'true'::jsonb AND jsonb_typeof(capture_gap_review->'observations') = 'array' AND jsonb_array_length(capture_gap_review->'observations') BETWEEN 1 AND 1000 AND octet_length(capture_gap_review::text) <= 786432), false)",
    )
    op.add_column(
        "workspace_note_reviews",
        sa.Column("capture_gap_review_sha256", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_workspace_note_gap_acknowledgment",
        "workspace_note_reviews",
        "capture_gap_review_sha256 IS NULL OR capture_gap_review_sha256 ~ '^[a-f0-9]{64}$'",
    )
    # ### end Alembic commands ###
    op.execute("""CREATE FUNCTION enforce_workspace_gap_acknowledgment() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
        DECLARE evidence jsonb;
        BEGIN
            PERFORM id FROM public.workspace_notes WHERE id=NEW.note_id FOR UPDATE;
            SELECT capture_gap_review INTO evidence FROM public.workspace_core_note_sources
                WHERE note_id=NEW.note_id;
            IF NEW.capture_gap_review_sha256 IS DISTINCT FROM evidence->>'recovery_sha256' THEN
                RAISE EXCEPTION 'exact capture gap acknowledgment required';
            END IF;
            RETURN NEW;
        END $$""")
    op.execute("""CREATE TRIGGER workspace_gap_acknowledgment_insert
        BEFORE INSERT ON workspace_note_reviews
        FOR EACH ROW EXECUTE FUNCTION enforce_workspace_gap_acknowledgment()""")
    op.execute("""CREATE FUNCTION enforce_workspace_core_source_before_review() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$ BEGIN
            PERFORM id FROM public.workspace_notes WHERE id=NEW.note_id FOR UPDATE;
            IF EXISTS (SELECT 1 FROM public.workspace_note_reviews WHERE note_id=NEW.note_id) THEN
                RAISE EXCEPTION 'reviewed note source cannot change';
            END IF;
            RETURN NEW;
        END $$""")
    op.execute("""CREATE TRIGGER workspace_core_source_before_review
        BEFORE INSERT ON workspace_core_note_sources
        FOR EACH ROW EXECUTE FUNCTION enforce_workspace_core_source_before_review()""")


def downgrade() -> None:
    raise RuntimeError("Disable qualified capture sources; retain gap review history")
