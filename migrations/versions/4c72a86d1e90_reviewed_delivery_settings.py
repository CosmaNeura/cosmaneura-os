"""Reviewed private delivery account/recipient setup; no external effects."""

from alembic import op

revision = "4c72a86d1e90"
down_revision = "3b61e79a0f24"
branch_labels = None
depends_on = None
TABLE_DDL = r"""

CREATE TABLE vendor_setups (
	id UUID NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	installation_id UUID, 
	account_setup_id UUID, 
	patient_link_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id, box_id) REFERENCES principals (id, box_id), 
	FOREIGN KEY(account_setup_id, box_id, owner_id) REFERENCES vendor_setups (id, box_id, owner_id), 
	FOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id), 
	CONSTRAINT uq_vendor_setup_scope UNIQUE (id, box_id, owner_id), 
	CONSTRAINT uq_vendor_setup_installation UNIQUE (box_id, owner_id, installation_id), 
	CHECK ((kind='account' AND installation_id IS NOT NULL AND account_setup_id IS NULL AND patient_link_id IS NULL) OR (kind='recipient' AND installation_id IS NULL AND account_setup_id IS NOT NULL AND patient_link_id IS NOT NULL))
)

;

CREATE TABLE vendor_setup_revisions (
	id UUID NOT NULL, 
	setup_id UUID NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	revision INTEGER NOT NULL, 
	installation_id UUID NOT NULL, 
	installation_sha256 VARCHAR(64) NOT NULL, 
	connection_version_id UUID NOT NULL, 
	correspondence_version_id UUID, 
	account_revision_id UUID, 
	patient_link_id UUID, 
	review JSONB NOT NULL, 
	review_sha256 VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(setup_id, box_id, owner_id) REFERENCES vendor_setups (id, box_id, owner_id), 
	FOREIGN KEY(account_revision_id, box_id, owner_id) REFERENCES vendor_setup_revisions (id, box_id, owner_id), 
	FOREIGN KEY(connection_version_id, box_id, owner_id) REFERENCES vendor_connection_versions (id, box_id, owner_id), 
	FOREIGN KEY(correspondence_version_id, connection_version_id, patient_link_id, box_id, owner_id) REFERENCES vendor_correspondence_versions (id, connection_version_id, patient_link_id, box_id, owner_id), 
	CONSTRAINT uq_vendor_setup_revision_owner UNIQUE (id, box_id, owner_id), 
	CONSTRAINT uq_vendor_setup_revision_scope UNIQUE (id, setup_id, box_id, owner_id), 
	CONSTRAINT uq_vendor_setup_revision UNIQUE (setup_id, revision), 
	CONSTRAINT uq_vendor_setup_recipient_binding UNIQUE (correspondence_version_id), 
	CHECK (revision BETWEEN 1 AND 20), 
	CHECK ((kind='account' AND correspondence_version_id IS NULL AND account_revision_id IS NULL AND patient_link_id IS NULL) OR (kind='recipient' AND correspondence_version_id IS NOT NULL AND account_revision_id IS NOT NULL AND patient_link_id IS NOT NULL)), 
	CHECK (installation_sha256 ~ '^[a-f0-9]{64}$' AND review_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(review) = 'object' AND octet_length(review::text) <= 8192)
)

;

CREATE TABLE vendor_setup_receipts (
	id UUID NOT NULL, 
	setup_id UUID NOT NULL, 
	revision_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	command_kind VARCHAR(24) NOT NULL, 
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
	FOREIGN KEY(revision_id, setup_id, box_id, owner_id) REFERENCES vendor_setup_revisions (id, setup_id, box_id, owner_id), 
	CONSTRAINT uq_vendor_setup_version UNIQUE (setup_id, version), 
	CONSTRAINT uq_vendor_setup_command UNIQUE (box_id, owner_id, idempotency_key), 
	CHECK (version BETWEEN 1 AND 100 AND command_kind IN ('propose_account','propose_recipient','activate','disable','revoke') AND state IN ('pending_review','active','disabled','revoked')), 
	CHECK (idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'), 
	CHECK (request_sha256 ~ '^[a-f0-9]{64}$' AND receipt_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(request) = 'object' AND octet_length(request::text) <= 8192), 
	CHECK (jsonb_typeof(response) = 'object' AND octet_length(response::text) <= 4096)
)

;
"""
GUARDS = r"""

CREATE FUNCTION public.vendor_settings_keys(value jsonb, names text[]) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_typeof(value)='object' AND value ?& names AND value-names='{}'::jsonb,false)
$$;
CREATE FUNCTION public.vendor_settings_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE e public.vendor_setups; c public.vendor_connection_versions; m public.vendor_correspondence_versions;
 account_revision public.vendor_setup_revisions; account_head public.vendor_setup_receipts; patient public.patient_links;
 names text[];
BEGIN
 SELECT * INTO e FROM public.vendor_setups WHERE id=NEW.setup_id;
 SELECT * INTO c FROM public.vendor_connection_versions WHERE id=NEW.connection_version_id;
 names:=ARRAY['kind','setup_id','revision_id','revision','installed','label','connection_version_id'] ||
 CASE NEW.kind WHEN 'account' THEN ARRAY['permissions'] ELSE ARRAY['account','account_label','correspondence_version_id','patient','destination','permission_reference','expires_at'] END;
 IF e.id IS NULL OR e.kind IS DISTINCT FROM NEW.kind OR c.id IS NULL
  OR NOT public.vendor_settings_keys(NEW.review,names)
  OR NOT public.vendor_settings_keys(NEW.review->'installed',ARRAY['installation_id','installation_sha256','label','vendor','environment','account_reference','sender_label','capabilities'])
  OR NEW.review_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-setup-review.v1',NEW.review)
  OR NEW.review->>'kind' IS DISTINCT FROM NEW.kind OR NEW.review->>'setup_id' IS DISTINCT FROM NEW.setup_id::text
  OR NEW.review->>'revision_id' IS DISTINCT FROM NEW.id::text OR NEW.review->'revision' IS DISTINCT FROM to_jsonb(NEW.revision)
  OR NEW.review->>'connection_version_id' IS DISTINCT FROM NEW.connection_version_id::text
  OR NEW.review->'installed'->>'installation_id' IS DISTINCT FROM NEW.installation_id::text
  OR NEW.review->'installed'->>'installation_sha256' IS DISTINCT FROM NEW.installation_sha256
  OR NEW.review->'installed'->>'environment' IS DISTINCT FROM c.environment
  OR NEW.review->'installed'->>'account_reference' IS DISTINCT FROM c.private_selection->>'remote_account_id'
  OR NEW.review->'installed'->>'vendor' IS DISTINCT FROM c.vendor
  OR c.vendor NOT IN ('spruce','srfax','documo')
  OR jsonb_typeof(NEW.review->'installed'->'capabilities') IS DISTINCT FROM 'array'
  OR jsonb_array_length(NEW.review->'installed'->'capabilities') NOT BETWEEN 1 AND 3
  OR NOT ((NEW.review->'installed'->'capabilities') <@ CASE c.vendor WHEN 'spruce' THEN '["spruce_secure_message","spruce_fax","spruce_media_upload"]'::jsonb WHEN 'srfax' THEN '["srfax_fax"]'::jsonb ELSE '["documo_fax"]'::jsonb END)
  OR (SELECT count(DISTINCT value) FROM jsonb_array_elements(NEW.review->'installed'->'capabilities')) <> jsonb_array_length(NEW.review->'installed'->'capabilities')

  OR c.private_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-selection.v1',c.private_selection)
  OR c.public_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-public-selection.v1',c.public_view-'public_sha256')
  OR c.private_selection->>'connection_id' IS DISTINCT FROM c.id::text
  OR c.private_selection->>'box_id' IS DISTINCT FROM c.box_id::text
  OR c.private_selection->>'owner_id' IS DISTINCT FROM c.owner_id::text
  OR c.private_selection->>'environment' IS DISTINCT FROM c.environment
  OR c.private_selection->>'vendor' IS DISTINCT FROM c.vendor
  OR c.public_view->>'vendor' IS DISTINCT FROM c.vendor
  OR c.public_view->>'environment' IS DISTINCT FROM c.environment
  OR c.public_view->>'id' IS DISTINCT FROM c.id::text
  OR c.public_view->'revision' IS DISTINCT FROM to_jsonb(c.revision)
 THEN RAISE EXCEPTION 'vendor settings review binding mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.kind='account' THEN
  IF NEW.installation_id IS DISTINCT FROM e.installation_id
   OR NEW.review->>'label' IS DISTINCT FROM c.public_view->>'label'
   OR NOT public.vendor_settings_keys(NEW.review->'permissions',ARRAY['read_status','prepare_and_submit','actions'])
   OR jsonb_typeof(NEW.review->'permissions'->'read_status') IS DISTINCT FROM 'boolean'
   OR jsonb_typeof(NEW.review->'permissions'->'prepare_and_submit') IS DISTINCT FROM 'boolean'
   OR NOT ((NEW.review->'permissions'->>'read_status')::boolean OR (NEW.review->'permissions'->>'prepare_and_submit')::boolean)
   OR NEW.review->'permissions'->'actions' IS DISTINCT FROM c.public_view->'actions'
   OR NOT ((NEW.review->'installed'->'capabilities') @> (NEW.review->'permissions'->'actions'))
   OR jsonb_typeof(NEW.review->'permissions'->'actions') IS DISTINCT FROM 'array'
   OR jsonb_array_length(NEW.review->'permissions'->'actions') NOT BETWEEN 1 AND 3
   OR (SELECT count(DISTINCT value) FROM jsonb_array_elements(NEW.review->'permissions'->'actions')) <> jsonb_array_length(NEW.review->'permissions'->'actions')
   OR ((NEW.review->'permissions'->'actions') ? 'spruce_fax' AND NOT (NEW.review->'permissions'->'actions') ? 'spruce_media_upload')
   OR c.family_id IS DISTINCT FROM NEW.setup_id OR c.revision IS DISTINCT FROM NEW.revision
   OR EXISTS(SELECT 1 FROM public.vendor_setup_revisions WHERE kind='account' AND connection_version_id=NEW.connection_version_id)
  THEN RAISE EXCEPTION 'vendor account review mismatch' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO m FROM public.vendor_correspondence_versions WHERE id=NEW.correspondence_version_id;
  SELECT * INTO patient FROM public.patient_links WHERE id=NEW.patient_link_id;
  SELECT * INTO account_revision FROM public.vendor_setup_revisions WHERE id=NEW.account_revision_id;
  SELECT * INTO account_head FROM public.vendor_setup_receipts WHERE setup_id=e.account_setup_id ORDER BY version DESC LIMIT 1;
  IF m.id IS NULL OR account_revision.kind IS DISTINCT FROM 'account' OR account_head.state IS DISTINCT FROM 'active'
   OR account_head.revision_id IS DISTINCT FROM account_revision.id
   OR (account_revision.setup_id,account_revision.connection_version_id,account_revision.installation_id,account_revision.installation_sha256)
      IS DISTINCT FROM (e.account_setup_id,NEW.connection_version_id,NEW.installation_id,NEW.installation_sha256)
   OR NEW.review->'installed' IS DISTINCT FROM account_revision.review->'installed'
   OR NEW.review->'account' IS DISTINCT FROM jsonb_build_object('setup_id',e.account_setup_id,'expected_version',account_head.version,'revision_id',account_revision.id,'review_sha256',account_revision.review_sha256)
   OR NEW.review->>'account_label' IS DISTINCT FROM account_revision.review->>'label'
   OR NEW.review->>'correspondence_version_id' IS DISTINCT FROM m.id::text
   OR NEW.review->>'label' IS DISTINCT FROM m.public_view->>'recipient_label'
   OR m.family_id IS DISTINCT FROM NEW.setup_id OR m.revision IS DISTINCT FROM NEW.revision
   OR m.public_view->'revision' IS DISTINCT FROM to_jsonb(m.revision)
   OR m.public_view->>'id' IS DISTINCT FROM m.id::text
   OR m.public_view->>'connection_id' IS DISTINCT FROM m.connection_version_id::text
   OR m.public_view->>'channel' IS DISTINCT FROM NEW.review->'destination'->>'channel'
   OR m.public_view->>'expires_at' IS DISTINCT FROM NEW.review->>'expires_at'
   OR m.expires_at IS DISTINCT FROM (NEW.review->>'expires_at')::timestamptz
   OR m.expires_at <= m.reviewed_at OR m.expires_at>m.reviewed_at+interval '30 days'
   OR m.public_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-public-selection.v1',m.public_view-'public_sha256')
   OR m.private_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-correspondence.v1',m.private_proof)
   OR m.private_proof IS DISTINCT FROM jsonb_build_object(
    'destination',CASE WHEN c.vendor='spruce' THEN NEW.review->'destination' ELSE to_jsonb(substring(NEW.review->'destination'->>'number' FROM 2)) END,
    'permission_sha256',public.vendor_public_digest('cosmas-vendor-recipient-permission.v1',jsonb_build_object('scope',jsonb_build_object('box_id',NEW.box_id,'owner_id',NEW.owner_id),'patient_link_id',NEW.patient_link_id,'destination',NEW.review->'destination','permission_reference',NEW.review->'permission_reference','expires_at',NEW.review->'expires_at')),
    'patient_mapping_sha256',public.vendor_public_digest('cosmas-vendor-patient-mapping.v1',jsonb_build_object('box_id',NEW.box_id,'patient_link_id',NEW.patient_link_id)),
    'practice_mapping_sha256',public.vendor_public_digest('cosmas-vendor-practice-mapping.v1',jsonb_build_object('connection_version_id',NEW.connection_version_id,'installation_sha256',NEW.installation_sha256)),
    'recipient_mapping_sha256',public.vendor_public_digest('cosmas-vendor-recipient-mapping.v1',jsonb_build_object('account',NEW.review->'account','patient_link_id',NEW.patient_link_id,'destination',NEW.review->'destination')))
   OR account_revision.review->'permissions'->'prepare_and_submit' IS DISTINCT FROM 'true'::jsonb
   OR NOT (account_revision.review->'permissions'->'actions' ? CASE NEW.review->'destination'->>'channel' WHEN 'secure' THEN 'spruce_secure_message' ELSE c.vendor||'_fax' END)
   OR (NEW.review->'destination'->>'channel'='secure' AND (c.vendor<>'spruce' OR NOT public.vendor_settings_keys(NEW.review->'destination',ARRAY['channel','contact_id']) OR NEW.review->'destination'->>'contact_id' !~ '^[A-Za-z0-9_-]{1,100}$'))
   OR (NEW.review->'destination'->>'channel'='fax' AND (NOT public.vendor_settings_keys(NEW.review->'destination',ARRAY['channel','number']) OR NEW.review->'destination'->>'number' !~ '^\+1[2-9][0-9]{9}$'))
   OR NEW.review->'destination'->>'channel' NOT IN ('secure','fax')
   OR (e.patient_link_id,NEW.patient_link_id) IS DISTINCT FROM (m.patient_link_id,m.patient_link_id)
   OR patient.state IS DISTINCT FROM 'confirmed' OR patient.revoked_at IS NOT NULL
   OR NEW.review->'patient' IS DISTINCT FROM jsonb_build_object('patient_link_id',patient.id,'label',patient.label)
  THEN RAISE EXCEPTION 'vendor recipient review mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER vendor_settings_revision_admission BEFORE INSERT ON public.vendor_setup_revisions FOR EACH ROW EXECUTE FUNCTION public.vendor_settings_revision_guard();

CREATE FUNCTION public.vendor_settings_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous public.vendor_setup_receipts; r public.vendor_setup_revisions; e public.vendor_setups;
 expected_state text; keys text[]; result jsonb;
BEGIN
 PERFORM 1 FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id
  AND principal_type='human' AND state='active' AND is_owner AND tombstoned_at IS NULL)
 THEN RAISE EXCEPTION 'vendor settings owner required' USING ERRCODE='23514'; END IF;
 SELECT * INTO e FROM public.vendor_setups WHERE id=NEW.setup_id FOR UPDATE;
 SELECT * INTO r FROM public.vendor_setup_revisions WHERE id=NEW.revision_id;
 SELECT * INTO previous FROM public.vendor_setup_receipts WHERE setup_id=NEW.setup_id ORDER BY version DESC LIMIT 1;
 expected_state:=CASE NEW.command_kind WHEN 'propose_account' THEN 'pending_review' WHEN 'propose_recipient' THEN 'pending_review'
  WHEN 'activate' THEN 'active' WHEN 'disable' THEN 'disabled' WHEN 'revoke' THEN 'revoked' END;
 keys:=ARRAY['setup_id','expected_version','idempotency_key'] || CASE NEW.command_kind
  WHEN 'propose_account' THEN ARRAY['installation_id','installation_sha256','label','permissions']
  WHEN 'propose_recipient' THEN ARRAY['account','patient_link_id','destination','label','permission_reference','expires_at']
  WHEN 'activate' THEN ARRAY['revision_id','review_sha256','reviewed_account','reviewed_environment','reviewed_sender','reviewed_capabilities','confirm_local_activation'] || CASE r.kind WHEN 'recipient' THEN ARRAY['reviewed_patient','reviewed_recipient','reviewed_permission'] ELSE ARRAY[]::text[] END
  WHEN 'disable' THEN ARRAY['revision_id','review_sha256','confirm_disable']
  WHEN 'revoke' THEN ARRAY['revision_id','review_sha256','confirm_revoke'] END;
 IF r.id IS NULL OR previous.state='revoked' OR NEW.version<>coalesce(previous.version,0)+1
  OR (NEW.command_kind IN ('propose_account','propose_recipient','activate') AND NEW.version>98)
  OR (NEW.command_kind='disable' AND NEW.version>99)
  OR NEW.state IS DISTINCT FROM expected_state OR NOT public.vendor_settings_keys(NEW.request,keys)
  OR NEW.request->>'setup_id' IS DISTINCT FROM NEW.setup_id::text
  OR NEW.request->'expected_version' IS DISTINCT FROM to_jsonb(coalesce(previous.version,0))
  OR NEW.request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
  OR NEW.request_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-setup-request.v1',jsonb_build_object(
   'scope',jsonb_build_object('box_id',NEW.box_id,'owner_id',NEW.owner_id),'command_kind',NEW.command_kind,'request',NEW.request))
 THEN RAISE EXCEPTION 'vendor settings command binding mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.command_kind IN ('propose_account','propose_recipient') THEN
  IF NEW.command_kind<>'propose_' || r.kind
   OR r.revision<>coalesce((SELECT revision FROM public.vendor_setup_revisions WHERE id=previous.revision_id),0)+1
   OR NEW.request->>'label' IS DISTINCT FROM r.review->>'label'
  THEN RAISE EXCEPTION 'vendor settings proposal revision mismatch' USING ERRCODE='23514'; END IF;
  IF r.kind='account' THEN
   IF NEW.request->>'installation_id' IS DISTINCT FROM r.installation_id::text
    OR NEW.request->>'installation_sha256' IS DISTINCT FROM r.installation_sha256
    OR NEW.request->'permissions' IS DISTINCT FROM r.review->'permissions'
   THEN RAISE EXCEPTION 'vendor settings account proposal mismatch' USING ERRCODE='23514'; END IF;
  ELSE
   IF NEW.request->'account' IS DISTINCT FROM r.review->'account'
    OR NEW.request->>'patient_link_id' IS DISTINCT FROM r.patient_link_id::text
    OR NEW.request->'destination' IS DISTINCT FROM r.review->'destination' OR NEW.request->'permission_reference' IS DISTINCT FROM r.review->'permission_reference' OR NEW.request->'expires_at' IS DISTINCT FROM r.review->'expires_at'
   THEN RAISE EXCEPTION 'vendor settings recipient proposal mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 ELSE
  IF previous.id IS NULL OR previous.revision_id<>r.id
   OR NEW.request->>'revision_id' IS DISTINCT FROM r.id::text OR NEW.request->>'review_sha256' IS DISTINCT FROM r.review_sha256
   OR (NEW.command_kind='activate' AND (previous.state <> 'pending_review'
     OR NEW.request->'reviewed_account' IS DISTINCT FROM 'true'::jsonb
     OR NEW.request->'reviewed_environment' IS DISTINCT FROM 'true'::jsonb OR NEW.request->'reviewed_sender' IS DISTINCT FROM 'true'::jsonb OR NEW.request->'reviewed_capabilities' IS DISTINCT FROM 'true'::jsonb
     OR NEW.request->'confirm_local_activation' IS DISTINCT FROM 'true'::jsonb
     OR (r.kind='recipient' AND (NEW.request->'reviewed_patient' IS DISTINCT FROM 'true'::jsonb OR NEW.request->'reviewed_recipient' IS DISTINCT FROM 'true'::jsonb OR NEW.request->'reviewed_permission' IS DISTINCT FROM 'true'::jsonb OR (r.review->>'expires_at')::timestamptz<=statement_timestamp()))))
   OR (NEW.command_kind='disable' AND (previous.state='disabled' OR NEW.request->'confirm_disable' IS DISTINCT FROM 'true'::jsonb))
   OR (NEW.command_kind='revoke' AND NEW.request->'confirm_revoke' IS DISTINCT FROM 'true'::jsonb)
  THEN RAISE EXCEPTION 'vendor settings command transition mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 result:=jsonb_build_object('contract_version',1,'outcome','recorded','scope',jsonb_build_object('box_id',NEW.box_id,'owner_id',NEW.owner_id),
  'command_kind',NEW.command_kind,'idempotency_key',NEW.idempotency_key,'request_sha256',NEW.request_sha256,
  'receipt_id',NEW.id,'recorded_at',NEW.response->'recorded_at','effect',jsonb_build_object('setup_id',NEW.setup_id,'kind',r.kind,
   'version',NEW.version,'revision_id',r.id,'review_sha256',r.review_sha256,'state',NEW.state));
 IF NEW.response-'receipt_sha256' IS DISTINCT FROM result
  OR (NEW.response->>'recorded_at')::timestamptz IS DISTINCT FROM NEW.recorded_at
  OR NEW.receipt_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-setup-receipt.v1',result)
  OR NEW.response->>'receipt_sha256' IS DISTINCT FROM NEW.receipt_sha256
 THEN RAISE EXCEPTION 'vendor settings public receipt mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER vendor_settings_receipt_admission BEFORE INSERT ON public.vendor_setup_receipts FOR EACH ROW EXECUTE FUNCTION public.vendor_settings_receipt_guard();

CREATE FUNCTION public.vendor_settings_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public.vendor_setup_revisions; h public.vendor_setup_receipts; c public.vendor_connection_versions;
 m public.vendor_correspondence_versions; a public.vendor_setup_receipts; expected boolean; target_connection uuid;
BEGIN
 IF TG_TABLE_NAME='vendor_connection_versions' THEN target_connection:=NEW.id;
 ELSIF TG_TABLE_NAME IN ('vendor_correspondence_versions','vendor_setup_revisions') THEN target_connection:=NEW.connection_version_id;
 ELSE SELECT connection_version_id INTO target_connection FROM public.vendor_setup_revisions WHERE id=NEW.revision_id; END IF;
 IF TG_TABLE_NAME='vendor_correspondence_versions' THEN
  IF EXISTS(SELECT 1 FROM public.vendor_setup_revisions WHERE kind='account' AND connection_version_id=target_connection)
   AND NOT EXISTS(SELECT 1 FROM public.vendor_setup_revisions WHERE kind='recipient' AND correspondence_version_id=NEW.id)
  THEN RAISE EXCEPTION 'managed recipient binding requires setup review' USING ERRCODE='23514'; END IF;
 END IF;
 FOR r IN SELECT * FROM public.vendor_setup_revisions WHERE connection_version_id=target_connection AND box_id=NEW.box_id AND owner_id=NEW.owner_id LOOP
  SELECT * INTO h FROM public.vendor_setup_receipts WHERE setup_id=r.setup_id ORDER BY version DESC LIMIT 1;
  IF h.id IS NULL THEN RAISE EXCEPTION 'vendor settings revision requires receipt' USING ERRCODE='23514'; END IF;
  IF r.kind='account' THEN
   SELECT * INTO c FROM public.vendor_connection_versions WHERE id=r.connection_version_id;
   expected:=(h.revision_id=r.id AND h.state='active');
   IF c.id IS NULL OR (c.write_enabled IS DISTINCT FROM (expected AND (r.review->'permissions'->>'prepare_and_submit')::boolean))
    OR (c.read_enabled IS DISTINCT FROM (expected AND (r.review->'permissions'->>'read_status')::boolean))
    OR c.is_current IS DISTINCT FROM expected OR (expected AND c.revoked_at IS NOT NULL)
    OR (h.revision_id<>r.id AND c.is_current)
    OR (h.state='revoked' AND c.revoked_at IS NULL)
   THEN RAISE EXCEPTION 'vendor managed account state mismatch' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT * INTO m FROM public.vendor_correspondence_versions WHERE id=r.correspondence_version_id;
   SELECT * INTO a FROM public.vendor_setup_receipts WHERE setup_id=(r.review->'account'->>'setup_id')::uuid ORDER BY version DESC LIMIT 1;
   expected:=(h.revision_id=r.id AND h.state='active' AND a.state='active' AND a.revision_id=r.account_revision_id
     AND to_jsonb(a.version)=r.review->'account'->'expected_version');
   IF m.id IS NULL OR m.is_current IS DISTINCT FROM expected OR (expected AND m.revoked_at IS NOT NULL)
    OR (h.state='revoked' AND m.revoked_at IS NULL)
   THEN RAISE EXCEPTION 'vendor managed recipient state mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER vendor_settings_revision_complete AFTER INSERT ON public.vendor_setup_revisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vendor_settings_binding_guard();
CREATE CONSTRAINT TRIGGER vendor_settings_receipt_complete AFTER INSERT ON public.vendor_setup_receipts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vendor_settings_binding_guard();
CREATE CONSTRAINT TRIGGER vendor_settings_account_current AFTER INSERT OR UPDATE ON public.vendor_connection_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vendor_settings_binding_guard();
CREATE CONSTRAINT TRIGGER vendor_settings_recipient_current AFTER INSERT OR UPDATE ON public.vendor_correspondence_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vendor_settings_binding_guard();

CREATE TRIGGER vendor_settings_entity_immutable BEFORE UPDATE OR DELETE ON public.vendor_setups FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER vendor_settings_revision_immutable BEFORE UPDATE OR DELETE ON public.vendor_setup_revisions FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER vendor_settings_receipt_immutable BEFORE UPDATE OR DELETE ON public.vendor_setup_receipts FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();

"""


def upgrade():
    op.execute(TABLE_DDL)
    op.execute(GUARDS)


def downgrade():
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.vendor_setups) THEN RAISE EXCEPTION 'vendor settings history prevents downgrade' USING ERRCODE='23514'; END IF; END $$;"
    )
    op.execute(
        "DROP TRIGGER vendor_settings_account_current ON public.vendor_connection_versions; DROP TRIGGER vendor_settings_recipient_current ON public.vendor_correspondence_versions; DROP TABLE public.vendor_setup_receipts; DROP TABLE public.vendor_setup_revisions; DROP TABLE public.vendor_setups; DROP FUNCTION public.vendor_settings_binding_guard(); DROP FUNCTION public.vendor_settings_receipt_guard(); DROP FUNCTION public.vendor_settings_revision_guard(); DROP FUNCTION public.vendor_settings_keys(jsonb,text[]);"
    )
