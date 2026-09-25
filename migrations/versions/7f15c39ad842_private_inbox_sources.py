"""Private inbound source observations and exact local human review."""

from alembic import op

revision = "7f15c39ad842"
down_revision = "6e04b2f98c71"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLE_DDL)
    op.execute(GUARDS)


def downgrade():
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.inbox_items) THEN RAISE EXCEPTION 'inbox history prevents downgrade' USING ERRCODE='23514'; END IF; END $$;"
    )
    op.execute(
        "DROP FUNCTION public.inbox_grant_valid(public.inbox_items); DROP TABLE public.inbox_events; ALTER TABLE public.inbox_items DROP CONSTRAINT fk_inbox_current_source; DROP TABLE public.inbox_sources; DROP TABLE public.inbox_items; DROP FUNCTION public.inbox_item_guard(); DROP FUNCTION public.inbox_source_guard(); DROP FUNCTION public.inbox_event_guard(); DROP FUNCTION public.inbox_read_state(uuid); DROP FUNCTION public.inbox_item_identity_guard(); DROP FUNCTION public.inbox_source_reference_guard();"
    )


TABLE_DDL = r"""

CREATE TABLE inbox_items (
	id UUID NOT NULL, 
	grant_id UUID NOT NULL, 
	grant_sha256 VARCHAR(64) NOT NULL, 
	grant_payload JSONB NOT NULL, 
	patient_link_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	current_source_id UUID, 
	source_conflict BOOLEAN NOT NULL, 
	read_issue VARCHAR(48), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id, box_id) REFERENCES principals (id, box_id), 
	FOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id), 
	CONSTRAINT uq_inbox_item_scope UNIQUE (id, box_id, owner_id), 
	CONSTRAINT uq_inbox_grant_item UNIQUE (box_id, owner_id, grant_id), 
	CHECK (version BETWEEN 1 AND 100), 
	CHECK (grant_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(grant_payload) = 'object' AND octet_length(grant_payload::text) <= 16384)
)

;

CREATE TABLE inbox_sources (
	id UUID NOT NULL, 
	item_id UUID NOT NULL, 
	sequence INTEGER NOT NULL, 
	source_sha256 VARCHAR(64) NOT NULL, 
	snapshot JSONB NOT NULL, 
	snapshot_sha256 VARCHAR(64) NOT NULL, 
	recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(item_id, box_id, owner_id) REFERENCES inbox_items (id, box_id, owner_id), 
	CONSTRAINT uq_inbox_source_identity UNIQUE (id, item_id), 
	CONSTRAINT uq_inbox_source_sequence UNIQUE (item_id, sequence), 
	CONSTRAINT uq_inbox_source_content UNIQUE (item_id, source_sha256), 
	CHECK (sequence BETWEEN 1 AND 50), 
	CHECK (source_sha256 ~ '^[a-f0-9]{64}$' AND snapshot_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(snapshot) = 'object' AND octet_length(snapshot::text) <= 131072)
)

;

CREATE TABLE inbox_events (
	id UUID NOT NULL, 
	item_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	origin VARCHAR(8) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	idempotency_key VARCHAR(100) NOT NULL, 
	request JSONB NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	source_id UUID, 
	response JSONB NOT NULL, 
	receipt_sha256 VARCHAR(64) NOT NULL, 
	recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(item_id, box_id, owner_id) REFERENCES inbox_items (id, box_id, owner_id), 
	FOREIGN KEY(source_id, item_id) REFERENCES inbox_sources (id, item_id), 
	CONSTRAINT uq_inbox_event_version UNIQUE (item_id, version), 
	CONSTRAINT uq_inbox_event_key UNIQUE (item_id, origin, idempotency_key), 
	CHECK (version BETWEEN 1 AND 100), 
	CHECK ((origin='read' AND kind IN ('ingest','read_failed')) OR (origin='human' AND kind IN ('review','triage','result','verify'))), 
	CHECK (idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'), 
	CHECK (request_sha256 ~ '^[a-f0-9]{64}$' AND receipt_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(request) = 'object' AND octet_length(request::text) <= 16384), 
	CHECK (jsonb_typeof(response) = 'object' AND octet_length(response::text) <= 16384)
)

;
ALTER TABLE inbox_items ADD CONSTRAINT fk_inbox_current_source FOREIGN KEY(current_source_id, id) REFERENCES inbox_sources (id, item_id) DEFERRABLE INITIALLY DEFERRED;
"""

