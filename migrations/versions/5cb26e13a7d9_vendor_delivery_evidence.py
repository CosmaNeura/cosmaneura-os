"""Durable reviewed vendor delivery around F8; no enabled configuration is seeded."""
from alembic import op

revision = "5cb26e13a7d9"
down_revision = "9f26a481b7c0"
branch_labels = None
depends_on = None

# Frozen DDL, deliberately independent of future ORM changes.
TABLE_DDL = r"""

CREATE TABLE vendor_connection_versions (
	id UUID NOT NULL, 
	family_id UUID NOT NULL, 
	revision INTEGER NOT NULL, 
	vendor VARCHAR(16) NOT NULL, 
	environment VARCHAR(16) NOT NULL, 
	private_selection JSONB NOT NULL, 
	routing JSONB NOT NULL, 
	private_sha256 VARCHAR(64) NOT NULL, 
	public_view JSONB NOT NULL, 
	public_sha256 VARCHAR(64) NOT NULL, 
	reviewed_by UUID NOT NULL, 
	reviewed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	is_current BOOLEAN DEFAULT true NOT NULL, 
	read_enabled BOOLEAN DEFAULT false NOT NULL, 
	write_enabled BOOLEAN DEFAULT false NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id, box_id) REFERENCES principals (id, box_id), 
	CONSTRAINT uq_vendor_connection_scope UNIQUE (id, box_id, owner_id), 
	CONSTRAINT uq_vendor_connection_revision UNIQUE (family_id, revision), 
	CHECK (revision > 0 AND reviewed_by = owner_id), 
	CHECK (vendor IN ('spruce','srfax','documo') AND (environment = 'production' OR (vendor = 'documo' AND environment = 'sandbox'))), 
	CHECK (private_sha256 ~ '^[a-f0-9]{64}$' AND public_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(private_selection) = 'object' AND octet_length(private_selection::text) <= 32768), 
	CHECK (jsonb_typeof(routing) = 'object' AND octet_length(routing::text) <= 32768), 
	CHECK (jsonb_typeof(public_view) = 'object' AND octet_length(public_view::text) <= 4096)
)

;
CREATE UNIQUE INDEX uq_vendor_connection_current ON vendor_connection_versions (box_id, owner_id, family_id) WHERE is_current;


CREATE TABLE vendor_correspondence_versions (
	id UUID NOT NULL, 
	family_id UUID NOT NULL, 
	revision INTEGER NOT NULL, 
	patient_link_id UUID NOT NULL, 
	connection_version_id UUID NOT NULL, 
	private_proof JSONB NOT NULL, 
	private_sha256 VARCHAR(64) NOT NULL, 
	public_view JSONB NOT NULL, 
	public_sha256 VARCHAR(64) NOT NULL, 
	reviewed_by UUID NOT NULL, 
	reviewed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	is_current BOOLEAN DEFAULT true NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(connection_version_id, box_id, owner_id) REFERENCES vendor_connection_versions (id, box_id, owner_id), 
	FOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id), 
	CONSTRAINT uq_vendor_correspondence_scope UNIQUE (id, connection_version_id, box_id, owner_id, patient_link_id), 
	CONSTRAINT uq_vendor_correspondence_revision UNIQUE (family_id, revision), 
	CHECK (revision > 0 AND reviewed_by = owner_id AND expires_at > reviewed_at), 
	CHECK (private_sha256 ~ '^[a-f0-9]{64}$' AND public_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(private_proof) = 'object' AND octet_length(private_proof::text) <= 32768), 
	CHECK (jsonb_typeof(public_view) = 'object' AND octet_length(public_view::text) <= 4096)
)

;
CREATE UNIQUE INDEX uq_vendor_correspondence_current ON vendor_correspondence_versions (box_id, owner_id, family_id) WHERE is_current;


CREATE TABLE vendor_event_candidates (
	id UUID NOT NULL, 
	route_id UUID NOT NULL, 
	connection_version_id UUID NOT NULL, 
	vendor VARCHAR(16) NOT NULL, 
	authenticity VARCHAR(16) NOT NULL, 
	body_sha256 VARCHAR(64) NOT NULL, 
	correlation JSONB NOT NULL, 
	received_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(connection_version_id, box_id, owner_id) REFERENCES vendor_connection_versions (id, box_id, owner_id), 
	CONSTRAINT uq_vendor_event_candidate UNIQUE (connection_version_id, vendor, authenticity, body_sha256), 
	CHECK (vendor IN ('spruce','srfax','documo') AND authenticity IN ('signed','untrusted_hint')), 
	CHECK (authenticity <> 'signed' OR vendor = 'spruce'), 
	CHECK (body_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(correlation) = 'object' AND octet_length(correlation::text) <= 8192)
)

;



CREATE TABLE vendor_artifacts (
	artifact_id UUID NOT NULL, 
	intent_sha256 VARCHAR(64) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	byte_length INTEGER NOT NULL, 
	media_type VARCHAR(32) NOT NULL, 
	scope_version INTEGER NOT NULL, 
	state VARCHAR(16) NOT NULL, 
	version INTEGER NOT NULL, 
	active_generation INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	note_id UUID NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	source_fingerprint VARCHAR(64) NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (artifact_id), 
	FOREIGN KEY(note_id, workspace_id, box_id, owner_id, content_hash, source_fingerprint) REFERENCES workspace_notes (id, workspace_id, box_id, owner_id, content_hash, source_fingerprint), 
	FOREIGN KEY(note_id) REFERENCES workspace_note_reviews (note_id), 
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), 
	CONSTRAINT uq_vendor_artifact_scope UNIQUE (artifact_id, workspace_id, box_id, owner_id), 
	CHECK (intent_sha256 ~ '^[a-f0-9]{64}$' AND sha256 ~ '^[a-f0-9]{64}$' AND content_hash ~ '^[a-f0-9]{64}$' AND source_fingerprint ~ '^[a-f0-9]{64}$'), 
	CHECK (byte_length BETWEEN 5 AND 8388608 AND media_type = 'application/pdf' AND scope_version = 1), 
	CHECK (state IN ('empty','receiving','ready','quarantined') AND version >= 1 AND active_generation >= 0), 
	CHECK ((state = 'empty') = (active_generation = 0))
)

;



CREATE TABLE vendor_artifact_attempts (
	id UUID NOT NULL, 
	artifact_id UUID NOT NULL, 
	actor_id UUID NOT NULL, 
	idempotency_key VARCHAR(100) NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	generation INTEGER NOT NULL, 
	fence_token UUID NOT NULL, 
	admitted_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	lease_until TIMESTAMP WITH TIME ZONE NOT NULL, 
	state VARCHAR(16) NOT NULL, 
	safe_error VARCHAR(64), 
	completed_at TIMESTAMP WITH TIME ZONE, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(artifact_id, workspace_id, box_id, owner_id) REFERENCES vendor_artifacts (artifact_id, workspace_id, box_id, owner_id), 
	FOREIGN KEY(actor_id, box_id) REFERENCES principals (id, box_id), 
	CONSTRAINT uq_vendor_artifact_generation UNIQUE (artifact_id, generation), 
	CONSTRAINT uq_vendor_artifact_key_generation UNIQUE (artifact_id, idempotency_key, generation), 
	CHECK (generation >= 1 AND actor_id = owner_id AND lease_until > admitted_at), 
	CHECK (state IN ('receiving','ready','failed','unknown')), 
	CHECK (request_sha256 ~ '^[a-f0-9]{64}$')
)

;



CREATE TABLE vendor_work (
	ticket_id UUID NOT NULL, 
	patient_link_id UUID NOT NULL, 
	origin_revision_id UUID NOT NULL, 
	origin_operation_id UUID NOT NULL, 
	supersedes_operation_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (ticket_id), 
	FOREIGN KEY(ticket_id, box_id) REFERENCES follow_up_sources (ticket_id, box_id) DEFERRABLE INITIALLY DEFERRED, 
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), 
	FOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id), 
	CONSTRAINT uq_vendor_work_scope UNIQUE (ticket_id, workspace_id, box_id, owner_id, patient_link_id), 
	CONSTRAINT uq_vendor_work_origin_scope UNIQUE (origin_operation_id, workspace_id, box_id, owner_id, patient_link_id)
)

;



CREATE TABLE vendor_work_revisions (
	action_revision_id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	patient_link_id UUID NOT NULL, 
	revision_number INTEGER NOT NULL, 
	action VARCHAR(32) NOT NULL, 
	payload_hash VARCHAR(64) NOT NULL, 
	intended_operation_id UUID NOT NULL, 
	source_workspace_revision INTEGER NOT NULL, 
	connection_version_id UUID NOT NULL, 
	correspondence_version_id UUID, 
	artifact_id UUID, 
	uploaded_media_operation_id UUID, 
	private_command JSONB NOT NULL, 
	private_command_sha256 VARCHAR(64) NOT NULL, 
	source_proof JSONB NOT NULL, 
	source_proof_sha256 VARCHAR(64) NOT NULL, 
	public_proposal JSONB NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	public_review JSONB NOT NULL, 
	review_sha256 VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	note_id UUID NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	source_fingerprint VARCHAR(64) NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (action_revision_id), 
	FOREIGN KEY(ticket_id, workspace_id, box_id, owner_id, patient_link_id) REFERENCES vendor_work (ticket_id, workspace_id, box_id, owner_id, patient_link_id) DEFERRABLE INITIALLY DEFERRED, 
	FOREIGN KEY(action_revision_id, ticket_id, box_id, payload_hash) REFERENCES action_revisions (id, ticket_id, box_id, payload_hash), 
	FOREIGN KEY(note_id, workspace_id, box_id, owner_id, content_hash, source_fingerprint) REFERENCES workspace_notes (id, workspace_id, box_id, owner_id, content_hash, source_fingerprint), 
	FOREIGN KEY(note_id) REFERENCES workspace_note_reviews (note_id), 
	FOREIGN KEY(connection_version_id, box_id, owner_id) REFERENCES vendor_connection_versions (id, box_id, owner_id), 
	FOREIGN KEY(correspondence_version_id, connection_version_id, box_id, owner_id, patient_link_id) REFERENCES vendor_correspondence_versions (id, connection_version_id, box_id, owner_id, patient_link_id), 
	FOREIGN KEY(artifact_id, workspace_id, box_id, owner_id) REFERENCES vendor_artifacts (artifact_id, workspace_id, box_id, owner_id), 
	CONSTRAINT uq_vendor_work_revision UNIQUE (ticket_id, revision_number), 
	CONSTRAINT uq_vendor_intended_operation UNIQUE (intended_operation_id), 
	CONSTRAINT uq_vendor_operation_revision UNIQUE (intended_operation_id, action_revision_id, ticket_id, box_id), 
	CONSTRAINT uq_vendor_operation_owner UNIQUE (intended_operation_id, workspace_id, box_id, owner_id, patient_link_id), 
	CHECK (revision_number BETWEEN 1 AND 20 AND source_workspace_revision >= 1), 
	CHECK (action IN ('spruce_secure_message','spruce_fax','spruce_media_upload','srfax_fax','documo_fax')), 
	CHECK ((action = 'spruce_media_upload' AND artifact_id IS NOT NULL AND correspondence_version_id IS NULL AND uploaded_media_operation_id IS NULL) OR (action IN ('srfax_fax','documo_fax') AND artifact_id IS NOT NULL AND correspondence_version_id IS NOT NULL AND uploaded_media_operation_id IS NULL) OR (action = 'spruce_secure_message' AND artifact_id IS NULL AND correspondence_version_id IS NOT NULL) OR (action = 'spruce_fax' AND artifact_id IS NULL AND correspondence_version_id IS NOT NULL AND uploaded_media_operation_id IS NOT NULL)), 
	CHECK (payload_hash ~ '^[a-f0-9]{64}$' AND private_command_sha256 ~ '^[a-f0-9]{64}$' AND source_proof_sha256 ~ '^[a-f0-9]{64}$' AND request_sha256 ~ '^[a-f0-9]{64}$' AND review_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(private_command) = 'object' AND octet_length(private_command::text) <= 65536), 
	CHECK (jsonb_typeof(source_proof) = 'object' AND octet_length(source_proof::text) <= 1048576), 
	CHECK (jsonb_typeof(public_proposal) = 'object' AND octet_length(public_proposal::text) <= 65536), 
	CHECK (jsonb_typeof(public_review) = 'object' AND octet_length(public_review::text) <= 65536)
)

;



CREATE TABLE vendor_command_receipts (
	id UUID NOT NULL, 
	actor_id UUID, 
	origin VARCHAR(16) NOT NULL, 
	scope_kind VARCHAR(16) NOT NULL, 
	scope_id UUID NOT NULL, 
	command_kind VARCHAR(24) NOT NULL, 
	idempotency_key VARCHAR(100), 
	fact_key VARCHAR(200), 
	public_request JSONB NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	ticket_id UUID, 
	action_revision_id UUID, 
	operation_id UUID, 
	artifact_id UUID, 
	effect_version INTEGER NOT NULL, 
	effect JSONB NOT NULL, 
	receipt_sha256 VARCHAR(64) NOT NULL, 
	result_receipt_id UUID, 
	observation_head_sha256 VARCHAR(64), 
	evidence_sha256 VARCHAR(64), 
	publication_projection JSONB, 
	publication_sha256 VARCHAR(64), 
	result_payload JSONB, 
	recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), 
	FOREIGN KEY(actor_id, box_id) REFERENCES principals (id, box_id), 
	FOREIGN KEY(operation_id, action_revision_id, ticket_id, box_id) REFERENCES vendor_work_revisions (intended_operation_id, action_revision_id, ticket_id, box_id) DEFERRABLE INITIALLY DEFERRED, 
	FOREIGN KEY(artifact_id, workspace_id, box_id, owner_id) REFERENCES vendor_artifacts (artifact_id, workspace_id, box_id, owner_id) DEFERRABLE INITIALLY DEFERRED, 
	CONSTRAINT uq_vendor_receipt_revision UNIQUE (id, ticket_id, action_revision_id, box_id), 
	CHECK (scope_kind IN ('workspace','practice_work') AND origin IN ('user','system') AND effect_version > 0), 
	CHECK ((origin = 'user' AND actor_id IS NOT NULL AND idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$' AND fact_key IS NULL) OR (origin = 'system' AND actor_id IS NULL AND idempotency_key IS NULL AND fact_key IS NOT NULL)), 
	CHECK ((artifact_id IS NULL AND ticket_id IS NOT NULL AND action_revision_id IS NOT NULL AND operation_id IS NOT NULL) OR (artifact_id IS NOT NULL AND ticket_id IS NULL AND action_revision_id IS NULL AND operation_id IS NULL)), 
	CHECK (command_kind IN ('propose','decide','withdraw','publish','submit','reconcile','result','verify','handoff','artifact_intent','artifact_content','reopen')), 
	CHECK (request_sha256 ~ '^[a-f0-9]{64}$' AND receipt_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(public_request) = 'object' AND octet_length(public_request::text) <= 65536), 
	CHECK (jsonb_typeof(effect) = 'object' AND octet_length(effect::text) <= 8192), 
	CHECK (publication_projection IS NULL OR (jsonb_typeof(publication_projection) = 'object' AND octet_length(publication_projection::text) <= 16384)), 
	CHECK (result_payload IS NULL OR (jsonb_typeof(result_payload) = 'object' AND octet_length(result_payload::text) <= 16384))
)

;
CREATE UNIQUE INDEX uq_vendor_command_user_key ON vendor_command_receipts (workspace_id, actor_id, idempotency_key) WHERE origin = 'user';
CREATE UNIQUE INDEX uq_vendor_verification ON vendor_command_receipts (action_revision_id, result_receipt_id, evidence_sha256) WHERE command_kind = 'verify';
CREATE UNIQUE INDEX uq_vendor_system_fact ON vendor_command_receipts (workspace_id, fact_key) WHERE origin = 'system';
CREATE UNIQUE INDEX uq_vendor_publication ON vendor_command_receipts (action_revision_id) WHERE publication_projection IS NOT NULL;


CREATE TABLE vendor_read_claims (
	id UUID NOT NULL, 
	actor_id UUID NOT NULL, 
	idempotency_key VARCHAR(100) NOT NULL, 
	command_receipt_id UUID NOT NULL, 
	connection_version_id UUID NOT NULL, 
	private_reference JSONB NOT NULL, 
	reference_sha256 VARCHAR(64) NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	claim_token UUID NOT NULL, 
	admitted_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	deadline TIMESTAMP WITH TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	state VARCHAR(16) NOT NULL, 
	operation_id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	action_revision_id UUID NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(operation_id, ticket_id, box_id) REFERENCES operations (id, ticket_id, box_id), 
	FOREIGN KEY(operation_id, action_revision_id, ticket_id, box_id) REFERENCES vendor_work_revisions (intended_operation_id, action_revision_id, ticket_id, box_id), 
	FOREIGN KEY(connection_version_id, box_id, owner_id) REFERENCES vendor_connection_versions (id, box_id, owner_id), 
	FOREIGN KEY(command_receipt_id, ticket_id, action_revision_id, box_id) REFERENCES vendor_command_receipts (id, ticket_id, action_revision_id, box_id), 
	CONSTRAINT uq_vendor_read_key UNIQUE (operation_id, actor_id, idempotency_key), 
	CHECK (actor_id = owner_id AND deadline > admitted_at AND state IN ('admitted','settled','unknown')), 
	CHECK (reference_sha256 ~ '^[a-f0-9]{64}$' AND request_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(private_reference) = 'object' AND octet_length(private_reference::text) <= 8192)
)

;



CREATE TABLE vendor_submit_claims (
	operation_id UUID NOT NULL, 
	actor_id UUID NOT NULL, 
	approval_receipt_id UUID NOT NULL, 
	command_receipt_id UUID NOT NULL, 
	command_sha256 VARCHAR(64) NOT NULL, 
	source_sha256 VARCHAR(64) NOT NULL, 
	selection_sha256 VARCHAR(64) NOT NULL, 
	correspondence_sha256 VARCHAR(64), 
	request_sha256 VARCHAR(64) NOT NULL, 
	claim_token UUID NOT NULL, 
	claimed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	deadline TIMESTAMP WITH TIME ZONE NOT NULL, 
	dispatch VARCHAR(32) NOT NULL, 
	invocation_started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	safe_error VARCHAR(64), 
	ticket_id UUID NOT NULL, 
	action_revision_id UUID NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (operation_id), 
	FOREIGN KEY(operation_id, ticket_id, box_id) REFERENCES operations (id, ticket_id, box_id), 
	FOREIGN KEY(operation_id, action_revision_id, ticket_id, box_id) REFERENCES vendor_work_revisions (intended_operation_id, action_revision_id, ticket_id, box_id), 
	FOREIGN KEY(approval_receipt_id, ticket_id, action_revision_id, box_id) REFERENCES vendor_command_receipts (id, ticket_id, action_revision_id, box_id), 
	FOREIGN KEY(command_receipt_id, ticket_id, action_revision_id, box_id) REFERENCES vendor_command_receipts (id, ticket_id, action_revision_id, box_id), 
	CHECK (actor_id = owner_id AND deadline > claimed_at), 
	CHECK (dispatch IN ('not_started','invocation_started','proved_not_dispatched','unconfirmed','response_observed')), 
	CHECK (command_sha256 ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$' AND selection_sha256 ~ '^[a-f0-9]{64}$' AND request_sha256 ~ '^[a-f0-9]{64}$')
)

;



CREATE TABLE vendor_provider_observations (
	id UUID NOT NULL, 
	connection_version_id UUID NOT NULL, 
	sequence INTEGER NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	source_id UUID NOT NULL, 
	submit_claim_id UUID, 
	read_claim_id UUID, 
	event_candidate_id UUID, 
	kind VARCHAR(16) NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	body_sha256 VARCHAR(64), 
	canonical_sha256 VARCHAR(64) NOT NULL, 
	private_reference JSONB, 
	public_observation JSONB NOT NULL, 
	public_sha256 VARCHAR(64) NOT NULL, 
	head_sha256 VARCHAR(64) NOT NULL, 
	operation_id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	action_revision_id UUID NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(operation_id, ticket_id, box_id) REFERENCES operations (id, ticket_id, box_id), 
	FOREIGN KEY(operation_id, action_revision_id, ticket_id, box_id) REFERENCES vendor_work_revisions (intended_operation_id, action_revision_id, ticket_id, box_id), 
	FOREIGN KEY(connection_version_id, box_id, owner_id) REFERENCES vendor_connection_versions (id, box_id, owner_id), 
	FOREIGN KEY(submit_claim_id) REFERENCES vendor_submit_claims (operation_id), 
	FOREIGN KEY(read_claim_id) REFERENCES vendor_read_claims (id), 
	FOREIGN KEY(event_candidate_id) REFERENCES vendor_event_candidates (id), 
	CONSTRAINT uq_vendor_observation_sequence UNIQUE (operation_id, sequence), 
	CONSTRAINT uq_vendor_observation_fact UNIQUE (operation_id, source, source_id, kind, canonical_sha256), 
	CHECK (sequence >= 1 AND source IN ('submit','read','event','internal_dispatch') AND kind IN ('submission','transport','dispatch')), 
	CHECK ((source IN ('submit','internal_dispatch') AND submit_claim_id IS NOT NULL AND read_claim_id IS NULL AND event_candidate_id IS NULL AND source_id = submit_claim_id) OR (source = 'read' AND read_claim_id IS NOT NULL AND submit_claim_id IS NULL AND event_candidate_id IS NULL AND source_id = read_claim_id) OR (source = 'event' AND event_candidate_id IS NOT NULL AND submit_claim_id IS NULL AND read_claim_id IS NULL AND source_id = event_candidate_id)), 
	CHECK (canonical_sha256 ~ '^[a-f0-9]{64}$' AND public_sha256 ~ '^[a-f0-9]{64}$' AND head_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(public_observation) = 'object' AND octet_length(public_observation::text) <= 4096), 
	CHECK (private_reference IS NULL OR (jsonb_typeof(private_reference) = 'object' AND octet_length(private_reference::text) <= 8192))
)

;

"""


