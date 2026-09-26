"""Private approved portal work on F8, with immutable evidence and once-ever claims."""

from alembic import op

revision = "e93a047b1c62"
down_revision = "d902e7c14b63"
branch_labels = None
depends_on = None
TABLE_DDL = r"""

CREATE TABLE portal_work (
	ticket_id UUID NOT NULL, 
	action_revision_id UUID NOT NULL, 
	operation_id UUID NOT NULL, 
	payload_hash VARCHAR(64) NOT NULL, 
	action VARCHAR(32) NOT NULL, 
	setup_connection_id UUID NOT NULL, 
	setup_revision_id UUID NOT NULL, 
	setup_version INTEGER NOT NULL, 
	artifact_id UUID NOT NULL, 
	uploaded_operation_id UUID, 
	private_command JSONB NOT NULL, 
	command_sha256 VARCHAR(64) NOT NULL, 
	proposal JSONB NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	review JSONB NOT NULL, 
	review_sha256 VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	note_id UUID NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	source_fingerprint VARCHAR(64) NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (ticket_id), 
	FOREIGN KEY(note_id, workspace_id, box_id, owner_id, content_hash, source_fingerprint) REFERENCES workspace_notes (id, workspace_id, box_id, owner_id, content_hash, source_fingerprint), 
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), 
	FOREIGN KEY(action_revision_id, ticket_id, box_id, payload_hash) REFERENCES action_revisions (id, ticket_id, box_id, payload_hash), 
	FOREIGN KEY(setup_revision_id, setup_connection_id, box_id, owner_id) REFERENCES portal_setup_revisions (id, connection_id, box_id, owner_id), 
	FOREIGN KEY(artifact_id, workspace_id, box_id, owner_id) REFERENCES vendor_artifacts (artifact_id, workspace_id, box_id, owner_id), 
	CONSTRAINT uq_portal_work_operation UNIQUE (operation_id), 
	CONSTRAINT uq_portal_work_op_scope UNIQUE (operation_id, workspace_id, box_id, owner_id), 
	CONSTRAINT uq_portal_work_scope UNIQUE (ticket_id, workspace_id, box_id, owner_id), 
	CONSTRAINT uq_portal_work_revision UNIQUE (action_revision_id), 
	FOREIGN KEY(uploaded_operation_id, workspace_id, box_id, owner_id) REFERENCES portal_work (operation_id, workspace_id, box_id, owner_id), 
	CHECK (action IN ('document.upload','referral.submit') AND setup_version>0), 
	CHECK ((action='document.upload' AND uploaded_operation_id IS NULL) OR (action='referral.submit' AND uploaded_operation_id IS NOT NULL)), 
	CHECK (payload_hash ~ '^[a-f0-9]{64}$' AND command_sha256 ~ '^[a-f0-9]{64}$' AND review_sha256 ~ '^[a-f0-9]{64}$' AND request_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(private_command) = 'object' AND octet_length(private_command::text) <= 32768), 
	CHECK (jsonb_typeof(proposal) = 'object' AND octet_length(proposal::text) <= 16384), 
	CHECK (jsonb_typeof(review) = 'object' AND octet_length(review::text) <= 16384)
)

;

CREATE TABLE portal_work_receipts (
	id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	command_kind VARCHAR(16) NOT NULL, 
	idempotency_key VARCHAR(100) NOT NULL, 
	request JSONB NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	response JSONB NOT NULL, 
	receipt_sha256 VARCHAR(64) NOT NULL, 
	recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ticket_id, workspace_id, box_id, owner_id) REFERENCES portal_work (ticket_id, workspace_id, box_id, owner_id), 
	CONSTRAINT uq_portal_work_receipt_key UNIQUE (workspace_id, owner_id, idempotency_key), 
	CONSTRAINT uq_portal_work_receipt_version UNIQUE (ticket_id, version), 
	CHECK (command_kind IN ('propose','decide','withdraw','submit','status','result','verify') AND version>0), 
	CHECK (request_sha256 ~ '^[a-f0-9]{64}$' AND receipt_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(request) = 'object' AND octet_length(request::text) <= 16384), 
	CHECK (jsonb_typeof(response) = 'object' AND octet_length(response::text) <= 8192)
)

;

CREATE TABLE portal_work_claims (
	id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	operation_id UUID NOT NULL, 
	receipt_id UUID NOT NULL, 
	mode VARCHAR(16) NOT NULL, 
	dispatch VARCHAR(16) NOT NULL, 
	claimed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	deadline TIMESTAMP WITH TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ticket_id, workspace_id, box_id, owner_id) REFERENCES portal_work (ticket_id, workspace_id, box_id, owner_id), 
	FOREIGN KEY(operation_id, ticket_id, box_id) REFERENCES operations (id, ticket_id, box_id), 
	FOREIGN KEY(receipt_id) REFERENCES portal_work_receipts (id), 
	CHECK (mode IN ('submit','status') AND dispatch IN ('claimed','invoking','settled') AND deadline>claimed_at), 
	CHECK ((dispatch='settled')=(completed_at IS NOT NULL))
)

;
CREATE UNIQUE INDEX uq_portal_work_once_submit ON portal_work_claims (operation_id) WHERE mode='submit';

CREATE TABLE portal_work_observations (
	id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	claim_id UUID NOT NULL, 
	sequence INTEGER NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	private_observation JSONB NOT NULL, 
	public_observation JSONB NOT NULL, 
	public_sha256 VARCHAR(64) NOT NULL, 
	head_sha256 VARCHAR(64) NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ticket_id, workspace_id, box_id, owner_id) REFERENCES portal_work (ticket_id, workspace_id, box_id, owner_id), 
	FOREIGN KEY(claim_id) REFERENCES portal_work_claims (id), 
	CONSTRAINT uq_portal_work_observation_sequence UNIQUE (ticket_id, sequence), 
	CONSTRAINT uq_portal_work_claim_observation UNIQUE (claim_id), 
	CHECK (sequence BETWEEN 1 AND 1000 AND kind IN ('submission','status','failure')), 
	CHECK (public_sha256 ~ '^[a-f0-9]{64}$' AND head_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(public_observation) = 'object' AND octet_length(public_observation::text) <= 4096), 
	CHECK (jsonb_typeof(private_observation) = 'object' AND octet_length(private_observation::text) <= 32768)
)

;

CREATE TABLE portal_work_reopens (
	id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	observation_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ticket_id, workspace_id, box_id, owner_id) REFERENCES portal_work (ticket_id, workspace_id, box_id, owner_id), 
	FOREIGN KEY(observation_id) REFERENCES portal_work_observations (id), 
	CONSTRAINT uq_portal_work_reopen_observation UNIQUE (observation_id)
)

;
"""
GUARDS = r"""
CREATE FUNCTION public.portal_work_head(tid uuid) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT coalesce((SELECT jsonb_build_object('sequence',sequence,'sha256',head_sha256) FROM portal_work_observations WHERE ticket_id=tid ORDER BY sequence DESC LIMIT 1),
  (SELECT jsonb_build_object('sequence',0,'sha256',vendor_public_digest('cosmas-portal-work-head.v1',jsonb_build_object('operation_id',operation_id,'sequence',0))) FROM portal_work WHERE ticket_id=tid))
$$;
CREATE FUNCTION public.portal_work_evidence(tid uuid) RETURNS text LANGUAGE sql STABLE AS $$
 SELECT vendor_public_digest('cosmas-portal-work-evidence.v1',jsonb_build_object('operation_id',w.operation_id,'observation_head',portal_work_head(tid),
  'result_receipt_id',r.id,'result_receipt_sha256',r.receipt_sha256)) FROM portal_work w LEFT JOIN LATERAL
  (SELECT * FROM portal_work_receipts WHERE ticket_id=tid AND command_kind='result' ORDER BY version DESC LIMIT 1) r ON true WHERE w.ticket_id=tid
$$;
CREATE FUNCTION public.portal_work_provider_met(tid uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM portal_work_observations WHERE ticket_id=tid AND public_observation->>'mode'='submit' AND public_observation->>'state'='accepted')
 AND NOT EXISTS(SELECT 1 FROM portal_work_observations WHERE ticket_id=tid AND public_observation->>'mode'='submit' AND public_observation->>'state'<>'accepted')
 AND ((SELECT action FROM portal_work WHERE ticket_id=tid)='document.upload' OR (
  (SELECT public_observation->>'state' FROM portal_work_observations WHERE ticket_id=tid AND public_observation->>'mode'='status' ORDER BY sequence DESC LIMIT 1)='received'
  AND NOT EXISTS(SELECT 1 FROM portal_work_observations WHERE ticket_id=tid AND public_observation->>'state'='declined')))
$$;
CREATE FUNCTION public.portal_work_row_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE t tickets; a action_revisions; p portal_setup_revisions; latest portal_setup_receipts; artifact vendor_artifacts;
BEGIN
 SELECT * INTO t FROM tickets WHERE id=NEW.ticket_id;
 SELECT * INTO a FROM action_revisions WHERE id=NEW.action_revision_id;
 SELECT * INTO p FROM portal_setup_revisions WHERE id=NEW.setup_revision_id;
 SELECT * INTO latest FROM portal_setup_receipts WHERE connection_id=NEW.setup_connection_id ORDER BY version DESC LIMIT 1;
 SELECT * INTO artifact FROM vendor_artifacts WHERE artifact_id=NEW.artifact_id;
 IF t.lane IS DISTINCT FROM 'encounter_portal_work' OR t.state IS DISTINCT FROM 'pending_approval' OR t.version<>1
  OR t.current_revision_id IS DISTINCT FROM NEW.action_revision_id OR t.created_by_principal_id<>NEW.owner_id
  OR latest.revision_id IS DISTINCT FROM NEW.setup_revision_id OR latest.version IS DISTINCT FROM NEW.setup_version OR latest.state IS DISTINCT FROM 'active'
  OR p.patient_link_id IS DISTINCT FROM t.patient_link_id OR artifact.state IS DISTINCT FROM 'ready'
  OR (artifact.note_id,artifact.content_hash,artifact.source_fingerprint) IS DISTINCT FROM (NEW.note_id,NEW.content_hash,NEW.source_fingerprint)
  OR a.content IS DISTINCT FROM 'Portal action — private review' OR a.action_type IS DISTINCT FROM 'portal_work.'||NEW.action
  OR a.target_ref IS DISTINCT FROM 'portal_work:'||NEW.ticket_id::text OR a.automation_class IS DISTINCT FROM 'hitl_required'
  OR NEW.command_sha256 IS DISTINCT FROM vendor_public_digest('cosmas-vendor-command.v1',NEW.private_command)
  OR NEW.private_command->>'operation_id' IS DISTINCT FROM NEW.operation_id::text OR NEW.private_command->>'revision_id' IS DISTINCT FROM NEW.action_revision_id::text
  OR NEW.private_command->'selection'->>'box_id' IS DISTINCT FROM NEW.box_id::text OR NEW.private_command->'selection'->>'owner_id' IS DISTINCT FROM NEW.owner_id::text
  OR NEW.private_command->'selection'->>'vendor' IS DISTINCT FROM 'portal' OR NEW.private_command->'selection'->>'environment' IS DISTINCT FROM 'sandbox'
  OR NEW.private_command->'intent'->>'kind' IS DISTINCT FROM NEW.action
  OR NEW.private_command->'intent'->>'portal_id' IS DISTINCT FROM p.portal_id
  OR NEW.private_command->'intent'->>'profile_sha256' IS DISTINCT FROM p.profile_sha256
  OR NEW.review_sha256 IS DISTINCT FROM vendor_public_digest('cosmas-portal-work-review.v1',NEW.review)
  OR NEW.review->'mappings' IS DISTINCT FROM p.review->'mappings'
  OR NEW.request_sha256 IS DISTINCT FROM vendor_public_digest('cosmas-portal-work-request.v1',jsonb_build_object('scope',jsonb_build_object('kind','workspace','id',NEW.workspace_id),'command_kind','propose','request',NEW.proposal))
  OR a.payload IS DISTINCT FROM jsonb_build_object('action','portal_work.'||NEW.action,'operation_id',NEW.operation_id,'command_sha256',NEW.command_sha256,'review_sha256',NEW.review_sha256,'request_sha256',NEW.request_sha256)
  OR NEW.payload_hash IS DISTINCT FROM encode(sha256(convert_to(vendor_public_canonical(a.payload),'UTF8')),'hex')
 THEN RAISE EXCEPTION 'portal work source binding' USING ERRCODE='23514'; END IF;
 IF NEW.action='referral.submit' AND NOT EXISTS(SELECT 1 FROM portal_work upload WHERE upload.operation_id=NEW.uploaded_operation_id
  AND upload.action='document.upload' AND upload.artifact_id=NEW.artifact_id AND upload.setup_revision_id=NEW.setup_revision_id
  AND (upload.note_id,upload.content_hash,upload.source_fingerprint)=(NEW.note_id,NEW.content_hash,NEW.source_fingerprint)
  AND portal_work_provider_met(upload.ticket_id)) THEN RAISE EXCEPTION 'accepted exact portal upload required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER portal_work_bound BEFORE INSERT ON portal_work FOR EACH ROW EXECUTE FUNCTION portal_work_row_guard();

CREATE FUNCTION public.portal_work_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE w portal_work; t tickets; r portal_work_receipts; prior portal_work_receipts; h jsonb; keys text[]; previous_version integer; previous_state text;
BEGIN
 SELECT * INTO w FROM portal_work WHERE ticket_id=NEW.ticket_id;
 SELECT * INTO t FROM tickets WHERE id=NEW.ticket_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM principals WHERE id=NEW.owner_id AND box_id=NEW.box_id AND principal_type='human' AND state='active' AND tombstoned_at IS NULL)
 THEN RAISE EXCEPTION 'current portal owner required' USING ERRCODE='23514'; END IF;
 SELECT * INTO prior FROM portal_work_receipts WHERE ticket_id=NEW.ticket_id ORDER BY version DESC LIMIT 1;
 previous_version:=coalesce(prior.version,0);previous_state:=prior.response->'effect'->>'state';
 IF EXISTS(SELECT 1 FROM portal_work_reopens WHERE ticket_id=NEW.ticket_id AND version>previous_version) THEN
  SELECT max(version) INTO previous_version FROM portal_work_reopens WHERE ticket_id=NEW.ticket_id;previous_state:='approved';
 END IF;
 IF NEW.version<>previous_version+1
  OR (NEW.command_kind='propose' AND t.state<>'pending_approval')
  OR (NEW.command_kind='decide' AND previous_state IS DISTINCT FROM 'pending_approval')
  OR (NEW.command_kind='withdraw' AND (previous_state NOT IN ('pending_approval','approved') OR t.state<>'cancelled' OR EXISTS(SELECT 1 FROM portal_work_claims WHERE ticket_id=NEW.ticket_id AND mode='submit')))
  OR (NEW.command_kind IN ('submit','result') AND (previous_state IS DISTINCT FROM 'approved' OR t.state<>'approved'))
  OR (NEW.command_kind='status' AND (previous_state NOT IN ('approved','closed') OR t.state IS DISTINCT FROM previous_state))
  OR (NEW.command_kind='verify' AND (previous_state IS DISTINCT FROM 'approved' OR t.state<>'closed'))
 THEN RAISE EXCEPTION 'portal state transition' USING ERRCODE='23514'; END IF;
 keys:=ARRAY['expected_version','revision_id','operation_id','payload_hash','idempotency_key'];
 IF NEW.command_kind='propose' THEN
  IF NEW.request IS DISTINCT FROM w.proposal OR NEW.version<>1 THEN RAISE EXCEPTION 'portal proposal receipt' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.request->'expected_version' IS DISTINCT FROM to_jsonb(NEW.version-1) OR NEW.request->>'revision_id' IS DISTINCT FROM w.action_revision_id::text
   OR NEW.request->>'operation_id' IS DISTINCT FROM w.operation_id::text OR NEW.request->>'payload_hash' IS DISTINCT FROM w.payload_hash
  THEN RAISE EXCEPTION 'portal exact command binding' USING ERRCODE='23514'; END IF;
  IF NEW.command_kind='decide' THEN
   keys:=keys||ARRAY['review_sha256','choice','reviewed_document','reviewed_mapping','reviewed_action'];
   IF NEW.request->>'review_sha256' IS DISTINCT FROM w.review_sha256 OR NEW.request->'reviewed_document' IS DISTINCT FROM 'true'::jsonb
    OR NEW.request->'reviewed_mapping' IS DISTINCT FROM 'true'::jsonb OR NEW.request->'reviewed_action' IS DISTINCT FROM 'true'::jsonb
    OR t.state IS DISTINCT FROM (CASE NEW.request->>'choice' WHEN 'approve' THEN 'approved' WHEN 'reject' THEN 'rejected' END)
   THEN RAISE EXCEPTION 'explicit portal review required' USING ERRCODE='23514'; END IF;
  ELSIF NEW.command_kind IN ('result','verify') THEN
   keys:=keys||ARRAY['observation_head','evidence_sha256'];h:=portal_work_head(NEW.ticket_id);
   IF NEW.request->'observation_head' IS DISTINCT FROM h OR NEW.request->>'evidence_sha256' IS DISTINCT FROM portal_work_evidence(NEW.ticket_id)
   THEN RAISE EXCEPTION 'current portal evidence required' USING ERRCODE='23514'; END IF;
   IF NEW.command_kind='result' THEN keys:=keys||ARRAY['disposition','evidence'];
   ELSE
    keys:=keys||ARRAY['result_receipt_id','result_receipt_sha256','reviewed_result','reviewed_observations','outcome_confirmed'];
    SELECT * INTO r FROM portal_work_receipts WHERE ticket_id=NEW.ticket_id AND command_kind='result' ORDER BY version DESC LIMIT 1;
    IF r.id IS NULL OR NEW.request->>'result_receipt_id' IS DISTINCT FROM r.id::text OR NEW.request->>'result_receipt_sha256' IS DISTINCT FROM r.receipt_sha256
     OR r.request->>'disposition' IS DISTINCT FROM 'verified_in_portal' OR r.request->'observation_head' IS DISTINCT FROM h
     OR NEW.request->'reviewed_result' IS DISTINCT FROM 'true'::jsonb OR NEW.request->'reviewed_observations' IS DISTINCT FROM 'true'::jsonb
     OR NEW.request->'outcome_confirmed' IS DISTINCT FROM 'true'::jsonb OR portal_work_provider_met(NEW.ticket_id) IS DISTINCT FROM true
    THEN RAISE EXCEPTION 'unambiguous owner-verified portal result required' USING ERRCODE='23514'; END IF;
   END IF;
  END IF;
  IF NOT portal_setup_keys(NEW.request,keys) THEN RAISE EXCEPTION 'closed portal command required' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.version<>t.version OR NEW.request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
  OR NEW.request_sha256 IS DISTINCT FROM vendor_public_digest('cosmas-portal-work-request.v1',jsonb_build_object('scope',jsonb_build_object('kind','workspace','id',NEW.workspace_id),'command_kind',NEW.command_kind,'request',NEW.request))
  OR NEW.receipt_sha256 IS DISTINCT FROM vendor_public_digest('cosmas-portal-work-receipt.v1',NEW.response-'receipt_sha256')
  OR NEW.response->>'receipt_sha256' IS DISTINCT FROM NEW.receipt_sha256
  OR NEW.response->'scope' IS DISTINCT FROM jsonb_build_object('kind','workspace','id',NEW.workspace_id)
  OR NEW.response->>'request_sha256' IS DISTINCT FROM NEW.request_sha256 OR NEW.response->>'command_kind' IS DISTINCT FROM NEW.command_kind
  OR NEW.response->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key OR NEW.response->>'outcome' IS DISTINCT FROM 'recorded'
  OR NEW.response->'effect'->>'ticket_id' IS DISTINCT FROM NEW.ticket_id::text OR NEW.response->'effect'->>'receipt_id' IS DISTINCT FROM NEW.id::text
  OR NEW.response->'effect'->>'operation_id' IS DISTINCT FROM w.operation_id::text OR NEW.response->'effect'->>'revision_id' IS DISTINCT FROM w.action_revision_id::text
  OR NEW.response->'effect'->>'payload_hash' IS DISTINCT FROM w.payload_hash OR NEW.response->'effect'->'version' IS DISTINCT FROM to_jsonb(NEW.version)
  OR NEW.response->'effect'->>'state' IS DISTINCT FROM t.state
 THEN RAISE EXCEPTION 'portal receipt integrity' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER portal_work_receipt_binding BEFORE INSERT ON portal_work_receipts FOR EACH ROW EXECUTE FUNCTION portal_work_receipt_guard();

CREATE FUNCTION public.portal_work_claim_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE w portal_work; t tickets; op operations; r portal_work_receipts;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'portal claim retained' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['dispatch','completed_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['dispatch','completed_at'])
   OR OLD.dispatch='settled' OR (OLD.dispatch='invoking' AND NEW.dispatch='claimed')
  THEN RAISE EXCEPTION 'portal claim immutable' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO w FROM portal_work WHERE ticket_id=NEW.ticket_id; SELECT * INTO t FROM tickets WHERE id=NEW.ticket_id;
 SELECT * INTO op FROM operations WHERE id=NEW.operation_id; SELECT * INTO r FROM portal_work_receipts WHERE id=NEW.receipt_id;
 IF NEW.operation_id IS DISTINCT FROM w.operation_id OR op.adapter IS DISTINCT FROM 'workspace_portal' OR op.action_revision_id IS DISTINCT FROM w.action_revision_id
  OR r.ticket_id IS DISTINCT FROM NEW.ticket_id OR r.command_kind IS DISTINCT FROM NEW.mode OR r.version IS DISTINCT FROM t.version
  OR NEW.dispatch<>'claimed' OR NEW.completed_at IS NOT NULL OR NEW.deadline>NEW.claimed_at+interval '45 seconds'
  OR (NEW.mode='submit' AND (t.state<>'approved' OR op.attempt_count<>1 OR NEW.claimed_at>=w.expires_at))
  OR (NEW.mode='status' AND w.action<>'referral.submit')
 THEN RAISE EXCEPTION 'portal admission binding' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER portal_work_claim_binding BEFORE INSERT OR UPDATE OR DELETE ON portal_work_claims FOR EACH ROW EXECUTE FUNCTION portal_work_claim_guard();

CREATE FUNCTION public.portal_work_observation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE w portal_work; claim portal_work_claims; previous jsonb; body jsonb; ref jsonb;
BEGIN
 SELECT * INTO w FROM portal_work WHERE ticket_id=NEW.ticket_id; PERFORM 1 FROM tickets WHERE id=NEW.ticket_id FOR UPDATE;
 SELECT * INTO claim FROM portal_work_claims WHERE id=NEW.claim_id;
 previous:=portal_work_head(NEW.ticket_id);body:=NEW.public_observation-'sha256';
 IF claim.ticket_id IS DISTINCT FROM NEW.ticket_id OR claim.completed_at IS NOT NULL
  OR NEW.sequence<>(previous->>'sequence')::integer+1 OR NEW.public_observation->>'mode' IS DISTINCT FROM claim.mode
  OR NEW.public_observation->>'id' IS DISTINCT FROM NEW.id::text OR NEW.public_observation->'sequence' IS DISTINCT FROM to_jsonb(NEW.sequence)
  OR NEW.public_observation->>'operation_id' IS DISTINCT FROM w.operation_id::text OR NEW.public_observation->>'kind' IS DISTINCT FROM NEW.kind
  OR NEW.public_sha256 IS DISTINCT FROM vendor_public_digest('cosmas-portal-work-observation.v1',body) OR NEW.public_observation->>'sha256' IS DISTINCT FROM NEW.public_sha256
  OR NEW.head_sha256 IS DISTINCT FROM vendor_public_digest('cosmas-portal-work-head.v1',jsonb_build_object('operation_id',w.operation_id,'sequence',NEW.sequence,'previous_sha256',previous->>'sha256','observation_sha256',NEW.public_sha256))
  OR NOT portal_setup_keys(NEW.public_observation,ARRAY['id','sequence','operation_id','kind','mode','state','observed_at','sha256'])
 THEN RAISE EXCEPTION 'portal observation chain' USING ERRCODE='23514'; END IF;
 IF NEW.kind='failure' THEN
  IF NEW.public_observation->>'state'<>'unknown' OR NOT portal_setup_keys(NEW.private_observation,ARRAY['safe_error'])
  THEN RAISE EXCEPTION 'portal failure evidence' USING ERRCODE='23514'; END IF;
 ELSE
  ref:=NEW.private_observation->'reference';
  IF NEW.public_observation->>'state' IS DISTINCT FROM NEW.private_observation->>'state'
   OR (NEW.kind='submission' AND (claim.mode<>'submit' OR NEW.private_observation->>'operation_id' IS DISTINCT FROM w.operation_id::text
     OR NEW.private_observation->>'request_sha256' IS DISTINCT FROM w.command_sha256 OR NEW.private_observation->>'vendor' IS DISTINCT FROM 'portal'
     OR NEW.private_observation->>'connection_id' IS DISTINCT FROM w.private_command->'selection'->>'connection_id'))
   OR (NEW.kind='status' AND (claim.mode<>'status' OR NOT EXISTS(SELECT 1 FROM portal_work_observations WHERE ticket_id=w.ticket_id AND kind='submission' AND private_observation->'reference'=ref)))
  THEN RAISE EXCEPTION 'portal provider evidence mismatch' USING ERRCODE='23514'; END IF;
  IF (NEW.kind='submission' AND NEW.public_observation->>'state'='accepted') OR NEW.kind='status' THEN
   IF ref->>'operation_id' IS DISTINCT FROM w.operation_id::text OR ref->>'request_sha256' IS DISTINCT FROM w.command_sha256
    OR ref->>'connection_id' IS DISTINCT FROM w.private_command->'selection'->>'connection_id'
    OR ref->>'portal_id' IS DISTINCT FROM w.private_command->'intent'->>'portal_id'
    OR ref->>'portal_profile_sha256' IS DISTINCT FROM w.private_command->'intent'->>'profile_sha256'
    OR ref->>'kind' IS DISTINCT FROM (CASE w.action WHEN 'document.upload' THEN 'portal_document' ELSE 'portal_referral' END)
   THEN RAISE EXCEPTION 'portal reference binding' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER portal_work_observation_binding BEFORE INSERT ON portal_work_observations FOR EACH ROW EXECUTE FUNCTION portal_work_observation_guard();

CREATE FUNCTION public.portal_work_f8_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE tid uuid; w portal_work; t tickets; v portal_work_receipts; latest_result portal_work_receipts;
BEGIN
 IF TG_TABLE_NAME='tickets' THEN tid:=NEW.id; ELSE tid:=NEW.ticket_id; END IF;
 SELECT * INTO w FROM portal_work WHERE ticket_id=tid; SELECT * INTO t FROM tickets WHERE id=tid;
 IF w.ticket_id IS NULL THEN
  IF t.lane='encounter_portal_work' THEN RAISE EXCEPTION 'private portal binding required' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF t.lane<>'encounter_portal_work' OR t.current_revision_id<>w.action_revision_id OR t.created_by_principal_id<>w.owner_id
  OR t.state NOT IN ('pending_approval','approved','rejected','cancelled','closed')
  OR NOT (EXISTS(SELECT 1 FROM portal_work_receipts WHERE ticket_id=tid AND version=t.version) OR EXISTS(SELECT 1 FROM portal_work_reopens WHERE ticket_id=tid AND version=t.version))
 THEN RAISE EXCEPTION 'portal F8 state binding' USING ERRCODE='23514'; END IF;
 IF t.state='closed' THEN
  SELECT * INTO v FROM portal_work_receipts WHERE ticket_id=tid AND command_kind='verify' ORDER BY version DESC LIMIT 1;
  SELECT * INTO latest_result FROM portal_work_receipts WHERE ticket_id=tid AND command_kind='result' ORDER BY version DESC LIMIT 1;
  IF v.id IS NULL OR v.request->'observation_head' IS DISTINCT FROM portal_work_head(tid)
   OR v.request->>'result_receipt_id' IS DISTINCT FROM latest_result.id::text OR latest_result.request->>'disposition' IS DISTINCT FROM 'verified_in_portal'
   OR portal_work_provider_met(tid) IS DISTINCT FROM true THEN RAISE EXCEPTION 'portal completion must remain verified' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER portal_work_ticket_binding AFTER INSERT OR UPDATE ON tickets DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION portal_work_f8_guard();
CREATE CONSTRAINT TRIGGER portal_work_fact_binding AFTER INSERT ON portal_work_observations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION portal_work_f8_guard();

CREATE FUNCTION public.portal_work_operation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE w portal_work;
BEGIN
 IF TG_OP='DELETE' THEN
  IF EXISTS(SELECT 1 FROM portal_work WHERE operation_id=OLD.id) THEN RAISE EXCEPTION 'portal operation retained' USING ERRCODE='23514'; END IF;
  RETURN OLD;
 END IF;
 SELECT * INTO w FROM portal_work WHERE operation_id=NEW.id;
 IF w.ticket_id IS NULL THEN RETURN NEW; END IF;
 IF NEW.adapter<>'workspace_portal' OR NEW.ticket_id<>w.ticket_id OR NEW.action_revision_id<>w.action_revision_id OR NEW.box_id<>w.box_id OR NEW.attempt_count NOT BETWEEN 0 AND 1
 THEN RAISE EXCEPTION 'portal operation binding' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['status','attempt_count','started_at','completed_at','result_receipt_hash','error_message']) IS DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['status','attempt_count','started_at','completed_at','result_receipt_hash','error_message']) OR NEW.attempt_count<OLD.attempt_count
  THEN RAISE EXCEPTION 'portal operation identity or attempt cannot reset' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER portal_work_operation_immutable BEFORE INSERT OR UPDATE OR DELETE ON operations FOR EACH ROW EXECUTE FUNCTION portal_work_operation_guard();

CREATE FUNCTION public.portal_work_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM portal_work WHERE action_revision_id=OLD.id) THEN RAISE EXCEPTION 'portal action immutable' USING ERRCODE='23514'; END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER portal_work_action_immutable BEFORE UPDATE OR DELETE ON action_revisions FOR EACH ROW EXECUTE FUNCTION portal_work_action_guard();
"""


def upgrade():
    op.execute(TABLE_DDL)
    op.execute(GUARDS)
    for name in (
        "portal_work",
        "portal_work_receipts",
        "portal_work_observations",
        "portal_work_reopens",
    ):
        op.execute(
            f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION reject_workspace_history_change()"
        )


def downgrade():
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM portal_work) THEN RAISE EXCEPTION 'portal work history prevents downgrade'; END IF; END $$"
    )
    op.execute(
        "DROP TRIGGER portal_work_action_immutable ON action_revisions; DROP TRIGGER portal_work_ticket_binding ON tickets; DROP TRIGGER portal_work_operation_immutable ON operations"
    )
    op.execute(
        "DROP TABLE portal_work_reopens,portal_work_observations,portal_work_claims,portal_work_receipts,portal_work"
    )
    op.execute(
        "DROP FUNCTION portal_work_operation_guard(),portal_work_action_guard(),portal_work_f8_guard(),portal_work_observation_guard(),portal_work_claim_guard(),portal_work_receipt_guard(),portal_work_row_guard(),portal_work_provider_met(uuid),portal_work_evidence(uuid),portal_work_head(uuid)"
    )
