"""Append-only preparation retirement and reciprocal exact-key admission fences."""

from alembic import op

revision = "c83a2f19b650"
down_revision = "ab71e0c92d64"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLE_DDL)
    op.execute(GUARD_DDL)


def downgrade():
    raise RuntimeError("Preparation retirement history must remain forward-compatible")


TABLE_DDL = r"""
CREATE TABLE public.vendor_preparation_retirements (
 id uuid PRIMARY KEY,
 box_id uuid NOT NULL,
 workspace_id uuid NOT NULL,
 owner_id uuid NOT NULL,
 actor_id uuid NOT NULL,
 command_kind varchar(24) NOT NULL,
 idempotency_key varchar(100) NOT NULL,
 request_sha256 varchar(64) NOT NULL,
 public_request jsonb NOT NULL,
 public_retirement jsonb NOT NULL,
 receipt_sha256 varchar(64) NOT NULL,
 retired_at timestamptz NOT NULL,
 FOREIGN KEY (workspace_id,box_id,owner_id) REFERENCES public.encounter_workspaces(id,box_id,owner_id),
 CONSTRAINT uq_vendor_preparation_retirement_key UNIQUE(workspace_id,actor_id,idempotency_key),
 CHECK (actor_id=owner_id AND command_kind IN ('propose','artifact_intent','artifact_content') AND idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'),
 CHECK (request_sha256 ~ '^[a-f0-9]{64}$' AND receipt_sha256 ~ '^[a-f0-9]{64}$'),
 CHECK (jsonb_typeof(public_request)='object' AND octet_length(public_request::text)<=65536),
 CHECK (jsonb_typeof(public_retirement)='object' AND octet_length(public_retirement::text)<=4096)
);
"""