def upgrade():
    op.execute(TABLE_DDL)
    op.execute(GUARD_DDL)


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM public.follow_up_sources WHERE source_kind = 'vendor_reviewed_note')
            OR EXISTS (SELECT 1 FROM public.work_handoffs WHERE vendor_publication_receipt_id IS NOT NULL)
            OR EXISTS (SELECT 1 FROM public.vendor_connection_versions)
            OR EXISTS (SELECT 1 FROM public.vendor_correspondence_versions)
            OR EXISTS (SELECT 1 FROM public.vendor_artifacts)
            OR EXISTS (SELECT 1 FROM public.vendor_artifact_attempts)
            OR EXISTS (SELECT 1 FROM public.vendor_work)
            OR EXISTS (SELECT 1 FROM public.vendor_work_revisions)
            OR EXISTS (SELECT 1 FROM public.vendor_command_receipts)
            OR EXISTS (SELECT 1 FROM public.vendor_submit_claims)
            OR EXISTS (SELECT 1 FROM public.vendor_read_claims)
            OR EXISTS (SELECT 1 FROM public.vendor_event_candidates)
            OR EXISTS (SELECT 1 FROM public.vendor_provider_observations)
        THEN RAISE EXCEPTION 'vendor evidence prevents downgrade' USING ERRCODE='23514'; END IF;
    END $$""")
    op.execute(DOWNGRADE_DDL)


GUARD_DDL = r"""
ALTER TABLE public.follow_up_sources DROP CONSTRAINT ck_follow_up_source_kind;
ALTER TABLE public.follow_up_sources ADD CONSTRAINT ck_follow_up_source_kind CHECK (COALESCE(
  (source_kind IN ('reviewed_note','vendor_reviewed_note') AND note_id IS NOT NULL AND content_hash IS NOT NULL
   AND source_fingerprint IS NOT NULL AND prep_snapshot_sha256 IS NULL AND prep_receipt IS NULL)
  OR (source_kind = 'core_prep' AND note_id IS NULL AND content_hash IS NULL AND source_fingerprint IS NULL
   AND prep_snapshot_sha256 ~ '^[a-f0-9]{64}$' AND jsonb_typeof(prep_receipt) = 'object'
   AND prep_receipt->>'snapshot_sha256' = prep_snapshot_sha256 AND jsonb_typeof(prep_receipt->'sources') = 'array'
   AND jsonb_array_length(prep_receipt->'sources') <= 6 AND octet_length(prep_receipt::text) <= 262144), false));
