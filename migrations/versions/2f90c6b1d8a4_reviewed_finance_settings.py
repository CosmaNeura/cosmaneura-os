"""Reviewed owner Stripe account and customer settings with exact local recovery."""

from alembic import op

revision = "2f90c6b1d8a4"
down_revision = "1d86e2f49a70"
branch_labels = None
depends_on = None

TABLE_DDL = r"""

CREATE TABLE finance_setups (
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
	FOREIGN KEY(account_setup_id, box_id, owner_id) REFERENCES finance_setups (id, box_id, owner_id), 
	FOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id), 
	CONSTRAINT uq_finance_setup_scope UNIQUE (id, box_id, owner_id), 
	CONSTRAINT uq_finance_setup_installation UNIQUE (box_id, owner_id, installation_id), 
	CONSTRAINT uq_finance_setup_patient UNIQUE (box_id, owner_id, account_setup_id, patient_link_id), 
	CHECK ((kind='account' AND installation_id IS NOT NULL AND account_setup_id IS NULL AND patient_link_id IS NULL) OR (kind='customer' AND installation_id IS NULL AND account_setup_id IS NOT NULL AND patient_link_id IS NOT NULL))
)

;


CREATE TABLE finance_setup_revisions (
	id UUID NOT NULL, 
	setup_id UUID NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	revision INTEGER NOT NULL, 
	installation_id UUID NOT NULL, 
	installation_sha256 VARCHAR(64) NOT NULL, 
	connection_version_id UUID NOT NULL, 
	customer_version_id UUID, 
	account_revision_id UUID, 
	patient_link_id UUID, 
	review JSONB NOT NULL, 
	review_sha256 VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(setup_id, box_id, owner_id) REFERENCES finance_setups (id, box_id, owner_id), 
	FOREIGN KEY(account_revision_id, box_id, owner_id) REFERENCES finance_setup_revisions (id, box_id, owner_id), 
	FOREIGN KEY(connection_version_id, box_id, owner_id) REFERENCES finance_connection_versions (id, box_id, owner_id), 
	FOREIGN KEY(customer_version_id, connection_version_id, patient_link_id, box_id, owner_id) REFERENCES finance_customer_versions (id, connection_version_id, patient_link_id, box_id, owner_id), 
	CONSTRAINT uq_finance_setup_revision_owner UNIQUE (id, box_id, owner_id), 
	CONSTRAINT uq_finance_setup_revision_scope UNIQUE (id, setup_id, box_id, owner_id), 
	CONSTRAINT uq_finance_setup_revision UNIQUE (setup_id, revision), 
	CONSTRAINT uq_finance_setup_customer_binding UNIQUE (customer_version_id), 
	CHECK (revision BETWEEN 1 AND 20), 
	CHECK ((kind='account' AND customer_version_id IS NULL AND account_revision_id IS NULL AND patient_link_id IS NULL) OR (kind='customer' AND customer_version_id IS NOT NULL AND account_revision_id IS NOT NULL AND patient_link_id IS NOT NULL)), 
	CHECK (installation_sha256 ~ '^[a-f0-9]{64}$' AND review_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(review) = 'object' AND octet_length(review::text) <= 8192)
)

;


CREATE TABLE finance_setup_receipts (
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
	FOREIGN KEY(revision_id, setup_id, box_id, owner_id) REFERENCES finance_setup_revisions (id, setup_id, box_id, owner_id), 
	CONSTRAINT uq_finance_setup_version UNIQUE (setup_id, version), 
	CONSTRAINT uq_finance_setup_command UNIQUE (box_id, owner_id, idempotency_key), 
	CHECK (version BETWEEN 1 AND 100 AND command_kind IN ('propose_account','propose_customer','activate','disable','revoke') AND state IN ('pending_review','active','disabled','revoked')), 
	CHECK (idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'), 
	CHECK (request_sha256 ~ '^[a-f0-9]{64}$' AND receipt_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(request) = 'object' AND octet_length(request::text) <= 8192), 
	CHECK (jsonb_typeof(response) = 'object' AND octet_length(response::text) <= 4096)
)

;
"""

