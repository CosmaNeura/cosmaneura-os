"""Bind reviewed private notes to F-8 work; retain exact local outcome evidence."""

from alembic import op

revision = "d318fa49b762"
down_revision = "c297e591db73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_ticket_scope", "tickets", ["id", "box_id"])
    op.create_unique_constraint("uq_action_binding", "action_revisions", ["id", "ticket_id", "box_id", "payload_hash"])
    op.create_unique_constraint("uq_operation_scope", "operations", ["id", "ticket_id", "box_id"])
    op.execute("""CREATE TABLE follow_up_sources (
        ticket_id uuid PRIMARY KEY, box_id uuid NOT NULL, workspace_id uuid NOT NULL,
        owner_id uuid NOT NULL, note_id uuid NOT NULL,
        content_hash varchar(64) NOT NULL, source_fingerprint varchar(64) NOT NULL,
        action_revision_id uuid NOT NULL UNIQUE, payload_hash varchar(64) NOT NULL,
        workspace_revision integer NOT NULL, idempotency_key varchar(100) NOT NULL,
        request_hash varchar(64) NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY (ticket_id, box_id) REFERENCES tickets(id, box_id),
        FOREIGN KEY (action_revision_id, ticket_id, box_id, payload_hash)
            REFERENCES action_revisions(id, ticket_id, box_id, payload_hash),
        FOREIGN KEY (note_id, workspace_id, box_id, owner_id, content_hash, source_fingerprint)
            REFERENCES workspace_notes(id, workspace_id, box_id, owner_id, content_hash, source_fingerprint),
        FOREIGN KEY (note_id) REFERENCES workspace_note_reviews(note_id),
        CONSTRAINT uq_follow_up_scope UNIQUE (ticket_id, box_id),
        CONSTRAINT uq_follow_up_key UNIQUE (workspace_id, idempotency_key),
        CONSTRAINT uq_follow_up_revision UNIQUE (workspace_id, workspace_revision)
    )""")
    op.execute("""CREATE TABLE follow_up_receipts (
        id uuid PRIMARY KEY, ticket_id uuid NOT NULL, box_id uuid NOT NULL,
        operation_id uuid NOT NULL, actor_id uuid NOT NULL, kind varchar(32) NOT NULL,
        content text NOT NULL, request_hash varchar(64) NOT NULL,
        idempotency_key varchar(100) NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY (ticket_id, box_id) REFERENCES follow_up_sources(ticket_id, box_id),
        FOREIGN KEY (operation_id, ticket_id, box_id) REFERENCES operations(id, ticket_id, box_id),
        FOREIGN KEY (actor_id, box_id) REFERENCES principals(id, box_id),
        CONSTRAINT uq_follow_up_receipt_kind UNIQUE (ticket_id, kind),
        CONSTRAINT ck_follow_up_receipt_kind CHECK (kind IN ('local_delivery', 'human_completion')),
        CONSTRAINT ck_follow_up_receipt_content CHECK (char_length(content) BETWEEN 1 AND 2000)
    )""")
    for table in ("follow_up_sources", "follow_up_receipts"):
        op.execute(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE
            ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change()""")
    op.execute("""CREATE FUNCTION reject_bound_follow_up_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF EXISTS (SELECT 1 FROM public.follow_up_sources WHERE action_revision_id = OLD.id) THEN
            RAISE EXCEPTION 'bound follow-up action is immutable';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END; $$""")
    op.execute("""CREATE TRIGGER bound_follow_up_action_immutable BEFORE UPDATE OR DELETE
        ON public.action_revisions FOR EACH ROW EXECUTE FUNCTION reject_bound_follow_up_change()""")


def downgrade() -> None:
    raise RuntimeError("Disable WORKSPACE_ENABLED; follow-up history cannot be downgraded destructively")