ALTER TABLE public.follow_up_sources DROP CONSTRAINT uq_follow_up_revision;
CREATE UNIQUE INDEX uq_follow_up_revision ON public.follow_up_sources(workspace_id,workspace_revision)
  WHERE source_kind <> 'vendor_reviewed_note';
ALTER TABLE public.work_handoffs ADD COLUMN vendor_publication_receipt_id uuid;
ALTER TABLE public.work_handoffs ADD CONSTRAINT fk_handoff_vendor_publication
  FOREIGN KEY (vendor_publication_receipt_id,ticket_id,action_revision_id,box_id)
  REFERENCES public.vendor_command_receipts(id,ticket_id,action_revision_id,box_id);
ALTER TABLE public.vendor_work ADD CONSTRAINT fk_vendor_supersedes_scope
  FOREIGN KEY (supersedes_operation_id,workspace_id,box_id,owner_id,patient_link_id)
  REFERENCES public.vendor_work_revisions(intended_operation_id,workspace_id,box_id,owner_id,patient_link_id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE public.vendor_work_revisions ADD CONSTRAINT fk_vendor_media_scope
  FOREIGN KEY (uploaded_media_operation_id,workspace_id,box_id,owner_id,patient_link_id)
  REFERENCES public.vendor_work_revisions(intended_operation_id,workspace_id,box_id,owner_id,patient_link_id);
ALTER TABLE public.vendor_command_receipts ADD CONSTRAINT fk_vendor_result_receipt
  FOREIGN KEY (result_receipt_id,ticket_id,action_revision_id,box_id)
  REFERENCES public.vendor_command_receipts(id,ticket_id,action_revision_id,box_id);

CREATE FUNCTION public.vendor_private_version_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE allowed text[];
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'vendor evidence is immutable' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME = 'vendor_connection_versions' THEN allowed := ARRAY['is_current','read_enabled','write_enabled','revoked_at'];
  ELSE allowed := ARRAY['is_current','revoked_at']; END IF;
  IF (to_jsonb(NEW) - allowed) IS DISTINCT FROM (to_jsonb(OLD) - allowed)
     OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at)
  THEN RAISE EXCEPTION 'vendor private version is immutable' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME = 'vendor_connection_versions' THEN
    IF NEW.revoked_at IS NOT NULL AND (NEW.read_enabled OR NEW.write_enabled)
    THEN RAISE EXCEPTION 'revoked connector cannot be enabled' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER vendor_connection_private_immutable BEFORE UPDATE OR DELETE ON public.vendor_connection_versions
 FOR EACH ROW EXECUTE FUNCTION public.vendor_private_version_guard();