GUARD_DDL = r"""
CREATE FUNCTION public.vendor_preparation_retirement_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE names text[]; metadata jsonb; sha text; a public.vendor_artifacts;
BEGIN
 PERFORM 1 FROM public.principals WHERE id=NEW.owner_id FOR UPDATE;
 PERFORM 1 FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 IF NEW.actor_id<>NEW.owner_id
  OR NOT EXISTS(SELECT 1 FROM public.encounter_workspaces WHERE id=NEW.workspace_id AND box_id=NEW.box_id AND owner_id=NEW.owner_id)
  OR NEW.public_request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
  OR octet_length(public.vendor_public_canonical(NEW.public_request))>(CASE WHEN NEW.command_kind='propose' THEN 32768 ELSE 2048 END)
  OR NEW.request_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-public-request.v1',jsonb_build_object('command_kind',NEW.command_kind,'scope',jsonb_build_object('kind','workspace','id',NEW.workspace_id),'request',NEW.public_request))
 THEN RAISE EXCEPTION 'vendor preparation exact request mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.command_kind='propose' THEN
  names:=ARRAY['expected_workspace_revision','idempotency_key','proposed_operation_id','action','connection','source','due_date','expected_outcome','share_to_practice'];
  names:=names||ARRAY(SELECT jsonb_object_keys(NEW.public_request) INTERSECT SELECT unnest(ARRAY['correspondence','document','message','uploaded_media_operation_id','supersedes_operation_id','acknowledge_prior_uncertainty','revises']));
 ELSIF NEW.command_kind='artifact_intent' THEN
  names:=ARRAY['artifact_id','idempotency_key','source','sha256','byte_length','media_type'];
 ELSIF NEW.command_kind='artifact_content' THEN
  names:=ARRAY['artifact_id','intent_sha256','idempotency_key','sha256','byte_length','media_type'];
  SELECT * INTO a FROM public.vendor_artifacts WHERE artifact_id=(NEW.public_request->>'artifact_id')::uuid FOR UPDATE;
  IF a.artifact_id IS NULL OR (a.workspace_id,a.box_id,a.owner_id) IS DISTINCT FROM (NEW.workspace_id,NEW.box_id,NEW.owner_id)
   OR (a.intent_sha256,a.sha256,a.byte_length,a.media_type) IS DISTINCT FROM (NEW.public_request->>'intent_sha256',NEW.public_request->>'sha256',(NEW.public_request->>'byte_length')::integer,NEW.public_request->>'media_type')
  THEN RAISE EXCEPTION 'vendor preparation artifact mismatch' USING ERRCODE='23514'; END IF;
 ELSE RAISE EXCEPTION 'vendor preparation kind mismatch' USING ERRCODE='23514'; END IF;
 IF NOT public.vendor_settings_keys(NEW.public_request,names)
 THEN RAISE EXCEPTION 'vendor preparation exact keys mismatch' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM public.vendor_command_receipts q WHERE q.workspace_id=NEW.workspace_id AND q.actor_id=NEW.actor_id AND q.idempotency_key=NEW.idempotency_key AND q.origin='user')
  OR EXISTS(SELECT 1 FROM public.vendor_artifact_attempts q WHERE q.workspace_id=NEW.workspace_id AND q.actor_id=NEW.actor_id AND q.idempotency_key=NEW.idempotency_key)
 THEN RAISE EXCEPTION 'admitted vendor preparation cannot be retired' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM public.vendor_command_retirements q WHERE q.workspace_id=NEW.workspace_id AND q.actor_id=NEW.actor_id AND q.idempotency_key=NEW.idempotency_key)
 THEN RAISE EXCEPTION 'vendor retirement key already reserved' USING ERRCODE='23514'; END IF;
 metadata:=jsonb_build_object('receipt_id',NEW.id,'retired_at',to_char(NEW.retired_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
 sha:=public.vendor_public_digest('cosmas-vendor-public-preparation-retirement.v1',jsonb_build_object('scope',jsonb_build_object('kind','workspace','id',NEW.workspace_id),'command_kind',NEW.command_kind,'idempotency_key',NEW.idempotency_key,'request_sha256',NEW.request_sha256,'retirement',metadata));
 IF NEW.receipt_sha256 IS DISTINCT FROM sha OR NEW.public_retirement IS DISTINCT FROM metadata||jsonb_build_object('receipt_sha256',sha)
 THEN RAISE EXCEPTION 'vendor preparation receipt mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER vendor_preparation_retirement_admission BEFORE INSERT ON public.vendor_preparation_retirements FOR EACH ROW EXECUTE FUNCTION public.vendor_preparation_retirement_guard();
CREATE TRIGGER vendor_preparation_retirement_immutable BEFORE UPDATE OR DELETE ON public.vendor_preparation_retirements FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();

CREATE FUNCTION public.vendor_preparation_key_fence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='vendor_command_receipts' THEN
  IF NEW.origin<>'user' THEN RETURN NEW; END IF;
 END IF;
 PERFORM 1 FROM public.principals WHERE id=NEW.owner_id FOR UPDATE;
 PERFORM 1 FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 IF EXISTS(SELECT 1 FROM public.vendor_preparation_retirements q WHERE q.workspace_id=NEW.workspace_id AND q.actor_id=NEW.actor_id AND q.idempotency_key=NEW.idempotency_key)
 THEN RAISE EXCEPTION 'retired vendor preparation key cannot be admitted or reused' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='vendor_artifact_attempts' AND EXISTS(SELECT 1 FROM public.vendor_command_retirements q WHERE q.workspace_id=NEW.workspace_id AND q.actor_id=NEW.actor_id AND q.idempotency_key=NEW.idempotency_key)
 THEN RAISE EXCEPTION 'retired vendor command cannot admit an artifact attempt' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER vendor_00_preparation_fence BEFORE INSERT ON public.vendor_command_receipts FOR EACH ROW EXECUTE FUNCTION public.vendor_preparation_key_fence();
CREATE TRIGGER vendor_00_preparation_fence BEFORE INSERT ON public.vendor_command_retirements FOR EACH ROW EXECUTE FUNCTION public.vendor_preparation_key_fence();
CREATE TRIGGER vendor_00_preparation_fence BEFORE INSERT ON public.vendor_artifact_attempts FOR EACH ROW EXECUTE FUNCTION public.vendor_preparation_key_fence();
"""
