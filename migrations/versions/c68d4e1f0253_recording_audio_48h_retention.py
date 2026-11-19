"""Recording audio 48-hour retention Box opt-in (T1).

Additive only. Default false so existing live users keep today's behavior.
Process switch recording_audio_48h_retention_enabled must also be true.
"""

from alembic import op

revision = "c68d4e1f0253"
down_revision = "b57c3d0e9142"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(UPGRADE)


def downgrade():
    op.execute(DOWNGRADE)


UPGRADE = r"""
ALTER TABLE box_contexts
	ADD COLUMN recording_audio_48h_retention_enabled BOOLEAN NOT NULL DEFAULT false;
"""

DOWNGRADE = r"""
ALTER TABLE box_contexts
	DROP COLUMN IF EXISTS recording_audio_48h_retention_enabled;
"""
