"""Practice-bound expiring invitation links and immutable use/revocation history."""
from alembic import op
import sqlalchemy as sa

revision = "d2f7b89013a4"
down_revision = "c1e5a64f9201"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("practice_invitations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("box_id", sa.UUID(), sa.ForeignKey("box_contexts.id"), nullable=False),
        sa.Column("owner_id", sa.UUID(), sa.ForeignKey("principals.id"), nullable=False),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("organization_id", sa.String(255), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("request_key", sa.UUID(), nullable=False),
        sa.Column("token_sha256", sa.String(64), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "box_id", name="uq_practice_invite_scope"),
        sa.UniqueConstraint("owner_id", "request_key", name="uq_practice_invite_key"),
        sa.UniqueConstraint("token_sha256", name="uq_practice_invite_token"),
        sa.CheckConstraint("token_sha256 ~ '^[a-f0-9]{64}$' AND request_sha256 ~ '^[a-f0-9]{64}$'", name="ck_practice_invite_hash"),
        sa.CheckConstraint("expires_at > created_at AND expires_at <= created_at + interval '7 days'", name="ck_practice_invite_expiry"))
    op.create_table("practice_invite_revocations",
        sa.Column("invitation_id", sa.UUID(), sa.ForeignKey("practice_invitations.id"), primary_key=True),
        sa.Column("owner_id", sa.UUID(), sa.ForeignKey("principals.id"), nullable=False),
        sa.Column("request_key", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "request_key", name="uq_practice_invite_revoke_key"))
    op.create_table("practice_invite_uses",
        sa.Column("invitation_id", sa.UUID(), sa.ForeignKey("practice_invitations.id"), primary_key=True),
        sa.Column("request_id", sa.UUID(), sa.ForeignKey("practice_access_requests.id"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for table in ("practice_invitations", "practice_invite_revocations", "practice_invite_uses"):
        op.execute("CREATE TRIGGER " + table + "_immutable BEFORE UPDATE OR DELETE ON public." + table +
            " FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change()")


def downgrade():
    raise RuntimeError("Disable invitation creation and retain invitation, revocation and review history.")
