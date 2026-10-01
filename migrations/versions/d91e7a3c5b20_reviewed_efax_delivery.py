"""Admit reviewed eFax outbound PDF work without changing retained evidence.

Only the provider/action allowlists expand. Existing account, exact approval,
recipient, private PDF and evidence guards remain; inbound/event routes stay closed.
"""

from alembic import op

revision = "d91e7a3c5b20"
down_revision = "c83a2f19b650"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(CHECK_DDL)
    op.execute(GUARD_DDL)


def downgrade():
    raise RuntimeError("Retained eFax work must remain forward-compatible")


CHECK_DDL = r"""
DO $$ DECLARE names text[]; BEGIN
 SELECT array_agg(conname) INTO names FROM pg_constraint
 WHERE conrelid='public.vendor_connection_versions'::regclass AND contype='c'
 AND pg_get_constraintdef(oid) LIKE '%vendor%' AND pg_get_constraintdef(oid) LIKE '%environment%';
 IF cardinality(names) IS DISTINCT FROM 1 THEN
  RAISE EXCEPTION 'expected one delivery vendor/environment constraint';
 END IF;
 EXECUTE format('ALTER TABLE public.vendor_connection_versions DROP CONSTRAINT %I',names[1]);
 SELECT array_agg(conname) INTO names FROM pg_constraint
 WHERE conrelid='public.vendor_work_revisions'::regclass AND contype='c'
 AND pg_get_constraintdef(oid) LIKE '%action%' AND pg_get_constraintdef(oid) NOT LIKE '%artifact_id%';
 IF cardinality(names) IS DISTINCT FROM 1 THEN
  RAISE EXCEPTION 'expected one delivery action constraint';
 END IF;
 EXECUTE format('ALTER TABLE public.vendor_work_revisions DROP CONSTRAINT %I',names[1]);
 SELECT array_agg(conname) INTO names FROM pg_constraint
 WHERE conrelid='public.vendor_work_revisions'::regclass AND contype='c'
 AND pg_get_constraintdef(oid) LIKE '%action%' AND pg_get_constraintdef(oid) LIKE '%artifact_id%';
 IF cardinality(names) IS DISTINCT FROM 1 THEN
  RAISE EXCEPTION 'expected one delivery document/recipient constraint';
 END IF;
 EXECUTE format('ALTER TABLE public.vendor_work_revisions DROP CONSTRAINT %I',names[1]);
END $$;
ALTER TABLE public.vendor_connection_versions ADD CONSTRAINT ck_vendor_connection_provider_environment
 CHECK (vendor IN ('spruce','srfax','documo','efax') AND (environment = 'production' OR (vendor = 'documo' AND environment = 'sandbox')));
ALTER TABLE public.vendor_work_revisions ADD CONSTRAINT ck_vendor_work_action
 CHECK (action IN ('spruce_secure_message','spruce_fax','spruce_media_upload','srfax_fax','documo_fax','efax_fax'));
ALTER TABLE public.vendor_work_revisions ADD CONSTRAINT ck_vendor_work_document_recipient
 CHECK ((action = 'spruce_media_upload' AND artifact_id IS NOT NULL AND correspondence_version_id IS NULL AND uploaded_media_operation_id IS NULL)
 OR (action IN ('srfax_fax','documo_fax','efax_fax') AND artifact_id IS NOT NULL AND correspondence_version_id IS NOT NULL AND uploaded_media_operation_id IS NULL)
 OR (action = 'spruce_secure_message' AND artifact_id IS NULL AND correspondence_version_id IS NOT NULL)
 OR (action = 'spruce_fax' AND artifact_id IS NULL AND correspondence_version_id IS NOT NULL AND uploaded_media_operation_id IS NOT NULL));
"""

GUARD_DDL = r"""
CREATE OR REPLACE FUNCTION public.vendor_settings_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
  OR c.vendor NOT IN ('spruce','srfax','documo','efax')
  OR jsonb_typeof(NEW.review->'installed'->'capabilities') IS DISTINCT FROM 'array'
  OR jsonb_array_length(NEW.review->'installed'->'capabilities') NOT BETWEEN 1 AND 3
  OR NOT ((NEW.review->'installed'->'capabilities') <@ CASE c.vendor WHEN 'spruce' THEN '["spruce_secure_message","spruce_fax","spruce_media_upload"]'::jsonb WHEN 'srfax' THEN '["srfax_fax"]'::jsonb WHEN 'documo' THEN '["documo_fax"]'::jsonb WHEN 'efax' THEN '["efax_fax"]'::jsonb ELSE '[]'::jsonb END)
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
"""
