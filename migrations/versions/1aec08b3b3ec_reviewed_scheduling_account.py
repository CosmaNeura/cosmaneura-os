"""reviewed_scheduling_account"""

import sqlalchemy as sa
from alembic import op

revision = '1aec08b3b3ec'
down_revision = 'a5b3bab89f19'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "scheduling_accounts",
        sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
        sa.Column("external_identity_id", sa.UUID(as_uuid=False), sa.ForeignKey("external_identities.id"), nullable=False),
        *(sa.Column(name, sa.UUID(as_uuid=False), nullable=False) for name in
          ("practice_id", "actor_id", "practitioner_id", "location_id", "appointment_type_id")),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("reviewed_by", sa.String(200), nullable=False),
        sa.Column("evidence_ref", sa.String(255), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("char_length(reviewed_by) > 0 AND char_length(evidence_ref) > 0", name="ck_scheduling_review"),
    )
    op.create_index("uq_scheduling_active_identity", "scheduling_accounts", ["external_identity_id"],
                    unique=True, postgresql_where=sa.text("revoked_at IS NULL"))
    op.execute("""CREATE FUNCTION reject_scheduling_account_change() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Scheduling correspondence is immutable'; END IF;
          IF (to_jsonb(NEW) - 'revoked_at') IS DISTINCT FROM (to_jsonb(OLD) - 'revoked_at')
             OR OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
            RAISE EXCEPTION 'Scheduling correspondence is immutable';
          END IF;
          RETURN NEW;
        END $$""")
    op.execute("""CREATE TRIGGER scheduling_account_immutable BEFORE UPDATE OR DELETE
        ON scheduling_accounts FOR EACH ROW EXECUTE FUNCTION reject_scheduling_account_change()""")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM scheduling_accounts)")):
        raise RuntimeError("Disable Scheduling reads; preserve reviewed correspondence history")
    op.drop_table("scheduling_accounts")
    op.execute("DROP FUNCTION reject_scheduling_account_change()")
