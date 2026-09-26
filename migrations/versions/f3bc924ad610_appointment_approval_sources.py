"""Reviewed patient correspondence and private sources for F-8 appointment work."""

from alembic import op

revision = "f3bc924ad610"
down_revision = "e782cd3a51f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE scheduling_patient_accounts (
        id uuid PRIMARY KEY, box_id uuid NOT NULL, patient_link_id uuid NOT NULL,
        practice_id uuid NOT NULL, patient_id uuid NOT NULL,
        reviewed_by varchar(200) NOT NULL, evidence_ref varchar(255) NOT NULL,
        reviewed_at timestamptz NOT NULL, revoked_at timestamptz,
        FOREIGN KEY (patient_link_id, box_id) REFERENCES patient_links(id, box_id),
        CONSTRAINT uq_scheduling_patient_scope UNIQUE (id, box_id, patient_link_id),
        CONSTRAINT ck_scheduling_patient_review CHECK (char_length(reviewed_by) > 0 AND char_length(evidence_ref) > 0)
    )""")
    op.execute("""CREATE UNIQUE INDEX uq_scheduling_patient_active_link
        ON scheduling_patient_accounts (box_id, patient_link_id, practice_id) WHERE revoked_at IS NULL""")
    op.execute("""CREATE UNIQUE INDEX uq_scheduling_patient_active_remote
        ON scheduling_patient_accounts (box_id, practice_id, patient_id) WHERE revoked_at IS NULL""")
    op.execute("""CREATE TRIGGER scheduling_patient_immutable BEFORE UPDATE OR DELETE
        ON scheduling_patient_accounts FOR EACH ROW EXECUTE FUNCTION reject_scheduling_account_change()""")
    op.execute("""CREATE TABLE appointment_work (
        ticket_id uuid PRIMARY KEY, box_id uuid NOT NULL, workspace_id uuid NOT NULL,
        owner_id uuid NOT NULL, patient_link_id uuid NOT NULL,
        account_id uuid NOT NULL REFERENCES scheduling_accounts(id), patient_mapping_id uuid NOT NULL,
        action_revision_id uuid NOT NULL, payload_hash varchar(64) NOT NULL,
        idempotency_key varchar(100) NOT NULL, request_hash varchar(64) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY (ticket_id, box_id) REFERENCES tickets(id, box_id),
        FOREIGN KEY (workspace_id, box_id, owner_id) REFERENCES encounter_workspaces(id, box_id, owner_id),
        FOREIGN KEY (action_revision_id, ticket_id, box_id, payload_hash)
            REFERENCES action_revisions(id, ticket_id, box_id, payload_hash),
        FOREIGN KEY (patient_mapping_id, box_id, patient_link_id)
            REFERENCES scheduling_patient_accounts(id, box_id, patient_link_id),
        CONSTRAINT uq_appointment_work_key UNIQUE (workspace_id, idempotency_key),
        CONSTRAINT ck_appointment_work_key CHECK (char_length(idempotency_key) BETWEEN 1 AND 100)
    )""")
    op.execute("""CREATE TRIGGER appointment_work_immutable BEFORE UPDATE OR DELETE
        ON appointment_work FOR EACH ROW EXECUTE FUNCTION reject_workspace_history_change()""")


def downgrade() -> None:
    raise RuntimeError("Preserve appointment approval history; disable appointment actions instead")
