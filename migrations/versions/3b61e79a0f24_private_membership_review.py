"""Private membership review and manual evidence, with no executable operation."""

from alembic import op

revision = "3b61e79a0f24"
down_revision = "2f90c6b1d8a4"
branch_labels = None
depends_on = None

TABLE_DDL = r"""
CREATE TABLE membership_work (
	ticket_id UUID NOT NULL, 
	revision_id UUID NOT NULL, 
	patient_link_id UUID NOT NULL, 
	source_workspace_revision INTEGER NOT NULL, 
	payload_hash VARCHAR(64) NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	review_sha256 VARCHAR(64) NOT NULL, 
	proposal JSONB NOT NULL, 
	review JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	note_id UUID NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	source_fingerprint VARCHAR(64) NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (ticket_id), 
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), 
	FOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id), 
	FOREIGN KEY(revision_id, ticket_id, box_id, payload_hash) REFERENCES action_revisions (id, ticket_id, box_id, payload_hash), 
	FOREIGN KEY(note_id, workspace_id, box_id, owner_id, content_hash, source_fingerprint) REFERENCES workspace_notes (id, workspace_id, box_id, owner_id, content_hash, source_fingerprint), 
	FOREIGN KEY(note_id) REFERENCES workspace_note_reviews (note_id), 
	CONSTRAINT uq_membership_work_scope UNIQUE (ticket_id, workspace_id, box_id, owner_id), 
	CHECK (source_workspace_revision > 0), 
	CHECK (payload_hash ~ '^[a-f0-9]{64}$' AND request_sha256 ~ '^[a-f0-9]{64}$' AND review_sha256 ~ '^[a-f0-9]{64}$' AND content_hash ~ '^[a-f0-9]{64}$' AND source_fingerprint ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(proposal) = 'object' AND octet_length(proposal::text) <= 8192), 
	CHECK (jsonb_typeof(review) = 'object' AND octet_length(review::text) <= 16384), 
	UNIQUE (revision_id)
)

;


CREATE TABLE membership_receipts (
	id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	command_kind VARCHAR(16) NOT NULL, 
	idempotency_key VARCHAR(100) NOT NULL, 
	request JSONB NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	response JSONB NOT NULL, 
	receipt_sha256 VARCHAR(64) NOT NULL, 
	result_receipt_id UUID, 
	recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ticket_id, workspace_id, box_id, owner_id) REFERENCES membership_work (ticket_id, workspace_id, box_id, owner_id), 
	FOREIGN KEY(result_receipt_id) REFERENCES membership_receipts (id), 
	CONSTRAINT uq_membership_command UNIQUE (workspace_id, owner_id, idempotency_key), 
	CONSTRAINT uq_membership_receipt_version UNIQUE (ticket_id, version), 
	CHECK (version BETWEEN 1 AND 100 AND command_kind IN ('propose','decide','result','verify','withdraw')), 
	CHECK (idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'), 
	CHECK (request_sha256 ~ '^[a-f0-9]{64}$' AND receipt_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(request) = 'object' AND octet_length(request::text) <= 8192), 
	CHECK (jsonb_typeof(response) = 'object' AND octet_length(response::text) <= 8192)
)

;
"""

