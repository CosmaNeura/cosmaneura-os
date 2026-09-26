"""Conclusive local membership rejection and reciprocal late-admission fencing."""
from alembic import op

revision = "6e04b2f98c71"
down_revision = "4c72a86d1e90"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLE_DDL)
    op.execute(GUARD_DDL)


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.membership_command_retirements) THEN RAISE EXCEPTION 'membership retirement history prevents downgrade' USING ERRCODE='23514'; END IF; END $$;")
    op.execute("DROP TRIGGER membership_00_retirement_fence ON public.membership_receipts; DROP TABLE public.membership_command_retirements; DROP FUNCTION public.membership_retirement_guard(); DROP FUNCTION public.membership_retired_command_fence(); DROP FUNCTION public.membership_rejection_reason(uuid,text,jsonb);")


TABLE_DDL = r"""

CREATE TABLE membership_command_retirements (
	id UUID NOT NULL, 
	ticket_id UUID, 
	command_kind VARCHAR(16) NOT NULL, 
	idempotency_key VARCHAR(100) NOT NULL, 
	request JSONB NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	reason VARCHAR(48) NOT NULL, 
	response JSONB NOT NULL, 
	receipt_sha256 VARCHAR(64) NOT NULL, 
	retired_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), 
	FOREIGN KEY(ticket_id, workspace_id, box_id, owner_id) REFERENCES membership_work (ticket_id, workspace_id, box_id, owner_id), 
	CONSTRAINT uq_membership_retirement_key UNIQUE (workspace_id, owner_id, idempotency_key), 
	CHECK (command_kind IN ('propose','decide','result','verify','withdraw') AND (ticket_id IS NULL)=(command_kind='propose')), 
	CHECK (idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'), 
	CHECK (reason IN ('membership_source_changed','membership_revision_changed','membership_result_changed','membership_exception_unresolved','membership_evidence_changed','membership_history_limit')), 
	CHECK (request_sha256 ~ '^[a-f0-9]{64}$' AND receipt_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(request) = 'object' AND octet_length(request::text) <= 16384), 
	CHECK (jsonb_typeof(response) = 'object' AND octet_length(response::text) <= 8192)
)


"""

