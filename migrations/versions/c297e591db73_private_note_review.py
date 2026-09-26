"""Private note versions and human review, additive only."""

from alembic import op

revision = "c297e591db73"
down_revision = "b184d870ca62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE workspace_notes (
        id uuid PRIMARY KEY,
        workspace_id uuid NOT NULL, box_id uuid NOT NULL, owner_id uuid NOT NULL,
        version integer NOT NULL, workspace_revision integer NOT NULL,
        parent_id uuid, source_reply_id uuid, source_revision integer NOT NULL,
        source_fingerprint varchar(64) NOT NULL, content text NOT NULL,
        content_hash varchar(64) NOT NULL, idempotency_key varchar(100) NOT NULL,
        request_hash varchar(64) NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY (workspace_id, box_id, owner_id)
            REFERENCES encounter_workspaces(id, box_id, owner_id),
        CONSTRAINT uq_workspace_note_scope UNIQUE (id, workspace_id, box_id),
        CONSTRAINT uq_workspace_note_review_binding
            UNIQUE (id, workspace_id, box_id, owner_id, content_hash, source_fingerprint),
        FOREIGN KEY (parent_id, workspace_id, box_id)
            REFERENCES workspace_notes(id, workspace_id, box_id),
        FOREIGN KEY (source_reply_id, workspace_id, box_id)
            REFERENCES workspace_entries(id, workspace_id, box_id),
        CONSTRAINT uq_workspace_note_version UNIQUE (workspace_id, version),
        CONSTRAINT uq_workspace_note_revision UNIQUE (workspace_id, workspace_revision),
        CONSTRAINT uq_workspace_note_key UNIQUE (workspace_id, idempotency_key),
        CONSTRAINT ck_workspace_note_revisions CHECK
            (version BETWEEN 1 AND 50 AND source_revision >= 1 AND workspace_revision > source_revision),
        CONSTRAINT ck_workspace_note_content CHECK (char_length(content) BETWEEN 1 AND 20000),
        CONSTRAINT ck_workspace_note_parent CHECK
            ((version = 1 AND parent_id IS NULL) OR (version > 1 AND parent_id IS NOT NULL))
    )""")
    op.execute("""CREATE TABLE workspace_note_reviews (
        id uuid PRIMARY KEY,
        workspace_id uuid NOT NULL, box_id uuid NOT NULL, owner_id uuid NOT NULL,
        note_id uuid NOT NULL, workspace_revision integer NOT NULL,
        content_hash varchar(64) NOT NULL, source_fingerprint varchar(64) NOT NULL,
        idempotency_key varchar(100) NOT NULL, request_hash varchar(64) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY (note_id, workspace_id, box_id, owner_id, content_hash, source_fingerprint)
            REFERENCES workspace_notes(id, workspace_id, box_id, owner_id, content_hash, source_fingerprint),
        CONSTRAINT uq_workspace_note_review UNIQUE (note_id),
        CONSTRAINT uq_workspace_note_review_revision UNIQUE (workspace_id, workspace_revision),
        CONSTRAINT uq_workspace_note_review_key UNIQUE (workspace_id, idempotency_key),
        CONSTRAINT ck_workspace_note_review_revision CHECK (workspace_revision >= 2)
    )""")
    for table in ("workspace_notes", "workspace_note_reviews"):
        op.execute(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE
            ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change()""")


def downgrade() -> None:
    raise RuntimeError(
        "Disable WORKSPACE_ENABLED; private note history cannot be downgraded destructively"
    )
