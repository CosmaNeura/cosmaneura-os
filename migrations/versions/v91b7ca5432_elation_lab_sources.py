"""One selected Elation Lab report retains verified visit and workspace custody."""
from alembic import op

revision = "v91b7ca5432"
down_revision = "u80a6b9e4321"
branch_labels = None
depends_on = None


def definition(signature):
    return op.get_bind().exec_driver_sql("SELECT pg_get_functiondef(%s::regprocedure)", (signature,)).scalar_one()


def changed(sql, pairs):
    for before, after in pairs:
        if sql.count(before) != 1:
            raise RuntimeError("Prior EHR guard differs from Lab extension: " + before)
        sql = sql.replace(before, after)
    return sql


def upgrade():
    old = op.get_bind().exec_driver_sql("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='public.ehr_read_requests'::regclass AND conname='ck_ehr_read_request_kind'").scalar_one()
    op.drop_constraint("ck_ehr_read_request_kind", "ehr_read_requests")
    op.create_check_constraint("ck_ehr_read_request_kind", "ehr_read_requests", old[7:-1] + " OR (kind IN ('lab_reports','lab_report') AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL AND fhir_grant_id IS NULL AND athena_grant_id IS NULL AND workspace_id IS NOT NULL AND patient_link_id IS NOT NULL)")
    for signature in ("public.ehr_read_request_current(uuid)", "public.ehr_read_payload_valid(jsonb,public.ehr_read_requests)", "public.ehr_read_source_content(jsonb)", "public.ehr_read_source_valid(uuid)"):
        name = signature.split("(")[0]
        op.execute(definition(signature).replace(name + "(", name.replace("ehr_read_", "ehr_pre_lab_") + "(", 1))
    op.execute(FIELDS)
    op.execute(CLINICAL)
    op.execute(SCOPE)
    op.execute(CURRENT)
    op.execute(changed(definition("public.guard_ehr_read_request()"), ((" IF b.protocol='core' THEN", REQUEST + " IF b.protocol='core' THEN"),)))
    op.execute(CONTENT)
    op.execute(PAYLOAD)
    op.execute("""CREATE OR REPLACE FUNCTION public.ehr_read_payload_valid(payload jsonb,r public.ehr_read_requests) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$ SELECT CASE WHEN r.kind IN ('lab_reports','lab_report') THEN coalesce(public.ehr_lab_payload_valid(payload,r),false) ELSE public.ehr_pre_lab_payload_valid(payload,r) END $$""")
    op.execute("""CREATE OR REPLACE FUNCTION public.ehr_read_source_content(pub jsonb) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$ SELECT CASE WHEN pub->>'provider'='elation' AND pub->>'kind'='verified_lab_report' THEN pub->'item'->>'source_content' ELSE public.ehr_pre_lab_source_content(pub) END $$""")
    op.execute(SOURCES)
    op.execute(changed(definition("public.guard_ehr_read_review()"), (("r.kind NOT IN ('verify','problems','medications','fhir_medications','core_allergies')", "r.kind NOT IN ('verify','problems','medications','fhir_medications','core_allergies','lab_report')"),
        ("r.kind IN ('fhir_medications','core_allergies') AND", "r.kind IN ('fhir_medications','core_allergies','lab_report') AND"))))


def downgrade():
    raise RuntimeError("Retain immutable reviewed Lab report history")


