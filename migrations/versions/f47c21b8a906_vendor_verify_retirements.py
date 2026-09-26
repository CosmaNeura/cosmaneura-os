"""Exact owner verification retirement, with reciprocal no-admission fencing."""
from alembic import op

revision = "f47c21b8a906"
down_revision = "e93a047b1c62"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLE_DDL)
    op.execute(GUARD_DDL)


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.vendor_command_retirements) THEN RAISE EXCEPTION 'retirement history prevents downgrade' USING ERRCODE='23514'; END IF; END $$;")
    op.execute("DROP TRIGGER vendor_00_retirement_fence ON public.vendor_command_receipts; DROP TABLE public.vendor_command_retirements; DROP FUNCTION public.vendor_retirement_guard(); DROP FUNCTION public.vendor_retired_command_fence();")


TABLE_DDL = r"""

CREATE TABLE vendor_command_retirements (
	id UUID NOT NULL, 
	actor_id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	action_revision_id UUID NOT NULL, 
	operation_id UUID NOT NULL, 
	command_kind VARCHAR(24) NOT NULL, 
	idempotency_key VARCHAR(100) NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	payload_hash VARCHAR(64) NOT NULL, 
	public_request JSONB NOT NULL, 
	public_retirement JSONB NOT NULL, 
	receipt_sha256 VARCHAR(64) NOT NULL, 
	retired_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), 
	FOREIGN KEY(operation_id, action_revision_id, ticket_id, box_id) REFERENCES vendor_work_revisions (intended_operation_id, action_revision_id, ticket_id, box_id), 
	CONSTRAINT uq_vendor_retirement_key UNIQUE (workspace_id, actor_id, idempotency_key), 
	CHECK (actor_id=owner_id AND command_kind='verify' AND idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'), 
	CHECK (request_sha256 ~ '^[a-f0-9]{64}$' AND receipt_sha256 ~ '^[a-f0-9]{64}$' AND payload_hash ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(public_request) = 'object' AND octet_length(public_request::text) <= 4096), 
	CHECK (jsonb_typeof(public_retirement) = 'object' AND octet_length(public_retirement::text) <= 4096)
)


"""

GUARD_DDL = r"""
CREATE FUNCTION public.vendor_retirement_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public.vendor_work_revisions; metadata jsonb; sha text;
BEGIN
 PERFORM 1 FROM public.principals WHERE id=NEW.owner_id FOR UPDATE;
 PERFORM 1 FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 SELECT * INTO r FROM public.vendor_work_revisions WHERE action_revision_id=NEW.action_revision_id;
 IF r.action_revision_id IS NULL OR (NEW.box_id,NEW.owner_id,NEW.workspace_id,NEW.ticket_id,NEW.operation_id,NEW.payload_hash)
  IS DISTINCT FROM (r.box_id,r.owner_id,r.workspace_id,r.ticket_id,r.intended_operation_id,r.payload_hash)
  OR NEW.actor_id<>NEW.owner_id OR NEW.command_kind<>'verify'
  OR NEW.public_request->>'revision_id' IS DISTINCT FROM NEW.action_revision_id::text
  OR NEW.public_request->>'operation_id' IS DISTINCT FROM NEW.operation_id::text
  OR NEW.public_request->>'payload_hash' IS DISTINCT FROM NEW.payload_hash
  OR NEW.public_request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
  OR NEW.public_request->'reviewed_result' IS DISTINCT FROM 'true'::jsonb
  OR NEW.public_request->'reviewed_observations' IS DISTINCT FROM 'true'::jsonb
  OR NEW.public_request->'outcome_confirmed' IS DISTINCT FROM 'true'::jsonb
  OR jsonb_typeof(NEW.public_request->'reviewed_conflicting_evidence') IS DISTINCT FROM 'boolean'
  OR (NEW.public_request-ARRAY['revision_id','operation_id','payload_hash','idempotency_key','expected_version','result_receipt_id','result_receipt_sha256','observation_head','evidence_sha256','reviewed_result','reviewed_observations','outcome_confirmed','reviewed_conflicting_evidence'])<>'{}'::jsonb
  OR NEW.request_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-public-request.v1',jsonb_build_object('command_kind','verify','scope',jsonb_build_object('kind','workspace','id',NEW.workspace_id),'request',NEW.public_request))
 THEN RAISE EXCEPTION 'vendor retirement exact request mismatch' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM public.vendor_command_receipts q WHERE q.workspace_id=NEW.workspace_id AND q.actor_id=NEW.actor_id AND q.idempotency_key=NEW.idempotency_key AND q.origin='user')
 THEN RAISE EXCEPTION 'recorded vendor command cannot be retired' USING ERRCODE='23514'; END IF;
 metadata:=jsonb_build_object('receipt_id',NEW.id,'ticket_id',NEW.ticket_id,'revision_id',NEW.action_revision_id,'operation_id',NEW.operation_id,'payload_hash',NEW.payload_hash,'retired_at',to_char(NEW.retired_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
 sha:=public.vendor_public_digest('cosmas-vendor-public-retirement.v1',jsonb_build_object('scope',jsonb_build_object('kind','workspace','id',NEW.workspace_id),'command_kind','verify','idempotency_key',NEW.idempotency_key,'request_sha256',NEW.request_sha256,'retirement',metadata));
 IF NEW.receipt_sha256 IS DISTINCT FROM sha OR NEW.public_retirement IS DISTINCT FROM metadata||jsonb_build_object('receipt_sha256',sha)
 THEN RAISE EXCEPTION 'vendor retirement receipt mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER vendor_retirement_admission BEFORE INSERT ON public.vendor_command_retirements FOR EACH ROW EXECUTE FUNCTION public.vendor_retirement_guard();
CREATE TRIGGER vendor_retirement_immutable BEFORE UPDATE OR DELETE ON public.vendor_command_retirements FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();

CREATE FUNCTION public.vendor_retired_command_fence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.origin='user' THEN
  PERFORM 1 FROM public.principals WHERE id=NEW.owner_id FOR UPDATE;
  PERFORM 1 FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
  IF EXISTS(SELECT 1 FROM public.vendor_command_retirements retired WHERE retired.workspace_id=NEW.workspace_id AND retired.actor_id=NEW.actor_id AND retired.idempotency_key=NEW.idempotency_key)
  THEN RAISE EXCEPTION 'retired vendor command cannot be admitted' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER vendor_00_retirement_fence BEFORE INSERT ON public.vendor_command_receipts FOR EACH ROW EXECUTE FUNCTION public.vendor_retired_command_fence();
"""