GUARDS = r"""
CREATE FUNCTION public.inbox_grant_valid(r public.inbox_items) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT coalesce(
 r.grant_sha256=public.vendor_public_digest('cosmas-inbox-read-grant.v1',r.grant_payload)
 AND r.grant_payload->>'grant_id'=r.grant_id::text
 AND r.grant_payload->'reviewed_inbox_read'='true'::jsonb
 AND r.grant_payload->>'reviewed_by'=r.owner_id::text
 AND r.grant_payload->'binding'->>'patient_link_id'=r.patient_link_id::text
 AND (r.grant_payload->>'reviewed_at')::timestamptz<=clock_timestamp()
 AND (r.grant_payload->>'expires_at')::timestamptz>clock_timestamp()
 AND EXISTS(SELECT 1 FROM public.principals WHERE id=r.owner_id AND box_id=r.box_id AND is_owner AND state='active' AND principal_type='human' AND tombstoned_at IS NULL)
 AND EXISTS(SELECT 1 FROM public.patient_links WHERE id=r.patient_link_id AND box_id=r.box_id AND state='confirmed' AND revoked_at IS NULL)
 AND EXISTS(SELECT 1 FROM public.vendor_connection_versions n JOIN public.vendor_correspondence_versions c ON c.connection_version_id=n.id
  WHERE n.id=(r.grant_payload->'binding'->'selection'->>'connection_id')::uuid AND n.box_id=r.box_id AND n.owner_id=r.owner_id AND n.is_current AND n.revoked_at IS NULL
  AND n.private_selection=r.grant_payload->'binding'->'selection' AND n.private_sha256=public.vendor_public_digest('cosmas-vendor-selection.v1',n.private_selection)
  AND c.id=(r.grant_payload->'binding'->>'correspondence_version_id')::uuid AND c.box_id=r.box_id AND c.owner_id=r.owner_id AND c.patient_link_id=r.patient_link_id
  AND c.is_current AND c.revoked_at IS NULL AND c.expires_at>clock_timestamp()
  AND c.private_sha256=r.grant_payload->'binding'->>'correspondence_sha256'
  AND c.public_sha256=r.grant_payload->>'correspondence_public_sha256'
  AND c.private_sha256=public.vendor_public_digest('cosmas-vendor-correspondence.v1',c.private_proof)
  AND c.private_proof->'destination'=jsonb_build_object('channel','secure','contact_id',r.grant_payload->'binding'->>'contact_id')),
 false)
$$;

CREATE FUNCTION public.inbox_read_state(iid uuid) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE e public.inbox_events; sid uuid; conflicted boolean:=false; issue text;
BEGIN
 FOR e IN SELECT * FROM public.inbox_events WHERE item_id=iid AND origin='read' ORDER BY version LOOP
  IF e.response->>'outcome' IN ('new','newer') THEN sid:=e.source_id;conflicted:=false;
  ELSIF e.response->>'outcome'='conflict' THEN conflicted:=true; END IF;
  issue:=CASE WHEN e.kind='read_failed' THEN e.response->>'safe_error' WHEN e.response->>'outcome' IN ('new','newer','same') THEN NULL ELSE issue END;
 END LOOP;
 RETURN jsonb_build_object('source_id',sid,'conflict',conflicted,'read_issue',issue);
END $$;

CREATE FUNCTION public.inbox_item_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE iid uuid; r public.inbox_items; read_state_value jsonb; maximum integer;
BEGIN
 IF TG_TABLE_NAME='inbox_items' THEN iid:=NEW.id;ELSE iid:=NEW.item_id;END IF;
 SELECT * INTO r FROM public.inbox_items WHERE id=iid;
 SELECT max(version) INTO maximum FROM public.inbox_events WHERE item_id=iid;
 read_state_value:=public.inbox_read_state(iid);
 IF maximum IS NULL OR r.version<>maximum OR (SELECT count(*) FROM public.inbox_events WHERE item_id=iid)<>maximum
  OR r.grant_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-inbox-read-grant.v1',r.grant_payload)
  OR r.grant_payload->>'grant_id' IS DISTINCT FROM r.grant_id::text
  OR r.grant_payload->'binding'->>'patient_link_id' IS DISTINCT FROM r.patient_link_id::text
  OR r.grant_payload->'binding'->'selection'->>'box_id' IS DISTINCT FROM r.box_id::text
  OR r.grant_payload->'binding'->'selection'->>'owner_id' IS DISTINCT FROM r.owner_id::text
  OR r.current_source_id::text IS DISTINCT FROM read_state_value->>'source_id'
  OR to_jsonb(r.source_conflict) IS DISTINCT FROM read_state_value->'conflict'
  OR r.read_issue IS DISTINCT FROM read_state_value->>'read_issue'
 THEN RAISE EXCEPTION 'inbox item/evidence chain mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER inbox_item_complete AFTER INSERT OR UPDATE ON public.inbox_items DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.inbox_item_guard();
CREATE CONSTRAINT TRIGGER inbox_event_complete AFTER INSERT ON public.inbox_events DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.inbox_item_guard();

CREATE FUNCTION public.inbox_item_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (to_jsonb(OLD)-ARRAY['version','current_source_id','source_conflict','read_issue']) IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['version','current_source_id','source_conflict','read_issue'])
 THEN RAISE EXCEPTION 'inbox item identity is immutable' USING ERRCODE='23514';END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER inbox_item_identity BEFORE UPDATE ON public.inbox_items FOR EACH ROW EXECUTE FUNCTION public.inbox_item_identity_guard();
CREATE TRIGGER inbox_item_no_delete BEFORE DELETE ON public.inbox_items FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();

CREATE FUNCTION public.inbox_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public.inbox_items;
BEGIN
 SELECT * INTO r FROM public.inbox_items WHERE id=NEW.item_id FOR UPDATE;
 IF r.id IS NULL OR NOT public.inbox_grant_valid(r)
  OR (NEW.box_id,NEW.owner_id) IS DISTINCT FROM (r.box_id,r.owner_id)
  OR NEW.sequence<>(SELECT count(*)+1 FROM public.inbox_sources WHERE item_id=r.id)
  OR NEW.snapshot_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-inbox-stored-snapshot.v1',NEW.snapshot)
  OR NEW.source_sha256 IS DISTINCT FROM NEW.snapshot->>'source_sha256'
  OR NEW.snapshot->'binding' IS DISTINCT FROM r.grant_payload->'binding'
  OR NEW.source_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-spruce-inbox-source.v1',NEW.snapshot-ARRAY['source_sha256','observed_at','item_response_sha256','conversation_response_sha256'])
  OR NOT public.finance_settings_keys(NEW.snapshot,ARRAY['binding','created_at','modified_at','observed_at','text','item_response_sha256','conversation_response_sha256','item_content_sha256','conversation_content_sha256','source_sha256','unsupported','conversation_archived','conversation_read_only','trust'])
  OR EXISTS(SELECT 1 FROM jsonb_each(NEW.snapshot) pair WHERE pair.value='null'::jsonb)
  OR jsonb_typeof(NEW.snapshot->'text') IS DISTINCT FROM 'string'
  OR NOT public.finance_settings_keys(NEW.snapshot->'unsupported',ARRAY['attachments','pages','buttons','event','attachment_types'])
  OR EXISTS(SELECT 1 FROM jsonb_each(NEW.snapshot->'unsupported') pair WHERE pair.key<>'attachment_types' AND jsonb_typeof(pair.value)<>'boolean')
  OR jsonb_typeof(NEW.snapshot->'unsupported'->'attachment_types') IS DISTINCT FROM 'array'
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.snapshot->'unsupported'->'attachment_types') x WHERE jsonb_typeof(x)<>'string' OR x#>>'{}' NOT IN ('audio','carePlan','document','entityProfile','genericUrl','image','paymentRequest','video','visit','unknown'))
  OR NEW.snapshot->'unsupported'->'attachment_types' IS DISTINCT FROM (SELECT coalesce(jsonb_agg(x ORDER BY x),'[]'::jsonb) FROM (SELECT DISTINCT value x FROM jsonb_array_elements(NEW.snapshot->'unsupported'->'attachment_types')) values_)
  OR NEW.snapshot->'unsupported'->'attachments' IS DISTINCT FROM to_jsonb(jsonb_array_length(NEW.snapshot->'unsupported'->'attachment_types')>0)
  OR jsonb_typeof(NEW.snapshot->'conversation_archived') IS DISTINCT FROM 'boolean' OR jsonb_typeof(NEW.snapshot->'conversation_read_only') IS DISTINCT FROM 'boolean'
  OR EXISTS(SELECT 1 FROM jsonb_each_text(NEW.snapshot) pair WHERE pair.key IN ('item_response_sha256','conversation_response_sha256','item_content_sha256','conversation_content_sha256') AND pair.value !~ '^[a-f0-9]{64}$')
  OR NEW.snapshot->>'trust' IS DISTINCT FROM 'untrusted_external_text' OR octet_length(NEW.snapshot->>'text')>16384
  OR EXISTS(SELECT 1 FROM generate_series(1,31) code WHERE code NOT IN (9,10,13) AND strpos(NEW.snapshot->>'text',chr(code))>0)
  OR (NEW.snapshot->>'modified_at')::timestamptz<(NEW.snapshot->>'created_at')::timestamptz
 THEN RAISE EXCEPTION 'inbox source commitment/scope mismatch' USING ERRCODE='23514';END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER inbox_source_admission BEFORE INSERT ON public.inbox_sources FOR EACH ROW EXECUTE FUNCTION public.inbox_source_guard();
CREATE TRIGGER inbox_source_immutable BEFORE UPDATE OR DELETE ON public.inbox_sources FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER inbox_event_immutable BEFORE UPDATE OR DELETE ON public.inbox_events FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();


CREATE FUNCTION public.inbox_source_reference_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.inbox_events WHERE item_id=NEW.item_id AND source_id=NEW.id AND origin='read' AND kind='ingest') THEN RAISE EXCEPTION 'inbox source requires read receipt' USING ERRCODE='23514';END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER inbox_source_complete AFTER INSERT ON public.inbox_sources DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.inbox_source_reference_guard();

CREATE FUNCTION public.inbox_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public.inbox_items; previous integer; read_state_value jsonb; src public.inbox_sources; oldsrc public.inbox_sources; outcome text; expected jsonb; names text[];
 reviewed public.inbox_events; triage public.inbox_events; result public.inbox_events; w public.encounter_workspaces; incomplete boolean; workspace_ok boolean;
BEGIN
 SELECT * INTO r FROM public.inbox_items WHERE id=NEW.item_id FOR UPDATE;
 SELECT coalesce(max(version),0) INTO previous FROM public.inbox_events WHERE item_id=r.id;
 IF r.id IS NULL OR NEW.version<>previous+1 OR NEW.version<>r.version OR (NEW.box_id,NEW.owner_id) IS DISTINCT FROM (r.box_id,r.owner_id)
  OR NEW.request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
  OR NOT EXISTS(SELECT 1 FROM public.principals WHERE id=r.owner_id AND box_id=r.box_id AND is_owner AND principal_type='human' AND state='active' AND tombstoned_at IS NULL)
  OR NOT EXISTS(SELECT 1 FROM public.patient_links WHERE id=r.patient_link_id AND box_id=r.box_id AND state='confirmed' AND revoked_at IS NULL)
 THEN RAISE EXCEPTION 'inbox event sequence/owner mismatch' USING ERRCODE='23514';END IF;
 IF NEW.source_id IS NOT NULL THEN SELECT * INTO src FROM public.inbox_sources WHERE id=NEW.source_id AND item_id=r.id;IF src.id IS NULL THEN RAISE EXCEPTION 'inbox source missing' USING ERRCODE='23514';END IF;END IF;
 IF NEW.origin='read' THEN
  IF NOT public.inbox_grant_valid(r) OR NOT public.finance_settings_keys(NEW.request,ARRAY['grant_sha256','snapshot_sha256','safe_error','idempotency_key','observed_at','item_response_sha256','conversation_response_sha256'])
   OR NEW.request->>'grant_sha256' IS DISTINCT FROM r.grant_sha256
   OR NEW.request_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-inbox-ingest-request.v1',NEW.request)
  THEN RAISE EXCEPTION 'inbox read authority mismatch' USING ERRCODE='23514';END IF;
  read_state_value:=public.inbox_read_state(r.id);
  SELECT * INTO oldsrc FROM public.inbox_sources WHERE id=(read_state_value->>'source_id')::uuid;
  IF NEW.kind='read_failed' THEN
   outcome:='failure';
   IF NEW.source_id IS NOT NULL OR NEW.request->'snapshot_sha256'<>'null'::jsonb OR NEW.request->>'safe_error' IS NULL OR NEW.request->>'safe_error' NOT IN ('authority_required','reference_unavailable','response_invalid','response_too_large','provider_throttled','provider_unavailable','request_timeout','source_scope_changed')
   OR NEW.request->'observed_at' IS DISTINCT FROM 'null'::jsonb OR NEW.request->'item_response_sha256' IS DISTINCT FROM 'null'::jsonb OR NEW.request->'conversation_response_sha256' IS DISTINCT FROM 'null'::jsonb
   THEN RAISE EXCEPTION 'inbox read failure must remain metadata only' USING ERRCODE='23514';END IF;
  ELSE
   IF src.id IS NULL OR NEW.request->>'snapshot_sha256' IS NULL OR NEW.request->'safe_error'<>'null'::jsonb THEN RAISE EXCEPTION 'inbox incoming source missing' USING ERRCODE='23514';END IF;
   IF NEW.request->>'snapshot_sha256' IS DISTINCT FROM public.vendor_public_digest('cosmas-inbox-stored-snapshot.v1',src.snapshot||jsonb_build_object('observed_at',NEW.request->'observed_at','item_response_sha256',NEW.request->'item_response_sha256','conversation_response_sha256',NEW.request->'conversation_response_sha256'))
   THEN RAISE EXCEPTION 'inbox exact read snapshot commitment mismatch' USING ERRCODE='23514'; END IF;
   outcome:=CASE WHEN oldsrc.id IS NULL THEN 'new'
    WHEN (src.snapshot->>'created_at')::timestamptz IS DISTINCT FROM (oldsrc.snapshot->>'created_at')::timestamptz THEN 'conflict'
    WHEN src.source_sha256=oldsrc.source_sha256 THEN 'same'
    WHEN (src.snapshot->>'modified_at')::timestamptz<(oldsrc.snapshot->>'modified_at')::timestamptz THEN CASE WHEN src.snapshot->>'conversation_content_sha256'=oldsrc.snapshot->>'conversation_content_sha256' THEN 'older' ELSE 'conflict' END
    WHEN (src.snapshot->>'modified_at')::timestamptz=(oldsrc.snapshot->>'modified_at')::timestamptz THEN 'conflict' ELSE 'newer' END;
  END IF;
  expected:=jsonb_build_object('id',NEW.id,'item_id',r.id,'version',NEW.version,'outcome',outcome,'source_id',NEW.source_id,'source_sha256',src.source_sha256,'safe_error',NEW.request->'safe_error','observed_at',to_char((NEW.request->>'observed_at')::timestamptz AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'item_response_sha256',NEW.request->'item_response_sha256','conversation_response_sha256',NEW.request->'conversation_response_sha256','request_sha256',NEW.request_sha256,'grant_sha256',r.grant_sha256,'recorded_at',to_char(NEW.recorded_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
  IF NEW.response IS DISTINCT FROM expected OR NEW.receipt_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-inbox-read-receipt.v1',expected)
  THEN RAISE EXCEPTION 'inbox read receipt mismatch' USING ERRCODE='23514';END IF;
  RETURN NEW;
 END IF;
 IF NEW.request_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-inbox-request.v1',jsonb_build_object('scope',jsonb_build_object('box_id',r.box_id,'owner_id',r.owner_id),'command_kind',NEW.kind,'request',NEW.request))
  OR NEW.request->>'item_id' IS DISTINCT FROM r.id::text
  OR NEW.request->>'source_id' IS DISTINCT FROM NEW.source_id::text OR NEW.request->>'source_sha256' IS DISTINCT FROM src.source_sha256
 THEN RAISE EXCEPTION 'inbox human exact request mismatch' USING ERRCODE='23514';END IF;
 names:=ARRAY['item_id','expected_version','idempotency_key']||CASE WHEN NEW.request ? 'source_id' THEN ARRAY['source_id','source_sha256'] ELSE ARRAY[]::text[] END;
 IF NEW.kind='review' THEN names:=names||ARRAY['workspace_id','expected_workspace_revision','patient_link_id','reviewed_patient','reviewed_exact_thread','reviewed_untrusted_source'];
 ELSIF NEW.kind='triage' THEN names:=names||ARRAY['classification','due_date','instructions','human_disposition_required'];
 ELSIF NEW.kind='result' THEN names:=names||ARRAY['triage_receipt_id','triage_receipt_sha256','disposition','evidence','no_external_action_claimed'];
 ELSE names:=names||ARRAY['result_receipt_id','result_receipt_sha256','reviewed_patient','reviewed_exact_source','reviewed_human_result','confirm_local_review_only'];END IF;
 IF NOT public.finance_settings_keys(NEW.request,names) OR EXISTS(SELECT 1 FROM jsonb_each(NEW.request) pair WHERE pair.value='null'::jsonb) THEN RAISE EXCEPTION 'inbox exact request keys mismatch' USING ERRCODE='23514';END IF;
 expected:=jsonb_build_object('contract_version',1,'scope',jsonb_build_object('box_id',r.box_id,'owner_id',r.owner_id),'command_kind',NEW.kind,'idempotency_key',NEW.idempotency_key,'request_sha256',NEW.request_sha256,'outcome',NEW.response->'outcome','effect',NEW.response->'effect','rejection',NEW.response->'rejection','receipt_id',NEW.id,'recorded_at',to_char(NEW.recorded_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
 IF NEW.response IS DISTINCT FROM expected OR NEW.receipt_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-inbox-receipt.v1',expected)
 THEN RAISE EXCEPTION 'inbox human receipt commitment mismatch' USING ERRCODE='23514';END IF;
 IF NEW.response->>'outcome'='rejected' THEN
  IF NEW.response->'effect' IS DISTINCT FROM 'null'::jsonb OR NEW.response->>'rejection' IS NULL OR NEW.response->>'rejection' NOT IN ('inbox_version_changed','inbox_source_changed','inbox_binding_unavailable','inbox_workspace_changed','inbox_review_required','inbox_triage_required','inbox_result_changed','inbox_exception_unresolved','inbox_feature_disabled','inbox_history_limit')
  THEN RAISE EXCEPTION 'inbox rejection mismatch' USING ERRCODE='23514';END IF;
  RETURN NEW;
 END IF;
 IF NEW.response->>'outcome' IS DISTINCT FROM 'recorded' OR NEW.response->'rejection' IS DISTINCT FROM 'null'::jsonb OR NOT public.inbox_grant_valid(r)
  OR (NEW.request->>'expected_version')::integer<>previous OR NEW.source_id IS DISTINCT FROM r.current_source_id
 THEN RAISE EXCEPTION 'inbox admission lost source authority' USING ERRCODE='23514';END IF;
 SELECT * INTO reviewed FROM public.inbox_events WHERE item_id=r.id AND kind='review' AND source_id=r.current_source_id AND response->>'outcome'='recorded' ORDER BY version DESC LIMIT 1;
 SELECT * INTO triage FROM public.inbox_events WHERE item_id=r.id AND kind='triage' AND source_id IS NOT DISTINCT FROM r.current_source_id AND response->>'outcome'='recorded' ORDER BY version DESC LIMIT 1;
 SELECT * INTO result FROM public.inbox_events WHERE item_id=r.id AND kind='result' AND source_id IS NOT DISTINCT FROM r.current_source_id AND response->>'outcome'='recorded' ORDER BY version DESC LIMIT 1;
 IF reviewed.id IS NOT NULL THEN SELECT * INTO w FROM public.encounter_workspaces WHERE id=(reviewed.request->>'workspace_id')::uuid;END IF;
 workspace_ok:=coalesce(reviewed.id IS NOT NULL AND w.id IS NOT NULL AND (w.box_id,w.owner_id,w.patient_link_id,w.revision)=(r.box_id,r.owner_id,r.patient_link_id,(reviewed.request->>'expected_workspace_revision')::integer),false);
 incomplete:=src.id IS NULL OR r.source_conflict OR r.read_issue IS NOT NULL OR btrim(src.snapshot->>'text',chr(9)||chr(10)||chr(13)||chr(32)||chr(133)||chr(160)||chr(5760)||chr(8192)||chr(8193)||chr(8194)||chr(8195)||chr(8196)||chr(8197)||chr(8198)||chr(8199)||chr(8200)||chr(8201)||chr(8202)||chr(8232)||chr(8233)||chr(8239)||chr(8287)||chr(12288))='' OR src.snapshot->'unsupported'->>'attachments'='true' OR src.snapshot->'unsupported'->>'pages'='true' OR src.snapshot->'unsupported'->>'buttons'='true' OR src.snapshot->'unsupported'->>'event'='true';
 IF NEW.kind='review' THEN
  SELECT * INTO w FROM public.encounter_workspaces WHERE id=(NEW.request->>'workspace_id')::uuid;
  IF src.id IS NULL OR r.source_conflict OR r.read_issue IS NOT NULL OR w.id IS NULL OR (w.box_id,w.owner_id,w.patient_link_id,w.revision) IS DISTINCT FROM (r.box_id,r.owner_id,r.patient_link_id,(NEW.request->>'expected_workspace_revision')::integer)
   OR NEW.request->>'patient_link_id' IS DISTINCT FROM r.patient_link_id::text OR NEW.request->'reviewed_patient'<>'true'::jsonb OR NEW.request->'reviewed_exact_thread'<>'true'::jsonb OR NEW.request->'reviewed_untrusted_source'<>'true'::jsonb
  THEN RAISE EXCEPTION 'inbox patient/thread review mismatch' USING ERRCODE='23514';END IF;outcome:='reviewed';
 ELSIF NEW.kind='triage' THEN
  IF NEW.request->'human_disposition_required'<>'true'::jsonb OR NEW.request->>'classification' NOT IN ('administrative_review','clinical_human_review','urgent_human_review','source_exception')
   OR char_length(NEW.request->>'instructions') NOT BETWEEN 1 AND 2000
   OR (NEW.request->>'classification'='administrative_review' AND (incomplete OR NOT workspace_ok))
  THEN RAISE EXCEPTION 'inbox triage requires exact human review' USING ERRCODE='23514';END IF;
  outcome:=CASE WHEN NEW.request->>'classification'='administrative_review' THEN 'triaged' ELSE 'needs_human' END;
 ELSIF NEW.kind='result' THEN
  IF triage.id IS NULL OR NEW.request->>'triage_receipt_id' IS DISTINCT FROM triage.id::text OR NEW.request->>'triage_receipt_sha256' IS DISTINCT FROM triage.receipt_sha256
   OR NEW.request->'no_external_action_claimed'<>'true'::jsonb OR NEW.request->>'disposition' NOT IN ('local_review_complete','needs_human')
   OR char_length(NEW.request->>'evidence') NOT BETWEEN 1 AND 2000
   OR (NEW.request->>'disposition'='local_review_complete' AND (incomplete OR NOT workspace_ok OR triage.version<=reviewed.version OR triage.request->>'classification'<>'administrative_review'))
  THEN RAISE EXCEPTION 'inbox human result mismatch' USING ERRCODE='23514';END IF;
  outcome:=CASE WHEN NEW.request->>'disposition'='local_review_complete' THEN 'result_recorded' ELSE 'needs_human' END;
 ELSE
  IF result.id IS NULL OR triage.id IS NULL OR NEW.request->>'result_receipt_id' IS DISTINCT FROM result.id::text OR NEW.request->>'result_receipt_sha256' IS DISTINCT FROM result.receipt_sha256
   OR result.request->>'disposition'<>'local_review_complete' OR result.request->>'triage_receipt_id' IS DISTINCT FROM triage.id::text
   OR incomplete OR NOT workspace_ok OR triage.version<=reviewed.version OR triage.request->>'classification'<>'administrative_review'
   OR NEW.request->'reviewed_patient'<>'true'::jsonb OR NEW.request->'reviewed_exact_source'<>'true'::jsonb OR NEW.request->'reviewed_human_result'<>'true'::jsonb OR NEW.request->'confirm_local_review_only'<>'true'::jsonb
  THEN RAISE EXCEPTION 'inbox local verification requires current human proof' USING ERRCODE='23514';END IF;outcome:='closed_local_review';
 END IF;
 IF NEW.response->'effect' IS DISTINCT FROM jsonb_build_object('item_id',r.id,'version',r.version,'source_id',r.current_source_id,'source_sha256',src.source_sha256,'state',outcome)
 THEN RAISE EXCEPTION 'inbox exact effect mismatch' USING ERRCODE='23514';END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER inbox_event_admission BEFORE INSERT ON public.inbox_events FOR EACH ROW EXECUTE FUNCTION public.inbox_event_guard();

"""
