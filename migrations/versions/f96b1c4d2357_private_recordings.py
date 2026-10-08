"""Immutable device-local recording metadata; no audio blobs or clinical admission."""
import sqlalchemy as sa
from alembic import op

revision="f96b1c4d2357"
down_revision="e85f0a3c1246"
branch_labels=None
depends_on=None


def upgrade():
    op.execute("""
CREATE TABLE private_recordings (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	box_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	external_identity_id UUID NOT NULL,
	agent_id UUID NOT NULL,
	team_revision_id UUID NOT NULL,
	workspace_revision INTEGER NOT NULL,
	local_recording_id UUID NOT NULL,
	request_key UUID NOT NULL,
	request_sha256 VARCHAR(64) NOT NULL,
	recovery_scope VARCHAR(64) NOT NULL,
	request JSONB NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id),
	FOREIGN KEY(agent_id, box_id, owner_id) REFERENCES provider_bots (agent_id, box_id, owner_id),
	FOREIGN KEY(team_revision_id, box_id, owner_id) REFERENCES provider_team_revisions (id, box_id, owner_id),
	CONSTRAINT uq_private_recording_key UNIQUE (owner_id, request_key),
	CONSTRAINT uq_private_recording_local UNIQUE (owner_id, local_recording_id),
	CONSTRAINT uq_private_recording_scope UNIQUE (id, workspace_id, box_id, owner_id),
	CONSTRAINT ck_private_recording_binding CHECK (workspace_revision >= 1 AND request_sha256 ~ '^[a-f0-9]{64}$' AND recovery_scope ~ '^[a-f0-9]{64}$'),
	FOREIGN KEY(external_identity_id) REFERENCES external_identities (id)
)

""")
    op.execute("""
CREATE TABLE private_recording_finishes (
	id UUID NOT NULL,
	recording_id UUID NOT NULL,
	request_key UUID NOT NULL,
	request_sha256 VARCHAR(64) NOT NULL,
	request JSONB NOT NULL,
	capture_state VARCHAR(16) NOT NULL,
	manifest_sha256 VARCHAR(64),
	chunks INTEGER,
	frames INTEGER,
	ended_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_private_recording_finish UNIQUE (recording_id),
	CONSTRAINT uq_private_recording_finish_scope UNIQUE (id, recording_id),
	CONSTRAINT ck_private_recording_finish_hash CHECK (request_sha256 ~ '^[a-f0-9]{64}$'),
	CONSTRAINT ck_private_recording_finish_outcome CHECK (((capture_state = 'unknown' AND manifest_sha256 IS NULL AND chunks IS NULL AND frames IS NULL AND ended_at IS NULL) OR (capture_state IN ('finished','interrupted') AND manifest_sha256 IS NOT NULL AND manifest_sha256 ~ '^[a-f0-9]{64}$' AND chunks BETWEEN 1 AND 1000 AND frames BETWEEN 1 AND 115200000 AND ended_at IS NOT NULL)) IS TRUE),
	FOREIGN KEY(recording_id) REFERENCES private_recordings (id)
)

""")
    op.execute("""
CREATE TABLE private_recording_links (
	id UUID NOT NULL,
	recording_id UUID NOT NULL,
	finish_id UUID NOT NULL,
	workspace_link_receipt_id UUID NOT NULL,
	request_key UUID NOT NULL,
	request_sha256 VARCHAR(64) NOT NULL,
	source_sha256 VARCHAR(64) NOT NULL,
	request JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(finish_id, recording_id) REFERENCES private_recording_finishes (id, recording_id),
	CONSTRAINT uq_private_recording_link UNIQUE (recording_id),
	CONSTRAINT ck_private_recording_link_hash CHECK (request_sha256 ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$'),
	FOREIGN KEY(recording_id) REFERENCES private_recordings (id),
	FOREIGN KEY(workspace_link_receipt_id) REFERENCES workspace_appointment_links (id)
)

""")
    for table in ["private_recordings", "private_recording_finishes", "private_recording_links"]:
        op.execute("CREATE TRIGGER " + table + "_immutable BEFORE UPDATE OR DELETE ON public." + table +
                   " FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change()")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM private_recordings)")).scalar():
        raise RuntimeError("Private recording metadata cannot be erased")
    for table in ["private_recording_links", "private_recording_finishes", "private_recordings"]:
        op.drop_table(table)
