"""Reviewed local portal mapping administration; production registry remains empty."""

from alembic import op

revision = "d902e7c14b63"
down_revision = "8ab4d11ce208"
branch_labels = None
depends_on = None

# Frozen DDL; independent of future ORM imports.
TABLE_DDL = r"""

CREATE TABLE portal_setups (
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id, box_id) REFERENCES principals (id, box_id), 
	CONSTRAINT uq_portal_setup_scope UNIQUE (id, box_id, owner_id)
)

;

CREATE TABLE portal_setup_revisions (
	id UUID NOT NULL, 
	connection_id UUID NOT NULL, 
	revision INTEGER NOT NULL, 
	installation_id UUID NOT NULL, 
	portal_id VARCHAR(32) NOT NULL, 
	profile_sha256 VARCHAR(64) NOT NULL, 
	configuration_sha256 VARCHAR(64) NOT NULL, 
	patient_link_id UUID NOT NULL, 
	practice_mapping_id UUID NOT NULL, 
	patient_mapping_id UUID NOT NULL, 
	recipient_mapping_id UUID NOT NULL, 
	mappings_sha256 VARCHAR(64) NOT NULL, 
	review JSONB NOT NULL, 
	review_sha256 VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(connection_id, box_id, owner_id) REFERENCES portal_setups (id, box_id, owner_id), 
	FOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id), 
	CONSTRAINT uq_portal_setup_revision_scope UNIQUE (id, connection_id, box_id, owner_id), 
	CONSTRAINT uq_portal_setup_revision UNIQUE (connection_id, revision), 
	CHECK (revision BETWEEN 1 AND 100), 
	CHECK (profile_sha256 ~ '^[a-f0-9]{64}$' AND configuration_sha256 ~ '^[a-f0-9]{64}$' AND review_sha256 ~ '^[a-f0-9]{64}$' AND mappings_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(review) = 'object' AND octet_length(review::text) <= 8192)
)

;

CREATE TABLE portal_setup_receipts (
	id UUID NOT NULL, 
	connection_id UUID NOT NULL, 
	revision_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	command_kind VARCHAR(16) NOT NULL, 
	state VARCHAR(16) NOT NULL, 
	idempotency_key VARCHAR(100) NOT NULL, 
	request JSONB NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	response JSONB NOT NULL, 
	receipt_sha256 VARCHAR(64) NOT NULL, 
	recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(revision_id, connection_id, box_id, owner_id) REFERENCES portal_setup_revisions (id, connection_id, box_id, owner_id), 
	CONSTRAINT uq_portal_setup_version UNIQUE (connection_id, version), 
	CONSTRAINT uq_portal_setup_command_key UNIQUE (box_id, owner_id, idempotency_key), 
	CHECK (command_kind IN ('propose','activate','disable','revoke') AND version BETWEEN 1 AND 1000), 
	CHECK (state IN ('pending_review','active','disabled','revoked')), 
	CHECK (idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'), 
	CHECK (request_sha256 ~ '^[a-f0-9]{64}$' AND receipt_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(request) = 'object' AND octet_length(request::text) <= 8192), 
	CHECK (jsonb_typeof(response) = 'object' AND octet_length(response::text) <= 4096)
)

;
"""