GUARDS = r"""
CREATE FUNCTION public.finance_settings_keys(value jsonb, names text[]) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_typeof(value)='object' AND value ?& names AND value-names='{}'::jsonb,false)
$$;
CREATE FUNCTION public.finance_settings_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE e public.finance_setups; c public.finance_connection_versions; m public.finance_customer_versions;
 account_revision public.finance_setup_revisions; account_head public.finance_setup_receipts; patient public.patient_links;
 names text[];
BEGIN
 SELECT * INTO e FROM public.finance_setups WHERE id=NEW.setup_id;
 SELECT * INTO c FROM public.finance_connection_versions WHERE id=NEW.connection_version_id;
 names:=ARRAY['kind','setup_id','revision_id','revision','installed','label','connection_version_id'] ||
 CASE NEW.kind WHEN 'account' THEN ARRAY['permissions'] ELSE ARRAY['account','account_label','customer_version_id','patient','customer_id'] END;
 IF e.id IS NULL OR e.kind IS DISTINCT FROM NEW.kind OR c.id IS NULL
  OR NOT public.finance_settings_keys(NEW.review,names)
  OR NOT public.finance_settings_keys(NEW.review->'installed',ARRAY['installation_id','installation_sha256','label','environment','account_reference'])
  OR NEW.review_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-finance-setup-review.v1',NEW.review)
  OR NEW.review->>'kind' IS DISTINCT FROM NEW.kind OR NEW.review->>'setup_id' IS DISTINCT FROM NEW.setup_id::text
  OR NEW.review->>'revision_id' IS DISTINCT FROM NEW.id::text OR NEW.review->'revision' IS DISTINCT FROM to_jsonb(NEW.revision)
  OR NEW.review->>'connection_version_id' IS DISTINCT FROM NEW.connection_version_id::text
  OR NEW.review->'installed'->>'installation_id' IS DISTINCT FROM NEW.installation_id::text
  OR NEW.review->'installed'->>'installation_sha256' IS DISTINCT FROM NEW.installation_sha256
  OR NEW.review->'installed'->>'environment' IS DISTINCT FROM c.environment
  OR NEW.review->'installed'->>'account_reference' IS DISTINCT FROM c.private_selection->>'remote_account_id'
  OR c.environment<>'sandbox' OR c.private_selection->>'vendor'<>'stripe'
 THEN RAISE EXCEPTION 'finance settings review binding mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.kind='account' THEN
  IF NEW.installation_id IS DISTINCT FROM e.installation_id
   OR NEW.review->>'label' IS DISTINCT FROM c.public_view->>'label'
   OR NOT public.finance_settings_keys(NEW.review->'permissions',ARRAY['read_status','create_unconfirmed_intents'])
   OR jsonb_typeof(NEW.review->'permissions'->'read_status') IS DISTINCT FROM 'boolean'
   OR jsonb_typeof(NEW.review->'permissions'->'create_unconfirmed_intents') IS DISTINCT FROM 'boolean'
   OR NOT ((NEW.review->'permissions'->>'read_status')::boolean OR (NEW.review->'permissions'->>'create_unconfirmed_intents')::boolean)
   OR EXISTS(SELECT 1 FROM public.finance_setup_revisions WHERE kind='account' AND connection_version_id=NEW.connection_version_id)
  THEN RAISE EXCEPTION 'finance account review mismatch' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO m FROM public.finance_customer_versions WHERE id=NEW.customer_version_id;
  SELECT * INTO patient FROM public.patient_links WHERE id=NEW.patient_link_id;
  SELECT * INTO account_revision FROM public.finance_setup_revisions WHERE id=NEW.account_revision_id;
  SELECT * INTO account_head FROM public.finance_setup_receipts WHERE setup_id=e.account_setup_id ORDER BY version DESC LIMIT 1;
  IF m.id IS NULL OR account_revision.kind IS DISTINCT FROM 'account' OR account_head.state IS DISTINCT FROM 'active'
   OR account_head.revision_id IS DISTINCT FROM account_revision.id
   OR (account_revision.setup_id,account_revision.connection_version_id,account_revision.installation_id,account_revision.installation_sha256)
      IS DISTINCT FROM (e.account_setup_id,NEW.connection_version_id,NEW.installation_id,NEW.installation_sha256)
   OR NEW.review->'installed' IS DISTINCT FROM account_revision.review->'installed'
   OR NEW.review->'account' IS DISTINCT FROM jsonb_build_object('setup_id',e.account_setup_id,'expected_version',account_head.version,'revision_id',account_revision.id,'review_sha256',account_revision.review_sha256)
   OR NEW.review->>'account_label' IS DISTINCT FROM account_revision.review->>'label'
   OR NEW.review->>'customer_version_id' IS DISTINCT FROM m.id::text
   OR NEW.review->>'customer_id' IS DISTINCT FROM m.customer_id OR NEW.review->>'label' IS DISTINCT FROM m.public_view->>'label'
   OR (e.patient_link_id,NEW.patient_link_id) IS DISTINCT FROM (m.patient_link_id,m.patient_link_id)
   OR patient.state IS DISTINCT FROM 'confirmed' OR patient.revoked_at IS NOT NULL
   OR NEW.review->'patient' IS DISTINCT FROM jsonb_build_object('patient_link_id',patient.id,'label',patient.label)
  THEN RAISE EXCEPTION 'finance customer review mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER finance_settings_revision_admission BEFORE INSERT ON public.finance_setup_revisions FOR EACH ROW EXECUTE FUNCTION public.finance_settings_revision_guard();

CREATE FUNCTION public.finance_settings_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous public.finance_setup_receipts; r public.finance_setup_revisions; e public.finance_setups;
 expected_state text; keys text[]; result jsonb;
BEGIN
 PERFORM 1 FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id
  AND principal_type='human' AND state='active' AND is_owner AND tombstoned_at IS NULL)
 THEN RAISE EXCEPTION 'finance settings owner required' USING ERRCODE='23514'; END IF;
 SELECT * INTO e FROM public.finance_setups WHERE id=NEW.setup_id FOR UPDATE;
 SELECT * INTO r FROM public.finance_setup_revisions WHERE id=NEW.revision_id;
 SELECT * INTO previous FROM public.finance_setup_receipts WHERE setup_id=NEW.setup_id ORDER BY version DESC LIMIT 1;
 expected_state:=CASE NEW.command_kind WHEN 'propose_account' THEN 'pending_review' WHEN 'propose_customer' THEN 'pending_review'
  WHEN 'activate' THEN 'active' WHEN 'disable' THEN 'disabled' WHEN 'revoke' THEN 'revoked' END;
 keys:=ARRAY['setup_id','expected_version','idempotency_key'] || CASE NEW.command_kind
  WHEN 'propose_account' THEN ARRAY['installation_id','installation_sha256','label','permissions']
  WHEN 'propose_customer' THEN ARRAY['account','patient_link_id','customer_id','label']
  WHEN 'activate' THEN ARRAY['revision_id','review_sha256','reviewed_account','reviewed_environment','confirm_local_activation'] || CASE r.kind WHEN 'customer' THEN ARRAY['reviewed_patient_customer'] ELSE ARRAY[]::text[] END
  WHEN 'disable' THEN ARRAY['revision_id','review_sha256','confirm_disable']
  WHEN 'revoke' THEN ARRAY['revision_id','review_sha256','confirm_revoke'] END;
 IF r.id IS NULL OR previous.state='revoked' OR NEW.version<>coalesce(previous.version,0)+1
  OR (NEW.command_kind IN ('propose_account','propose_customer','activate') AND NEW.version>98)
  OR (NEW.command_kind='disable' AND NEW.version>99)
  OR NEW.state IS DISTINCT FROM expected_state OR NOT public.finance_settings_keys(NEW.request,keys)
  OR NEW.request->>'setup_id' IS DISTINCT FROM NEW.setup_id::text
  OR NEW.request->'expected_version' IS DISTINCT FROM to_jsonb(coalesce(previous.version,0))
  OR NEW.request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
  OR NEW.request_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-finance-setup-request.v1',jsonb_build_object(
   'scope',jsonb_build_object('box_id',NEW.box_id,'owner_id',NEW.owner_id),'command_kind',NEW.command_kind,'request',NEW.request))
 THEN RAISE EXCEPTION 'finance settings command binding mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.command_kind IN ('propose_account','propose_customer') THEN
  IF NEW.command_kind<>'propose_' || r.kind
   OR r.revision<>coalesce((SELECT revision FROM public.finance_setup_revisions WHERE id=previous.revision_id),0)+1
   OR NEW.request->>'label' IS DISTINCT FROM r.review->>'label'
  THEN RAISE EXCEPTION 'finance settings proposal revision mismatch' USING ERRCODE='23514'; END IF;
  IF r.kind='account' THEN
   IF NEW.request->>'installation_id' IS DISTINCT FROM r.installation_id::text
    OR NEW.request->>'installation_sha256' IS DISTINCT FROM r.installation_sha256
    OR NEW.request->'permissions' IS DISTINCT FROM r.review->'permissions'
   THEN RAISE EXCEPTION 'finance settings account proposal mismatch' USING ERRCODE='23514'; END IF;
  ELSE
   IF NEW.request->'account' IS DISTINCT FROM r.review->'account'
    OR NEW.request->>'patient_link_id' IS DISTINCT FROM r.patient_link_id::text
    OR NEW.request->>'customer_id' IS DISTINCT FROM r.review->>'customer_id'
   THEN RAISE EXCEPTION 'finance settings customer proposal mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 ELSE
  IF previous.id IS NULL OR previous.revision_id<>r.id
   OR NEW.request->>'revision_id' IS DISTINCT FROM r.id::text OR NEW.request->>'review_sha256' IS DISTINCT FROM r.review_sha256
   OR (NEW.command_kind='activate' AND (previous.state NOT IN ('pending_review','disabled')
     OR NEW.request->'reviewed_account' IS DISTINCT FROM 'true'::jsonb
     OR NEW.request->'reviewed_environment' IS DISTINCT FROM 'true'::jsonb
     OR NEW.request->'confirm_local_activation' IS DISTINCT FROM 'true'::jsonb
     OR (r.kind='customer' AND NEW.request->'reviewed_patient_customer' IS DISTINCT FROM 'true'::jsonb)))
   OR (NEW.command_kind='disable' AND (previous.state='disabled' OR NEW.request->'confirm_disable' IS DISTINCT FROM 'true'::jsonb))
   OR (NEW.command_kind='revoke' AND NEW.request->'confirm_revoke' IS DISTINCT FROM 'true'::jsonb)
  THEN RAISE EXCEPTION 'finance settings command transition mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 result:=jsonb_build_object('contract_version',1,'outcome','recorded','scope',jsonb_build_object('box_id',NEW.box_id,'owner_id',NEW.owner_id),
  'command_kind',NEW.command_kind,'idempotency_key',NEW.idempotency_key,'request_sha256',NEW.request_sha256,
  'receipt_id',NEW.id,'recorded_at',NEW.response->'recorded_at','effect',jsonb_build_object('setup_id',NEW.setup_id,'kind',r.kind,
   'version',NEW.version,'revision_id',r.id,'review_sha256',r.review_sha256,'state',NEW.state));
 IF NEW.response-'receipt_sha256' IS DISTINCT FROM result
  OR (NEW.response->>'recorded_at')::timestamptz IS DISTINCT FROM NEW.recorded_at
  OR NEW.receipt_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-finance-setup-receipt.v1',result)
  OR NEW.response->>'receipt_sha256' IS DISTINCT FROM NEW.receipt_sha256
 THEN RAISE EXCEPTION 'finance settings public receipt mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER finance_settings_receipt_admission BEFORE INSERT ON public.finance_setup_receipts FOR EACH ROW EXECUTE FUNCTION public.finance_settings_receipt_guard();

CREATE FUNCTION public.finance_settings_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public.finance_setup_revisions; h public.finance_setup_receipts; c public.finance_connection_versions;
 m public.finance_customer_versions; a public.finance_setup_receipts; expected boolean; target_connection uuid;
BEGIN
 IF TG_TABLE_NAME='finance_connection_versions' THEN target_connection:=NEW.id;
 ELSIF TG_TABLE_NAME IN ('finance_customer_versions','finance_setup_revisions') THEN target_connection:=NEW.connection_version_id;
 ELSE SELECT connection_version_id INTO target_connection FROM public.finance_setup_revisions WHERE id=NEW.revision_id; END IF;
 IF TG_TABLE_NAME='finance_customer_versions' THEN
  IF EXISTS(SELECT 1 FROM public.finance_setup_revisions WHERE kind='account' AND connection_version_id=target_connection)
   AND NOT EXISTS(SELECT 1 FROM public.finance_setup_revisions WHERE kind='customer' AND customer_version_id=NEW.id)
  THEN RAISE EXCEPTION 'managed customer binding requires setup review' USING ERRCODE='23514'; END IF;
 END IF;
 FOR r IN SELECT * FROM public.finance_setup_revisions WHERE connection_version_id=target_connection AND box_id=NEW.box_id AND owner_id=NEW.owner_id LOOP
  SELECT * INTO h FROM public.finance_setup_receipts WHERE setup_id=r.setup_id ORDER BY version DESC LIMIT 1;
  IF h.id IS NULL THEN RAISE EXCEPTION 'finance settings revision requires receipt' USING ERRCODE='23514'; END IF;
  IF r.kind='account' THEN
   SELECT * INTO c FROM public.finance_connection_versions WHERE id=r.connection_version_id;
   expected:=(h.revision_id=r.id AND h.state='active');
   IF c.id IS NULL OR (c.write_enabled IS DISTINCT FROM (expected AND (r.review->'permissions'->>'create_unconfirmed_intents')::boolean))
    OR (c.read_enabled IS DISTINCT FROM (expected AND (r.review->'permissions'->>'read_status')::boolean))
    OR (expected AND (NOT c.is_current OR c.revoked_at IS NOT NULL))
    OR (h.revision_id<>r.id AND c.is_current)
    OR (h.state='revoked' AND c.revoked_at IS NULL)
   THEN RAISE EXCEPTION 'finance managed account state mismatch' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT * INTO m FROM public.finance_customer_versions WHERE id=r.customer_version_id;
   SELECT * INTO a FROM public.finance_setup_receipts WHERE setup_id=(r.review->'account'->>'setup_id')::uuid ORDER BY version DESC LIMIT 1;
   expected:=(h.revision_id=r.id AND h.state='active' AND a.state='active' AND a.revision_id=r.account_revision_id
     AND to_jsonb(a.version)=r.review->'account'->'expected_version');
   IF m.id IS NULL OR m.is_current IS DISTINCT FROM expected OR (expected AND m.revoked_at IS NOT NULL)
    OR (h.state='revoked' AND m.revoked_at IS NULL)
   THEN RAISE EXCEPTION 'finance managed customer state mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER finance_settings_revision_complete AFTER INSERT ON public.finance_setup_revisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.finance_settings_binding_guard();
CREATE CONSTRAINT TRIGGER finance_settings_receipt_complete AFTER INSERT ON public.finance_setup_receipts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.finance_settings_binding_guard();
CREATE CONSTRAINT TRIGGER finance_settings_account_current AFTER INSERT OR UPDATE ON public.finance_connection_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.finance_settings_binding_guard();
CREATE CONSTRAINT TRIGGER finance_settings_customer_current AFTER INSERT OR UPDATE ON public.finance_customer_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.finance_settings_binding_guard();

CREATE TRIGGER finance_settings_entity_immutable BEFORE UPDATE OR DELETE ON public.finance_setups FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER finance_settings_revision_immutable BEFORE UPDATE OR DELETE ON public.finance_setup_revisions FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER finance_settings_receipt_immutable BEFORE UPDATE OR DELETE ON public.finance_setup_receipts FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
"""


def upgrade():
    op.execute(TABLE_DDL)
    op.execute(GUARDS)


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.finance_setups) THEN RAISE EXCEPTION 'finance settings history prevents downgrade' USING ERRCODE='23514'; END IF; END $$;")
    op.execute("DROP TRIGGER finance_settings_account_current ON public.finance_connection_versions; DROP TRIGGER finance_settings_customer_current ON public.finance_customer_versions; DROP TABLE public.finance_setup_receipts; DROP TABLE public.finance_setup_revisions; DROP TABLE public.finance_setups; DROP FUNCTION public.finance_settings_binding_guard(); DROP FUNCTION public.finance_settings_receipt_guard(); DROP FUNCTION public.finance_settings_revision_guard(); DROP FUNCTION public.finance_settings_keys(jsonb,text[]);")
