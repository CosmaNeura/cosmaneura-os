"""Private reviewed payment requests and retained Stripe evidence on F8."""
from alembic import op

revision = "8ab4d11ce208"
down_revision = "5cb26e13a7d9"
branch_labels = None
depends_on = None

def upgrade():
    op.execute(TABLE_DDL)
    op.execute(GUARD_DDL)

def downgrade():
    op.execute(PREFLIGHT_DDL)
    op.execute(DOWNGRADE_DDL)

TABLE_DDL = r"""
CREATE TABLE finance_connection_versions (
	id UUID NOT NULL, 
	family_id UUID NOT NULL, 
	revision INTEGER NOT NULL, 
	environment VARCHAR(16) NOT NULL, 
	private_selection JSONB NOT NULL, 
	private_sha256 VARCHAR(64) NOT NULL, 
	public_view JSONB NOT NULL, 
	public_sha256 VARCHAR(64) NOT NULL, 
	reviewed_by UUID NOT NULL, 
	reviewed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	is_current BOOLEAN DEFAULT true NOT NULL, 
	write_enabled BOOLEAN DEFAULT false NOT NULL, 
	read_enabled BOOLEAN DEFAULT false NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id, box_id) REFERENCES principals (id, box_id), 
	CONSTRAINT uq_finance_connection_scope UNIQUE (id, box_id, owner_id), 
	CONSTRAINT uq_finance_connection_revision UNIQUE (family_id, revision), 
	CHECK (revision > 0 AND reviewed_by = owner_id AND environment IN ('production','sandbox')), 
	CHECK (private_sha256 ~ '^[a-f0-9]{64}$' AND public_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(private_selection) = 'object' AND octet_length(private_selection::text) <= 8192), 
	CHECK (jsonb_typeof(public_view) = 'object' AND octet_length(public_view::text) <= 4096)
);

CREATE UNIQUE INDEX uq_finance_connection_current ON finance_connection_versions (box_id, owner_id, family_id) WHERE is_current;

CREATE TABLE finance_customer_versions (
	id UUID NOT NULL, 
	family_id UUID NOT NULL, 
	revision INTEGER NOT NULL, 
	patient_link_id UUID NOT NULL, 
	connection_version_id UUID NOT NULL, 
	customer_id VARCHAR(255) NOT NULL, 
	mapping_sha256 VARCHAR(64) NOT NULL, 
	public_view JSONB NOT NULL, 
	public_sha256 VARCHAR(64) NOT NULL, 
	reviewed_by UUID NOT NULL, 
	reviewed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	is_current BOOLEAN DEFAULT true NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(connection_version_id, box_id, owner_id) REFERENCES finance_connection_versions (id, box_id, owner_id), 
	FOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id), 
	CONSTRAINT uq_finance_customer_scope UNIQUE (id, connection_version_id, patient_link_id, box_id, owner_id), 
	CONSTRAINT uq_finance_customer_revision UNIQUE (family_id, revision), 
	CHECK (revision > 0 AND reviewed_by = owner_id AND customer_id ~ '^cus_[A-Za-z0-9]+$'), 
	CHECK (mapping_sha256 ~ '^[a-f0-9]{64}$' AND public_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(public_view) = 'object' AND octet_length(public_view::text) <= 4096)
);

CREATE UNIQUE INDEX uq_finance_customer_current ON finance_customer_versions (box_id, owner_id, family_id) WHERE is_current;

CREATE TABLE finance_event_candidates (
	id UUID NOT NULL, 
	connection_version_id UUID NOT NULL, 
	route_id UUID NOT NULL, 
	body_sha256 VARCHAR(64) NOT NULL, 
	correlation JSONB NOT NULL, 
	received_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(connection_version_id, box_id, owner_id) REFERENCES finance_connection_versions (id, box_id, owner_id), 
	CONSTRAINT uq_finance_event_candidate UNIQUE (connection_version_id, body_sha256), 
	CHECK (body_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(correlation) = 'object' AND octet_length(correlation::text) <= 4096)
);

CREATE TABLE finance_work_revisions (
	action_revision_id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	patient_link_id UUID NOT NULL, 
	revision_number INTEGER NOT NULL, 
	source_workspace_revision INTEGER NOT NULL, 
	intended_operation_id UUID NOT NULL, 
	connection_version_id UUID NOT NULL, 
	customer_version_id UUID NOT NULL, 
	amount INTEGER NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	payload_hash VARCHAR(64) NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	review_sha256 VARCHAR(64) NOT NULL, 
	private_command_sha256 VARCHAR(64) NOT NULL, 
	private_command JSONB NOT NULL, 
	public_proposal JSONB NOT NULL, 
	public_review JSONB NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	note_id UUID NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	source_fingerprint VARCHAR(64) NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (action_revision_id), 
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), 
	FOREIGN KEY(note_id, workspace_id, box_id, owner_id, content_hash, source_fingerprint) REFERENCES workspace_notes (id, workspace_id, box_id, owner_id, content_hash, source_fingerprint), 
	FOREIGN KEY(note_id) REFERENCES workspace_note_reviews (note_id), 
	FOREIGN KEY(action_revision_id, ticket_id, box_id, payload_hash) REFERENCES action_revisions (id, ticket_id, box_id, payload_hash), 
	FOREIGN KEY(customer_version_id, connection_version_id, patient_link_id, box_id, owner_id) REFERENCES finance_customer_versions (id, connection_version_id, patient_link_id, box_id, owner_id), 
	CONSTRAINT uq_finance_intended_operation UNIQUE (intended_operation_id), 
	CONSTRAINT uq_finance_ticket_revision UNIQUE (ticket_id, revision_number), 
	CONSTRAINT uq_finance_revision_scope UNIQUE (action_revision_id, ticket_id, box_id), 
	CONSTRAINT uq_finance_operation_revision UNIQUE (intended_operation_id, action_revision_id, ticket_id, box_id), 
	CHECK (revision_number BETWEEN 1 AND 20 AND source_workspace_revision > 0 AND amount BETWEEN 50 AND 99999999 AND currency='usd'), 
	CHECK (payload_hash ~ '^[a-f0-9]{64}$' AND request_sha256 ~ '^[a-f0-9]{64}$' AND review_sha256 ~ '^[a-f0-9]{64}$' AND private_command_sha256 ~ '^[a-f0-9]{64}$' AND content_hash ~ '^[a-f0-9]{64}$' AND source_fingerprint ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(private_command) = 'object' AND octet_length(private_command::text) <= 16384), 
	CHECK (jsonb_typeof(public_proposal) = 'object' AND octet_length(public_proposal::text) <= 16384), 
	CHECK (jsonb_typeof(public_review) = 'object' AND octet_length(public_review::text) <= 16384)
);

CREATE TABLE finance_command_receipts (
	id UUID NOT NULL, 
	actor_id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	action_revision_id UUID NOT NULL, 
	operation_id UUID NOT NULL, 
	command_kind VARCHAR(24) NOT NULL, 
	idempotency_key VARCHAR(100) NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	public_request JSONB NOT NULL, 
	effect_version INTEGER NOT NULL, 
	effect JSONB NOT NULL, 
	receipt_sha256 VARCHAR(64) NOT NULL, 
	result_payload JSONB, 
	result_receipt_id UUID, 
	observation_head_sha256 VARCHAR(64), 
	evidence_sha256 VARCHAR(64), 
	recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(operation_id, action_revision_id, ticket_id, box_id) REFERENCES finance_work_revisions (intended_operation_id, action_revision_id, ticket_id, box_id), 
	FOREIGN KEY(result_receipt_id, ticket_id, action_revision_id, box_id) REFERENCES finance_command_receipts (id, ticket_id, action_revision_id, box_id), 
	FOREIGN KEY(actor_id, box_id) REFERENCES principals (id, box_id), 
	CONSTRAINT uq_finance_command_key UNIQUE (workspace_id, actor_id, idempotency_key), 
	CONSTRAINT uq_finance_receipt_scope UNIQUE (id, ticket_id, action_revision_id, box_id), 
	CHECK (actor_id=owner_id AND command_kind IN ('propose','decide','withdraw','submit','reconcile','result','verify') AND effect_version>0 AND idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'), 
	CHECK (request_sha256 ~ '^[a-f0-9]{64}$' AND receipt_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(public_request) = 'object' AND octet_length(public_request::text) <= 16384), 
	CHECK (jsonb_typeof(effect) = 'object' AND octet_length(effect::text) <= 8192)
);

CREATE TABLE finance_read_claims (
	id UUID NOT NULL, 
	private_reference JSONB NOT NULL, 
	state VARCHAR(16) NOT NULL, 
	operation_id UUID NOT NULL, 
	action_revision_id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	actor_id UUID NOT NULL, 
	command_receipt_id UUID NOT NULL, 
	claim_token UUID NOT NULL, 
	admitted_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	deadline TIMESTAMP WITH TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id),
 CONSTRAINT uq_finance_read_receipt UNIQUE (command_receipt_id), 
	FOREIGN KEY(operation_id, action_revision_id, ticket_id, box_id) REFERENCES finance_work_revisions (intended_operation_id, action_revision_id, ticket_id, box_id), 
	FOREIGN KEY(operation_id, ticket_id, box_id) REFERENCES operations (id, ticket_id, box_id), 
	FOREIGN KEY(command_receipt_id, ticket_id, action_revision_id, box_id) REFERENCES finance_command_receipts (id, ticket_id, action_revision_id, box_id), 
	CHECK (actor_id=owner_id AND deadline > admitted_at), 
	CHECK (jsonb_typeof(private_reference) = 'object' AND octet_length(private_reference::text) <= 4096), 
	CHECK (state IN ('admitted','settled','unknown'))
);

CREATE TABLE finance_submit_claims (
	operation_id UUID NOT NULL, 
	approval_receipt_id UUID NOT NULL, 
	command_sha256 VARCHAR(64) NOT NULL, 
	dispatch VARCHAR(32) NOT NULL, 
	invocation_started_at TIMESTAMP WITH TIME ZONE, 
	safe_error VARCHAR(64), 
	action_revision_id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	actor_id UUID NOT NULL, 
	command_receipt_id UUID NOT NULL, 
	claim_token UUID NOT NULL, 
	admitted_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	deadline TIMESTAMP WITH TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (operation_id), 
	FOREIGN KEY(operation_id, action_revision_id, ticket_id, box_id) REFERENCES finance_work_revisions (intended_operation_id, action_revision_id, ticket_id, box_id), 
	FOREIGN KEY(operation_id, ticket_id, box_id) REFERENCES operations (id, ticket_id, box_id), 
	FOREIGN KEY(command_receipt_id, ticket_id, action_revision_id, box_id) REFERENCES finance_command_receipts (id, ticket_id, action_revision_id, box_id), 
	CHECK (actor_id=owner_id AND deadline > admitted_at), 
	FOREIGN KEY(approval_receipt_id, ticket_id, action_revision_id, box_id) REFERENCES finance_command_receipts (id, ticket_id, action_revision_id, box_id), 
	CHECK (dispatch IN ('not_started','invocation_started','proved_not_dispatched','unconfirmed','response_observed')), 
	CHECK (command_sha256 ~ '^[a-f0-9]{64}$')
);

CREATE TABLE finance_provider_observations (
	id UUID NOT NULL, 
	operation_id UUID NOT NULL, 
	action_revision_id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	sequence INTEGER NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	submit_claim_id UUID, 
	read_claim_id UUID, 
	private_reference JSONB, 
	public_observation JSONB NOT NULL, 
	public_sha256 VARCHAR(64) NOT NULL, 
	head_sha256 VARCHAR(64) NOT NULL, 
	recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(operation_id, action_revision_id, ticket_id, box_id) REFERENCES finance_work_revisions (intended_operation_id, action_revision_id, ticket_id, box_id), 
	FOREIGN KEY(submit_claim_id) REFERENCES finance_submit_claims (operation_id), 
	FOREIGN KEY(read_claim_id) REFERENCES finance_read_claims (id), 
	CONSTRAINT uq_finance_observation_sequence UNIQUE (operation_id, sequence), 
	CHECK (sequence > 0 AND kind IN ('dispatch','creation','payment') AND ((submit_claim_id=operation_id AND read_claim_id IS NULL) OR (submit_claim_id IS NULL AND read_claim_id IS NOT NULL))), 
	CHECK (public_sha256 ~ '^[a-f0-9]{64}$' AND head_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(public_observation) = 'object' AND octet_length(public_observation::text) <= 4096)
);

CREATE TABLE finance_reopen_facts (
	id UUID NOT NULL, 
	operation_id UUID NOT NULL, 
	action_revision_id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	observation_id UUID NOT NULL, 
	observation_sha256 VARCHAR(64) NOT NULL, 
	effect_version INTEGER NOT NULL, 
	recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(operation_id, action_revision_id, ticket_id, box_id) REFERENCES finance_work_revisions (intended_operation_id, action_revision_id, ticket_id, box_id), 
	FOREIGN KEY(observation_id) REFERENCES finance_provider_observations (id), 
	CONSTRAINT uq_finance_reopen_fact UNIQUE (operation_id, observation_id), 
	CHECK (observation_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (effect_version > 0)
);
"""