FIELDS = r"""
CREATE FUNCTION public.ehr_lab_canonical(v jsonb,depth integer DEFAULT 0) RETURNS text LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog AS $$
DECLARE result text; kind text:=jsonb_typeof(v); row record;
BEGIN
 IF depth>20 THEN RAISE EXCEPTION 'Lab JSON depth'; END IF;
 IF kind='object' THEN
  FOR row IN SELECT * FROM jsonb_each(v) LOOP IF public.ehr_medication_text(to_jsonb(row.key),100) IS NOT TRUE THEN RAISE EXCEPTION 'Lab JSON key'; END IF; END LOOP;
  SELECT '{'||coalesce(string_agg(public.clinical_note_ascii_canonical(to_jsonb(key))||':'||public.ehr_lab_canonical(value,depth+1),',' ORDER BY key COLLATE "C"),'')||'}' INTO result FROM jsonb_each(v);
 ELSIF kind='array' THEN
  SELECT '['||coalesce(string_agg(public.ehr_lab_canonical(value,depth+1),',' ORDER BY ordinal),'')||']' INTO result FROM jsonb_array_elements(v) WITH ORDINALITY items(value,ordinal);
 ELSIF kind='number' THEN
  IF v::text !~ '^-?[0-9]+$' THEN RAISE EXCEPTION 'Lab numeric conversion refused'; END IF;
  result:=v::text;
 ELSIF kind='string' THEN
  IF public.ehr_medication_text(v,65536,true) IS NOT TRUE THEN RAISE EXCEPTION 'Lab JSON text'; END IF;
  result:=public.clinical_note_ascii_canonical(v);
 ELSE result:=public.clinical_note_ascii_canonical(v);
 END IF;
 RETURN result;
END $$;
CREATE FUNCTION public.ehr_lab_digest(v jsonb) RETURNS text LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog AS $$ SELECT encode(sha256(convert_to(public.ehr_lab_canonical(v),'UTF8')),'hex') $$;
CREATE FUNCTION public.ehr_lab_text(v jsonb,maximum integer,nullable boolean DEFAULT false,multiline boolean DEFAULT false,nonblank boolean DEFAULT false) RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT coalesce((nullable AND v='null'::jsonb) OR (public.ehr_medication_text(v,maximum,multiline) AND (NOT nonblank OR public.ehr_athena_nonblank(v#>>'{}'))),false)
$$;
CREATE FUNCTION public.ehr_lab_time(v jsonb,nullable boolean DEFAULT false) RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$ SELECT coalesce((nullable AND v='null'::jsonb) OR public.ehr_medication_time(v),false) $$;
CREATE FUNCTION public.ehr_lab_id(v jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$ SELECT public.ehr_athena_integer(v,1) $$;
CREATE FUNCTION public.ehr_lab_header(v jsonb,scoped jsonb,selected bigint DEFAULT NULL) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE k text; allowed text[]:=ARRAY['id','chart_date','document_date','patient','physician','practice','report_type','created_date','custom_title','deleted_date','is_urgent','order_status','reported_date','requisition_number','signed_by','signed_date','vendor'];
BEGIN
 IF jsonb_typeof(v) IS DISTINCT FROM 'object' OR NOT v ?& ARRAY['id','chart_date','document_date','patient','physician','practice','report_type'] OR EXISTS(SELECT 1 FROM jsonb_object_keys(v) key WHERE NOT key=ANY(allowed)) THEN RETURN false; END IF;
 FOREACH k IN ARRAY ARRAY['id','patient','practice','physician'] LOOP IF public.ehr_lab_id(v->k) IS NOT TRUE THEN RETURN false; END IF; END LOOP;
 IF v->'patient' IS DISTINCT FROM scoped->'patient_id' OR v->'practice' IS DISTINCT FROM scoped->'connection_scope'->'practice_id' OR v->>'report_type' IS DISTINCT FROM 'Lab'
 OR selected IS NOT NULL AND v->>'id' IS DISTINCT FROM selected::text OR public.ehr_lab_time(v->'chart_date') IS NOT TRUE OR public.ehr_lab_time(v->'document_date') IS NOT TRUE THEN RETURN false; END IF;
 FOREACH k IN ARRAY ARRAY['created_date','deleted_date','signed_date','reported_date'] LOOP IF v ? k AND public.ehr_lab_time(v->k,true) IS NOT TRUE THEN RETURN false; END IF; END LOOP;
 FOREACH k IN ARRAY ARRAY['custom_title','requisition_number','order_status'] LOOP IF v ? k AND public.ehr_lab_text(v->k,CASE WHEN k='custom_title' THEN 255 ELSE 100 END,true) IS NOT TRUE THEN RETURN false; END IF; END LOOP;
 FOREACH k IN ARRAY ARRAY['signed_by','vendor'] LOOP IF v ? k AND v->k<>'null'::jsonb AND public.ehr_lab_id(v->k) IS NOT TRUE THEN RETURN false; END IF; END LOOP;
 IF v ? 'is_urgent' AND jsonb_typeof(v->'is_urgent') IS DISTINCT FROM 'boolean' THEN RETURN false; END IF;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

CLINICAL = r"""
CREATE FUNCTION public.ehr_lab_report(raw text,scoped jsonb,rid bigint) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE v jsonb:=raw::jsonb; row jsonb; result jsonb; item jsonb; k text; collection text; allowed text[];
BEGIN
 IF octet_length(raw)>65536 OR public.ehr_lab_canonical(v) IS DISTINCT FROM raw
 OR public.ehr_lab_header(v-'files'-'grids'-'images'-'routed_document_delegates'-'tags'-'printable_view',scoped,rid) IS NOT TRUE THEN RETURN false; END IF;
 IF v ? 'grids' THEN
  IF jsonb_typeof(v->'grids') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'grids')>10 THEN RETURN false; END IF;
  FOR row IN SELECT * FROM jsonb_array_elements(v->'grids') LOOP
   IF public.finance_settings_keys(row,ARRAY['accession_number','collected_date','note','resulted_date','results','status']) IS NOT TRUE
   OR public.ehr_lab_text(row->'accession_number',300) IS NOT TRUE OR public.ehr_lab_text(row->'status',100,false,false,true) IS NOT TRUE
   OR public.ehr_lab_text(row->'note',4000,true,true) IS NOT TRUE OR public.ehr_lab_time(row->'collected_date') IS NOT TRUE OR public.ehr_lab_time(row->'resulted_date') IS NOT TRUE
   OR jsonb_typeof(row->'results') IS DISTINCT FROM 'array' OR jsonb_array_length(row->'results')>100 THEN RETURN false; END IF;
   FOR result IN SELECT * FROM jsonb_array_elements(row->'results') LOOP
    IF public.finance_settings_keys(result-'units'-'value_type',ARRAY['abnormal_flag','is_abnormal','note','reference_max','reference_min','status','test','test_category','text','value']) IS NOT TRUE
    OR public.ehr_lab_text(result->'value',500,false,true) IS NOT TRUE OR public.ehr_lab_text(result->'abnormal_flag',200,false,false,true) IS NOT TRUE
    OR public.ehr_lab_text(result->'status',100,false,false,true) IS NOT TRUE OR jsonb_typeof(result->'is_abnormal') IS DISTINCT FROM 'boolean' THEN RETURN false; END IF;
    FOREACH k IN ARRAY ARRAY['note','text','reference_min','reference_max'] LOOP IF public.ehr_lab_text(result->k,4000,true,true) IS NOT TRUE THEN RETURN false; END IF; END LOOP;
    IF result ? 'units' AND public.ehr_lab_text(result->'units',20,true) IS NOT TRUE OR result ? 'value_type' AND public.ehr_lab_text(result->'value_type',100,true) IS NOT TRUE
    OR public.finance_settings_keys(result->'test',ARRAY['code','loinc','name']) IS NOT TRUE OR public.ehr_lab_text(result->'test'->'code',50) IS NOT TRUE
    OR public.ehr_lab_text(result->'test'->'loinc',300,true) IS NOT TRUE OR public.ehr_lab_text(result->'test'->'name',255,false,false,true) IS NOT TRUE
    OR public.finance_settings_keys(result->'test_category',ARRAY['description','value']) IS NOT TRUE OR public.ehr_lab_text(result->'test_category'->'description',200) IS NOT TRUE
    OR public.ehr_lab_text(result->'test_category'->'value',50) IS NOT TRUE THEN RETURN false; END IF;
   END LOOP;
  END LOOP;
 END IF;
 FOREACH collection IN ARRAY ARRAY['files','images','routed_document_delegates','tags'] LOOP
  IF NOT v ? collection OR collection IN ('files','images') AND v->collection='null'::jsonb THEN CONTINUE; END IF;
  IF jsonb_typeof(v->collection) IS DISTINCT FROM 'array' OR jsonb_array_length(v->collection)>25 THEN RETURN false; END IF;
  FOR item IN SELECT * FROM jsonb_array_elements(v->collection) LOOP
   IF collection='tags' THEN IF public.ehr_lab_id(item) IS NOT TRUE THEN RETURN false; END IF; CONTINUE; END IF;
   allowed:=CASE collection WHEN 'files' THEN ARRAY['base64_content','content_type','document','external_content','id','original_filename'] WHEN 'images' THEN ARRAY['id','document'] ELSE ARRAY['id','user','group','created_date','deleted_date'] END;
   IF jsonb_typeof(item) IS DISTINCT FROM 'object' OR EXISTS(SELECT 1 FROM jsonb_object_keys(item) key WHERE NOT key=ANY(allowed)) THEN RETURN false; END IF;
   IF item ? 'base64_content' AND item->'base64_content' NOT IN ('null'::jsonb,'""'::jsonb) THEN RETURN false; END IF;
   FOR k IN SELECT jsonb_object_keys(item) LOOP
    IF k='external_content' THEN CONTINUE;
    ELSIF k IN ('id','user','group') THEN IF item->k<>'null'::jsonb AND public.ehr_lab_id(item->k) IS NOT TRUE THEN RETURN false; END IF;
    ELSIF right(k,5)='_date' THEN IF public.ehr_lab_time(item->k,true) IS NOT TRUE THEN RETURN false; END IF;
    ELSIF public.ehr_lab_text(item->k,2048) IS NOT TRUE THEN RETURN false;
    END IF;
   END LOOP;
  END LOOP;
 END LOOP;
 IF v ? 'printable_view' AND public.ehr_lab_text(v->'printable_view',2048) IS NOT TRUE THEN RETURN false; END IF;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