GUARD_DDL = r"""
CREATE FUNCTION public.membership_rejection_reason(wid uuid, kind text, q jsonb) RETURNS text LANGUAGE plpgsql AS $$
DECLARE w public.encounter_workspaces; r public.membership_work; t public.tickets; h public.membership_receipts; category text;
BEGIN
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=wid FOR UPDATE;
 IF w.id IS NULL OR NOT EXISTS(SELECT 1 FROM public.principals WHERE id=w.owner_id AND box_id=w.box_id AND state='active' AND principal_type='human')
  OR NOT EXISTS(SELECT 1 FROM public.patient_links WHERE id=w.patient_link_id AND box_id=w.box_id AND state='confirmed' AND revoked_at IS NULL)
 THEN RETURN NULL; END IF;
 IF kind='propose' THEN
  -- Missing/foreign evidence is not authority to retire another patient's request.
  IF q->>'patient_link_id' IS DISTINCT FROM w.patient_link_id::text
   OR NOT EXISTS(SELECT 1 FROM public.workspace_notes n JOIN public.workspace_note_reviews reviewed ON reviewed.note_id=n.id
    WHERE n.id=(q->'source'->>'note_id')::uuid AND n.workspace_id=w.id AND n.box_id=w.box_id AND n.owner_id=w.owner_id
     AND n.content_hash=q->'source'->>'content_sha256' AND n.source_fingerprint=q->'source'->>'source_fingerprint')
   OR (q->>'expected_workspace_revision')::integer>w.revision
  THEN RETURN NULL; END IF;
  IF (q->>'expected_workspace_revision')::integer<w.revision
   OR q->'source'->>'note_id' IS DISTINCT FROM (SELECT id::text FROM public.workspace_notes WHERE workspace_id=w.id ORDER BY version DESC LIMIT 1)
  THEN RETURN 'membership_source_changed'; END IF;
  IF (SELECT count(*) FROM public.membership_work WHERE workspace_id=wid)>=100 THEN RETURN 'membership_history_limit'; END IF;
  RETURN NULL;
 END IF;
 IF kind NOT IN ('decide','result','verify','withdraw') THEN RETURN NULL; END IF;
 SELECT * INTO r FROM public.membership_work WHERE ticket_id=(q->>'ticket_id')::uuid;
 SELECT * INTO t FROM public.tickets WHERE id=r.ticket_id FOR UPDATE;
 IF r.ticket_id IS NULL OR (r.workspace_id,r.box_id,r.owner_id,r.patient_link_id) IS DISTINCT FROM (w.id,w.box_id,w.owner_id,w.patient_link_id)
  OR (t.box_id,t.created_by_principal_id,t.patient_link_id,t.appointment_id,t.current_revision_id,t.lane)
   IS DISTINCT FROM (w.box_id,w.owner_id,w.patient_link_id,w.appointment_id,r.revision_id,'encounter_membership_work')
  OR q->>'revision_id' IS DISTINCT FROM r.revision_id::text OR q->>'payload_hash' IS DISTINCT FROM r.payload_hash
  OR (q->>'expected_version')::integer>t.version
  OR EXISTS(SELECT 1 FROM public.operations WHERE ticket_id=t.id)
 THEN RETURN NULL; END IF;
 IF (q->>'expected_version')::integer<t.version THEN RETURN 'membership_revision_changed'; END IF;
 IF kind<>'withdraw' AND (w.revision<>r.source_workspace_revision
  OR r.note_id IS DISTINCT FROM (SELECT id FROM public.workspace_notes WHERE workspace_id=w.id ORDER BY version DESC LIMIT 1))
 THEN RETURN 'membership_source_changed'; END IF;
 IF kind='withdraw' THEN
  IF t.state NOT IN ('pending_approval','approved') THEN RETURN 'membership_revision_changed'; END IF;
 ELSIF kind='decide' THEN
  IF t.state<>'pending_approval' OR q->>'review_sha256' IS DISTINCT FROM r.review_sha256 THEN RETURN 'membership_revision_changed'; END IF;
 ELSIF kind='result' THEN
  IF t.state<>'approved' THEN RETURN 'membership_revision_changed'; END IF;
  IF t.version>=98 THEN RETURN 'membership_history_limit'; END IF;
  IF NOT public.membership_evidence_valid(q->'ledger',w) THEN RETURN 'membership_evidence_changed'; END IF;
 ELSE
  SELECT * INTO h FROM public.membership_receipts WHERE ticket_id=t.id AND command_kind='result' ORDER BY version DESC LIMIT 1;
  IF t.state<>'approved' OR h.id IS NULL OR q->>'result_receipt_id' IS DISTINCT FROM h.id::text OR q->>'result_receipt_sha256' IS DISTINCT FROM h.receipt_sha256
  THEN RETURN 'membership_result_changed'; END IF;
  category:=CASE WHEN h.request->'ledger' ? 'finance' THEN 'manual_ledger_and_finance_review' WHEN h.request ? 'ledger' THEN 'manual_ledger_record' ELSE 'local_unreconciled' END;
  IF h.request->>'disposition'='needs_human' OR q->>'evidence_classification' IS DISTINCT FROM category THEN RETURN 'membership_exception_unresolved'; END IF;
  IF NOT public.membership_evidence_valid(h.request->'ledger',w) THEN RETURN 'membership_evidence_changed'; END IF;
 END IF;
 IF t.version>=100 THEN RETURN 'membership_history_limit'; END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION public.membership_retirement_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE reason text; result jsonb; names text[];
BEGIN
 PERFORM 1 FROM public.principals WHERE id=NEW.owner_id FOR UPDATE;
 PERFORM 1 FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 IF NEW.request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
  OR NEW.request_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-membership-request.v1',jsonb_build_object('scope',jsonb_build_object('box_id',NEW.box_id,'owner_id',NEW.owner_id,'workspace_id',NEW.workspace_id),'command_kind',NEW.command_kind,'request',NEW.request))
  OR NOT EXISTS(SELECT 1 FROM public.encounter_workspaces WHERE id=NEW.workspace_id AND box_id=NEW.box_id AND owner_id=NEW.owner_id)
  OR NEW.ticket_id::text IS DISTINCT FROM NEW.request->>'ticket_id'
 THEN RAISE EXCEPTION 'membership retirement exact identity mismatch' USING ERRCODE='23514'; END IF;
 names:=ARRAY['ticket_id','expected_version','revision_id','payload_hash','idempotency_key'];
 IF NEW.command_kind='propose' THEN names:=ARRAY['expected_workspace_revision','idempotency_key','source','patient_link_id','purpose','due_date','expected_outcome','instructions'];
 ELSIF NEW.command_kind='decide' THEN names:=names||ARRAY['review_sha256','choice','reviewed_patient','reviewed_local_only_authority'];
 ELSIF NEW.command_kind='result' THEN names:=names||ARRAY['disposition','evidence']||CASE WHEN NEW.request ? 'ledger' THEN ARRAY['ledger'] ELSE ARRAY[]::text[] END;
 ELSIF NEW.command_kind='verify' THEN names:=names||ARRAY['result_receipt_id','result_receipt_sha256','evidence_classification','reviewed_patient','reviewed_result','reviewed_evidence_limits','confirm_review_completion'];
 ELSE names:=names||ARRAY['confirm_withdraw']; END IF;
 IF NOT public.finance_settings_keys(NEW.request,names) THEN RAISE EXCEPTION 'membership retirement exact keys mismatch' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM public.membership_receipts q WHERE q.workspace_id=NEW.workspace_id AND q.owner_id=NEW.owner_id AND q.idempotency_key=NEW.idempotency_key)
 THEN RAISE EXCEPTION 'recorded membership command cannot be retired' USING ERRCODE='23514'; END IF;
 reason:=public.membership_rejection_reason(NEW.workspace_id,NEW.command_kind,NEW.request);
 IF reason IS NULL OR reason IS DISTINCT FROM NEW.reason THEN RAISE EXCEPTION 'membership retirement requires conclusive rejection' USING ERRCODE='23514'; END IF;
 result:=jsonb_build_object('contract_version',1,'scope',jsonb_build_object('box_id',NEW.box_id,'owner_id',NEW.owner_id,'workspace_id',NEW.workspace_id),'command_kind',NEW.command_kind,'idempotency_key',NEW.idempotency_key,'request_sha256',NEW.request_sha256,'outcome','retired','effect',NULL,'retirement',jsonb_build_object('receipt_id',NEW.id,'reason',NEW.reason,'retired_at',to_char(NEW.retired_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')));
 IF NEW.response IS DISTINCT FROM result OR NEW.receipt_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-membership-retirement.v1',result)
 THEN RAISE EXCEPTION 'membership retirement receipt mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER membership_retirement_admission BEFORE INSERT ON public.membership_command_retirements FOR EACH ROW EXECUTE FUNCTION public.membership_retirement_guard();
CREATE TRIGGER membership_retirement_immutable BEFORE UPDATE OR DELETE ON public.membership_command_retirements FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();

CREATE FUNCTION public.membership_retired_command_fence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM 1 FROM public.principals WHERE id=NEW.owner_id FOR UPDATE;
 PERFORM 1 FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 IF EXISTS(SELECT 1 FROM public.membership_command_retirements q WHERE q.workspace_id=NEW.workspace_id AND q.owner_id=NEW.owner_id AND q.idempotency_key=NEW.idempotency_key)
 THEN RAISE EXCEPTION 'retired membership command cannot be admitted' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER membership_00_retirement_fence BEFORE INSERT ON public.membership_receipts FOR EACH ROW EXECUTE FUNCTION public.membership_retired_command_fence();
"""
