"""link exact Core note versions to private review"""

from alembic import op

revision = "e4450ca5d524"
down_revision = "f15ed8f133f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_workspace_note_content", "workspace_notes", type_="check")
    op.create_check_constraint(
        "ck_workspace_note_content", "workspace_notes", "char_length(content) BETWEEN 1 AND 270336"
    )
    op.execute("""CREATE TABLE workspace_core_note_sources (
        note_id uuid PRIMARY KEY, workspace_id uuid NOT NULL, box_id uuid NOT NULL,
        owner_id uuid NOT NULL, content_hash varchar(64) NOT NULL,
        source_fingerprint varchar(64) NOT NULL, session_id uuid NOT NULL,
        scribe_source_id uuid NOT NULL, source_sha256 varchar(64) NOT NULL,
        schema_ref varchar(160) NOT NULL, transcript_ref varchar(160) NOT NULL,
        note_ref varchar(160) NOT NULL, note_sha256 varchar(64) NOT NULL,
        note_type varchar(160) NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY (note_id, workspace_id, box_id, owner_id, content_hash, source_fingerprint)
            REFERENCES workspace_notes(id, workspace_id, box_id, owner_id, content_hash, source_fingerprint),
        CONSTRAINT ck_workspace_core_note_digests CHECK (
            source_sha256 ~ '^[a-f0-9]{64}$' AND note_sha256 ~ '^[a-f0-9]{64}$')
    )""")
    op.execute("""CREATE TRIGGER workspace_core_note_sources_immutable BEFORE UPDATE OR DELETE
        ON public.workspace_core_note_sources FOR EACH ROW
        EXECUTE FUNCTION public.reject_workspace_history_change()""")


def downgrade() -> None:
    raise RuntimeError(
        "Disable WORKSPACE_CAPTURE_NOTES_ENABLED; retain Core source and private review history"
    )