SCOPE = r"""
CREATE FUNCTION public.ehr_lab_verified_request(r public.ehr_read_requests) RETURNS public.ehr_read_requests LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT v FROM public.ehr_read_snapshots p JOIN public.ehr_read_requests prior ON prior.id=p.observation_id
 LEFT JOIN public.ehr_read_snapshots q ON q.id=prior.parent_snapshot_id
 JOIN public.ehr_read_requests v ON v.id=CASE WHEN r.kind='lab_reports' THEN prior.id ELSE q.observation_id END
 WHERE p.id=r.parent_snapshot_id AND v.kind='verify' AND prior.kind=CASE WHEN r.kind='lab_reports' THEN 'verify' ELSE 'lab_reports' END
$$;
CREATE FUNCTION public.ehr_lab_identity(r public.ehr_read_requests) RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('id',(p->>'patient_id')::bigint,'caregiver_practice',r.practice_id::bigint,'primary_physician',(p->>'primary_physician_id')::bigint,
 'first_name',p->'first_name','last_name',p->'last_name','dob',p->'birth_date','deleted_date',NULL)
 FROM public.ehr_read_snapshots z CROSS JOIN LATERAL (SELECT z.payload->'private'->'items'->0->'patient' p) patient
 WHERE z.observation_id=(public.ehr_lab_verified_request(r)).id
$$;
CREATE FUNCTION public.ehr_lab_scope(r public.ehr_read_requests) RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('connection_scope',jsonb_build_object('box_id',b.box_id,'owner_id',b.owner_id,'connection_id',b.connection_id,'credential_generation',b.credential_generation,
 'practice_id',b.practice_id::bigint,'practice_name',b.practice_name,'environment',b.environment),'account_id',r.account_id,'workspace_id',r.workspace_id,'patient_link_id',r.patient_link_id,
 'patient_id',public.ehr_lab_identity(r)->'id','patient_identity_sha256',public.ehr_lab_digest(public.ehr_lab_identity(r)),
 'authorization_sha256',public.google_calendar_json_digest(jsonb_build_object('contract','ehr-elation-lab-authority.v1','account_id',r.account_id,'binding_sha256',r.binding_digest,
 'workspace_id',r.workspace_id,'patient_link_id',r.patient_link_id,'verified_observation_id',v.id,'verified_source_sha256',z.source_sha256,
 'verified_item_handle',z.payload->'public'->'item'->'handle','verified_item_sha256',z.payload->'public'->'item'->'sha256')))
 FROM public.ehr_read_bindings b JOIN public.ehr_read_requests v ON v.id=(public.ehr_lab_verified_request(r)).id JOIN public.ehr_read_snapshots z ON z.observation_id=v.id WHERE b.id=r.binding_id
$$;
CREATE FUNCTION public.ehr_lab_scope_digest(scoped jsonb,binding_digest text) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT public.ehr_lab_digest((scoped-'connection_scope')||jsonb_build_object('contract','elation-lab-patient-scope.v1','connection_scope_sha256',binding_digest))
$$;
CREATE FUNCTION public.ehr_lab_public_identity(raw text) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT public.ehr_lab_canonical(jsonb_build_object('first_name',raw::jsonb->'first_name','last_name',raw::jsonb->'last_name','dob',raw::jsonb->'dob'))
$$;
"""

