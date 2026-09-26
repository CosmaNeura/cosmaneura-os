"""Fenced F-8 appointment attempts and immutable result observations."""

from alembic import op

revision = "07c65a2b89df"
down_revision = "f3bc924ad610"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE appointment_executions (
        operation_id uuid PRIMARY KEY, ticket_id uuid NOT NULL, box_id uuid NOT NULL,
        generation integer NOT NULL, mode varchar(16) NOT NULL,
        claim_token uuid, lease_until timestamptz,
        FOREIGN KEY (operation_id, ticket_id, box_id) REFERENCES operations(id, ticket_id, box_id),
        FOREIGN KEY (ticket_id) REFERENCES appointment_work(ticket_id),
        CONSTRAINT ck_appointment_execution_generation CHECK (generation >= 1),
        CONSTRAINT ck_appointment_execution_mode CHECK (mode IN ('submit', 'reconcile')),
        CONSTRAINT ck_appointment_execution_claim CHECK ((claim_token IS NULL) = (lease_until IS NULL))
    )""")
    op.execute("""CREATE TABLE appointment_receipts (
        id uuid PRIMARY KEY, operation_id uuid NOT NULL, ticket_id uuid NOT NULL, box_id uuid NOT NULL,
        request_hash varchar(64) NOT NULL, response_hash varchar(64) NOT NULL, payload jsonb NOT NULL,
        observed_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY (operation_id, ticket_id, box_id) REFERENCES operations(id, ticket_id, box_id),
        FOREIGN KEY (ticket_id) REFERENCES appointment_work(ticket_id),
        CONSTRAINT uq_appointment_receipt_response UNIQUE (operation_id, response_hash),
        CONSTRAINT ck_appointment_receipt_hashes CHECK (request_hash ~ '^[0-9a-f]{64}$' AND response_hash ~ '^[0-9a-f]{64}$')
    )""")
    op.execute("""CREATE INDEX ix_appointment_receipt_latest
        ON appointment_receipts (operation_id, observed_at DESC, created_at DESC)""")
    op.execute("""CREATE TRIGGER appointment_receipt_immutable BEFORE UPDATE OR DELETE
        ON appointment_receipts FOR EACH ROW EXECUTE FUNCTION reject_workspace_history_change()""")


def downgrade() -> None:
    raise RuntimeError("Preserve appointment execution evidence; disable appointment execution instead")
