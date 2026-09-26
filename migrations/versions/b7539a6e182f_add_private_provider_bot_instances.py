"""Additional private bots retain template and exact principal identity.

Revision ID: b7539a6e182f
Revises: 24350ae2c396
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "b7539a6e182f"
down_revision = "24350ae2c396"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL denotes an existing baseline slot. No existing row or request digest
    # is rewritten; immutable ProviderBot/history triggers remain installed.
    op.add_column("provider_bots", sa.Column("instance_id", UUID(as_uuid=False), nullable=True))
    op.create_unique_constraint("uq_provider_bot_instance", "provider_bots", ["owner_id", "instance_id"])
    op.create_index("uq_provider_bot_default_role", "provider_bots", ["owner_id", "role"],
                    unique=True, postgresql_where=sa.text("instance_id IS NULL"))
    op.create_check_constraint("ck_provider_bot_additional_template", "provider_bots",
                               "instance_id IS NULL OR role <> 'chief'")
    op.drop_constraint("uq_provider_bot_role", "provider_bots", type_="unique")
    op.create_unique_constraint("uq_handoff_origin_recipient", "workspace_handoffs",
                                ["origin_entry_id", "recipient_agent_id"])
    op.drop_constraint("uq_handoff_origin_role", "workspace_handoffs", type_="unique")


def downgrade() -> None:
    raise RuntimeError("Disable WORKSPACE_ENABLED; preserve additional bots and their private history")