CURRENT = r"""
CREATE OR REPLACE FUNCTION public.ehr_read_request_current(rid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN r.kind NOT IN ('lab_reports','lab_report') THEN public.ehr_pre_lab_request_current(r.id) ELSE EXISTS(
 SELECT 1 FROM public.ehr_read_bindings b JOIN public.encounter_workspaces w ON (w.id,w.box_id,w.owner_id,w.patient_link_id)=(r.workspace_id,r.box_id,r.owner_id,r.patient_link_id)
 JOIN public.patient_links link ON (link.id,link.box_id)=(r.patient_link_id,r.box_id)
 JOIN public.ehr_read_snapshots z ON z.id=r.parent_snapshot_id JOIN public.ehr_read_requests p ON p.id=z.observation_id
 JOIN public.ehr_read_requests v ON v.id=(public.ehr_lab_verified_request(r)).id
 WHERE b.id=r.binding_id AND b.protocol IS NULL AND b.vendor='elation' AND public.ehr_read_binding_current(b.id) AND r.transport='mock' AND r.valid_until>clock_timestamp()
 AND (r.box_id,r.owner_id,r.account_id,r.connection_id,r.credential_generation,r.binding_digest,r.practice_id)=(b.box_id,b.owner_id,b.account_id,b.connection_id,b.credential_generation,b.binding_digest,b.practice_id)
 AND (p.box_id,p.owner_id,p.account_id,p.binding_id,p.window_start,p.window_end,p.transport)=(r.box_id,r.owner_id,r.account_id,r.binding_id,r.window_start,r.window_end,r.transport)
 AND (r.kind='lab_reports' OR (p.workspace_id,p.patient_link_id)=(r.workspace_id,r.patient_link_id)) AND r.valid_until<=p.valid_until
 AND link.state='confirmed' AND link.revoked_at IS NULL AND public.ehr_pre_lab_request_current(v.id)
 AND NOT EXISTS(SELECT 1 FROM public.ehr_read_requests newer WHERE newer.binding_id=r.binding_id AND newer.workspace_id=r.workspace_id AND newer.kind='lab_reports' AND newer.ordinal>CASE WHEN r.kind='lab_reports' THEN r.ordinal ELSE p.ordinal END)) END
 FROM public.ehr_read_requests r WHERE r.id=rid
$$;
"""

REQUEST = r"""
 IF NEW.kind IN ('lab_reports','lab_report') THEN
  SELECT * INTO parent FROM public.ehr_read_snapshots WHERE id=NEW.parent_snapshot_id;
  SELECT * INTO root FROM public.ehr_read_requests WHERE id=parent.observation_id;
  IF b.protocol IS NOT NULL OR b.vendor IS DISTINCT FROM 'elation' OR NEW.transport IS DISTINCT FROM 'mock'
  OR root.kind IS DISTINCT FROM (CASE WHEN NEW.kind='lab_reports' THEN 'verify' ELSE 'lab_reports' END)
  OR (root.box_id,root.owner_id,root.account_id,root.binding_id,root.window_start,root.window_end,root.transport) IS DISTINCT FROM (NEW.box_id,NEW.owner_id,NEW.account_id,NEW.binding_id,NEW.window_start,NEW.window_end,NEW.transport)
  OR NEW.kind='lab_report' AND (root.workspace_id,root.patient_link_id) IS DISTINCT FROM (NEW.workspace_id,NEW.patient_link_id)
  OR NOT EXISTS(SELECT 1 FROM public.encounter_workspaces w JOIN public.patient_links p ON (p.id,p.box_id)=(w.patient_link_id,w.box_id) WHERE (w.id,w.box_id,w.owner_id,w.patient_link_id)=(NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.patient_link_id) AND p.state='confirmed' AND p.revoked_at IS NULL)
  OR public.ehr_read_request_current(root.id) IS NOT TRUE OR public.ehr_read_snapshot_valid(parent.id) IS NOT TRUE OR NEW.valid_until>root.valid_until
  OR public.finance_settings_keys(NEW.request_json,ARRAY['provider','action','workspace_id','connection_id','binding_sha256','idempotency_key','observation_id','observation_sha256','item_handle','item_sha256']) IS NOT TRUE
  OR NEW.request_json->>'provider' IS DISTINCT FROM 'elation' OR NEW.request_json->>'workspace_id' IS DISTINCT FROM NEW.workspace_id::text OR NEW.request_json->>'action' IS DISTINCT FROM NEW.kind
  OR NEW.request_json->>'observation_id' IS DISTINCT FROM root.id::text OR NEW.request_json->>'observation_sha256' IS DISTINCT FROM parent.source_sha256 OR NEW.request_json->>'item_handle' IS DISTINCT FROM NEW.item_handle::text
  THEN RAISE EXCEPTION 'Elation Lab request authority invalid' USING ERRCODE='23514'; END IF;
  IF NEW.kind='lab_reports' THEN
   IF parent.payload->'public'->'item'->>'handle' IS DISTINCT FROM NEW.item_handle::text OR parent.payload->'public'->'item'->>'sha256' IS DISTINCT FROM NEW.request_json->>'item_sha256' THEN RAISE EXCEPTION 'Exact verified visit required' USING ERRCODE='23514'; END IF;
  ELSIF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent.payload->'public'->'items') item WHERE item->>'handle'=NEW.item_handle::text AND item->>'sha256'=NEW.request_json->>'item_sha256') THEN RAISE EXCEPTION 'Exact Lab selection required' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
 END IF;
"""

