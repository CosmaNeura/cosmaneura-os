"""retain reviewed English source on Core note links"""

import sqlalchemy as sa
from alembic import op

revision = 'fe4aa2f140a8'
down_revision = 'f72b834c1e90'
branch_labels = None
depends_on = None

def upgrade() -> None:
    from sqlalchemy.dialects.postgresql import JSONB
    op.add_column("workspace_core_note_sources", sa.Column("reviewed_source", JSONB(none_as_null=True), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Disable configured capture; preserve recorded source and review history")