CREATE TRIGGER vendor_correspondence_private_immutable BEFORE UPDATE OR DELETE ON public.vendor_correspondence_versions
 FOR EACH ROW EXECUTE FUNCTION public.vendor_private_version_guard();

CREATE FUNCTION public.vendor_scoped_human_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.principals p WHERE p.id=NEW.owner_id AND p.box_id=NEW.box_id
    AND p.principal_type='human') THEN
    RAISE EXCEPTION 'vendor owner must be scoped human' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER vendor_connection_human BEFORE INSERT ON public.vendor_connection_versions FOR EACH ROW EXECUTE FUNCTION public.vendor_scoped_human_guard();
CREATE TRIGGER vendor_correspondence_human BEFORE INSERT ON public.vendor_correspondence_versions FOR EACH ROW EXECUTE FUNCTION public.vendor_scoped_human_guard();

CREATE FUNCTION public.vendor_work_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE tid uuid; f public.follow_up_sources; w public.vendor_work; t public.tickets; r public.vendor_work_revisions;
BEGIN
  IF TG_TABLE_NAME='tickets' THEN tid:=NEW.id; ELSE tid:=NEW.ticket_id; END IF;
  SELECT * INTO f FROM public.follow_up_sources WHERE ticket_id=tid;
  SELECT * INTO w FROM public.vendor_work WHERE ticket_id=tid;
  SELECT * INTO t FROM public.tickets WHERE id=tid;
  IF f.source_kind IS DISTINCT FROM 'vendor_reviewed_note' THEN
    IF w.ticket_id IS NOT NULL OR t.lane='encounter_vendor_delivery' THEN
      RAISE EXCEPTION 'vendor source kind required' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO r FROM public.vendor_work_revisions WHERE action_revision_id=w.origin_revision_id;
  IF w.ticket_id IS NULL OR r.action_revision_id IS NULL OR t.lane<>'encounter_vendor_delivery'
    OR (w.workspace_id,w.box_id,w.owner_id,w.origin_revision_id,w.origin_operation_id)
      IS DISTINCT FROM (f.workspace_id,f.box_id,f.owner_id,f.action_revision_id,r.intended_operation_id)
    OR (r.note_id,r.content_hash,r.source_fingerprint,r.payload_hash,r.source_workspace_revision)
      IS DISTINCT FROM (f.note_id,f.content_hash,f.source_fingerprint,f.payload_hash,f.workspace_revision)
    OR (t.box_id,t.created_by_principal_id,t.patient_link_id)
      IS DISTINCT FROM (w.box_id,w.owner_id,w.patient_link_id)
    OR NOT EXISTS(SELECT 1 FROM public.encounter_workspaces e WHERE e.id=w.workspace_id AND e.box_id=w.box_id
      AND e.owner_id=w.owner_id AND e.patient_link_id=w.patient_link_id AND e.appointment_id=t.appointment_id)
    OR NOT EXISTS(SELECT 1 FROM public.vendor_work_revisions c WHERE c.action_revision_id=t.current_revision_id AND c.ticket_id=tid)
  THEN RAISE EXCEPTION 'vendor work source binding mismatch' USING ERRCODE='23514'; END IF;
  IF EXISTS(SELECT 1 FROM public.vendor_work_revisions v JOIN public.action_revisions a ON a.id=v.action_revision_id
    WHERE v.ticket_id=tid AND (a.action_type <> 'vendor_delivery.'||v.action OR a.target_ref <> 'vendor_work:'||tid::text
      OR a.content <> 'Vendor delivery — private review' OR a.automation_class <> 'hitl_required'
      OR a.created_by_principal_id<>v.owner_id OR a.invalidated OR a.revision_number<>v.revision_number
      OR a.payload->>'private_command_sha256' IS DISTINCT FROM v.private_command_sha256
      OR a.payload->>'review_sha256' IS DISTINCT FROM v.review_sha256
      OR a.payload->>'request_sha256' IS DISTINCT FROM v.request_sha256
      OR a.payload->>'operation_id' IS DISTINCT FROM v.intended_operation_id::text))
  THEN RAISE EXCEPTION 'vendor action envelope mismatch' USING ERRCODE='23514'; END IF;
  IF w.supersedes_operation_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.vendor_submit_claims c
     WHERE c.operation_id=w.supersedes_operation_id)
  THEN RAISE EXCEPTION 'replacement must retain a spent operation' USING ERRCODE='23514'; END IF;
  IF EXISTS(SELECT 1 FROM public.vendor_work_revisions v JOIN public.vendor_work_revisions u
    ON u.intended_operation_id=v.uploaded_media_operation_id WHERE v.ticket_id=tid
    AND (u.action<>'spruce_media_upload' OR u.connection_version_id<>v.connection_version_id
      OR (u.note_id,u.content_hash,u.source_fingerprint) IS DISTINCT FROM (v.note_id,v.content_hash,v.source_fingerprint)
      OR NOT EXISTS(SELECT 1 FROM public.vendor_provider_observations o WHERE o.operation_id=u.intended_operation_id
        AND o.kind='submission' AND o.public_observation->>'acceptance'='accepted' AND o.private_reference IS NOT NULL)))
  THEN RAISE EXCEPTION 'media requires exact accepted upload' USING ERRCODE='23514'; END IF;
  IF t.state IN ('withdrawn','rejected','superseded') AND EXISTS(SELECT 1 FROM public.vendor_submit_claims c
    WHERE c.operation_id=(SELECT intended_operation_id FROM public.vendor_work_revisions WHERE action_revision_id=t.current_revision_id))
  THEN RAISE EXCEPTION 'spent vendor claim cannot be cancelled' USING ERRCODE='23514'; END IF;
  IF t.state='closed' AND NOT EXISTS(SELECT 1 FROM public.vendor_command_receipts q
     JOIN public.vendor_command_receipts result ON result.id=q.result_receipt_id
     WHERE q.ticket_id=tid AND q.action_revision_id=t.current_revision_id AND q.command_kind='verify'
       AND q.actor_id=w.owner_id AND result.command_kind='result'
       AND result.result_payload->>'disposition' IN ('reported_success','verified_in_vendor')
       AND NOT EXISTS(SELECT 1 FROM public.vendor_command_receipts n WHERE n.ticket_id=tid
         AND n.action_revision_id=t.current_revision_id AND n.command_kind IN ('result','reopen')
         AND n.effect_version>q.effect_version))
  THEN RAISE EXCEPTION 'vendor close requires current owner verification' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER vendor_source_binding AFTER INSERT OR UPDATE ON public.follow_up_sources DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vendor_work_binding_guard();
