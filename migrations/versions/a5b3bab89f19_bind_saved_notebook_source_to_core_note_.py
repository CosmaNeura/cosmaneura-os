"""bind_saved_notebook_source_to_core_note_review"""

import sqlalchemy as sa
from alembic import op

revision = 'a5b3bab89f19'
down_revision = 'b7539a6e182f'
branch_labels = None
depends_on = None

def upgrade() -> None:
    from sqlalchemy.dialects.postgresql import JSONB
    op.add_column("workspace_core_note_sources", sa.Column("notebook_source", JSONB(none_as_null=True), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Disable capture notes; preserve saved notebook provenance")