CONTENT = r"""
CREATE FUNCTION public.ehr_lab_warnings(v jsonb) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE report jsonb:=(v->>'report_json')::jsonb; warnings jsonb:=jsonb_build_array('Only returned API fields of one selected Lab report are included; a complete chart or correction history is not established.','Attachment, image, printable-view contents and internal notes were not fetched.');
BEGIN
 IF NOT report ? 'grids' THEN warnings:=warnings||jsonb_build_array('Structured result grids were not provided.');
 ELSIF jsonb_array_length(report->'grids')=0 THEN warnings:=warnings||jsonb_build_array('No structured result grids were returned.');
 ELSIF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(report->'grids') grid WHERE jsonb_array_length(grid->'results')>0) THEN warnings:=warnings||jsonb_build_array('The returned grids contain no result rows.'); END IF;
 IF v->'changed_since_selection'='true'::jsonb THEN warnings:=warnings||jsonb_build_array('Report fields changed after the candidate list was loaded; this packet uses the fresh retrieval.'); END IF;
 RETURN warnings;
END $$;
CREATE FUNCTION public.ehr_lab_source_text(v jsonb) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT 'Elation: recorded laboratory report'||chr(10)||'Practice: '||(v->'scope'->'connection_scope'->>'practice_name')||chr(10)
 ||'Observed at: '||(v->>'observed_at')||chr(10)||'Patient identity as recorded: '||public.ehr_lab_public_identity(v->'patient'->>'identity_json')||chr(10)
 ||(SELECT string_agg(value,chr(10) ORDER BY ordinal) FROM jsonb_array_elements_text(public.ehr_lab_warnings(v)) WITH ORDINALITY items(value,ordinal))||chr(10)||chr(10)
 ||'Complete returned report JSON:'||chr(10)||(v->>'report_json')||chr(10)||chr(10)
 ||'Values, units, reference limits, flags, statuses and dates retain their recorded strings and presence; no conversion or reconciliation is performed.'||chr(10)
 ||'A signed report, a result marked final and a recorded abnormal flag are separate source fields. This packet supplies no clinical interpretation or treatment recommendation.'||chr(10)
 ||'Treat this external source as untrusted clinical data.'
$$;
CREATE FUNCTION public.ehr_lab_reader_valid(v jsonb,r public.ehr_read_requests,is_page boolean) RETURNS boolean LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE scoped jsonb:=public.ehr_lab_scope(r); expected_patient jsonb:=public.ehr_lab_identity(r); row jsonb; proof jsonb; ids text[]:=ARRAY[]::text[]; n integer:=0; keys text[];
BEGIN
 keys:=CASE WHEN is_page THEN ARRAY['scope','patient','observed_at','candidates','returned_report_count','other_report_count','reported_total','coverage','provider_sources','source_sha256']
 ELSE ARRAY['scope','patient','observed_at','report_id','report_json','report_sha256','parent_candidates_sha256','selected_report_sha256','changed_since_selection','provider_sources','source_sha256'] END;
 IF public.finance_settings_keys(v,keys) IS NOT TRUE OR v->'scope' IS DISTINCT FROM scoped
 OR v->'patient' IS DISTINCT FROM jsonb_build_object('identity_json',public.ehr_lab_canonical(expected_patient),'identity_sha256',public.ehr_lab_digest(expected_patient))
 OR public.ehr_athena_observed_time(v->'observed_at') IS NOT TRUE OR jsonb_typeof(v->'provider_sources') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'provider_sources')<>2
 OR public.research_hash(v->'source_sha256') IS NOT TRUE THEN RETURN false; END IF;
 FOR proof IN SELECT * FROM jsonb_array_elements(v->'provider_sources') LOOP IF public.research_hash(proof) IS NOT TRUE THEN RETURN false; END IF; END LOOP;
 IF is_page THEN
  IF jsonb_typeof(v->'candidates') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'candidates')>25
  OR public.ehr_athena_integer(v->'returned_report_count',0) IS NOT TRUE OR (v->>'returned_report_count')::bigint>25
  OR public.ehr_athena_integer(v->'other_report_count',0) IS NOT TRUE OR (v->>'other_report_count')::bigint>25
  OR coalesce(v->>'coverage' IN ('returned_page_only','more_rows_available','continuation_unknown'),false) IS NOT TRUE
  OR v->'reported_total'<>'null'::jsonb AND (public.ehr_athena_integer(v->'reported_total',0) IS NOT TRUE OR (v->>'reported_total')::numeric<(v->>'returned_report_count')::numeric) THEN RETURN false; END IF;
  FOR row IN SELECT * FROM jsonb_array_elements(v->'candidates') LOOP
   IF public.finance_settings_keys(row,ARRAY['report_id','metadata_json','report_sha256']) IS NOT TRUE OR public.ehr_lab_id(row->'report_id') IS NOT TRUE
   OR row->>'report_id'=ANY(ids) OR jsonb_typeof(row->'metadata_json') IS DISTINCT FROM 'string' OR char_length(row->>'metadata_json')>16384
   OR public.ehr_lab_canonical((row->>'metadata_json')::jsonb) IS DISTINCT FROM row->>'metadata_json'
   OR public.ehr_lab_header((row->>'metadata_json')::jsonb,scoped,(row->>'report_id')::bigint) IS NOT TRUE OR public.research_hash(row->'report_sha256') IS NOT TRUE THEN RETURN false; END IF;
   ids:=array_append(ids,row->>'report_id'); n:=n+1;
  END LOOP;
  RETURN coalesce((v->>'returned_report_count')::integer=n+(v->>'other_report_count')::integer
   AND v->>'source_sha256'=public.ehr_lab_digest((v-'scope'-'source_sha256')||jsonb_build_object('contract','elation-lab-candidates.v1','scope_sha256',public.ehr_lab_scope_digest(scoped,r.binding_digest))),false);
 END IF;
 IF public.ehr_lab_id(v->'report_id') IS NOT TRUE OR jsonb_typeof(v->'changed_since_selection') IS DISTINCT FROM 'boolean'
 OR public.research_hash(v->'report_sha256') IS NOT TRUE OR public.research_hash(v->'selected_report_sha256') IS NOT TRUE OR public.research_hash(v->'parent_candidates_sha256') IS NOT TRUE
 OR jsonb_typeof(v->'report_json') IS DISTINCT FROM 'string' OR public.ehr_lab_report(v->>'report_json',scoped,(v->>'report_id')::bigint) IS NOT TRUE
 OR v->>'report_sha256' IS DISTINCT FROM public.ehr_lab_digest((v->>'report_json')::jsonb)
 OR (v->>'changed_since_selection')::boolean IS DISTINCT FROM (v->>'report_sha256'<>v->>'selected_report_sha256') THEN RETURN false; END IF;
 RETURN coalesce(v->>'source_sha256'=public.ehr_lab_digest((v-'scope'-'source_sha256')||jsonb_build_object('contract','elation-lab-report.v1','scope_sha256',public.ehr_lab_scope_digest(scoped,r.binding_digest))),false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

PAYLOAD = r"""
CREATE FUNCTION public.ehr_lab_payload_valid(payload jsonb,r public.ehr_read_requests) RETURNS boolean LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE pub jsonb:=payload->'public'; priv jsonb:=payload->'private'; b public.ehr_read_bindings; previous public.ehr_read_snapshots; prior public.ehr_read_requests;
 verified public.ehr_read_requests; original public.ehr_read_snapshots; raw jsonb; page jsonb; item jsonb; candidate jsonb; shown jsonb; expected jsonb; proof jsonb;
 handles text[]:=ARRAY[]::text[]; ids text[]:=ARRAY[]::text[]; pos integer:=0; content text; contentsha text; metadata jsonb;
