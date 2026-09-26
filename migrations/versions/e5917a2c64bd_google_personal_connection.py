"""Encrypted personal Google connection and retained exchange receipts."""

import sqlalchemy as sa
from alembic import op

revision = "e5917a2c64bd"
down_revision = "de316d1b22db"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "google_connection_attempts",
        sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "account_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("external_identities.id"),
            nullable=False,
        ),
        sa.Column("state_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("binding_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("sealed", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending','exchanging','ready','failed')"),
        sa.CheckConstraint("sealed IS NULL OR octet_length(sealed) BETWEEN 28 AND 32768"),
        sa.CheckConstraint("state_digest ~ '^[a-f0-9]{64}$' AND binding_digest ~ '^[a-f0-9]{64}$'"),
        sa.CheckConstraint("expires_at > created_at"),
    )
    op.create_index(
        "ix_google_connection_attempts_account_id",
        "google_connection_attempts",
        ["account_id"],
    )
    op.create_index(
        "uq_google_connection_active",
        "google_connection_attempts",
        ["account_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending','exchanging')"),
    )
    op.create_table(
        "google_connection_credentials",
        sa.Column(
            "account_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("external_identities.id"),
            primary_key=True,
        ),
        sa.Column("binding_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("sealed", sa.LargeBinary(), nullable=True),
        sa.Column("refresh_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('ready','refreshing','failed','disconnected')"),
        sa.CheckConstraint("sealed IS NULL OR octet_length(sealed) BETWEEN 28 AND 32768"),
        sa.CheckConstraint("binding_digest ~ '^[a-f0-9]{64}$'"),
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM google_connection_attempts) OR EXISTS(SELECT 1 FROM google_connection_credentials)"
        )
    ):
        raise RuntimeError("Retain sign-in attempt and connection history before downgrade")
    op.drop_table("google_connection_credentials")
    op.drop_table("google_connection_attempts")
