"""Recording audio 48-hour retention Box opt-in (T1).

Additive only. Default false so existing live users keep today's behavior.
Process switch recording_audio_48h_retention_enabled must also be true.

enabled_at stamps when the Box opt-in first becomes true so clients can
grandfather pre-enable recordings (flip + 48h grace) instead of applying
48h retroactively from an old ended_at.
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
SET LOCAL lock_timeout = '5s';

ALTER TABLE box_contexts
	ADD COLUMN recording_audio_48h_retention_enabled BOOLEAN NOT NULL DEFAULT false,
	ADD COLUMN recording_audio_48h_retention_enabled_at TIMESTAMPTZ NULL;

CREATE FUNCTION public.box_recording_audio_48h_retention_enabled_at() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
	IF NEW.recording_audio_48h_retention_enabled IS TRUE THEN
		IF NEW.recording_audio_48h_retention_enabled_at IS NULL THEN
			NEW.recording_audio_48h_retention_enabled_at := clock_timestamp();
		END IF;
	ELSE
		NEW.recording_audio_48h_retention_enabled_at := NULL;
	END IF;
	RETURN NEW;
END;
$$;

CREATE TRIGGER box_recording_audio_48h_retention_enabled_at
BEFORE INSERT OR UPDATE ON public.box_contexts
FOR EACH ROW EXECUTE FUNCTION public.box_recording_audio_48h_retention_enabled_at();
"""

DOWNGRADE = r"""
DROP TRIGGER IF EXISTS box_recording_audio_48h_retention_enabled_at ON public.box_contexts;
DROP FUNCTION IF EXISTS public.box_recording_audio_48h_retention_enabled_at();
ALTER TABLE box_contexts
	DROP COLUMN IF EXISTS recording_audio_48h_retention_enabled_at,
	DROP COLUMN IF EXISTS recording_audio_48h_retention_enabled;
"""