CREATE CONSTRAINT TRIGGER vendor_work_binding AFTER INSERT ON public.vendor_work DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vendor_work_binding_guard();
CREATE CONSTRAINT TRIGGER vendor_revision_binding AFTER INSERT ON public.vendor_work_revisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vendor_work_binding_guard();
CREATE CONSTRAINT TRIGGER vendor_ticket_binding AFTER INSERT OR UPDATE ON public.tickets DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vendor_work_binding_guard();

CREATE OR REPLACE FUNCTION public.reject_bound_follow_up_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS(SELECT 1 FROM public.follow_up_sources WHERE action_revision_id=OLD.id)
     OR EXISTS(SELECT 1 FROM public.vendor_work_revisions WHERE action_revision_id=OLD.id)
  THEN RAISE EXCEPTION 'source-bound action is immutable' USING ERRCODE='23514'; END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;

CREATE FUNCTION public.vendor_operation_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE oid uuid; o public.operations; r public.vendor_work_revisions; c public.vendor_submit_claims;
BEGIN
  IF TG_TABLE_NAME='operations' THEN oid:=NEW.id; ELSE oid:=NEW.operation_id; END IF;
  SELECT * INTO o FROM public.operations WHERE id=oid;
  SELECT * INTO r FROM public.vendor_work_revisions WHERE action_revision_id=o.action_revision_id;
  IF r.action_revision_id IS NULL THEN
    IF o.adapter='workspace_vendor' THEN RAISE EXCEPTION 'vendor revision required' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO c FROM public.vendor_submit_claims WHERE operation_id=oid;
  IF (o.id,o.ticket_id,o.box_id) IS DISTINCT FROM (r.intended_operation_id,r.ticket_id,r.box_id)
    OR o.adapter<>'workspace_vendor' OR o.external_reference IS NOT NULL
    OR o.idempotency_key<>'os-vendor:'||o.id::text OR o.attempt_count<>(CASE WHEN c.operation_id IS NULL THEN 0 ELSE 1 END)
    OR (c.operation_id IS NOT NULL AND o.status='pending')
    OR NOT EXISTS(SELECT 1 FROM public.decisions d WHERE d.ticket_id=o.ticket_id AND d.action_revision_id=r.action_revision_id
      AND d.box_id=r.box_id AND d.actor_principal_id=r.owner_id AND d.kind='approve')
    OR NOT EXISTS(SELECT 1 FROM public.vendor_command_receipts q WHERE q.ticket_id=o.ticket_id
      AND q.action_revision_id=r.action_revision_id AND q.command_kind='decide' AND q.actor_id=r.owner_id
      AND q.effect->'summary'->>'effect'='approved')
  THEN RAISE EXCEPTION 'vendor operation binding mismatch' USING ERRCODE='23514'; END IF;
  IF c.operation_id IS NOT NULL AND ((c.ticket_id,c.action_revision_id,c.box_id,c.workspace_id,c.owner_id)
    IS DISTINCT FROM (r.ticket_id,r.action_revision_id,r.box_id,r.workspace_id,r.owner_id)
    OR c.command_sha256<>r.private_command_sha256 OR c.source_sha256<>r.source_proof_sha256
    OR NOT EXISTS(SELECT 1 FROM public.vendor_command_receipts q WHERE q.id=c.approval_receipt_id
      AND q.command_kind='decide' AND q.public_request->>'choice'='approve')
    OR NOT EXISTS(SELECT 1 FROM public.vendor_command_receipts q WHERE q.id=c.command_receipt_id
      AND q.command_kind='submit' AND q.request_sha256=c.request_sha256))
  THEN RAISE EXCEPTION 'vendor claim approval mismatch' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER vendor_operation_binding AFTER INSERT OR UPDATE ON public.operations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vendor_operation_binding_guard();
CREATE CONSTRAINT TRIGGER vendor_submit_binding AFTER INSERT OR UPDATE ON public.vendor_submit_claims DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vendor_operation_binding_guard();

CREATE FUNCTION public.vendor_operation_mutation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.adapter='workspace_vendor' THEN
    IF TG_OP='DELETE' OR (to_jsonb(NEW)-ARRAY['status','attempt_count','result_receipt_hash','error_message','started_at','completed_at'])
      IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','attempt_count','result_receipt_hash','error_message','started_at','completed_at'])
      OR NEW.attempt_count<OLD.attempt_count OR NEW.attempt_count>1
    THEN RAISE EXCEPTION 'vendor operation identity is immutable' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;
CREATE TRIGGER vendor_operation_mutation BEFORE UPDATE OR DELETE ON public.operations FOR EACH ROW EXECUTE FUNCTION public.vendor_operation_mutation_guard();

CREATE FUNCTION public.vendor_submit_mutation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' OR (to_jsonb(NEW)-ARRAY['dispatch','invocation_started_at','completed_at','safe_error'])
    IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['dispatch','invocation_started_at','completed_at','safe_error'])
    OR OLD.completed_at IS NOT NULL
    OR (OLD.invocation_started_at IS NOT NULL AND NEW.invocation_started_at IS DISTINCT FROM OLD.invocation_started_at)
    OR (OLD.dispatch<>'not_started' AND NEW.dispatch='not_started')
    OR (OLD.dispatch IN ('proved_not_dispatched','response_observed') AND NEW.dispatch<>OLD.dispatch)
  THEN RAISE EXCEPTION 'vendor submit claim cannot reset' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER vendor_submit_mutation BEFORE UPDATE OR DELETE ON public.vendor_submit_claims FOR EACH ROW EXECUTE FUNCTION public.vendor_submit_mutation_guard();

CREATE FUNCTION public.vendor_read_mutation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' OR (to_jsonb(NEW)-ARRAY['state','completed_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','completed_at'])
    OR OLD.completed_at IS NOT NULL OR (OLD.state<>'admitted' AND NEW.state='admitted')
  THEN RAISE EXCEPTION 'vendor read claim cannot reset' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER vendor_read_mutation BEFORE UPDATE OR DELETE ON public.vendor_read_claims FOR EACH ROW EXECUTE FUNCTION public.vendor_read_mutation_guard();

-- The public protocol admits only bounded integers and ASCII object keys. Match
-- its UTF-8, sorted-key, separator-free encoding without requiring pgcrypto.
CREATE FUNCTION public.vendor_public_canonical(value jsonb, depth integer DEFAULT 0)
RETURNS text LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE encoded text; kind text:=jsonb_typeof(value);
BEGIN
  IF depth>30 THEN RAISE EXCEPTION 'vendor JSON depth exceeded' USING ERRCODE='23514'; END IF;
  IF kind='object' THEN
    IF EXISTS(SELECT 1 FROM jsonb_object_keys(value) k WHERE octet_length(k)<>char_length(k))
    THEN RAISE EXCEPTION 'vendor JSON key invalid' USING ERRCODE='23514'; END IF;
    SELECT '{'||coalesce(string_agg(to_jsonb(key)::text||':'||public.vendor_public_canonical(child,depth+1),',' ORDER BY key COLLATE "C"),'')||'}'
      INTO encoded FROM jsonb_each(value) AS fields(key,child);
  ELSIF kind='array' THEN
    SELECT '['||coalesce(string_agg(public.vendor_public_canonical(child,depth+1),',' ORDER BY ordinal),'')||']'
      INTO encoded FROM jsonb_array_elements(value) WITH ORDINALITY AS elements(child,ordinal);
  ELSIF kind='number' THEN
    encoded:=value::text;
    IF encoded !~ '^-?(0|[1-9][0-9]*)$' OR abs(encoded::numeric)>2147483647
    THEN RAISE EXCEPTION 'vendor JSON integer invalid' USING ERRCODE='23514'; END IF;
  ELSE encoded:=value::text;
  END IF;
  RETURN encoded;
END $$;
CREATE FUNCTION public.vendor_public_digest(domain_name text, value jsonb)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT encode(sha256(convert_to(public.vendor_public_canonical(jsonb_build_object('domain',domain_name,'value',value)),'UTF8')),'hex')
$$;

