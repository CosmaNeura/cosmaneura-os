"""bind verified external identities to one Box principal

Revision ID: 0002_external_identities
Revises: 0001_initial
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_external_identities"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_principal_id_box",
        "principals",
        ["id", "box_id"],
    )
    op.create_table(
        "external_identities",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "box_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("box_contexts.id"),
            nullable=False,
        ),
        sa.Column("principal_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("organization_id", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("reviewed_by", sa.String(200), nullable=False),
        sa.Column("evidence_ref", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["principal_id", "box_id"],
            ["principals.id", "principals.box_id"],
            name="fk_external_identity_principal_box",
        ),
        sa.UniqueConstraint(
            "issuer",
            "subject",
            name="uq_external_identity_issuer_subject",
        ),
        sa.UniqueConstraint(
            "issuer",
            "organization_id",
            "principal_id",
            name="uq_external_identity_org_principal",
        ),
    )


def downgrade() -> None:
    op.drop_table("external_identities")
    op.drop_constraint("uq_principal_id_box", "principals", type_="unique")
