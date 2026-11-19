"""T2a: CosmaBot independent transcription tables and Box opt-in.

Additive and reversible. Default-false Box column; audio uploads expire in 48h;
transcripts, jobs and purge receipts are separate. Existing live users unchanged.
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
	CONSTRAINT uq_independent_audio_operation
		UNIQUE (box_id, workspace_id, recording_id, operation_id),
	CONSTRAINT uq_independent_audio_scope
		UNIQUE (id, recording_id, workspace_id, box_id, owner_id),
	CONSTRAINT ck_independent_audio_sha CHECK (sha256 ~ '^[a-f0-9]{64}$'),
	CONSTRAINT ck_independent_audio_recording_class
		CHECK (recording_class IN ('synthetic', 'demo', 'real')),
	CONSTRAINT ck_independent_audio_bytes CHECK (byte_count >= 0)
);

CREATE INDEX ix_independent_audio_purge_due
	ON independent_recording_audio_uploads (box_id, audio_expires_at)
	WHERE audio_purged_at IS NULL;

CREATE INDEX ix_independent_audio_owner_created
	ON independent_recording_audio_uploads (box_id, owner_id, created_at);

CREATE TABLE independent_recording_transcription_jobs (
	id UUID NOT NULL,
	upload_id UUID NOT NULL,
	recording_id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	box_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	operation_id UUID NOT NULL,
	state VARCHAR(32) NOT NULL,
	attempts INTEGER NOT NULL DEFAULT 0,
	claimed_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	error_kind VARCHAR(64),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(upload_id, recording_id, workspace_id, box_id, owner_id)
		REFERENCES independent_recording_audio_uploads
			(id, recording_id, workspace_id, box_id, owner_id),
	CONSTRAINT uq_independent_transcription_job_operation
		UNIQUE (box_id, workspace_id, recording_id, operation_id),
	CONSTRAINT ck_independent_transcription_job_state
		CHECK (state IN ('pending', 'claimed', 'ready', 'failed_retryable', 'failed_terminal')),
	CONSTRAINT ck_independent_transcription_job_attempts CHECK (attempts >= 0)
);

CREATE INDEX ix_independent_transcription_jobs_claim
	ON independent_recording_transcription_jobs (box_id, state, created_at);

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
	synthetic BOOLEAN NOT NULL,
	source_sha256 VARCHAR(64) NOT NULL,
	segments JSONB NOT NULL,
	label VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(upload_id, recording_id, workspace_id, box_id, owner_id)
		REFERENCES independent_recording_audio_uploads
			(id, recording_id, workspace_id, box_id, owner_id),
	CONSTRAINT uq_independent_transcript_operation
		UNIQUE (box_id, workspace_id, recording_id, operation_id),
	CONSTRAINT ck_independent_transcript_sha CHECK (source_sha256 ~ '^[a-f0-9]{64}$'),
	CONSTRAINT ck_independent_transcript_label CHECK (char_length(label) >= 1)
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
	FOREIGN KEY(box_id) REFERENCES box_contexts (id),
	CONSTRAINT ck_independent_purge_outcome
		CHECK (outcome IN ('purged', 'failed'))
);

CREATE INDEX ix_independent_purge_receipts_box
	ON independent_recording_audio_purge_receipts (box_id, deleted_at);
"""


DOWNGRADE = r"""
DROP TABLE IF EXISTS independent_recording_audio_purge_receipts;
DROP TABLE IF EXISTS independent_recording_transcripts;
DROP TABLE IF EXISTS independent_recording_transcription_jobs;
DROP TABLE IF EXISTS independent_recording_audio_uploads;
ALTER TABLE box_contexts
	DROP COLUMN IF EXISTS independent_recording_transcription_enabled;
"""
