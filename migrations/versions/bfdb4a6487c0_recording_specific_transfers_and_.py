"""recording_specific_transfers_and_consent_attempts"""

import sqlalchemy as sa
from alembic import op

revision = "bfdb4a6487c0"
down_revision = "f98d3e6f4579"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint(
        "uq_private_transfer_workspace", "private_recording_transfers", type_="unique"
    )
    op.create_table(
        "private_recording_transfer_attempts",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "transfer_id",
            sa.UUID(),
            sa.ForeignKey("private_recording_transfers.id"),
            nullable=False,
        ),
        sa.Column("prior_request_sha256", sa.String(64), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("request", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "transfer_id", "prior_request_sha256", name="uq_private_transfer_attempt_prior"
        ),
        sa.UniqueConstraint(
            "transfer_id", "request_sha256", name="uq_private_transfer_attempt_hash"
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^[a-f0-9]{64}$' AND prior_request_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_private_transfer_attempt_hash",
        ),
    )
    op.create_table(
        "private_recording_transfer_rejections",
        sa.Column(
            "transfer_id",
            sa.UUID(),
            sa.ForeignKey("private_recording_transfers.id"),
            primary_key=True,
        ),
        sa.Column("request_sha256", sa.String(64), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    for table in ("private_recording_transfer_attempts", "private_recording_transfer_rejections"):
        op.execute(
            "CREATE TRIGGER "
            + table
            + "_immutable BEFORE UPDATE OR DELETE ON public."
            + table
            + " FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change()"
        )


def downgrade() -> None:
    raise RuntimeError(
        "Disable recording transfers and retain original audio, consent and admission history."
    )
