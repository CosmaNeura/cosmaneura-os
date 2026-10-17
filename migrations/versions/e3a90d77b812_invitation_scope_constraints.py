"""Pin invitation history to its practice at the database boundary."""
from alembic import op
import sqlalchemy as sa

revision = "e3a90d77b812"
down_revision = "d2f7b89013a4"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_unique_constraint("uq_practice_access_request_scope", "practice_access_requests", ["id", "box_id"])
    op.create_foreign_key("fk_practice_invite_owner_scope", "practice_invitations", "principals", ["owner_id", "box_id"], ["id", "box_id"])
    for table, prefix in (("practice_invite_revocations", "revoke"), ("practice_invite_uses", "use")):
        op.add_column(table, sa.Column("box_id", sa.UUID(), nullable=True))
        # Only this transaction may backfill immutable history with its existing scope.
        op.execute("ALTER TABLE public." + table + " DISABLE TRIGGER " + table + "_immutable")
        op.execute("UPDATE public." + table + " h SET box_id=i.box_id FROM public.practice_invitations i WHERE i.id=h.invitation_id")
        op.execute("ALTER TABLE public." + table + " ENABLE TRIGGER " + table + "_immutable")
        op.alter_column(table, "box_id", nullable=False)
        op.create_foreign_key("fk_practice_invite_" + prefix + "_scope", table, "practice_invitations", ["invitation_id", "box_id"], ["id", "box_id"])
        op.create_foreign_key("fk_practice_invite_" + prefix + "_box", table, "box_contexts", ["box_id"], ["id"])
    op.create_foreign_key("fk_practice_invite_revoke_owner_scope", "practice_invite_revocations", "principals", ["owner_id", "box_id"], ["id", "box_id"])
    op.create_foreign_key("fk_practice_invite_use_request_scope", "practice_invite_uses", "practice_access_requests", ["request_id", "box_id"], ["id", "box_id"])

def downgrade():
    raise RuntimeError("Retain invitation history and practice scope constraints.")