GUARDS = r"""
CREATE FUNCTION public.portal_setup_keys(value jsonb, names text[]) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
  SELECT coalesce(jsonb_typeof(value)='object' AND value ?& names AND value-names='{}'::jsonb,false)
$$;
CREATE FUNCTION public.portal_setup_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT public.portal_setup_keys(NEW.review,ARRAY['connection_id','installation_id','portal_id','profile_label','mode',
      'profile_sha256','configuration_sha256','capabilities','mappings','mapping_ids','mappings_sha256'])
    OR NOT public.portal_setup_keys(NEW.review->'mappings',ARRAY['patient_link_id','practice_reference','patient_reference',
      'recipient_reference','practice_label','recipient_label','patient_label'])
    OR NEW.portal_id !~ '^synthetic_[a-z0-9_-]+$'
    OR jsonb_typeof(NEW.review->'capabilities') IS DISTINCT FROM 'array'
    OR NEW.review_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-portal-setup-review.v1',NEW.review)
    OR NEW.review->>'connection_id' IS DISTINCT FROM NEW.connection_id::text
    OR NEW.review->>'installation_id' IS DISTINCT FROM NEW.installation_id::text
    OR NEW.review->>'portal_id' IS DISTINCT FROM NEW.portal_id
    OR NEW.review->>'mode' IS DISTINCT FROM 'synthetic'
    OR NEW.review->>'profile_sha256' IS DISTINCT FROM NEW.profile_sha256
    OR NEW.review->>'configuration_sha256' IS DISTINCT FROM NEW.configuration_sha256
    OR NEW.review->'mappings'->>'patient_link_id' IS DISTINCT FROM NEW.patient_link_id::text
    OR NEW.review->'mapping_ids' IS DISTINCT FROM jsonb_build_object('practice_mapping_id',NEW.practice_mapping_id,
      'patient_mapping_id',NEW.patient_mapping_id,'recipient_mapping_id',NEW.recipient_mapping_id)
    OR NEW.review->>'mappings_sha256' IS DISTINCT FROM NEW.mappings_sha256
    OR NEW.mappings_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-portal-setup-mappings.v1',
      jsonb_build_object('scope',jsonb_build_object('box_id',NEW.box_id,'owner_id',NEW.owner_id),
        'installation_id',NEW.installation_id,'profile_sha256',NEW.profile_sha256,'configuration_sha256',NEW.configuration_sha256,
        'ids',NEW.review->'mapping_ids','mappings',(NEW.review->'mappings')-'patient_label'))
  THEN RAISE EXCEPTION 'portal review binding mismatch' USING ERRCODE='23514'; END IF;
  IF jsonb_array_length(NEW.review->'capabilities') NOT BETWEEN 1 AND 3
    OR (SELECT count(DISTINCT value) FROM jsonb_array_elements(NEW.review->'capabilities'))<>jsonb_array_length(NEW.review->'capabilities')
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.review->'capabilities') cap WHERE cap.value NOT IN
      ('"document.upload"'::jsonb,'"referral.submit"'::jsonb,'"referral.read"'::jsonb))
    OR EXISTS(SELECT 1 FROM unnest(ARRAY['practice_reference','patient_reference','recipient_reference']) k
      WHERE jsonb_typeof(NEW.review->'mappings'->k) IS DISTINCT FROM 'string' OR (NEW.review->'mappings'->>k) !~ '^[A-Za-z0-9_-]{1,120}$')
  THEN RAISE EXCEPTION 'portal capability or reference mismatch' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER portal_setup_revision_binding BEFORE INSERT ON public.portal_setup_revisions
  FOR EACH ROW EXECUTE FUNCTION public.portal_setup_revision_guard();

CREATE FUNCTION public.portal_setup_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous public.portal_setup_receipts; r public.portal_setup_revisions; expected_state text; digest text; request_keys text[];
BEGIN
  PERFORM 1 FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id FOR UPDATE;
  IF NOT EXISTS(SELECT 1 FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id
    AND principal_type='human' AND state='active' AND is_owner AND tombstoned_at IS NULL)
  THEN RAISE EXCEPTION 'portal owner required' USING ERRCODE='23514'; END IF;
  PERFORM 1 FROM public.portal_setups WHERE id=NEW.connection_id FOR UPDATE;
  SELECT * INTO previous FROM public.portal_setup_receipts WHERE connection_id=NEW.connection_id ORDER BY version DESC LIMIT 1;
  SELECT * INTO r FROM public.portal_setup_revisions WHERE id=NEW.revision_id;
  expected_state:=CASE NEW.command_kind WHEN 'propose' THEN 'pending_review' WHEN 'activate' THEN 'active'
    WHEN 'disable' THEN 'disabled' WHEN 'revoke' THEN 'revoked' END;
  request_keys:=ARRAY['connection_id','expected_version','idempotency_key'] || CASE NEW.command_kind
    WHEN 'propose' THEN ARRAY['installation_id','profile_sha256','configuration_sha256','capabilities','mappings']
    WHEN 'activate' THEN ARRAY['revision_id','review_sha256','reviewed_profile','reviewed_practice','reviewed_patient','reviewed_recipient','confirm_local_activation']
    WHEN 'disable' THEN ARRAY['revision_id','review_sha256','confirm_disable']
    WHEN 'revoke' THEN ARRAY['revision_id','review_sha256','confirm_revoke'] END;
  IF r.id IS NULL OR previous.state='revoked' OR NEW.version<>coalesce(previous.version,0)+1
    OR NOT public.portal_setup_keys(NEW.request,request_keys)
    OR NEW.state IS DISTINCT FROM expected_state
    OR NEW.request->'expected_version' IS DISTINCT FROM to_jsonb(coalesce(previous.version,0))
    OR NEW.request->>'connection_id' IS DISTINCT FROM NEW.connection_id::text
    OR NEW.request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
    OR NEW.request_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-portal-setup-request.v1',jsonb_build_object(
      'scope',jsonb_build_object('box_id',NEW.box_id,'owner_id',NEW.owner_id),'command_kind',NEW.command_kind,'request',NEW.request))
    OR (NEW.command_kind<>'propose' AND (previous.id IS NULL OR NEW.revision_id<>previous.revision_id
      OR NEW.request->>'revision_id' IS DISTINCT FROM NEW.revision_id::text OR NEW.request->>'review_sha256' IS DISTINCT FROM r.review_sha256))
    OR (NEW.command_kind='propose' AND (r.revision<>coalesce((SELECT revision FROM public.portal_setup_revisions WHERE id=previous.revision_id),0)+1
      OR NEW.request->>'installation_id' IS DISTINCT FROM r.installation_id::text
      OR NEW.request->>'profile_sha256' IS DISTINCT FROM r.profile_sha256
      OR NEW.request->>'configuration_sha256' IS DISTINCT FROM r.configuration_sha256
      OR NEW.request->'mappings' IS DISTINCT FROM (r.review->'mappings')-'patient_label'))
    OR (NEW.command_kind='activate' AND (previous.state NOT IN ('pending_review','disabled')
      OR NEW.request->'reviewed_profile' IS DISTINCT FROM 'true'::jsonb
      OR NEW.request->'reviewed_practice' IS DISTINCT FROM 'true'::jsonb
      OR NEW.request->'reviewed_patient' IS DISTINCT FROM 'true'::jsonb
      OR NEW.request->'reviewed_recipient' IS DISTINCT FROM 'true'::jsonb
      OR NEW.request->'confirm_local_activation' IS DISTINCT FROM 'true'::jsonb))
    OR (NEW.command_kind='disable' AND (previous.state='disabled' OR NEW.request->'confirm_disable' IS DISTINCT FROM 'true'::jsonb))
    OR (NEW.command_kind='revoke' AND NEW.request->'confirm_revoke' IS DISTINCT FROM 'true'::jsonb)
  THEN RAISE EXCEPTION 'portal command binding mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.command_kind='propose' THEN
    IF jsonb_typeof(NEW.request->'capabilities') IS DISTINCT FROM 'array' THEN
      RAISE EXCEPTION 'portal capability mismatch' USING ERRCODE='23514'; END IF;
    IF (SELECT jsonb_agg(value ORDER BY value::text COLLATE "C") FROM jsonb_array_elements(NEW.request->'capabilities')) IS DISTINCT FROM
       (SELECT jsonb_agg(value ORDER BY value::text COLLATE "C") FROM jsonb_array_elements(r.review->'capabilities'))
    THEN RAISE EXCEPTION 'portal capability mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF NEW.command_kind IN ('propose','activate') AND NOT EXISTS(SELECT 1 FROM public.patient_links WHERE id=r.patient_link_id
    AND box_id=NEW.box_id AND state='confirmed' AND revoked_at IS NULL)
  THEN RAISE EXCEPTION 'portal patient unavailable' USING ERRCODE='23514'; END IF;
  digest:=public.vendor_public_digest('cosmas-portal-setup-receipt.v1',NEW.response-'receipt_sha256');
  IF NOT public.portal_setup_keys(NEW.response,ARRAY['contract_version','outcome','scope','connection_id','command_kind',
      'idempotency_key','request_sha256','receipt_id','recorded_at','effect','receipt_sha256'])
    OR NEW.response->'contract_version' IS DISTINCT FROM '1'::jsonb
    OR NEW.response->>'outcome' IS DISTINCT FROM 'recorded'
    OR (NEW.response->>'recorded_at')::timestamptz IS DISTINCT FROM NEW.recorded_at
    OR NEW.receipt_sha256 IS DISTINCT FROM digest OR NEW.response->>'receipt_sha256' IS DISTINCT FROM digest
    OR NEW.response->>'receipt_id' IS DISTINCT FROM NEW.id::text
    OR NEW.response->>'connection_id' IS DISTINCT FROM NEW.connection_id::text
    OR NEW.response->>'command_kind' IS DISTINCT FROM NEW.command_kind
    OR NEW.response->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
    OR NEW.response->>'request_sha256' IS DISTINCT FROM NEW.request_sha256
    OR NEW.response->'scope' IS DISTINCT FROM jsonb_build_object('box_id',NEW.box_id,'owner_id',NEW.owner_id)
    OR NEW.response->'effect' IS DISTINCT FROM jsonb_build_object('version',NEW.version,'revision_id',NEW.revision_id,'state',NEW.state,'review_sha256',r.review_sha256)
  THEN RAISE EXCEPTION 'portal receipt mismatch' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER portal_setup_receipt_binding BEFORE INSERT ON public.portal_setup_receipts
  FOR EACH ROW EXECUTE FUNCTION public.portal_setup_receipt_guard();
CREATE TRIGGER portal_setups_immutable BEFORE UPDATE OR DELETE ON public.portal_setups
  FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER portal_setup_revisions_immutable BEFORE UPDATE OR DELETE ON public.portal_setup_revisions
  FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER portal_setup_receipts_immutable BEFORE UPDATE OR DELETE ON public.portal_setup_receipts
  FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
"""


def upgrade():
    op.execute(TABLE_DDL)
    op.execute(GUARDS)


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM portal_setups) THEN
      RAISE EXCEPTION 'portal history prevents downgrade' USING ERRCODE='23514'; END IF; END $$""")
    op.execute("DROP TABLE portal_setup_receipts, portal_setup_revisions, portal_setups")
    op.execute(
        "DROP FUNCTION public.portal_setup_receipt_guard(), public.portal_setup_revision_guard(), public.portal_setup_keys(jsonb,text[])"
    )
