"""Preserve exact human responsibility offers on delivered F-8 work."""

from alembic import op

revision = "e782cd3a51f0"
down_revision = "d60e13a92c4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE work_handoffs (
        id uuid PRIMARY KEY, ticket_id uuid NOT NULL, box_id uuid NOT NULL,
        action_revision_id uuid NOT NULL, payload_hash varchar(64) NOT NULL,
        sequence integer NOT NULL, expected_version integer NOT NULL,
        kind varchar(16) NOT NULL, actor_id uuid NOT NULL, from_id uuid NOT NULL,
        to_id uuid NOT NULL, offer_id uuid,
        idempotency_key varchar(100) NOT NULL, request_hash varchar(64) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY (ticket_id, box_id) REFERENCES follow_up_sources(ticket_id, box_id),
        FOREIGN KEY (action_revision_id, ticket_id, box_id, payload_hash)
            REFERENCES action_revisions(id, ticket_id, box_id, payload_hash),
        FOREIGN KEY (actor_id, box_id) REFERENCES principals(id, box_id),
        FOREIGN KEY (from_id, box_id) REFERENCES principals(id, box_id),
        FOREIGN KEY (to_id, box_id) REFERENCES principals(id, box_id),
        CONSTRAINT uq_work_handoff_scope UNIQUE (id, ticket_id, box_id),
        FOREIGN KEY (offer_id, ticket_id, box_id) REFERENCES work_handoffs(id, ticket_id, box_id),
        CONSTRAINT uq_work_handoff_sequence UNIQUE (ticket_id, sequence),
        CONSTRAINT uq_work_handoff_key UNIQUE (ticket_id, actor_id, idempotency_key),
        CONSTRAINT ck_work_handoff_kind CHECK (kind IN ('offer','accept','decline','recall','reclaim')),
        CONSTRAINT ck_work_handoff_version CHECK (sequence BETWEEN 1 AND 201 AND expected_version > 0),
        CONSTRAINT ck_work_handoff_people CHECK (from_id <> to_id),
        CONSTRAINT ck_work_handoff_offer CHECK ((kind IN ('accept','decline','recall')) = (offer_id IS NOT NULL)),
        CONSTRAINT ck_work_handoff_actor CHECK (
            (kind IN ('offer','recall') AND actor_id = from_id) OR
            (kind IN ('accept','decline','reclaim') AND actor_id = to_id))
    )""")
    op.execute("""CREATE TRIGGER work_handoffs_immutable BEFORE UPDATE OR DELETE
        ON public.work_handoffs FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change()""")


def downgrade() -> None:
    raise RuntimeError("Preserve responsibility history; disable the shared-work surface instead")