CREATE FUNCTION public.vendor_observation_head(oid uuid) RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT coalesce((SELECT jsonb_build_object('sequence',sequence,'sha256',head_sha256)
    FROM public.vendor_provider_observations WHERE operation_id=oid ORDER BY sequence DESC LIMIT 1),
    jsonb_build_object('sequence',0,'sha256',public.vendor_public_digest('cosmas-vendor-observation-head.v1',
      jsonb_build_object('operation_id',oid,'sequence',0))))
$$;

-- Current authority and evidence are checked once, when a receipt is inserted.
-- Deferred scope checks below must remain valid after later results/revisions.
CREATE FUNCTION public.vendor_receipt_current_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public.vendor_work_revisions; t public.tickets; result public.vendor_command_receipts;
  head jsonb; evidence text; projection jsonb; accepted boolean; rejected boolean;
  delivered boolean; failed boolean; conflict boolean; effect jsonb; receipt_hash text;
BEGIN
  IF NEW.command_kind<>'verify' AND NEW.publication_projection IS NULL THEN RETURN NEW; END IF;
  SELECT * INTO t FROM public.tickets WHERE id=NEW.ticket_id FOR UPDATE;
  SELECT * INTO r FROM public.vendor_work_revisions WHERE action_revision_id=NEW.action_revision_id;
  IF r.action_revision_id IS NULL OR t.current_revision_id IS DISTINCT FROM r.action_revision_id
    OR NEW.origin<>'user' OR NEW.actor_id IS DISTINCT FROM r.owner_id OR NEW.owner_id IS DISTINCT FROM r.owner_id
    OR NEW.effect_version IS DISTINCT FROM t.version
    OR NEW.public_request->>'operation_id' IS DISTINCT FROM r.intended_operation_id::text
    OR NEW.public_request->>'revision_id' IS DISTINCT FROM r.action_revision_id::text
    OR NEW.public_request->>'payload_hash' IS DISTINCT FROM r.payload_hash
    OR NEW.public_request->'expected_version' IS DISTINCT FROM to_jsonb(t.version-1)
    OR NEW.public_request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
  THEN RAISE EXCEPTION 'vendor current receipt mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.request_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-public-request.v1',
    jsonb_build_object('command_kind',NEW.command_kind,'scope',jsonb_build_object('kind',NEW.scope_kind,'id',NEW.scope_id),'request',NEW.public_request))
  THEN RAISE EXCEPTION 'vendor request hash mismatch' USING ERRCODE='23514'; END IF;
  effect:=jsonb_build_object('ticket_id',NEW.ticket_id,'operation_id',NEW.operation_id,'revision_id',NEW.action_revision_id,
    'payload_hash',r.payload_hash,'receipt_id',NEW.id,'effect_version',NEW.effect_version,
    'recorded_at',to_char(NEW.recorded_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
  receipt_hash:=public.vendor_public_digest('cosmas-vendor-public-receipt.v1',jsonb_build_object(
    'scope',jsonb_build_object('kind',NEW.scope_kind,'id',NEW.scope_id),'command_kind',NEW.command_kind,
    'idempotency_key',NEW.idempotency_key,'request_sha256',NEW.request_sha256,'effect',effect,'summary',NEW.effect->'summary'));
  IF NEW.effect->'effect' IS DISTINCT FROM effect||jsonb_build_object('receipt_sha256',receipt_hash)
    OR NEW.receipt_sha256 IS DISTINCT FROM receipt_hash
  THEN RAISE EXCEPTION 'vendor receipt hash mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.publication_projection IS NOT NULL THEN
    projection:=jsonb_build_object('body',r.public_review->'expected_outcome','due_date',r.public_review->'due_date',
      'expected_outcome',r.public_review->'expected_outcome','action',r.action,'account_label',r.public_review->'connection'->'label');
    IF NEW.command_kind NOT IN ('decide','publish') OR t.state<>'approved'
      OR NEW.publication_projection IS DISTINCT FROM projection
      OR NEW.publication_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-public-review.v1',projection)
      OR NEW.public_request->>'review_sha256' IS DISTINCT FROM r.review_sha256
      OR NEW.effect->'summary' IS DISTINCT FROM jsonb_build_object('effect',CASE WHEN NEW.command_kind='decide' THEN 'approved' ELSE 'published' END,'publication_recorded',true)
      OR (NEW.command_kind='decide' AND (NEW.public_request->>'choice' IS DISTINCT FROM 'approve'
        OR r.public_review->'share_to_practice' IS DISTINCT FROM 'true'::jsonb
        OR r.public_proposal->'share_to_practice' IS DISTINCT FROM 'true'::jsonb))
      OR (NEW.command_kind='publish' AND NEW.public_request->'share_to_practice' IS DISTINCT FROM 'true'::jsonb)
    THEN RAISE EXCEPTION 'vendor publication proof mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF NEW.command_kind='verify' THEN
    SELECT * INTO result FROM public.vendor_command_receipts WHERE action_revision_id=r.action_revision_id AND command_kind='result'
      ORDER BY effect_version DESC LIMIT 1;
    head:=public.vendor_observation_head(r.intended_operation_id);
    evidence:=public.vendor_public_digest('cosmas-vendor-evidence.v1',jsonb_build_object('operation_id',r.intended_operation_id,
      'observation_head',head,'result_receipt_id',result.id,'result_receipt_sha256',result.receipt_sha256));
    SELECT coalesce(bool_or(public_observation->>'acceptance'='accepted'),false),
      coalesce(bool_or(public_observation->>'acceptance'='rejected'),false),
      coalesce(bool_or(public_observation->>'transport'='delivered'),false),
      coalesce(bool_or(public_observation->>'transport'='failed'),false)
      INTO accepted,rejected,delivered,failed FROM public.vendor_provider_observations WHERE operation_id=r.intended_operation_id;
    conflict:=(accepted AND rejected) OR (delivered AND failed);
    IF t.state<>'closed' OR result.id IS NULL OR NEW.result_receipt_id IS DISTINCT FROM result.id
      OR NEW.public_request->>'result_receipt_id' IS DISTINCT FROM result.id::text
      OR NEW.public_request->>'result_receipt_sha256' IS DISTINCT FROM result.receipt_sha256
      OR NEW.public_request->'reviewed_result' IS DISTINCT FROM 'true'::jsonb
      OR NEW.public_request->'reviewed_observations' IS DISTINCT FROM 'true'::jsonb
      OR NEW.public_request->'outcome_confirmed' IS DISTINCT FROM 'true'::jsonb
      OR NEW.public_request->'reviewed_conflicting_evidence' IS DISTINCT FROM to_jsonb(conflict)
      OR NEW.public_request->'observation_head' IS DISTINCT FROM head
      OR NEW.observation_head_sha256 IS DISTINCT FROM head->>'sha256'
      OR NEW.public_request->>'evidence_sha256' IS DISTINCT FROM evidence OR NEW.evidence_sha256 IS DISTINCT FROM evidence
      OR NEW.effect->'summary' IS DISTINCT FROM jsonb_build_object('effect','verified','publication_recorded',false)
      OR result.result_payload->>'disposition' NOT IN ('reported_success','verified_in_vendor')
      OR ((conflict OR NOT accepted OR rejected OR NOT delivered OR failed)
        AND (result.result_payload->>'disposition' IS DISTINCT FROM 'verified_in_vendor' OR result.actor_id IS DISTINCT FROM NEW.owner_id))
    THEN RAISE EXCEPTION 'vendor verification proof mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER vendor_receipt_current BEFORE INSERT ON public.vendor_command_receipts FOR EACH ROW EXECUTE FUNCTION public.vendor_receipt_current_guard();

CREATE FUNCTION public.vendor_receipt_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public.vendor_work_revisions;
BEGIN
  IF NEW.scope_id IS DISTINCT FROM (CASE WHEN NEW.scope_kind='workspace' THEN NEW.workspace_id ELSE NEW.ticket_id END)
    OR (NEW.scope_kind='practice_work' AND NEW.command_kind NOT IN ('handoff','result'))
  THEN RAISE EXCEPTION 'vendor receipt scope mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.artifact_id IS NOT NULL THEN
    IF NEW.command_kind NOT IN ('artifact_intent','artifact_content') OR NEW.actor_id<>NEW.owner_id THEN
      RAISE EXCEPTION 'artifact command scope mismatch' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO r FROM public.vendor_work_revisions WHERE action_revision_id=NEW.action_revision_id;
  IF (NEW.workspace_id,NEW.box_id,NEW.owner_id) IS DISTINCT FROM (r.workspace_id,r.box_id,r.owner_id)
    OR (NEW.actor_id<>NEW.owner_id AND NEW.command_kind NOT IN ('handoff','result'))
    OR (NEW.publication_projection IS NOT NULL AND (NEW.command_kind NOT IN ('decide','publish') OR NEW.actor_id<>NEW.owner_id))
  THEN RAISE EXCEPTION 'vendor receipt work mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.command_kind='verify' AND (NEW.actor_id<>NEW.owner_id OR NOT EXISTS(
    SELECT 1 FROM public.vendor_command_receipts q WHERE q.id=NEW.result_receipt_id AND q.command_kind='result'
      AND (q.ticket_id,q.action_revision_id,q.operation_id,q.workspace_id,q.box_id,q.owner_id)
        IS NOT DISTINCT FROM (NEW.ticket_id,NEW.action_revision_id,NEW.operation_id,NEW.workspace_id,NEW.box_id,NEW.owner_id)
      AND q.result_payload->>'disposition' IN ('reported_success','verified_in_vendor')))
  THEN RAISE EXCEPTION 'vendor verification requires successful result' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER vendor_receipt_binding AFTER INSERT ON public.vendor_command_receipts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vendor_receipt_binding_guard();