GUARDS = r"""
CREATE FUNCTION public.membership_work_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE tid uuid; t public.tickets; r public.membership_work; a public.action_revisions; h public.membership_receipts; w public.encounter_workspaces;
BEGIN
 IF TG_TABLE_NAME='tickets' THEN tid:=NEW.id; ELSE tid:=NEW.ticket_id; END IF;
 SELECT * INTO t FROM public.tickets WHERE id=tid;
 IF t.lane<>'encounter_membership_work' AND NOT EXISTS(SELECT 1 FROM public.membership_work WHERE ticket_id=tid) THEN RETURN NEW; END IF;
 SELECT * INTO r FROM public.membership_work WHERE ticket_id=tid;
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=r.workspace_id;
 SELECT * INTO a FROM public.action_revisions WHERE id=r.revision_id;
 SELECT * INTO h FROM public.membership_receipts WHERE ticket_id=tid ORDER BY version DESC LIMIT 1;
 IF r.ticket_id IS NULL OR a.id IS NULL OR h.id IS NULL OR t.lane<>'encounter_membership_work'
  OR (r.box_id,r.owner_id,r.patient_link_id,r.revision_id) IS DISTINCT FROM (t.box_id,t.created_by_principal_id,t.patient_link_id,t.current_revision_id)
  OR (w.box_id,w.owner_id,w.patient_link_id,w.appointment_id) IS DISTINCT FROM (r.box_id,r.owner_id,r.patient_link_id,t.appointment_id)
  OR t.version<>h.version OR t.state IS DISTINCT FROM h.response->'effect'->>'state'
  OR (t.state='closed') IS DISTINCT FROM (t.closed_at IS NOT NULL)
  OR a.content<>'Membership work — private human review' OR a.target_ref<>'membership_work:'||tid::text OR a.action_type<>'membership.local_review'
  OR a.created_by_principal_id<>r.owner_id OR a.invalidated OR a.automation_class<>'hitl_required' OR a.revision_number<>1
  OR a.payload IS DISTINCT FROM jsonb_build_object('action','membership.local_review','review_sha256',r.review_sha256,'request_sha256',r.request_sha256)
  OR a.payload_hash<>r.payload_hash OR r.payload_hash<>encode(sha256(convert_to(public.vendor_public_canonical(a.payload),'UTF8')),'hex')
  OR r.review_sha256<>public.vendor_public_digest('cosmas-membership-review.v1',r.review)
  OR r.request_sha256<>public.vendor_public_digest('cosmas-membership-request.v1',jsonb_build_object('scope',jsonb_build_object('box_id',r.box_id,'owner_id',r.owner_id,'workspace_id',r.workspace_id),'command_kind','propose','request',r.proposal))
  OR r.review IS DISTINCT FROM jsonb_build_object('ticket_id',r.ticket_id,'revision_id',r.revision_id,'patient_link_id',r.patient_link_id,'proposal',r.proposal,'authority','local_human_review_only','automatic_membership_changes',false,'automatic_messages_or_money_movement',false)
  OR r.proposal->'source' IS DISTINCT FROM jsonb_build_object('kind','reviewed_note','note_id',r.note_id,'content_sha256',r.content_hash,'source_fingerprint',r.source_fingerprint)
  OR r.proposal->>'patient_link_id' IS DISTINCT FROM r.patient_link_id::text OR r.proposal->'expected_workspace_revision' IS DISTINCT FROM to_jsonb(r.source_workspace_revision)
  OR NOT public.finance_settings_keys(r.proposal,ARRAY['expected_workspace_revision','idempotency_key','source','patient_link_id','purpose','due_date','expected_outcome','instructions'])
  OR r.proposal->>'purpose' NOT IN ('enrollment_assistance','membership_status_review','failed_payment_follow_up')
  OR EXISTS(SELECT 1 FROM public.operations WHERE ticket_id=tid)
  OR (SELECT count(*) FROM public.decisions WHERE ticket_id=tid)<>(SELECT count(*) FROM public.membership_receipts WHERE ticket_id=tid AND command_kind='decide')
  OR EXISTS(SELECT 1 FROM public.decisions d WHERE d.ticket_id=tid AND (d.actor_principal_id<>r.owner_id OR d.action_revision_id<>r.revision_id OR d.box_id<>r.box_id OR NOT EXISTS(SELECT 1 FROM public.membership_receipts decision_receipt WHERE decision_receipt.ticket_id=tid AND decision_receipt.command_kind='decide' AND decision_receipt.request->>'choice'=d.kind)))
 THEN RAISE EXCEPTION 'membership work binding mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER membership_ticket_complete AFTER INSERT OR UPDATE ON public.tickets DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.membership_work_guard();
CREATE CONSTRAINT TRIGGER membership_work_complete AFTER INSERT ON public.membership_work DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.membership_work_guard();
CREATE CONSTRAINT TRIGGER membership_receipt_complete AFTER INSERT ON public.membership_receipts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.membership_work_guard();
CREATE CONSTRAINT TRIGGER membership_decision_complete AFTER INSERT ON public.decisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.membership_work_guard();

CREATE FUNCTION public.membership_evidence_valid(value jsonb, w public.encounter_workspaces) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE artifact public.vendor_artifacts; f public.finance_command_receipts; r public.finance_work_revisions; t public.tickets; last_result public.finance_command_receipts; evidence text;
BEGIN
 IF value IS NULL THEN RETURN true; END IF;
 IF NOT public.finance_settings_keys(value,ARRAY['source_label','system_kind','record_reference','observed_at','document','observed_membership_state','observed_billing_state','reviewed_record_matches_patient','reviewed_document'] || CASE WHEN value ? 'finance' THEN ARRAY['finance'] ELSE ARRAY[]::text[] END)
  OR value->'reviewed_record_matches_patient' IS DISTINCT FROM 'true'::jsonb OR value->'reviewed_document' IS DISTINCT FROM 'true'::jsonb
  OR value->>'system_kind' NOT IN ('hint','atlas_md','practice_owned_ledger','other')
  OR value->>'record_reference' !~ '^[A-Za-z0-9:_-]{1,120}$' OR char_length(value->>'source_label') NOT BETWEEN 1 AND 80
  OR value->>'observed_membership_state' NOT IN ('unknown','not_enrolled','pending_enrollment','active','paused','ended')
  OR value->>'observed_billing_state' NOT IN ('unknown','current','past_due','payment_failed')
  OR (value->>'observed_at')::timestamptz > clock_timestamp()+interval '5 minutes'
  OR NOT public.finance_settings_keys(value->'document',ARRAY['artifact_id','sha256','byte_length','media_type'])
 THEN RETURN false; END IF;
 SELECT * INTO artifact FROM public.vendor_artifacts WHERE artifact_id=(value->'document'->>'artifact_id')::uuid;
 IF artifact.artifact_id IS NULL OR (artifact.workspace_id,artifact.box_id,artifact.owner_id) IS DISTINCT FROM (w.id,w.box_id,w.owner_id) OR artifact.state<>'ready'
  OR value->'document' IS DISTINCT FROM jsonb_build_object('artifact_id',artifact.artifact_id,'sha256',artifact.sha256,'byte_length',artifact.byte_length,'media_type',artifact.media_type)
 THEN RETURN false; END IF;
 IF value ? 'finance' THEN
  IF NOT public.finance_settings_keys(value->'finance',ARRAY['ticket_id','verification_receipt_id','verification_receipt_sha256','evidence_sha256']) THEN RETURN false; END IF;
  SELECT * INTO f FROM public.finance_command_receipts WHERE id=(value->'finance'->>'verification_receipt_id')::uuid;
  SELECT * INTO r FROM public.finance_work_revisions WHERE action_revision_id=f.action_revision_id;
  SELECT * INTO t FROM public.tickets WHERE id=f.ticket_id;
  SELECT * INTO last_result FROM public.finance_command_receipts WHERE ticket_id=f.ticket_id AND command_kind='result' ORDER BY effect_version DESC LIMIT 1;
  evidence:=public.vendor_public_digest('cosmas-finance-evidence.v1',jsonb_build_object('operation_id',r.intended_operation_id,'observation_head',public.finance_head(r.intended_operation_id),'result_receipt_id',last_result.id,'result_receipt_sha256',last_result.receipt_sha256));
  IF f.id IS NULL OR f.command_kind<>'verify' OR (f.workspace_id,f.box_id,f.owner_id,r.patient_link_id) IS DISTINCT FROM (w.id,w.box_id,w.owner_id,w.patient_link_id)
   OR t.state<>'closed' OR t.current_revision_id<>f.action_revision_id OR value->'finance' IS DISTINCT FROM jsonb_build_object('ticket_id',f.ticket_id,'verification_receipt_id',f.id,'verification_receipt_sha256',f.receipt_sha256,'evidence_sha256',evidence)
  THEN RETURN false; END IF;
 END IF;
 RETURN true;
END $$;

CREATE FUNCTION public.membership_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public.membership_work; t public.tickets; w public.encounter_workspaces; previous public.membership_receipts; last_result public.membership_receipts;
 expected_effect text; expected_state text; category text; result jsonb; names text[];
BEGIN
 SELECT * INTO r FROM public.membership_work WHERE ticket_id=NEW.ticket_id;
 SELECT * INTO t FROM public.tickets WHERE id=NEW.ticket_id FOR UPDATE;
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=r.workspace_id;
 SELECT * INTO previous FROM public.membership_receipts WHERE ticket_id=NEW.ticket_id ORDER BY version DESC LIMIT 1;
 SELECT * INTO last_result FROM public.membership_receipts WHERE ticket_id=NEW.ticket_id AND command_kind='result' ORDER BY version DESC LIMIT 1;
 IF r.ticket_id IS NULL OR NEW.version<>coalesce(previous.version,0)+1 OR NEW.version<>t.version
  OR NEW.request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
  OR NEW.request_sha256<>public.vendor_public_digest('cosmas-membership-request.v1',jsonb_build_object('scope',jsonb_build_object('box_id',NEW.box_id,'owner_id',NEW.owner_id,'workspace_id',NEW.workspace_id),'command_kind',NEW.command_kind,'request',NEW.request))
 THEN RAISE EXCEPTION 'membership receipt identity mismatch' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id AND state='active' AND principal_type='human')
  OR NOT EXISTS(SELECT 1 FROM public.patient_links WHERE id=w.patient_link_id AND box_id=w.box_id AND state='confirmed' AND revoked_at IS NULL)
 THEN RAISE EXCEPTION 'membership current human or patient unavailable' USING ERRCODE='23514'; END IF;
 IF NEW.command_kind<>'withdraw' THEN
  IF (w.box_id,w.owner_id,w.patient_link_id,w.revision) IS DISTINCT FROM (r.box_id,r.owner_id,r.patient_link_id,r.source_workspace_revision)
   OR r.note_id IS DISTINCT FROM (SELECT id FROM public.workspace_notes WHERE workspace_id=w.id ORDER BY version DESC LIMIT 1)
   OR NOT EXISTS(SELECT 1 FROM public.patient_links WHERE id=w.patient_link_id AND box_id=w.box_id AND state='confirmed' AND revoked_at IS NULL)
   OR NOT EXISTS(SELECT 1 FROM public.principals WHERE id=w.owner_id AND box_id=w.box_id AND state='active' AND principal_type='human')
  THEN RAISE EXCEPTION 'membership source changed' USING ERRCODE='23514'; END IF;
 END IF;
 category:=CASE WHEN last_result.request->'ledger' ? 'finance' THEN 'manual_ledger_and_finance_review' WHEN last_result.request ? 'ledger' THEN 'manual_ledger_record' ELSE 'local_unreconciled' END;
 IF NEW.command_kind='propose' THEN
  IF previous.id IS NOT NULL OR NEW.request IS DISTINCT FROM r.proposal THEN RAISE EXCEPTION 'membership proposal mismatch' USING ERRCODE='23514'; END IF;
  expected_effect:='proposed';expected_state:='pending_approval';
 ELSE
  IF NEW.request->>'ticket_id' IS DISTINCT FROM t.id::text OR NEW.request->'expected_version' IS DISTINCT FROM to_jsonb(previous.version)
   OR NEW.request->>'revision_id' IS DISTINCT FROM r.revision_id::text OR NEW.request->>'payload_hash' IS DISTINCT FROM r.payload_hash
  THEN RAISE EXCEPTION 'membership exact revision mismatch' USING ERRCODE='23514'; END IF;
  names:=ARRAY['ticket_id','expected_version','revision_id','payload_hash','idempotency_key'];
  IF NEW.command_kind='decide' THEN
   names:=names||ARRAY['review_sha256','choice','reviewed_patient','reviewed_local_only_authority'];
   IF previous.response->'effect'->>'state'<>'pending_approval' OR NEW.request->>'review_sha256' IS DISTINCT FROM r.review_sha256
    OR NEW.request->>'choice' NOT IN ('approve','reject') OR NEW.request->'reviewed_patient' IS DISTINCT FROM 'true'::jsonb OR NEW.request->'reviewed_local_only_authority' IS DISTINCT FROM 'true'::jsonb
    OR NOT EXISTS(SELECT 1 FROM public.decisions WHERE ticket_id=t.id AND action_revision_id=r.revision_id AND actor_principal_id=w.owner_id AND kind=NEW.request->>'choice')
   THEN RAISE EXCEPTION 'membership approval mismatch' USING ERRCODE='23514'; END IF;
   expected_state:=CASE NEW.request->>'choice' WHEN 'approve' THEN 'approved' ELSE 'rejected' END;expected_effect:=expected_state;
  ELSIF NEW.command_kind='result' THEN
   names:=names||ARRAY['disposition','evidence']||CASE WHEN NEW.request ? 'ledger' THEN ARRAY['ledger'] ELSE ARRAY[]::text[] END;
   IF previous.response->'effect'->>'state'<>'approved' OR previous.version>=98 OR NEW.request->>'disposition' NOT IN ('local_preparation_ready','record_reviewed','needs_human')
    OR (NEW.request->>'disposition'='record_reviewed') IS DISTINCT FROM (NEW.request ? 'ledger') OR NOT public.membership_evidence_valid(NEW.request->'ledger',w)
   THEN RAISE EXCEPTION 'membership result evidence mismatch' USING ERRCODE='23514'; END IF;
   category:=CASE WHEN NEW.request->'ledger' ? 'finance' THEN 'manual_ledger_and_finance_review' WHEN NEW.request ? 'ledger' THEN 'manual_ledger_record' ELSE 'local_unreconciled' END;
   expected_state:='approved';expected_effect:='result_recorded';
  ELSIF NEW.command_kind='verify' THEN
   names:=names||ARRAY['result_receipt_id','result_receipt_sha256','evidence_classification','reviewed_patient','reviewed_result','reviewed_evidence_limits','confirm_review_completion'];
   IF previous.response->'effect'->>'state'<>'approved' OR last_result.id IS NULL OR last_result.request->>'disposition'='needs_human'
    OR NEW.result_receipt_id IS DISTINCT FROM last_result.id OR NEW.request->>'result_receipt_id' IS DISTINCT FROM last_result.id::text OR NEW.request->>'result_receipt_sha256' IS DISTINCT FROM last_result.receipt_sha256
    OR NEW.request->>'evidence_classification' IS DISTINCT FROM category OR NOT public.membership_evidence_valid(last_result.request->'ledger',w)
    OR NEW.request->'reviewed_patient' IS DISTINCT FROM 'true'::jsonb OR NEW.request->'reviewed_result' IS DISTINCT FROM 'true'::jsonb OR NEW.request->'reviewed_evidence_limits' IS DISTINCT FROM 'true'::jsonb OR NEW.request->'confirm_review_completion' IS DISTINCT FROM 'true'::jsonb
   THEN RAISE EXCEPTION 'membership verification mismatch' USING ERRCODE='23514'; END IF;
   expected_state:='closed';expected_effect:='review_verified';
  ELSE
   names:=names||ARRAY['confirm_withdraw'];
   IF previous.response->'effect'->>'state' NOT IN ('pending_approval','approved') OR NEW.request->'confirm_withdraw' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'membership withdrawal mismatch' USING ERRCODE='23514'; END IF;
   expected_state:='withdrawn';expected_effect:='withdrawn';
  END IF;
  IF NOT public.finance_settings_keys(NEW.request,names) THEN RAISE EXCEPTION 'membership command keys mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.command_kind<>'verify' AND NEW.result_receipt_id IS NOT NULL THEN RAISE EXCEPTION 'membership unexpected result binding' USING ERRCODE='23514'; END IF;
 result:=jsonb_build_object('contract_version',1,'scope',jsonb_build_object('box_id',NEW.box_id,'owner_id',NEW.owner_id,'workspace_id',NEW.workspace_id),'command_kind',NEW.command_kind,'idempotency_key',NEW.idempotency_key,'request_sha256',NEW.request_sha256,'outcome','recorded','effect',jsonb_build_object('ticket_id',t.id,'revision_id',r.revision_id,'payload_hash',r.payload_hash,'version',NEW.version,'receipt_id',NEW.id,'recorded_at',NEW.response->'effect'->>'recorded_at','effect',expected_effect,'state',expected_state,'evidence_classification',category,'external_service_verified',false));
 IF t.state<>expected_state OR NEW.response IS DISTINCT FROM result OR (NEW.response->'effect'->>'recorded_at')::timestamptz IS DISTINCT FROM NEW.recorded_at OR NEW.receipt_sha256<>public.vendor_public_digest('cosmas-membership-receipt.v1',result)
 THEN RAISE EXCEPTION 'membership receipt outcome mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER membership_receipt_admission BEFORE INSERT ON public.membership_receipts FOR EACH ROW EXECUTE FUNCTION public.membership_receipt_guard();

CREATE FUNCTION public.membership_no_operation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM public.tickets WHERE id=NEW.ticket_id AND lane='encounter_membership_work') OR EXISTS(SELECT 1 FROM public.membership_work WHERE ticket_id=NEW.ticket_id)
 THEN RAISE EXCEPTION 'membership review has no executable operation' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER membership_no_operation BEFORE INSERT OR UPDATE ON public.operations FOR EACH ROW EXECUTE FUNCTION public.membership_no_operation();
CREATE FUNCTION public.membership_protect_action() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM public.membership_work WHERE ticket_id=OLD.ticket_id) THEN RAISE EXCEPTION 'membership human history is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER membership_action_immutable BEFORE UPDATE OR DELETE ON public.action_revisions FOR EACH ROW EXECUTE FUNCTION public.membership_protect_action();
CREATE TRIGGER membership_decision_immutable BEFORE UPDATE OR DELETE ON public.decisions FOR EACH ROW EXECUTE FUNCTION public.membership_protect_action();
CREATE TRIGGER membership_work_immutable BEFORE UPDATE OR DELETE ON public.membership_work FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER membership_receipts_immutable BEFORE UPDATE OR DELETE ON public.membership_receipts FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
"""


def upgrade():
    op.execute(TABLE_DDL)
    op.execute(GUARDS)


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.membership_work) THEN RAISE EXCEPTION 'membership history prevents downgrade' USING ERRCODE='23514'; END IF; END $$;")
    op.execute("""
DROP TRIGGER membership_action_immutable ON public.action_revisions;
DROP TRIGGER membership_decision_immutable ON public.decisions;
DROP TRIGGER membership_decision_complete ON public.decisions;
DROP TRIGGER membership_no_operation ON public.operations;
DROP TRIGGER membership_ticket_complete ON public.tickets;
DROP TABLE public.membership_receipts;
DROP TABLE public.membership_work;
DROP FUNCTION public.membership_protect_action();
DROP FUNCTION public.membership_no_operation();
DROP FUNCTION public.membership_receipt_guard();
DROP FUNCTION public.membership_evidence_valid(jsonb,public.encounter_workspaces);
DROP FUNCTION public.membership_work_guard();
""")