BEGIN
 SELECT * INTO b FROM public.ehr_read_bindings WHERE id=r.binding_id;
 SELECT * INTO previous FROM public.ehr_read_snapshots WHERE id=r.parent_snapshot_id;
 SELECT * INTO prior FROM public.ehr_read_requests WHERE id=previous.observation_id;
 verified:=public.ehr_lab_verified_request(r);
 SELECT * INTO original FROM public.ehr_read_snapshots WHERE observation_id=verified.id;
 IF b.protocol IS NOT NULL OR b.vendor IS DISTINCT FROM 'elation' OR r.transport IS DISTINCT FROM 'mock' OR r.kind NOT IN ('lab_reports','lab_report')
 OR public.finance_settings_keys(payload,ARRAY['public','private']) IS NOT TRUE OR octet_length(public.ehr_lab_canonical(payload))>65536
 OR public.finance_settings_keys(priv,ARRAY['lab_contract','transport','binding_sha256','request_sha256','workspace_id','patient_link_id','items','page_snapshot_json','reader_snapshot_json','review_sha256','visit_provider_sources']) IS NOT TRUE
 OR priv->>'lab_contract' IS DISTINCT FROM 'elation_lab.v1' OR priv->>'transport' IS DISTINCT FROM 'mock' OR priv->>'binding_sha256' IS DISTINCT FROM r.binding_digest OR priv->>'request_sha256' IS DISTINCT FROM r.request_hash
 OR priv->>'workspace_id' IS DISTINCT FROM r.workspace_id::text OR priv->>'patient_link_id' IS DISTINCT FROM r.patient_link_id::text
 OR pub->>'workspace_id' IS DISTINCT FROM r.workspace_id::text OR pub->>'provider' IS DISTINCT FROM 'elation' OR pub->>'mode' IS DISTINCT FROM 'synthetic'
 OR pub->>'kind' IS DISTINCT FROM (CASE WHEN r.kind='lab_reports' THEN 'lab_reports' ELSE 'verified_lab_report' END)
 OR verified.id IS NULL OR public.ehr_read_snapshot_valid(original.id) IS NOT TRUE OR public.ehr_read_snapshot_valid(previous.id) IS NOT TRUE
 OR prior.kind IS DISTINCT FROM (CASE WHEN r.kind='lab_reports' THEN 'verify' ELSE 'lab_reports' END)
 OR (prior.box_id,prior.owner_id,prior.account_id,prior.binding_id,prior.window_start,prior.window_end) IS DISTINCT FROM (r.box_id,r.owner_id,r.account_id,r.binding_id,r.window_start,r.window_end)
 OR r.kind='lab_report' AND (prior.workspace_id,prior.patient_link_id) IS DISTINCT FROM (r.workspace_id,r.patient_link_id)
 OR pub->'practice' IS DISTINCT FROM original.payload->'public'->'practice' OR pub->'window' IS DISTINCT FROM original.payload->'public'->'window'
 OR pub->'parent' IS DISTINCT FROM jsonb_build_object('observation_id',prior.id,'source_sha256',previous.source_sha256,'item_sha256',r.request_json->'item_sha256')
 OR r.request_json->>'provider' IS DISTINCT FROM 'elation' OR r.request_json ? 'protocol' OR r.request_json->>'workspace_id' IS DISTINCT FROM r.workspace_id::text
 OR r.request_json->>'observation_id' IS DISTINCT FROM prior.id::text OR r.request_json->>'observation_sha256' IS DISTINCT FROM previous.source_sha256
 OR jsonb_typeof(priv->'items') IS DISTINCT FROM 'array' OR jsonb_array_length(priv->'items')>25
 OR jsonb_typeof(priv->'visit_provider_sources') IS DISTINCT FROM 'array' OR jsonb_array_length(priv->'visit_provider_sources')<>2
 OR public.google_message_aware_time(pub->'observed_at') IS NOT TRUE THEN RETURN false; END IF;
 FOR proof IN SELECT * FROM jsonb_array_elements(priv->'visit_provider_sources') LOOP IF public.research_hash(proof) IS NOT TRUE THEN RETURN false; END IF; END LOOP;
 IF r.kind='lab_reports' THEN
  IF public.finance_settings_keys(pub,ARRAY['provider','mode','kind','workspace_id','practice','window','observed_at','patient_identity_json','parent','coverage','returned_report_count','other_report_count','reported_total','items']) IS NOT TRUE
  OR jsonb_typeof(priv->'page_snapshot_json') IS DISTINCT FROM 'string' OR char_length(priv->>'page_snapshot_json')>65536 OR priv->'reader_snapshot_json' IS DISTINCT FROM 'null'::jsonb OR priv->'review_sha256' IS DISTINCT FROM 'null'::jsonb
  OR previous.payload->'public'->'item'->>'handle' IS DISTINCT FROM r.item_handle::text OR previous.payload->'public'->'item'->>'sha256' IS DISTINCT FROM r.request_json->>'item_sha256' THEN RETURN false; END IF;
  raw:=(priv->>'page_snapshot_json')::jsonb;
  IF public.ehr_lab_canonical(raw) IS DISTINCT FROM priv->>'page_snapshot_json' OR public.ehr_lab_reader_valid(raw,r,true) IS NOT TRUE
  OR jsonb_typeof(pub->'items') IS DISTINCT FROM 'array' OR jsonb_array_length(pub->'items')<>jsonb_array_length(priv->'items')
  OR jsonb_array_length(raw->'candidates')<>jsonb_array_length(priv->'items') THEN RETURN false; END IF;
 ELSE
  IF public.finance_settings_keys(pub,ARRAY['provider','mode','kind','workspace_id','practice','window','observed_at','patient_identity_json','parent','item']) IS NOT TRUE
  OR priv->'page_snapshot_json' IS DISTINCT FROM 'null'::jsonb OR jsonb_typeof(priv->'reader_snapshot_json') IS DISTINCT FROM 'string' OR char_length(priv->>'reader_snapshot_json')>65536
  OR jsonb_array_length(priv->'items')<>1 OR public.research_hash(priv->'review_sha256') IS NOT TRUE THEN RETURN false; END IF;
  raw:=(priv->>'reader_snapshot_json')::jsonb; page:=(previous.payload->'private'->>'page_snapshot_json')::jsonb;
  IF public.ehr_lab_canonical(raw) IS DISTINCT FROM priv->>'reader_snapshot_json' OR public.ehr_lab_reader_valid(raw,r,false) IS NOT TRUE
  OR raw->>'parent_candidates_sha256' IS DISTINCT FROM page->>'source_sha256' THEN RETURN false; END IF;
 END IF;
 IF (pub->>'observed_at')::timestamptz IS DISTINCT FROM (raw->>'observed_at')::timestamptz
 OR pub->>'patient_identity_json' IS DISTINCT FROM public.ehr_lab_public_identity(raw->'patient'->>'identity_json') THEN RETURN false; END IF;
 FOR item IN SELECT * FROM jsonb_array_elements(priv->'items') LOOP
  IF public.finance_settings_keys(item,ARRAY['handle','report_id','report_sha256']) IS NOT TRUE OR jsonb_typeof(item->'handle') IS DISTINCT FROM 'string'
  OR item->>'handle' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' OR item->>'handle'=ANY(handles)
  OR jsonb_typeof(item->'report_id') IS DISTINCT FROM 'string' OR item->>'report_id' !~ '^[1-9][0-9]{0,18}$' OR (item->>'report_id')::numeric>9223372036854775807
  OR item->>'report_id'=ANY(ids) OR public.research_hash(item->'report_sha256') IS NOT TRUE THEN RETURN false; END IF;
  handles:=array_append(handles,item->>'handle'); ids:=array_append(ids,item->>'report_id');
  IF r.kind='lab_reports' THEN
   candidate:=raw->'candidates'->pos; metadata:=(candidate->>'metadata_json')::jsonb;
   IF item->>'report_id' IS DISTINCT FROM candidate->>'report_id' OR item->'report_sha256' IS DISTINCT FROM candidate->'report_sha256' THEN RETURN false; END IF;
   metadata:=metadata-'id'-'patient'-'practice'-'physician'-'signed_by'-'vendor';
   expected:=jsonb_build_object('handle',item->'handle','metadata_json',public.ehr_lab_canonical(metadata));
   expected:=expected||jsonb_build_object('sha256',public.google_calendar_json_digest(jsonb_build_object('kind','ehr_elation_lab_candidate_item.v1','item',expected)));
   IF pub->'items'->pos IS DISTINCT FROM expected THEN RETURN false; END IF;
  ELSE
   IF item->>'handle' IS DISTINCT FROM r.item_handle::text OR item->>'report_id' IS DISTINCT FROM raw->>'report_id' OR item->'report_sha256' IS DISTINCT FROM raw->'selected_report_sha256'
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(previous.payload->'private'->'items') old WHERE old=item)
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(previous.payload->'public'->'items') old WHERE old->>'handle'=r.item_handle::text AND old->>'sha256'=r.request_json->>'item_sha256') THEN RETURN false; END IF;
  END IF;
  pos:=pos+1;
 END LOOP;
 IF r.kind='lab_reports' THEN
  RETURN coalesce(pub->'coverage'=raw->'coverage' AND pub->'returned_report_count'=raw->'returned_report_count' AND pub->'other_report_count'=raw->'other_report_count'
   AND pub->'reported_total'=CASE WHEN raw->'reported_total'='null'::jsonb THEN 'null'::jsonb ELSE to_jsonb(raw->>'reported_total') END,false);
 END IF;
 content:=public.ehr_lab_source_text(raw); contentsha:=encode(sha256(convert_to(content,'UTF8')),'hex');
 IF char_length(content)>5000 THEN RETURN false; END IF;
 expected:=jsonb_build_object('handle',item->'handle','report_json',raw->'report_json','changed_since_selection',raw->'changed_since_selection','warnings',public.ehr_lab_warnings(raw),
 'completeness','selected_report_api_fields_only','source_content',content,'content_sha256',contentsha);
 expected:=expected||jsonb_build_object('sha256',public.google_calendar_json_digest(jsonb_build_object('kind','ehr_elation_lab_report_item.v1','item',expected)));
 RETURN coalesce(pub->'item'=expected AND priv->>'review_sha256'=public.ehr_lab_digest(jsonb_build_object('contract','elation-lab-review-snapshot.v1',
 'scope_sha256',public.ehr_lab_scope_digest(raw->'scope',r.binding_digest),'observation_sha256',raw->>'source_sha256','parent_candidates_sha256',raw->>'parent_candidates_sha256',
 'report_id',raw->'report_id','patient_identity_sha256',raw->'patient'->>'identity_sha256','source_content_sha256',contentsha,'warnings',public.ehr_lab_warnings(raw),'completeness','selected_report_api_fields_only')),false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

SOURCES = r"""
CREATE FUNCTION public.ehr_lab_source_valid(eid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.ehr_read_source_reviews v JOIN public.workspace_entries e ON e.id=v.entry_id
 JOIN public.encounter_workspaces w ON w.id=v.workspace_id JOIN public.ehr_read_snapshots z ON z.id=v.snapshot_id JOIN public.ehr_read_requests r ON r.id=z.observation_id
 WHERE e.id=eid AND e.kind='ehr_read_source' AND r.kind='lab_report' AND coalesce(v.command_provider,'elation')='elation' AND v.command_protocol IS NULL AND v.reviewed_visit IS TRUE
 AND (e.workspace_id,e.box_id,e.actor_id,e.revision,e.request_hash,e.idempotency_key)=(v.workspace_id,v.box_id,v.owner_id,v.workspace_revision,v.request_hash,v.idempotency_key)
 AND (w.box_id,w.owner_id,w.patient_link_id)=(v.box_id,v.owner_id,v.patient_link_id)
 AND (r.box_id,r.owner_id,r.workspace_id,r.patient_link_id,z.box_id,z.owner_id)=(v.box_id,v.owner_id,v.workspace_id,v.patient_link_id,v.box_id,v.owner_id)
 AND public.ehr_read_snapshot_valid(z.id) AND v.workspace_revision=v.expected_revision+1 AND v.reviewed_patient_identity AND v.reviewed_exact_snapshot AND v.reviewed_untrusted_source
 AND v.item_handle=r.item_handle AND z.payload->'public'->'item'->>'handle'=v.item_handle::text AND v.item_sha256=z.payload->'public'->'item'->>'sha256' AND v.observation_sha256=z.source_sha256
 AND v.source_sha256=public.google_calendar_json_digest(jsonb_build_object('observation_sha256',v.observation_sha256,'item_handle',v.item_handle,'item_sha256',v.item_sha256))
 AND v.request_hash=public.google_calendar_json_digest(jsonb_build_object('workspace_id',v.workspace_id,'expected_revision',v.expected_revision,'idempotency_key',v.idempotency_key,
 'observation_id',r.id,'observation_sha256',v.observation_sha256,'item_handle',v.item_handle,'item_sha256',v.item_sha256,'reviewed_visit',true,'reviewed_patient_identity',true,'reviewed_exact_snapshot',true,'reviewed_untrusted_source',true)||CASE WHEN v.command_provider IS NULL THEN '{}'::jsonb ELSE jsonb_build_object('provider',v.command_provider) END)
 AND e.content=public.ehr_read_source_content(z.payload->'public') AND e.source_label='Elation: reviewed laboratory report'
 AND v.content_sha256=encode(sha256(convert_to(e.content,'UTF8')),'hex') AND v.valid_until=r.valid_until)
$$;
CREATE OR REPLACE FUNCTION public.ehr_read_source_valid(eid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM public.ehr_read_source_reviews v JOIN public.ehr_read_snapshots z ON z.id=v.snapshot_id JOIN public.ehr_read_requests r ON r.id=z.observation_id WHERE v.entry_id=eid AND r.kind='lab_report') THEN public.ehr_lab_source_valid(eid) ELSE public.ehr_pre_lab_source_valid(eid) END
$$;
"""