GUARD_DDL = r"""
CREATE FUNCTION public.finance_private_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE allowed text[];
BEGIN
 IF TG_TABLE_NAME='finance_connection_versions' THEN allowed:=ARRAY['is_current','read_enabled','write_enabled','revoked_at'];
 ELSE allowed:=ARRAY['is_current','revoked_at']; END IF;
 IF TG_OP='DELETE' OR (to_jsonb(NEW)-allowed) IS DISTINCT FROM (to_jsonb(OLD)-allowed)
  OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at)
 THEN RAISE EXCEPTION 'finance private history is immutable' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='finance_connection_versions' THEN
  IF NEW.revoked_at IS NOT NULL AND (NEW.write_enabled OR NEW.read_enabled)
  THEN RAISE EXCEPTION 'revoked finance account cannot be enabled' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER finance_connection_private BEFORE UPDATE OR DELETE ON public.finance_connection_versions FOR EACH ROW EXECUTE FUNCTION public.finance_private_guard();
CREATE TRIGGER finance_customer_private BEFORE UPDATE OR DELETE ON public.finance_customer_versions FOR EACH ROW EXECUTE FUNCTION public.finance_private_guard();
CREATE TRIGGER finance_connection_human BEFORE INSERT ON public.finance_connection_versions FOR EACH ROW EXECUTE FUNCTION public.vendor_scoped_human_guard();
CREATE TRIGGER finance_customer_human BEFORE INSERT ON public.finance_customer_versions FOR EACH ROW EXECUTE FUNCTION public.vendor_scoped_human_guard();

CREATE FUNCTION public.finance_head(oid uuid) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT coalesce((SELECT jsonb_build_object('sequence',sequence,'sha256',head_sha256) FROM public.finance_provider_observations
  WHERE operation_id=oid ORDER BY sequence DESC LIMIT 1),jsonb_build_object('sequence',0,'sha256',public.vendor_public_digest(
   'cosmas-finance-observation-head.v1',jsonb_build_object('operation_id',oid,'sequence',0))))
$$;

CREATE FUNCTION public.finance_work_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE tid uuid; t public.tickets; r public.finance_work_revisions; finance_account public.finance_connection_versions; m public.finance_customer_versions;
BEGIN
 IF TG_TABLE_NAME='tickets' THEN tid:=NEW.id; ELSE tid:=NEW.ticket_id; END IF;
 SELECT * INTO t FROM public.tickets WHERE id=tid;
 IF t.lane<>'encounter_payment_request' AND NOT EXISTS(SELECT 1 FROM public.finance_work_revisions WHERE ticket_id=tid) THEN RETURN NEW; END IF;
 SELECT * INTO r FROM public.finance_work_revisions WHERE action_revision_id=t.current_revision_id;
 IF r.action_revision_id IS NULL OR t.lane<>'encounter_payment_request' OR (r.ticket_id,r.box_id,r.owner_id,r.patient_link_id)
  IS DISTINCT FROM (t.id,t.box_id,t.created_by_principal_id,t.patient_link_id)
  OR NOT EXISTS(SELECT 1 FROM public.encounter_workspaces w WHERE w.id=r.workspace_id AND w.box_id=r.box_id AND w.owner_id=r.owner_id AND w.patient_link_id=r.patient_link_id AND w.appointment_id=t.appointment_id)
 THEN RAISE EXCEPTION 'finance work source mismatch' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM public.finance_work_revisions v JOIN public.action_revisions a ON a.id=v.action_revision_id WHERE v.ticket_id=tid AND
  (a.content<>'Payment request — private review' OR a.target_ref<>'finance_work:'||tid::text OR a.action_type<>'payment_request.create'
   OR a.created_by_principal_id<>v.owner_id OR a.invalidated OR a.automation_class<>'hitl_required'
   OR a.payload_hash<>v.payload_hash OR a.payload->>'private_command_sha256' IS DISTINCT FROM v.private_command_sha256
   OR a.payload->>'review_sha256' IS DISTINCT FROM v.review_sha256 OR a.payload->>'request_sha256' IS DISTINCT FROM v.request_sha256
   OR a.payload->>'operation_id' IS DISTINCT FROM v.intended_operation_id::text
   OR v.private_command_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-command.v1',v.private_command)
   OR v.review_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-finance-review.v1',v.public_review)
   OR v.private_command->'intent'->>'kind' IS DISTINCT FROM 'payment_intent.create'
   OR v.private_command->'intent'->'amount' IS DISTINCT FROM to_jsonb(v.amount) OR v.private_command->'intent'->>'currency' IS DISTINCT FROM v.currency))
 THEN RAISE EXCEPTION 'finance action envelope mismatch' USING ERRCODE='23514'; END IF;
 SELECT * INTO finance_account FROM public.finance_connection_versions WHERE id=r.connection_version_id;
 SELECT * INTO m FROM public.finance_customer_versions WHERE id=r.customer_version_id;
 IF r.private_command->'selection' IS DISTINCT FROM finance_account.private_selection
  OR r.private_command->>'operation_id' IS DISTINCT FROM r.intended_operation_id::text
  OR r.private_command->>'revision_id' IS DISTINCT FROM r.action_revision_id::text
  OR (r.private_command->>'expires_at')::timestamptz IS DISTINCT FROM r.expires_at
  OR r.private_command->'intent' IS DISTINCT FROM jsonb_build_object('kind','payment_intent.create','amount',r.amount,'currency',r.currency,'customer_id',m.customer_id)
  OR (r.private_command-ARRAY['selection','operation_id','revision_id','expires_at','intent'])<>'{}'::jsonb
  OR r.request_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-finance-public-request.v1',jsonb_build_object('command_kind','propose','scope',jsonb_build_object('kind','workspace','id',r.workspace_id),'request',r.public_proposal))
  OR r.public_proposal->>'proposed_operation_id' IS DISTINCT FROM r.intended_operation_id::text
  OR r.public_proposal->'amount' IS DISTINCT FROM to_jsonb(r.amount) OR r.public_proposal->>'currency' IS DISTINCT FROM r.currency
  OR r.public_review->>'operation_id' IS DISTINCT FROM r.intended_operation_id::text
  OR r.public_review->>'revision_id' IS DISTINCT FROM r.action_revision_id::text OR r.public_review->>'ticket_id' IS DISTINCT FROM t.id::text
  OR r.public_review->'amount' IS DISTINCT FROM to_jsonb(r.amount) OR r.public_review->>'currency' IS DISTINCT FROM r.currency
  OR r.public_review->>'processor_confirmation' IS DISTINCT FROM 'not_requested'
  OR r.public_review->'source' IS DISTINCT FROM jsonb_build_object('kind','reviewed_note','note_id',r.note_id,'content_sha256',r.content_hash,'source_fingerprint',r.source_fingerprint)
  OR EXISTS(SELECT 1 FROM public.action_revisions a WHERE a.id=r.action_revision_id AND a.payload IS DISTINCT FROM jsonb_build_object(
    'action','payment_request.create','private_command_sha256',r.private_command_sha256,'review_sha256',r.review_sha256,'request_sha256',r.request_sha256,'mapping_sha256',m.mapping_sha256,'operation_id',r.intended_operation_id))
 THEN RAISE EXCEPTION 'finance exact reviewed mapping mismatch' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='tickets' THEN
  IF TG_OP='UPDATE' THEN
   IF OLD.state='closed' AND t.state='approved' AND NOT EXISTS(SELECT 1 FROM public.finance_reopen_facts f WHERE f.ticket_id=t.id AND f.effect_version>OLD.version)
   THEN RAISE EXCEPTION 'finance reopening requires retained contradiction' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF t.state IN ('withdrawn','rejected','superseded') AND EXISTS(SELECT 1 FROM public.finance_submit_claims c WHERE c.operation_id=r.intended_operation_id)
 THEN RAISE EXCEPTION 'spent payment request cannot be cancelled' USING ERRCODE='23514'; END IF;
 IF t.state='closed' AND NOT EXISTS(SELECT 1 FROM public.finance_command_receipts v JOIN public.finance_command_receipts result ON result.id=v.result_receipt_id
  WHERE v.ticket_id=tid AND v.action_revision_id=r.action_revision_id AND v.command_kind='verify' AND result.command_kind='result'
   AND result.result_payload->>'disposition' IN ('reported_paid','verified_in_processor')
   AND NOT EXISTS(SELECT 1 FROM public.finance_command_receipts newer WHERE newer.action_revision_id=r.action_revision_id AND newer.command_kind='result' AND newer.effect_version>v.effect_version)
   AND NOT EXISTS(SELECT 1 FROM public.finance_reopen_facts fact WHERE fact.action_revision_id=r.action_revision_id AND fact.effect_version>v.effect_version))
 THEN RAISE EXCEPTION 'finance close requires exact owner verification' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER finance_ticket_binding AFTER INSERT OR UPDATE ON public.tickets DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.finance_work_guard();
CREATE CONSTRAINT TRIGGER finance_revision_binding AFTER INSERT ON public.finance_work_revisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.finance_work_guard();
CREATE TRIGGER finance_revision_immutable BEFORE UPDATE OR DELETE ON public.finance_work_revisions FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE FUNCTION public.finance_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM public.finance_work_revisions WHERE action_revision_id=OLD.id) THEN RAISE EXCEPTION 'finance action history is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;
CREATE TRIGGER finance_action_immutable BEFORE UPDATE OR DELETE ON public.action_revisions FOR EACH ROW EXECUTE FUNCTION public.finance_action_guard();

CREATE FUNCTION public.finance_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public.finance_work_revisions; t public.tickets; result public.finance_command_receipts;
 h jsonb; e text; successful boolean; canceled boolean; rejected boolean; accepted boolean; conflicting boolean; expected jsonb;
BEGIN
 SELECT * INTO r FROM public.finance_work_revisions WHERE action_revision_id=NEW.action_revision_id;
 SELECT * INTO t FROM public.tickets WHERE id=NEW.ticket_id FOR UPDATE;
 IF r.action_revision_id IS NULL OR (NEW.box_id,NEW.owner_id,NEW.workspace_id,NEW.ticket_id,NEW.operation_id,NEW.actor_id)
  IS DISTINCT FROM (r.box_id,r.owner_id,r.workspace_id,r.ticket_id,r.intended_operation_id,r.owner_id)
  OR t.current_revision_id IS DISTINCT FROM r.action_revision_id OR NEW.effect_version<>t.version
  OR NEW.public_request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
  OR NEW.request_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-finance-public-request.v1',jsonb_build_object(
   'command_kind',NEW.command_kind,'scope',jsonb_build_object('kind','workspace','id',NEW.workspace_id),'request',NEW.public_request))
 THEN RAISE EXCEPTION 'finance receipt scope mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.effect->>'effect' IS DISTINCT FROM (CASE NEW.command_kind WHEN 'propose' THEN 'proposed' WHEN 'decide' THEN CASE NEW.public_request->>'choice' WHEN 'approve' THEN 'approved' WHEN 'reject' THEN 'rejected' END WHEN 'withdraw' THEN 'withdrawn' WHEN 'submit' THEN 'submit_claimed' WHEN 'reconcile' THEN 'read_claimed' WHEN 'result' THEN 'result_recorded' WHEN 'verify' THEN 'verified' END)
  OR (NEW.command_kind='propose' AND (NEW.public_request IS DISTINCT FROM r.public_proposal OR t.state<>'pending_approval'))
  OR (NEW.command_kind='decide' AND (NEW.public_request->>'review_sha256' IS DISTINCT FROM r.review_sha256 OR t.state<>(CASE NEW.public_request->>'choice' WHEN 'approve' THEN 'approved' ELSE 'rejected' END)))
  OR (NEW.command_kind='withdraw' AND t.state<>'withdrawn')
 THEN RAISE EXCEPTION 'finance command effect mismatch' USING ERRCODE='23514'; END IF;
 expected:=jsonb_build_object('ticket_id',r.ticket_id,'revision_id',r.action_revision_id,'operation_id',r.intended_operation_id,'payload_hash',r.payload_hash,
  'receipt_id',NEW.id,'effect_version',NEW.effect_version,'recorded_at',to_char(NEW.recorded_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'effect',NEW.effect->'effect');
 IF NEW.effect IS DISTINCT FROM expected OR NEW.receipt_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-finance-public-receipt.v1',jsonb_build_object(
  'scope',jsonb_build_object('kind','workspace','id',NEW.workspace_id),'command_kind',NEW.command_kind,'idempotency_key',NEW.idempotency_key,'request_sha256',NEW.request_sha256,'effect',expected))
 THEN RAISE EXCEPTION 'finance receipt digest mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.command_kind<>'propose' AND (NEW.public_request->>'operation_id' IS DISTINCT FROM r.intended_operation_id::text
  OR NEW.public_request->>'revision_id' IS DISTINCT FROM r.action_revision_id::text OR NEW.public_request->>'payload_hash' IS DISTINCT FROM r.payload_hash
  OR NEW.public_request->'expected_version' IS DISTINCT FROM to_jsonb(t.version-1))
 THEN RAISE EXCEPTION 'finance receipt version mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.command_kind IN ('result','verify') THEN
  SELECT * INTO result FROM public.finance_command_receipts WHERE action_revision_id=r.action_revision_id AND command_kind='result' ORDER BY effect_version DESC LIMIT 1;
  h:=public.finance_head(r.intended_operation_id);
  e:=public.vendor_public_digest('cosmas-finance-evidence.v1',jsonb_build_object('operation_id',r.intended_operation_id,'observation_head',h,'result_receipt_id',result.id,'result_receipt_sha256',result.receipt_sha256));
  IF NEW.public_request->'observation_head' IS DISTINCT FROM h OR NEW.public_request->>'evidence_sha256' IS DISTINCT FROM e
   OR NEW.observation_head_sha256 IS DISTINCT FROM h->>'sha256' OR NEW.evidence_sha256 IS DISTINCT FROM e
  THEN RAISE EXCEPTION 'finance current evidence mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.command_kind='result' THEN
  IF t.state<>'approved' OR NEW.result_payload IS DISTINCT FROM jsonb_build_object('disposition',NEW.public_request->'disposition','evidence',NEW.public_request->'evidence','observation_head',h)
   OR NEW.result_payload->>'disposition' NOT IN ('reported_paid','reported_unpaid','verified_in_processor','unable_to_establish')
  THEN RAISE EXCEPTION 'finance result mismatch' USING ERRCODE='23514'; END IF;
 ELSIF NEW.result_payload IS NOT NULL THEN RAISE EXCEPTION 'non-result cannot claim financial outcome' USING ERRCODE='23514'; END IF;
 IF NEW.command_kind='verify' THEN
  SELECT coalesce(bool_or(public_observation->>'payment_state'='succeeded' AND public_observation->'amount_received'=to_jsonb(r.amount)),false),
   coalesce(bool_or(public_observation->>'payment_state'='canceled'),false),coalesce(bool_or(public_observation->>'acceptance'='rejected'),false),
   coalesce(bool_or(public_observation->>'acceptance'='accepted'),false) INTO successful,canceled,rejected,accepted FROM public.finance_provider_observations WHERE operation_id=r.intended_operation_id;
  conflicting:=(successful AND canceled) OR (accepted AND rejected);
  IF t.state<>'closed' OR result.id IS NULL OR NEW.result_receipt_id IS DISTINCT FROM result.id
   OR NEW.public_request->>'result_receipt_id' IS DISTINCT FROM result.id::text OR NEW.public_request->>'result_receipt_sha256' IS DISTINCT FROM result.receipt_sha256
   OR NEW.public_request->'reviewed_result' IS DISTINCT FROM 'true'::jsonb OR NEW.public_request->'reviewed_observations' IS DISTINCT FROM 'true'::jsonb
   OR NEW.public_request->'outcome_confirmed' IS DISTINCT FROM 'true'::jsonb OR NEW.public_request->'reviewed_conflicting_evidence' IS DISTINCT FROM to_jsonb(conflicting)
   OR result.result_payload->>'disposition' NOT IN ('reported_paid','verified_in_processor')
   OR ((NOT successful OR canceled OR conflicting) AND result.result_payload->>'disposition' IS DISTINCT FROM 'verified_in_processor')
  THEN RAISE EXCEPTION 'finance verification mismatch' USING ERRCODE='23514'; END IF;
 ELSIF NEW.result_receipt_id IS NOT NULL THEN RAISE EXCEPTION 'non-verification cannot bind result' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER finance_receipt_current BEFORE INSERT ON public.finance_command_receipts FOR EACH ROW EXECUTE FUNCTION public.finance_receipt_guard();
CREATE TRIGGER finance_receipt_immutable BEFORE UPDATE OR DELETE ON public.finance_command_receipts FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();

CREATE FUNCTION public.finance_operation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE oid uuid; o public.operations; r public.finance_work_revisions; c public.finance_submit_claims;
BEGIN
 IF TG_TABLE_NAME='operations' THEN oid:=NEW.id; ELSE oid:=NEW.operation_id; END IF;
 SELECT * INTO o FROM public.operations WHERE id=oid;
 SELECT * INTO r FROM public.finance_work_revisions WHERE action_revision_id=o.action_revision_id;
 IF r.action_revision_id IS NULL THEN
  IF o.adapter='workspace_finance' THEN RAISE EXCEPTION 'finance operation requires reviewed revision' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO c FROM public.finance_submit_claims WHERE operation_id=oid;
 IF (o.id,o.ticket_id,o.box_id) IS DISTINCT FROM (r.intended_operation_id,r.ticket_id,r.box_id) OR o.adapter<>'workspace_finance'
  OR o.external_reference IS NOT NULL OR o.idempotency_key<>'os-finance:'||oid::text OR o.attempt_count<>(CASE WHEN c.operation_id IS NULL THEN 0 ELSE 1 END)
  OR (c.operation_id IS NOT NULL AND o.status='pending')
  OR NOT EXISTS(SELECT 1 FROM public.decisions d WHERE d.ticket_id=r.ticket_id AND d.action_revision_id=r.action_revision_id AND d.kind='approve' AND d.actor_principal_id=r.owner_id)
  OR NOT EXISTS(SELECT 1 FROM public.finance_command_receipts q WHERE q.action_revision_id=r.action_revision_id AND q.command_kind='decide' AND q.public_request->>'choice'='approve')
 THEN RAISE EXCEPTION 'finance operation approval mismatch' USING ERRCODE='23514'; END IF;
 IF c.operation_id IS NOT NULL AND ((c.box_id,c.owner_id,c.workspace_id,c.actor_id) IS DISTINCT FROM (r.box_id,r.owner_id,r.workspace_id,r.owner_id)
  OR c.command_sha256<>r.private_command_sha256 OR NOT EXISTS(SELECT 1 FROM public.finance_command_receipts q WHERE q.id=c.approval_receipt_id AND q.command_kind='decide' AND q.public_request->>'choice'='approve')
  OR NOT EXISTS(SELECT 1 FROM public.finance_command_receipts q WHERE q.id=c.command_receipt_id AND q.command_kind='submit'))
 THEN RAISE EXCEPTION 'finance submit claim mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER finance_operation_binding AFTER INSERT OR UPDATE ON public.operations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.finance_operation_guard();
CREATE CONSTRAINT TRIGGER finance_submit_binding AFTER INSERT OR UPDATE ON public.finance_submit_claims DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.finance_operation_guard();
CREATE FUNCTION public.finance_operation_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.adapter='workspace_finance' AND (TG_OP='DELETE' OR (to_jsonb(NEW)-ARRAY['status','attempt_count','result_receipt_hash','error_message','started_at','completed_at'])
  IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','attempt_count','result_receipt_hash','error_message','started_at','completed_at']) OR NEW.attempt_count<OLD.attempt_count OR NEW.attempt_count>1)
 THEN RAISE EXCEPTION 'finance operation cannot reset' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;
CREATE TRIGGER finance_operation_immutable BEFORE UPDATE OR DELETE ON public.operations FOR EACH ROW EXECUTE FUNCTION public.finance_operation_mutation();
CREATE FUNCTION public.finance_claim_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE allowed text[];
BEGIN
 allowed:=CASE WHEN TG_TABLE_NAME='finance_submit_claims' THEN ARRAY['dispatch','invocation_started_at','completed_at','safe_error'] ELSE ARRAY['state','completed_at'] END;
 IF TG_OP='DELETE' OR (to_jsonb(NEW)-allowed) IS DISTINCT FROM (to_jsonb(OLD)-allowed) OR OLD.completed_at IS NOT NULL
 THEN RAISE EXCEPTION 'finance claim cannot reset' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='finance_submit_claims' THEN
  IF (OLD.invocation_started_at IS NOT NULL AND NEW.invocation_started_at IS DISTINCT FROM OLD.invocation_started_at)
   OR OLD.dispatch<>'not_started' AND NEW.dispatch='not_started'
  THEN RAISE EXCEPTION 'finance dispatch cannot reset' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER finance_submit_immutable BEFORE UPDATE OR DELETE ON public.finance_submit_claims FOR EACH ROW EXECUTE FUNCTION public.finance_claim_mutation();
CREATE TRIGGER finance_read_immutable BEFORE UPDATE OR DELETE ON public.finance_read_claims FOR EACH ROW EXECUTE FUNCTION public.finance_claim_mutation();

CREATE FUNCTION public.finance_reference_valid(ref jsonb, oid uuid, rid uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT coalesce(ref->>'vendor'='stripe' AND ref->>'kind'='payment_intent'
  AND ref->>'operation_id'=oid::text AND ref->>'connection_id'=r.connection_version_id::text
  AND ref->>'selection_sha256'=c.private_sha256 AND ref->>'request_sha256'=r.private_command_sha256
  AND ref->>'environment'=c.environment AND ref->>'value' ~ '^pi_[A-Za-z0-9]+$'
  AND coalesce(ref->>'artifact_sha256',ref->>'request_id',ref->>'portal_id',ref->>'portal_profile_sha256',ref->>'correspondence_sha256') IS NULL,false)
 FROM public.finance_work_revisions r JOIN public.finance_connection_versions c ON c.id=r.connection_version_id
 WHERE r.action_revision_id=rid AND r.intended_operation_id=oid
$$;
CREATE FUNCTION public.finance_read_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public.finance_work_revisions;
BEGIN
 PERFORM 1 FROM public.tickets WHERE id=NEW.ticket_id FOR UPDATE;
 SELECT * INTO r FROM public.finance_work_revisions WHERE action_revision_id=NEW.action_revision_id;
 IF (NEW.box_id,NEW.owner_id,NEW.workspace_id,NEW.ticket_id,NEW.operation_id,NEW.actor_id) IS DISTINCT FROM
  (r.box_id,r.owner_id,r.workspace_id,r.ticket_id,r.intended_operation_id,r.owner_id)
  OR NOT public.finance_reference_valid(NEW.private_reference,NEW.operation_id,NEW.action_revision_id)
  OR EXISTS(SELECT 1 FROM public.finance_read_claims previous_claim WHERE previous_claim.command_receipt_id=NEW.command_receipt_id)
  OR NEW.deadline IS DISTINCT FROM NEW.admitted_at+interval '45 seconds'
  OR NOT EXISTS(SELECT 1 FROM public.finance_provider_observations o WHERE o.operation_id=NEW.operation_id AND o.kind='creation' AND o.public_observation->>'acceptance'='accepted' AND o.private_reference=NEW.private_reference)
  OR NOT EXISTS(SELECT 1 FROM public.finance_command_receipts q WHERE q.id=NEW.command_receipt_id AND q.command_kind='reconcile' AND q.operation_id=NEW.operation_id AND q.actor_id=NEW.actor_id)
 THEN RAISE EXCEPTION 'finance read requires original accepted reference' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER finance_read_binding BEFORE INSERT ON public.finance_read_claims FOR EACH ROW EXECUTE FUNCTION public.finance_read_guard();

CREATE FUNCTION public.finance_observation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public.finance_work_revisions; h jsonb; sha text;
BEGIN
 PERFORM 1 FROM public.tickets WHERE id=NEW.ticket_id FOR UPDATE;
 SELECT * INTO r FROM public.finance_work_revisions WHERE action_revision_id=NEW.action_revision_id;
 h:=public.finance_head(NEW.operation_id);
 sha:=public.vendor_public_digest('cosmas-finance-public-observation.v1',NEW.public_observation-'sha256');
 IF (NEW.workspace_id,NEW.box_id,NEW.owner_id) IS DISTINCT FROM (r.workspace_id,r.box_id,r.owner_id)
  OR NEW.sequence<>(h->>'sequence')::integer+1 OR NEW.public_observation->>'id' IS DISTINCT FROM NEW.id::text
  OR NEW.public_observation->>'operation_id' IS DISTINCT FROM NEW.operation_id::text OR NEW.public_observation->'sequence' IS DISTINCT FROM to_jsonb(NEW.sequence)
  OR NEW.public_observation->>'kind' IS DISTINCT FROM NEW.kind OR NEW.public_observation->>'sha256' IS DISTINCT FROM sha OR NEW.public_sha256 IS DISTINCT FROM sha
  OR NEW.head_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-finance-observation-head.v1',jsonb_build_object('operation_id',NEW.operation_id,'sequence',NEW.sequence,'previous_sha256',h->'sha256','observation_sha256',sha))
  OR (NEW.read_claim_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.finance_read_claims c WHERE c.id=NEW.read_claim_id AND c.operation_id=NEW.operation_id))
  OR NEW.public_observation->>'recorded_at' IS DISTINCT FROM to_char(NEW.recorded_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  OR (NEW.kind IN ('creation','dispatch') AND NEW.submit_claim_id IS DISTINCT FROM NEW.operation_id)
  OR (NEW.kind='payment' AND NEW.read_claim_id IS NULL)
  OR (NEW.private_reference IS NOT NULL AND NOT public.finance_reference_valid(NEW.private_reference,NEW.operation_id,NEW.action_revision_id))
  OR (NEW.kind='creation' AND ((NEW.public_observation->>'acceptance'='accepted') IS DISTINCT FROM (NEW.private_reference IS NOT NULL)))
  OR (NEW.kind='payment' AND NEW.private_reference IS NOT NULL AND NEW.private_reference IS DISTINCT FROM (SELECT c.private_reference FROM public.finance_read_claims c WHERE c.id=NEW.read_claim_id))
  OR (NEW.kind='payment' AND NEW.public_observation->>'payment_state'<>'unknown' AND NEW.private_reference IS NULL)
  OR (NEW.kind='payment' AND (NEW.public_observation->>'amount_received')::integer NOT BETWEEN 0 AND r.amount)
  OR (NEW.kind='payment' AND NEW.public_observation->>'payment_state' NOT IN ('requires_payment_method','requires_confirmation','requires_action','processing','requires_capture','canceled','succeeded','unknown'))
  OR (NEW.kind='creation' AND NEW.public_observation->>'acceptance' NOT IN ('accepted','rejected','unconfirmed'))
  OR (NEW.kind='dispatch' AND NEW.public_observation->>'dispatch' NOT IN ('invocation_started','proved_not_dispatched','unconfirmed'))
  OR (NEW.public_observation-ARRAY['id','sequence','operation_id','kind','recorded_at','sha256','safe_error']-CASE NEW.kind WHEN 'dispatch' THEN ARRAY['dispatch'] WHEN 'creation' THEN ARRAY['acceptance'] ELSE ARRAY['payment_state','amount','currency','amount_received','livemode'] END)<>'{}'::jsonb
  OR (NEW.kind='payment' AND NEW.public_observation ? 'livemode' AND NEW.public_observation->'livemode' IS DISTINCT FROM to_jsonb(r.private_command->'selection'->>'environment'='production'))
  OR (NEW.kind='payment' AND EXISTS(SELECT 1 FROM public.finance_provider_observations WHERE read_claim_id=NEW.read_claim_id))
  OR (NEW.kind='creation' AND EXISTS(SELECT 1 FROM public.finance_provider_observations WHERE submit_claim_id=NEW.submit_claim_id AND kind='creation'))
  OR (NEW.kind='payment' AND (NEW.public_observation->'amount' IS DISTINCT FROM to_jsonb(r.amount) OR NEW.public_observation->>'currency' IS DISTINCT FROM r.currency
   OR (NEW.public_observation->>'payment_state'='succeeded' AND NEW.public_observation->'amount_received' IS DISTINCT FROM to_jsonb(r.amount))))
 THEN RAISE EXCEPTION 'finance observation binding mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER finance_observation_binding BEFORE INSERT ON public.finance_provider_observations FOR EACH ROW EXECUTE FUNCTION public.finance_observation_guard();
CREATE TRIGGER finance_observation_immutable BEFORE UPDATE OR DELETE ON public.finance_provider_observations FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER finance_event_immutable BEFORE UPDATE OR DELETE ON public.finance_event_candidates FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER finance_reopen_immutable BEFORE UPDATE OR DELETE ON public.finance_reopen_facts FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE FUNCTION public.finance_setup_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE view jsonb; availability text;
BEGIN
 view:=NEW.public_view-'public_sha256';
 IF NEW.public_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-finance-public-selection.v1',view)
  OR NEW.public_view->>'public_sha256' IS DISTINCT FROM NEW.public_sha256
  OR view->>'id' IS DISTINCT FROM NEW.id::text OR view->'revision' IS DISTINCT FROM to_jsonb(NEW.revision)
 THEN RAISE EXCEPTION 'finance setup public commitment mismatch' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='finance_connection_versions' THEN
  availability:=CASE WHEN NEW.write_enabled THEN 'enabled' WHEN NEW.read_enabled THEN 'read_only' ELSE 'unavailable' END;
  IF NEW.private_selection->>'vendor' IS DISTINCT FROM 'stripe' OR NEW.private_selection->>'connection_id' IS DISTINCT FROM NEW.id::text
   OR NEW.private_selection->>'box_id' IS DISTINCT FROM NEW.box_id::text OR NEW.private_selection->>'owner_id' IS DISTINCT FROM NEW.owner_id::text
   OR NEW.private_selection->>'environment' IS DISTINCT FROM NEW.environment
   OR NEW.private_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-selection.v1',NEW.private_selection)
   OR view IS DISTINCT FROM jsonb_build_object('id',NEW.id,'revision',NEW.revision,'environment',NEW.environment,'label',view->'label','availability',availability)
  THEN RAISE EXCEPTION 'finance setup selection mismatch' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.mapping_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-finance-customer.v1',jsonb_build_object('connection_id',NEW.connection_version_id,'patient_link_id',NEW.patient_link_id,'customer_id',NEW.customer_id))
   OR view IS DISTINCT FROM jsonb_build_object('id',NEW.id,'revision',NEW.revision,'connection_id',NEW.connection_version_id,'label',view->'label','availability','reviewed')
  THEN RAISE EXCEPTION 'finance setup customer mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER finance_connection_admission BEFORE INSERT ON public.finance_connection_versions FOR EACH ROW EXECUTE FUNCTION public.finance_setup_guard();
CREATE TRIGGER finance_customer_admission BEFORE INSERT ON public.finance_customer_versions FOR EACH ROW EXECUTE FUNCTION public.finance_setup_guard();

CREATE FUNCTION public.finance_reopen_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.finance_provider_observations o JOIN public.tickets t ON t.id=o.ticket_id
  WHERE (o.id,o.operation_id,o.action_revision_id,o.ticket_id,o.workspace_id,o.box_id,o.owner_id,o.public_sha256)
   =(NEW.observation_id,NEW.operation_id,NEW.action_revision_id,NEW.ticket_id,NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.observation_sha256)
   AND t.state='approved' AND t.version=NEW.effect_version)
 THEN RAISE EXCEPTION 'finance reopen fact mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER finance_reopen_binding AFTER INSERT ON public.finance_reopen_facts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.finance_reopen_guard();
CREATE FUNCTION public.finance_closed_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE t public.tickets; verified public.finance_command_receipts; boundary integer; contradiction boolean;
BEGIN
 SELECT * INTO t FROM public.tickets WHERE id=NEW.ticket_id;
 IF t.state<>'closed' OR t.current_revision_id<>NEW.action_revision_id THEN RETURN NEW; END IF;
 SELECT * INTO verified FROM public.finance_command_receipts WHERE action_revision_id=t.current_revision_id AND command_kind='verify' ORDER BY effect_version DESC LIMIT 1;
 boundary:=(verified.public_request->'observation_head'->>'sequence')::integer;
 SELECT EXISTS(SELECT 1 FROM public.finance_provider_observations o WHERE o.operation_id=NEW.operation_id AND o.sequence>boundary
   AND (o.public_observation->>'payment_state'='canceled' OR o.public_observation->>'acceptance'='rejected')
   AND NOT EXISTS(SELECT 1 FROM public.finance_provider_observations previous WHERE previous.operation_id=o.operation_id AND previous.sequence<=boundary
    AND ((o.public_observation->>'payment_state'='canceled' AND previous.public_observation->>'payment_state'='canceled')
     OR (o.public_observation->>'acceptance'='rejected' AND previous.public_observation->>'acceptance'='rejected'))))
  OR EXISTS(SELECT 1 FROM public.finance_provider_observations a JOIN public.finance_provider_observations b ON a.operation_id=b.operation_id
   WHERE a.operation_id=NEW.operation_id AND ((a.public_observation->>'payment_state'='succeeded' AND b.public_observation->>'payment_state'='canceled')
    OR (a.public_observation->>'acceptance'='accepted' AND b.public_observation->>'acceptance'='rejected'))
   AND NOT EXISTS(SELECT 1 FROM public.finance_provider_observations p JOIN public.finance_provider_observations q ON p.operation_id=q.operation_id
    WHERE p.operation_id=a.operation_id AND p.sequence<=boundary AND q.sequence<=boundary
    AND ((a.kind='payment' AND p.public_observation->>'payment_state'='succeeded' AND q.public_observation->>'payment_state'='canceled')
      OR (a.kind='creation' AND p.public_observation->>'acceptance'='accepted' AND q.public_observation->>'acceptance'='rejected')))) INTO contradiction;
 IF verified.id IS NULL OR contradiction THEN RAISE EXCEPTION 'finance contradictory evidence requires reopen' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER finance_closed_evidence AFTER INSERT ON public.finance_provider_observations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.finance_closed_evidence_guard();

"""

