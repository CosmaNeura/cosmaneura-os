"""Real-patient recording class and Box kill/enable switches (T-REL-6).

Additive only. Existing patient/visit rows default to synthetic so current
sign-in and notes stay unchanged. Real-patient recording stays off until Box
flags and evidence refs allow it; process env cannot enable it.
"""

from alembic import op

revision = "aa46f2c09b853"
down_revision = "z35e1b98a742"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(UPGRADE)


def downgrade():
    op.execute(DOWNGRADE)


UPGRADE = r"""
ALTER TABLE box_contexts
	ADD COLUMN real_patient_recording_enabled BOOLEAN NOT NULL DEFAULT false,
	ADD COLUMN real_patient_recording_kill_engaged BOOLEAN NOT NULL DEFAULT true;

ALTER TABLE patient_links
	ADD COLUMN recording_class VARCHAR(16) NOT NULL DEFAULT 'synthetic',
	ADD CONSTRAINT ck_patient_link_recording_class
		CHECK (recording_class IN ('synthetic', 'demo', 'real'));

ALTER TABLE appointment_observations
	ADD COLUMN recording_class VARCHAR(16) NOT NULL DEFAULT 'synthetic',
	ADD CONSTRAINT ck_appointment_recording_class
		CHECK (recording_class IN ('synthetic', 'demo', 'real'));
"""

DOWNGRADE = r"""
ALTER TABLE appointment_observations
	DROP CONSTRAINT IF EXISTS ck_appointment_recording_class,
	DROP COLUMN IF EXISTS recording_class;

ALTER TABLE patient_links
	DROP CONSTRAINT IF EXISTS ck_patient_link_recording_class,
	DROP COLUMN IF EXISTS recording_class;

ALTER TABLE box_contexts
	DROP COLUMN IF EXISTS real_patient_recording_kill_engaged,
	DROP COLUMN IF EXISTS real_patient_recording_enabled;
"""
