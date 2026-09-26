"""Extend exact owner retirement to unadmitted decisions and sends.

No history is rewritten. The existing reciprocal receipt fence and immutable
retirement trigger remain; kind-specific request and receipt hashes stay exact.
"""
from alembic import op

revision = "ab71e0c92d64"
down_revision = "fe4aa2f140a8"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(r"""
DO $$ DECLARE names text[]; BEGIN
 SELECT array_agg(conname) INTO names FROM pg_constraint
 WHERE conrelid='public.vendor_command_retirements'::regclass AND contype='c'
 AND pg_get_constraintdef(oid) LIKE '%command_kind%';
 IF cardinality(names) IS DISTINCT FROM 1 THEN
  RAISE EXCEPTION 'expected one existing vendor retirement command constraint';
 END IF;
 EXECUTE format('ALTER TABLE public.vendor_command_retirements DROP CONSTRAINT %I',names[1]);
END $$;
ALTER TABLE public.vendor_command_retirements ADD CONSTRAINT ck_vendor_retirement_command_kind
 CHECK (actor_id=owner_id AND command_kind IN ('decide','submit','verify') AND idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$');
""")
    op.execute(GUARD_DDL)


def downgrade():
    # Old consumers can leave these records dormant; never reopen retired keys.
    raise RuntimeError("vendor command retirement history must remain forward-compatible")


GUARD_DDL = r"""
CREATE OR REPLACE FUNCTION public.vendor_retirement_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public.vendor_work_revisions; metadata jsonb; sha text;
BEGIN
 PERFORM 1 FROM public.principals WHERE id=NEW.owner_id FOR UPDATE;
 PERFORM 1 FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 SELECT * INTO r FROM public.vendor_work_revisions WHERE action_revision_id=NEW.action_revision_id;
 IF r.action_revision_id IS NULL OR (NEW.box_id,NEW.owner_id,NEW.workspace_id,NEW.ticket_id,NEW.operation_id,NEW.payload_hash)
  IS DISTINCT FROM (r.box_id,r.owner_id,r.workspace_id,r.ticket_id,r.intended_operation_id,r.payload_hash)
  OR NEW.actor_id<>NEW.owner_id OR NEW.command_kind NOT IN ('decide','submit','verify')
  OR NEW.public_request->>'revision_id' IS DISTINCT FROM NEW.action_revision_id::text
  OR NEW.public_request->>'operation_id' IS DISTINCT FROM NEW.operation_id::text
  OR NEW.public_request->>'payload_hash' IS DISTINCT FROM NEW.payload_hash
  OR NEW.public_request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
  OR (NEW.command_kind='verify' AND (NEW.public_request->'reviewed_result' IS DISTINCT FROM 'true'::jsonb
  OR NEW.public_request->'reviewed_observations' IS DISTINCT FROM 'true'::jsonb
  OR NEW.public_request->'outcome_confirmed' IS DISTINCT FROM 'true'::jsonb
  OR jsonb_typeof(NEW.public_request->'reviewed_conflicting_evidence') IS DISTINCT FROM 'boolean'
  OR (NEW.public_request-ARRAY['revision_id','operation_id','payload_hash','idempotency_key','expected_version','result_receipt_id','result_receipt_sha256','observation_head','evidence_sha256','reviewed_result','reviewed_observations','outcome_confirmed','reviewed_conflicting_evidence'])<>'{}'::jsonb
))
  OR (NEW.command_kind='decide' AND (
      (NEW.public_request->>'choice') IS NULL OR (NEW.public_request->>'choice') NOT IN ('approve','reject')
      OR (NEW.public_request->>'review_sha256') IS NULL OR (NEW.public_request->>'review_sha256') !~ '^[a-f0-9]{64}$'
      OR (NEW.public_request-ARRAY['revision_id','operation_id','payload_hash','idempotency_key','expected_version','review_sha256','choice'])<>'{}'::jsonb))
  OR (NEW.command_kind='submit' AND (NEW.public_request-ARRAY['revision_id','operation_id','payload_hash','idempotency_key','expected_version'])<>'{}'::jsonb)
  OR jsonb_typeof(NEW.public_request->'expected_version') IS DISTINCT FROM 'number'
  OR (NEW.public_request->>'expected_version') !~ '^[1-9][0-9]{0,9}$'
  OR (NEW.public_request->>'expected_version')::numeric > 2147483647
  OR NEW.request_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-public-request.v1',jsonb_build_object('command_kind',NEW.command_kind,'scope',jsonb_build_object('kind','workspace','id',NEW.workspace_id),'request',NEW.public_request))
 THEN RAISE EXCEPTION 'vendor retirement exact request mismatch' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM public.vendor_command_receipts q WHERE q.workspace_id=NEW.workspace_id AND q.actor_id=NEW.actor_id AND q.idempotency_key=NEW.idempotency_key AND q.origin='user')
 THEN RAISE EXCEPTION 'recorded vendor command cannot be retired' USING ERRCODE='23514'; END IF;
 metadata:=jsonb_build_object('receipt_id',NEW.id,'ticket_id',NEW.ticket_id,'revision_id',NEW.action_revision_id,'operation_id',NEW.operation_id,'payload_hash',NEW.payload_hash,'retired_at',to_char(NEW.retired_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
 sha:=public.vendor_public_digest('cosmas-vendor-public-retirement.v1',jsonb_build_object('scope',jsonb_build_object('kind','workspace','id',NEW.workspace_id),'command_kind',NEW.command_kind,'idempotency_key',NEW.idempotency_key,'request_sha256',NEW.request_sha256,'retirement',metadata));
 IF NEW.receipt_sha256 IS DISTINCT FROM sha OR NEW.public_retirement IS DISTINCT FROM metadata||jsonb_build_object('receipt_sha256',sha)
 THEN RAISE EXCEPTION 'vendor retirement receipt mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""