PREFLIGHT_DDL = r"""
DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.finance_connection_versions) OR EXISTS(SELECT 1 FROM public.finance_customer_versions) OR EXISTS(SELECT 1 FROM public.finance_event_candidates) OR EXISTS(SELECT 1 FROM public.finance_work_revisions) OR EXISTS(SELECT 1 FROM public.finance_command_receipts) OR EXISTS(SELECT 1 FROM public.finance_read_claims) OR EXISTS(SELECT 1 FROM public.finance_submit_claims) OR EXISTS(SELECT 1 FROM public.finance_provider_observations) OR EXISTS(SELECT 1 FROM public.finance_reopen_facts) THEN RAISE EXCEPTION 'finance history prevents downgrade' USING ERRCODE='23514'; END IF; END $$;
"""

DOWNGRADE_DDL = r"""
DROP TRIGGER finance_ticket_binding ON public.tickets;
DROP TRIGGER finance_action_immutable ON public.action_revisions;
DROP TRIGGER finance_operation_binding ON public.operations;
DROP TRIGGER finance_operation_immutable ON public.operations;
DROP TABLE public.finance_reopen_facts;
DROP TABLE public.finance_provider_observations;
DROP TABLE public.finance_submit_claims;
DROP TABLE public.finance_read_claims;
DROP TABLE public.finance_command_receipts;
DROP TABLE public.finance_work_revisions;
DROP TABLE public.finance_event_candidates;
DROP TABLE public.finance_customer_versions;
DROP TABLE public.finance_connection_versions;
DROP FUNCTION public.finance_private_guard();
DROP FUNCTION public.finance_head (uuid);
DROP FUNCTION public.finance_work_guard();
DROP FUNCTION public.finance_action_guard();
DROP FUNCTION public.finance_receipt_guard();
DROP FUNCTION public.finance_operation_guard();
DROP FUNCTION public.finance_operation_mutation();
DROP FUNCTION public.finance_claim_mutation();
DROP FUNCTION public.finance_observation_guard();
DROP FUNCTION public.finance_reference_valid(jsonb, uuid, uuid);
DROP FUNCTION public.finance_read_guard();
DROP FUNCTION public.finance_setup_guard();
DROP FUNCTION public.finance_reopen_guard();
DROP FUNCTION public.finance_closed_evidence_guard();
"""
