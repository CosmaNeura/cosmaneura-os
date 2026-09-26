"""Owner-reviewed practice access requests from verified organization members."""

import sqlalchemy as sa
from alembic import op

revision = "f72b834c1e90"
down_revision = "e5917a2c64bd"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "practice_access_requests",
        sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
        sa.Column("box_id", sa.UUID(as_uuid=False), sa.ForeignKey("box_contexts.id"), nullable=False),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("organization_id", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("request_key", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("review_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.UUID(as_uuid=False), sa.ForeignKey("principals.id"), nullable=True),
        sa.UniqueConstraint("issuer", "subject", "request_key", name="uq_practice_access_retry"),
        sa.CheckConstraint("state IN ('pending','approved','declined','cancelled')", name="ck_practice_access_state"),
        sa.CheckConstraint("review_sha256 ~ '^[a-f0-9]{64}$'", name="ck_practice_access_hash"),
        sa.CheckConstraint("expires_at > created_at", name="ck_practice_access_expiry"),
        sa.CheckConstraint("(state='pending' AND decided_at IS NULL AND decided_by IS NULL) OR (state='cancelled' AND decided_at IS NOT NULL AND decided_by IS NULL) OR (state IN ('approved','declined') AND decided_at IS NOT NULL AND decided_by IS NOT NULL)", name="ck_practice_access_decision"),
    )
    op.create_index("ix_practice_access_pending", "practice_access_requests", ["box_id", "state", "created_at"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM practice_access_requests)")):
        raise RuntimeError("Retain practice access and decision history before downgrade")
    op.drop_table("practice_access_requests")