CREATE FUNCTION public.vendor_handoff_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE f public.follow_up_sources; q public.vendor_command_receipts;
BEGIN
  SELECT * INTO f FROM public.follow_up_sources WHERE ticket_id=NEW.ticket_id;
  IF f.source_kind='vendor_reviewed_note' THEN
    SELECT * INTO q FROM public.vendor_command_receipts WHERE id=NEW.vendor_publication_receipt_id;
    IF q.id IS NULL OR q.publication_projection IS NULL
      OR (q.ticket_id,q.action_revision_id,q.box_id) IS DISTINCT FROM (NEW.ticket_id,NEW.action_revision_id,NEW.box_id)
      OR NOT EXISTS(SELECT 1 FROM public.vendor_work_revisions r WHERE r.action_revision_id=NEW.action_revision_id AND r.payload_hash=NEW.payload_hash)
    THEN RAISE EXCEPTION 'vendor handoff requires exact publication' USING ERRCODE='23514'; END IF;
    IF NEW.offer_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.work_handoffs h WHERE h.id=NEW.offer_id
      AND h.kind='offer' AND h.action_revision_id=NEW.action_revision_id AND h.payload_hash=NEW.payload_hash
      AND h.vendor_publication_receipt_id=NEW.vendor_publication_receipt_id AND h.from_id=NEW.from_id AND h.to_id=NEW.to_id)
    THEN RAISE EXCEPTION 'vendor handoff offer mismatch' USING ERRCODE='23514'; END IF;
  ELSIF NEW.vendor_publication_receipt_id IS NOT NULL THEN
    RAISE EXCEPTION 'legacy handoff cannot claim vendor publication' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER vendor_handoff_binding BEFORE INSERT ON public.work_handoffs FOR EACH ROW EXECUTE FUNCTION public.vendor_handoff_binding_guard();

CREATE FUNCTION public.vendor_no_legacy_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS(SELECT 1 FROM public.follow_up_sources WHERE ticket_id=NEW.ticket_id AND source_kind='vendor_reviewed_note')
  THEN RAISE EXCEPTION 'vendor work cannot acquire synthetic follow-up receipt' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER vendor_no_legacy_receipt BEFORE INSERT ON public.follow_up_receipts FOR EACH ROW EXECUTE FUNCTION public.vendor_no_legacy_receipt();

CREATE FUNCTION public.vendor_artifact_mutation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' OR (to_jsonb(NEW)-ARRAY['state','version','active_generation'])
    IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','version','active_generation'])
    OR NEW.version<=OLD.version OR NEW.active_generation<OLD.active_generation OR NEW.active_generation>OLD.active_generation+1
    OR (OLD.state='quarantined' AND NEW.state<>'quarantined')
    OR (OLD.state='ready' AND NEW.state NOT IN ('ready','quarantined'))
  THEN RAISE EXCEPTION 'artifact identity or fence cannot reset' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER vendor_artifact_mutation BEFORE UPDATE OR DELETE ON public.vendor_artifacts FOR EACH ROW EXECUTE FUNCTION public.vendor_artifact_mutation_guard();
CREATE FUNCTION public.vendor_artifact_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' OR (to_jsonb(NEW)-ARRAY['state','safe_error','completed_at'])
    IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','safe_error','completed_at']) OR OLD.completed_at IS NOT NULL
    OR (OLD.state<>'receiving' AND NEW.state='receiving')
  THEN RAISE EXCEPTION 'artifact attempt cannot reset' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER vendor_artifact_attempt_mutation BEFORE UPDATE OR DELETE ON public.vendor_artifact_attempts FOR EACH ROW EXECUTE FUNCTION public.vendor_artifact_attempt_guard();
CREATE FUNCTION public.vendor_artifact_ready_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE aid uuid; a public.vendor_artifacts;
BEGIN
  IF TG_TABLE_NAME='vendor_artifacts' THEN aid:=NEW.artifact_id; ELSE aid:=NEW.artifact_id; END IF;
  SELECT * INTO a FROM public.vendor_artifacts WHERE artifact_id=aid;
  IF a.active_generation>0 AND NOT EXISTS(SELECT 1 FROM public.vendor_artifact_attempts x
     WHERE x.artifact_id=aid AND x.generation=a.active_generation)
  THEN RAISE EXCEPTION 'artifact generation must be retained' USING ERRCODE='23514'; END IF;
  IF a.state='ready' AND (NOT EXISTS(SELECT 1 FROM public.vendor_artifact_attempts x
      WHERE x.artifact_id=aid AND x.generation=a.active_generation AND x.state='ready')
    OR NOT EXISTS(SELECT 1 FROM public.vendor_command_receipts q WHERE q.artifact_id=aid AND q.command_kind='artifact_content'))
  THEN RAISE EXCEPTION 'artifact ready requires exact content evidence' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER vendor_artifact_ready AFTER INSERT OR UPDATE ON public.vendor_artifacts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vendor_artifact_ready_guard();
CREATE CONSTRAINT TRIGGER vendor_artifact_attempt_ready AFTER INSERT OR UPDATE ON public.vendor_artifact_attempts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vendor_artifact_ready_guard();

CREATE FUNCTION public.vendor_observation_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public.vendor_work_revisions; head jsonb; digest text;
BEGIN
  -- Serialize the append chain with the same ticket lock used by application commands.
  PERFORM 1 FROM public.tickets WHERE id=NEW.ticket_id FOR UPDATE;
  SELECT * INTO r FROM public.vendor_work_revisions WHERE action_revision_id=NEW.action_revision_id;
  IF (NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.connection_version_id)
    IS DISTINCT FROM (r.workspace_id,r.box_id,r.owner_id,r.connection_version_id)
    OR (NEW.submit_claim_id IS NOT NULL AND NEW.submit_claim_id<>NEW.operation_id)
    OR (NEW.read_claim_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.vendor_read_claims c
      WHERE c.id=NEW.read_claim_id AND c.operation_id=NEW.operation_id AND c.connection_version_id=NEW.connection_version_id))
    OR (NEW.event_candidate_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.vendor_event_candidates c
      WHERE c.id=NEW.event_candidate_id AND c.connection_version_id=NEW.connection_version_id AND c.authenticity='signed'))
    OR NEW.public_observation->>'id' IS DISTINCT FROM NEW.id::text
    OR NEW.public_observation->>'operation_id' IS DISTINCT FROM NEW.operation_id::text
    OR NEW.public_observation->>'sequence' IS DISTINCT FROM NEW.sequence::text
    OR NEW.public_observation->>'kind' IS DISTINCT FROM NEW.kind
    OR NEW.public_observation->>'sha256' IS DISTINCT FROM NEW.public_sha256
  THEN RAISE EXCEPTION 'vendor observation claim mismatch' USING ERRCODE='23514'; END IF;
  head:=public.vendor_observation_head(NEW.operation_id);
  digest:=public.vendor_public_digest('cosmas-vendor-public-observation.v1',NEW.public_observation-'sha256');
  IF NEW.sequence IS DISTINCT FROM (head->>'sequence')::integer+1
    OR NEW.public_observation->'sequence' IS DISTINCT FROM to_jsonb(NEW.sequence)
    OR NEW.public_sha256 IS DISTINCT FROM digest
    OR NEW.head_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-observation-head.v1',
      jsonb_build_object('operation_id',NEW.operation_id,'sequence',NEW.sequence,'previous_sha256',head->>'sha256','observation_sha256',digest))
  THEN RAISE EXCEPTION 'vendor observation chain mismatch' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER vendor_observation_binding BEFORE INSERT ON public.vendor_provider_observations FOR EACH ROW EXECUTE FUNCTION public.vendor_observation_binding_guard();

