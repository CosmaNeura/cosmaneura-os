"""T2a: CosmaBot independent transcription tables and Box opt-in.

Additive and reversible. Default-false Box column; audio uploads expire in 48h;
transcripts and purge receipts are separate. Existing live users unchanged.
"""

from alembic import op

revision = "c68f2a91b053"
down_revision = "b57c3d0e9142"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(UPGRADE)


def downgrade():
    op.execute(DOWNGRADE)


UPGRADE = r"""
ALTER TABLE box_contexts
	ADD COLUMN independent_recording_transcription_enabled BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE independent_recording_audio_uploads (
	id UUID NOT NULL,
	recording_id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	box_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	operation_id UUID NOT NULL,
	blob_key VARCHAR(512),
	sha256 VARCHAR(64) NOT NULL,
	byte_count BIGINT NOT NULL,
	duration_ms INTEGER NOT NULL,
	language VARCHAR(32) NOT NULL,
	recording_class VARCHAR(16) NOT NULL,
	consent JSONB NOT NULL,
	lease_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	audio_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	audio_purged_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(recording_id, workspace_id, box_id, owner_id)
		REFERENCES private_recordings (id, workspace_id, box_id, owner_id),
	CONSTRAINT uq_independent_audio_operation UNIQUE (owner_id, operation_id),
	CONSTRAINT uq_independent_audio_op_sha UNIQUE (owner_id, operation_id, sha256),
	CONSTRAINT ck_independent_audio_sha CHECK (sha256 ~ '^[a-f0-9]{64}$'),
	CONSTRAINT ck_independent_audio_recording_class
		CHECK (recording_class IN ('synthetic', 'demo', 'real')),
	CONSTRAINT ck_independent_audio_bytes CHECK (byte_count >= 0)
);

CREATE TABLE independent_recording_transcripts (
	id UUID NOT NULL,
	upload_id UUID NOT NULL,
	recording_id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	box_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	operation_id UUID NOT NULL,
	processor_id VARCHAR(64) NOT NULL,
	profile_id VARCHAR(64) NOT NULL,
	synthetic BOOLEAN DEFAULT true NOT NULL,
	source_sha256 VARCHAR(64) NOT NULL,
	segments JSONB NOT NULL,
	label VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(upload_id) REFERENCES independent_recording_audio_uploads (id),
	FOREIGN KEY(recording_id) REFERENCES private_recordings (id),
	CONSTRAINT uq_independent_transcript_operation UNIQUE (owner_id, operation_id),
	CONSTRAINT ck_independent_transcript_sha CHECK (source_sha256 ~ '^[a-f0-9]{64}$')
);

CREATE TABLE independent_recording_audio_purge_receipts (
	id UUID NOT NULL,
	box_id UUID NOT NULL,
	upload_id UUID NOT NULL,
	retention_rule VARCHAR(64) NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE NOT NULL,
	outcome VARCHAR(32) NOT NULL,
	detail TEXT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(box_id) REFERENCES box_contexts (id)
);
"""


DOWNGRADE = r"""
DROP TABLE IF EXISTS independent_recording_audio_purge_receipts;
DROP TABLE IF EXISTS independent_recording_transcripts;
DROP TABLE IF EXISTS independent_recording_audio_uploads;
ALTER TABLE box_contexts
	DROP COLUMN IF EXISTS independent_recording_transcription_enabled;
"""
