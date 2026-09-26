"""Private schedules and atomic derived F-8 brief history."""

from alembic import op

revision = "189ab72c0fd4"
down_revision = "07c65a2b89df"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE routine_revisions (
        id uuid PRIMARY KEY, agent_id uuid NOT NULL, box_id uuid NOT NULL, owner_id uuid NOT NULL,
        team_revision_id uuid NOT NULL, revision integer NOT NULL, configuration jsonb NOT NULL,
        idempotency_key varchar(100) NOT NULL, request_hash varchar(64) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        FOREIGN KEY (agent_id, box_id, owner_id) REFERENCES provider_bots(agent_id, box_id, owner_id),
        FOREIGN KEY (team_revision_id, box_id, owner_id) REFERENCES provider_team_revisions(id, box_id, owner_id),
        CONSTRAINT uq_routine_revision UNIQUE (agent_id, revision),
        CONSTRAINT uq_routine_key UNIQUE (agent_id, idempotency_key),
        CONSTRAINT uq_routine_scope UNIQUE (id, agent_id, box_id, owner_id),
        CONSTRAINT ck_routine_revision CHECK (revision BETWEEN 1 AND 100),
        CONSTRAINT ck_routine_request_hash CHECK (request_hash ~ '^[0-9a-f]{64}$')
    )""")
    op.execute("""CREATE TABLE routine_runs (
        id uuid PRIMARY KEY, agent_id uuid NOT NULL, box_id uuid NOT NULL, owner_id uuid NOT NULL,
        routine_revision_id uuid NOT NULL, local_date date NOT NULL,
        scheduled_at timestamptz NOT NULL, completed_at timestamptz NOT NULL,
        snapshot jsonb NOT NULL, snapshot_hash varchar(64) NOT NULL,
        FOREIGN KEY (routine_revision_id, agent_id, box_id, owner_id)
            REFERENCES routine_revisions(id, agent_id, box_id, owner_id),
        CONSTRAINT uq_routine_occurrence UNIQUE (agent_id, local_date),
        CONSTRAINT ck_routine_completion CHECK (completed_at >= scheduled_at),
        CONSTRAINT ck_routine_snapshot_hash CHECK (snapshot_hash ~ '^[0-9a-f]{64}$')
    )""")
    op.execute("CREATE INDEX ix_routine_recent_runs ON routine_runs (agent_id, completed_at)")
    for table in ("routine_revisions", "routine_runs"):
        op.execute(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_workspace_history_change()""")


def downgrade() -> None:
    raise RuntimeError("Preserve routine history; pause routines instead")