CREATE FUNCTION public.vendor_closed_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE t public.tickets; verified public.vendor_command_receipts; boundary integer; prior_conflict boolean; current_conflict boolean;
BEGIN
  SELECT * INTO t FROM public.tickets WHERE id=NEW.ticket_id;
  IF t.state<>'closed' OR t.current_revision_id<>NEW.action_revision_id THEN RETURN NEW; END IF;
  SELECT * INTO verified FROM public.vendor_command_receipts WHERE action_revision_id=t.current_revision_id AND command_kind='verify'
    ORDER BY effect_version DESC LIMIT 1;
  boundary:=(verified.public_request->'observation_head'->>'sequence')::integer;
  SELECT coalesce(bool_or(public_observation->>'acceptance'='accepted') AND bool_or(public_observation->>'acceptance'='rejected'),false)
      OR coalesce(bool_or(public_observation->>'transport'='delivered') AND bool_or(public_observation->>'transport'='failed'),false),
    coalesce(bool_or(public_observation->>'acceptance'='accepted') FILTER (WHERE sequence<=boundary)
      AND bool_or(public_observation->>'acceptance'='rejected') FILTER (WHERE sequence<=boundary),false)
      OR coalesce(bool_or(public_observation->>'transport'='delivered') FILTER (WHERE sequence<=boundary)
      AND bool_or(public_observation->>'transport'='failed') FILTER (WHERE sequence<=boundary),false)
    INTO current_conflict,prior_conflict FROM public.vendor_provider_observations WHERE operation_id=NEW.operation_id;
  IF verified.id IS NULL OR (current_conflict AND NOT prior_conflict)
  THEN RAISE EXCEPTION 'vendor contradictory evidence requires reopen' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER vendor_closed_evidence AFTER INSERT ON public.vendor_provider_observations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vendor_closed_evidence_guard();

CREATE TRIGGER vendor_work_immutable BEFORE UPDATE OR DELETE ON public.vendor_work FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER vendor_work_revisions_immutable BEFORE UPDATE OR DELETE ON public.vendor_work_revisions FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER vendor_command_receipts_immutable BEFORE UPDATE OR DELETE ON public.vendor_command_receipts FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER vendor_event_candidates_immutable BEFORE UPDATE OR DELETE ON public.vendor_event_candidates FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER vendor_observations_immutable BEFORE UPDATE OR DELETE ON public.vendor_provider_observations FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
"""

DOWNGRADE_DDL = r"""
DROP TRIGGER vendor_closed_evidence ON public.vendor_provider_observations;
DROP TRIGGER vendor_observation_binding ON public.vendor_provider_observations;
DROP TRIGGER vendor_artifact_attempt_ready ON public.vendor_artifact_attempts;
DROP TRIGGER vendor_artifact_ready ON public.vendor_artifacts;
DROP TRIGGER vendor_artifact_attempt_mutation ON public.vendor_artifact_attempts;
DROP TRIGGER vendor_artifact_mutation ON public.vendor_artifacts;
DROP TRIGGER vendor_no_legacy_receipt ON public.follow_up_receipts;
DROP TRIGGER vendor_handoff_binding ON public.work_handoffs;
DROP TRIGGER vendor_receipt_binding ON public.vendor_command_receipts;
DROP TRIGGER vendor_receipt_current ON public.vendor_command_receipts;
DROP TRIGGER vendor_read_mutation ON public.vendor_read_claims;
DROP TRIGGER vendor_submit_mutation ON public.vendor_submit_claims;
DROP TRIGGER vendor_operation_mutation ON public.operations;
DROP TRIGGER vendor_submit_binding ON public.vendor_submit_claims;
DROP TRIGGER vendor_operation_binding ON public.operations;
DROP TRIGGER vendor_ticket_binding ON public.tickets;
DROP TRIGGER vendor_revision_binding ON public.vendor_work_revisions;
DROP TRIGGER vendor_work_binding ON public.vendor_work;
DROP TRIGGER vendor_source_binding ON public.follow_up_sources;
DROP TRIGGER vendor_connection_private_immutable ON public.vendor_connection_versions;
DROP TRIGGER vendor_correspondence_private_immutable ON public.vendor_correspondence_versions;
DROP TRIGGER vendor_connection_human ON public.vendor_connection_versions;
DROP TRIGGER vendor_correspondence_human ON public.vendor_correspondence_versions;
DROP FUNCTION public.vendor_observation_binding_guard();
DROP FUNCTION public.vendor_closed_evidence_guard();
DROP FUNCTION public.vendor_artifact_ready_guard();
DROP FUNCTION public.vendor_artifact_attempt_guard();
DROP FUNCTION public.vendor_artifact_mutation_guard();
DROP FUNCTION public.vendor_no_legacy_receipt();
DROP FUNCTION public.vendor_handoff_binding_guard();
DROP FUNCTION public.vendor_receipt_binding_guard();
DROP FUNCTION public.vendor_receipt_current_guard();
DROP FUNCTION public.vendor_observation_head(uuid);
DROP FUNCTION public.vendor_public_digest(text,jsonb);
DROP FUNCTION public.vendor_public_canonical(jsonb,integer);
DROP FUNCTION public.vendor_read_mutation_guard();
DROP FUNCTION public.vendor_submit_mutation_guard();
DROP FUNCTION public.vendor_operation_mutation_guard();
DROP FUNCTION public.vendor_operation_binding_guard();
DROP FUNCTION public.vendor_work_binding_guard();
DROP FUNCTION public.vendor_private_version_guard();
DROP FUNCTION public.vendor_scoped_human_guard();
CREATE OR REPLACE FUNCTION public.reject_bound_follow_up_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM public.follow_up_sources WHERE action_revision_id=OLD.id) THEN
  RAISE EXCEPTION 'follow-up action history is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;
ALTER TABLE public.work_handoffs DROP CONSTRAINT fk_handoff_vendor_publication, DROP COLUMN vendor_publication_receipt_id;
ALTER TABLE public.vendor_work DROP CONSTRAINT fk_vendor_supersedes_scope;
DROP TABLE public.vendor_provider_observations;
DROP TABLE public.vendor_read_claims;
DROP TABLE public.vendor_submit_claims;
DROP TABLE public.vendor_event_candidates;
DROP TABLE public.vendor_command_receipts;
DROP TABLE public.vendor_work_revisions;
DROP TABLE public.vendor_work;
DROP TABLE public.vendor_artifact_attempts;
DROP TABLE public.vendor_artifacts;
DROP TABLE public.vendor_correspondence_versions;
DROP TABLE public.vendor_connection_versions;
DROP INDEX public.uq_follow_up_revision;
ALTER TABLE public.follow_up_sources ADD CONSTRAINT uq_follow_up_revision UNIQUE(workspace_id,workspace_revision);
ALTER TABLE public.follow_up_sources DROP CONSTRAINT ck_follow_up_source_kind;
ALTER TABLE public.follow_up_sources ADD CONSTRAINT ck_follow_up_source_kind CHECK (COALESCE(
  (source_kind='reviewed_note' AND note_id IS NOT NULL AND content_hash IS NOT NULL AND source_fingerprint IS NOT NULL
   AND prep_snapshot_sha256 IS NULL AND prep_receipt IS NULL)
  OR (source_kind='core_prep' AND note_id IS NULL AND content_hash IS NULL AND source_fingerprint IS NULL
   AND prep_snapshot_sha256 ~ '^[a-f0-9]{64}$' AND jsonb_typeof(prep_receipt)='object'
   AND prep_receipt->>'snapshot_sha256'=prep_snapshot_sha256 AND jsonb_typeof(prep_receipt->'sources')='array'
   AND jsonb_array_length(prep_receipt->'sources')<=6 AND octet_length(prep_receipt::text)<=262144),false));
"""
