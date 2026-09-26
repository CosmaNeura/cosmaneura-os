"""Custom private bots use existing identities, revisions and handoffs."""

import sqlalchemy as sa
from alembic import op

revision = "d60e13a92c4f"
down_revision = "1aec08b3b3ec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_provider_bot_role", "provider_bots", type_="check")
    op.create_check_constraint("ck_provider_bot_role", "provider_bots",
        "role IN ('scribe', 'visit_prep', 'follow_up', 'chief', 'custom')")
    op.create_check_constraint("ck_provider_bot_custom_identity", "provider_bots",
        "role <> 'custom' OR instance_id IS NOT NULL")
    op.drop_constraint("ck_handoff_role", "workspace_handoffs", type_="check")
    op.create_check_constraint("ck_handoff_role", "workspace_handoffs",
        "recipient_role IN ('scribe', 'visit_prep', 'follow_up', 'custom')")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM provider_bots WHERE role = 'custom')")):
        raise RuntimeError("Preserve custom bot identity and history; downgrade is unavailable")
    op.drop_constraint("ck_handoff_role", "workspace_handoffs", type_="check")
    op.create_check_constraint("ck_handoff_role", "workspace_handoffs",
        "recipient_role IN ('scribe', 'visit_prep', 'follow_up')")
    op.drop_constraint("ck_provider_bot_custom_identity", "provider_bots", type_="check")
    op.drop_constraint("ck_provider_bot_role", "provider_bots", type_="check")
    op.create_check_constraint("ck_provider_bot_role", "provider_bots",
        "role IN ('scribe', 'visit_prep', 'follow_up', 'chief')")
