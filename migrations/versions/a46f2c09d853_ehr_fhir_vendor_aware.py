"""Make shared FHIR custody vendor-aware for athena Preview (C5).

Tebra digests and product behavior stay unchanged. athena protocol=fhir +
environment=preview (practice 195900 / Certified FHIR base) is accepted on the
same EhrFhirPatientGrant and source-review path. No route wiring (C8).
"""

from alembic import op

revision = "a46f2c09d853"
down_revision = "cc68d2f1a903"
branch_labels = None
depends_on = None


def definition(signature):
    return op.get_bind().exec_driver_sql("SELECT pg_get_functiondef(%s::regprocedure)", (signature,)).scalar_one()


def changed(sql, pairs):
    for before, after in pairs:
        if sql.count(before) != 1:
            raise RuntimeError("Prior FHIR custody differs from vendor-aware extension: " + before)
        sql = sql.replace(before, after)
    return sql


def upgrade():
    for table, name, sql in CONSTRAINTS:
        op.drop_constraint(name, table)
        op.create_check_constraint(name, table, sql)
    # FHIR connection digest lives in the renamed pre-athena wrapper from u80.
    op.execute(BINDING)
    op.execute(SCOPE)
    op.execute(READER)
    op.execute("DROP FUNCTION IF EXISTS public.ehr_fhir_source_text(jsonb)")
    op.execute(SOURCE_TEXT)
    op.execute("DROP FUNCTION IF EXISTS public.ehr_fhir_reader_valid(jsonb,public.ehr_fhir_patient_grants)")
    op.execute(READER_VALID)
    op.execute(PAYLOAD)
    op.execute(SOURCES)
    op.execute(changed(definition("public.guard_ehr_read_request()"), (
        ("OR NEW.request_json->>'provider' IS DISTINCT FROM 'tebra'",
         "OR NEW.request_json->>'provider' IS DISTINCT FROM b.vendor OR b.vendor NOT IN ('tebra','athena')"),
    )))


def downgrade():
    raise RuntimeError("Retain vendor-aware FHIR custody history")


CONSTRAINTS = (
    ("ehr_read_bindings", "ck_ehr_read_binding_vendor",
     "coalesce((protocol IS NULL AND vendor='elation' AND environment='sandbox' AND customer_id IS NULL AND practice_timezone IS NULL) OR "
     "(protocol IS NULL AND vendor='tebra' AND environment='synthetic' AND customer_id IS NOT NULL AND customer_id ~ '^[1-9][0-9]{0,9}$' "
     "AND customer_id::numeric<=2147483647 AND practice_id::numeric<=2147483647 AND practice_timezone IS NOT NULL) OR "
     "(protocol='fhir' AND vendor='tebra' AND environment='synthetic' AND practice_id IS NULL AND customer_id IS NULL AND practice_timezone IS NULL) OR "
     "(protocol='fhir' AND vendor='athena' AND environment='preview' AND practice_id IS NULL AND customer_id IS NULL AND practice_timezone IS NULL) OR "
     "(protocol='core' AND vendor='athena' AND environment IN ('preview','production') AND customer_id IS NULL AND practice_timezone IS NULL),false)"),
    ("ehr_read_source_reviews", "ck_ehr_review_protocol",
     "coalesce(command_protocol IS NULL OR (command_protocol='fhir' AND command_provider IN ('tebra','athena')) OR "
     "(command_protocol='core' AND command_provider='athena'),false)"),
)

BINDING = r"""
CREATE OR REPLACE FUNCTION public.ehr_pre_athena_binding_digest(b public.ehr_read_bindings) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE
  WHEN b.protocol='fhir' AND b.vendor='tebra' THEN public.google_calendar_json_digest(jsonb_build_object(
   'contract','tebra-fhir-connection-scope.v1','fhir_base','https://fhir.prd.cloud.tebra.com/fhir-request',
   'box_id',b.box_id,'owner_id',b.owner_id,'account_id',b.account_id,'connection_id',b.connection_id,
   'credential_generation',b.credential_generation,'display_label',b.practice_name))
  WHEN b.protocol='fhir' AND b.vendor='athena' THEN public.google_calendar_json_digest(jsonb_build_object(
   'contract','athena-fhir-connection-scope.v1','fhir_base','https://api.preview.platform.athenahealth.com/fhir/r4',
   'ah_practice','Organization/a-1.Practice-195900','practice_id','195900',
   'box_id',b.box_id,'owner_id',b.owner_id,'account_id',b.account_id,'connection_id',b.connection_id,
   'credential_generation',b.credential_generation,'display_label',b.practice_name))
  ELSE public.ehr_pre_fhir_binding_digest(b) END
$$;
"""

SCOPE = r"""
CREATE OR REPLACE FUNCTION public.ehr_fhir_scope_digest(g public.ehr_fhir_patient_grants) RETURNS text LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT CASE b.vendor
  WHEN 'tebra' THEN public.google_calendar_json_digest(public.ehr_fhir_scope(g)||jsonb_build_object(
   'contract','tebra-fhir-patient-scope.v1','fhir_base','https://fhir.prd.cloud.tebra.com/fhir-request'))
  WHEN 'athena' THEN public.google_calendar_json_digest(public.ehr_fhir_scope(g)||jsonb_build_object(
   'contract','athena-fhir-patient-scope.v1','fhir_base','https://api.preview.platform.athenahealth.com/fhir/r4'))
  ELSE NULL END
 FROM public.ehr_read_bindings b WHERE b.id=g.binding_id
$$;
CREATE OR REPLACE FUNCTION public.ehr_fhir_grant_digest(g public.ehr_fhir_patient_grants) RETURNS text LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT public.google_calendar_json_digest(jsonb_build_object(
  'contract',CASE b.vendor WHEN 'athena' THEN 'athena-fhir-patient-grant.v1' ELSE 'tebra-fhir-patient-grant.v1' END,
  'grant_id',g.id,'connection_sha256',b.binding_digest,'workspace_id',g.workspace_id,'patient_link_id',g.patient_link_id,
  'read_scope_sha256',public.ehr_fhir_scope_digest(g),'patient_identity_sha256',g.identity_sha256))
 FROM public.ehr_read_bindings b WHERE b.id=g.binding_id
$$;
CREATE OR REPLACE FUNCTION public.ehr_fhir_grant_current(gid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.ehr_fhir_patient_grants g JOIN public.ehr_read_bindings b ON b.id=g.binding_id
 JOIN public.encounter_workspaces w ON (w.id,w.box_id,w.owner_id,w.patient_link_id)=(g.workspace_id,g.box_id,g.owner_id,g.patient_link_id)
 JOIN public.patient_links p ON (p.id,p.box_id)=(g.patient_link_id,g.box_id)
 WHERE g.id=gid AND g.state='active' AND g.revoked_at IS NULL AND b.protocol='fhir'
 AND ((b.vendor='tebra' AND b.environment='synthetic') OR (b.vendor='athena' AND b.environment='preview'))
 AND public.ehr_read_binding_current(b.id)
 AND p.state='confirmed' AND p.revoked_at IS NULL AND g.grant_digest=public.ehr_fhir_grant_digest(g))
$$;
CREATE OR REPLACE FUNCTION public.guard_ehr_fhir_grant() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE b public.ehr_read_bindings; identity jsonb;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Retain FHIR grant history' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF to_jsonb(NEW)-'state'-'revoked_at' IS DISTINCT FROM to_jsonb(OLD)-'state'-'revoked_at' OR OLD.state<>'active' OR NEW.state<>'revoked' OR NEW.revoked_at IS NULL OR NOT isfinite(NEW.revoked_at) OR NEW.revoked_at<OLD.created_at THEN RAISE EXCEPTION 'FHIR grant immutable' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO b FROM public.ehr_read_bindings WHERE id=NEW.binding_id FOR UPDATE;
 PERFORM 1 FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 IF b.id IS NULL OR b.protocol IS DISTINCT FROM 'fhir'
 OR b.vendor NOT IN ('tebra','athena')
 OR (b.vendor='tebra' AND b.environment IS DISTINCT FROM 'synthetic')
 OR (b.vendor='athena' AND b.environment IS DISTINCT FROM 'preview')
 OR NOT public.ehr_read_binding_current(b.id)
 OR (NEW.box_id,NEW.owner_id,NEW.account_id) IS DISTINCT FROM (b.box_id,b.owner_id,b.account_id)
 OR NEW.state<>'active' OR NEW.revoked_at IS NOT NULL OR NOT isfinite(NEW.created_at)
 OR NOT EXISTS(SELECT 1 FROM public.encounter_workspaces w JOIN public.patient_links p ON (p.id,p.box_id)=(w.patient_link_id,w.box_id) WHERE (w.id,w.box_id,w.owner_id,w.patient_link_id)=(NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.patient_link_id) AND p.state='confirmed' AND p.revoked_at IS NULL)
 OR octet_length(NEW.identity_json)>16384 OR NOT public.ehr_fhir_json(NEW.identity_json,'object')
 THEN RAISE EXCEPTION 'FHIR grant authority invalid' USING ERRCODE='23514'; END IF;
 identity:=NEW.identity_json::jsonb;
 IF identity->>'resourceType' IS DISTINCT FROM 'Patient' OR identity->>'id' IS DISTINCT FROM NEW.fhir_patient_id
 OR identity-ARRAY['resourceType','id','name','birthDate','gender','identifier','active','deceasedBoolean','deceasedDateTime','link','managingOrganization']<>'{}'::jsonb
 OR public.ehr_fhir_identity(identity) IS NOT TRUE
 OR NEW.identity_sha256 IS DISTINCT FROM encode(sha256(convert_to(NEW.identity_json,'UTF8')),'hex')
 OR NEW.grant_digest IS DISTINCT FROM public.ehr_fhir_grant_digest(NEW)
 THEN RAISE EXCEPTION 'FHIR grant identity invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

SOURCE_TEXT = r"""
CREATE OR REPLACE FUNCTION public.ehr_fhir_source_text(v jsonb, vendor text) RETURNS text LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE result text; row jsonb; position integer:=0; title text; label text;
BEGIN
 label:=CASE vendor WHEN 'athena' THEN 'Athena' ELSE 'Tebra' END;
 result:=label||' medication records (bounded synthetic snapshot)'||chr(10)||'Patient identity: '||(v->'patient'->>'identity_json')||chr(10)||'Observed: '||(v->>'observed_at')||chr(10)
 ||'Coverage: '||CASE WHEN v->>'coverage'='more_rows_available' THEN 'More rows are available; only this page was read.' ELSE 'Returned page only; completeness is not established.' END||chr(10)
 ||'Returned records: '||jsonb_array_length(v->'rows')||'; reported total: '||coalesce(v->>'reported_total','not provided')||'.'||chr(10)
 ||'Unlisted optional fields were not provided. Dates keep their recorded precision; no timezone or current use is inferred.'||chr(10)
 ||'JSON sections preserve codes, qualifiers and decoded instruction/string contents; request details do not establish dispensing.';
 IF jsonb_array_length(v->'warnings')>0 THEN result:=result||chr(10)||'Provider warning codes: '||public.clinical_note_ascii_canonical(v->'warnings'); END IF;
 FOR row IN SELECT * FROM jsonb_array_elements(v->'rows') LOOP
  position:=position+1;
  title:=CASE WHEN row->'medication_name'='null'::jsonb THEN 'No unambiguous recorded medication name' ELSE public.vendor_public_canonical(row->'medication_name') END;
  result:=result||chr(10)||chr(10)||'Record '||position||': '||title||chr(10)||'Record ID: '||(row->>'record_id')||chr(10)
   ||'Recorded status: '||(row->>'status')||chr(10)||'Recorded intent: '||(row->>'intent')||chr(10)||'Authored date/time: '||(row->>'authored_on')||chr(10)
   ||'Do-not-perform flag: '||coalesce(row->>'do_not_perform','not provided')||chr(10)||'Reported information: '||coalesce(row->>'reported_json','not provided')||chr(10)
   ||'Original medication choice: '||(row->>'request_medication_json')||chr(10)||'Resolved medication: '||(row->>'medication_json')||chr(10)
   ||'Dose instructions: '||coalesce(row->>'dosage_instructions_json','not provided')||chr(10)||'Other recorded request details: '||(row->>'context_json');
 END LOOP;
 IF position=0 THEN result:=result||chr(10)||chr(10)||'No medication records returned; this does not establish absence of medications.'; END IF;
 RETURN result||chr(10)||chr(10)||'These are recorded medication requests/history, not a reconciled current list or proof of transmission, dispensing or use.'||chr(10)
  ||'This snapshot does not prescribe or update the EHR. Preparing it does not establish human approval or source admission.';
END $$;
"""

READER = r"""
CREATE OR REPLACE FUNCTION public.ehr_fhir_medication_base(vendor text) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE vendor
  WHEN 'athena' THEN 'https://api.preview.platform.athenahealth.com/fhir/r4'
  ELSE 'https://fhir.prd.cloud.tebra.com/fhir-request' END
$$;
CREATE OR REPLACE FUNCTION public.ehr_fhir_history_contract(vendor text) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE vendor WHEN 'athena' THEN 'athena-fhir-medication-history.v1' ELSE 'tebra-fhir-medication-history.v1' END
$$;
CREATE OR REPLACE FUNCTION public.ehr_fhir_review_contract(vendor text) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE vendor WHEN 'athena' THEN 'athena-fhir-review-snapshot.v1' ELSE 'tebra-fhir-review-snapshot.v1' END
$$;
CREATE OR REPLACE FUNCTION public.ehr_fhir_medications_item_kind(vendor text) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE vendor WHEN 'athena' THEN 'ehr_athena_fhir_medications_item.v1' ELSE 'ehr_tebra_fhir_medications_item.v1' END
$$;
"""

PAYLOAD = r"""
CREATE OR REPLACE FUNCTION public.ehr_fhir_payload_valid(payload jsonb,r public.ehr_read_requests) RETURNS boolean LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE pub jsonb:=payload->'public'; priv jsonb:=payload->'private'; b public.ehr_read_bindings; g public.ehr_fhir_patient_grants;
 parent public.ehr_read_snapshots; prior public.ehr_read_requests; item jsonb; shown jsonb; raw jsonb; expected jsonb; content text; contentsha text;
 position integer:=0; handles text[]:=ARRAY[]::text[]; grants text[]:=ARRAY[]::text[]; med_prefix text; history_contract text; review_contract text; item_kind text;
BEGIN
 SELECT * INTO b FROM public.ehr_read_bindings WHERE id=r.binding_id;
 IF b.protocol IS DISTINCT FROM 'fhir' OR b.vendor NOT IN ('tebra','athena') OR r.transport<>'mock' OR r.kind NOT IN ('fhir_patients','fhir_medications')
 OR NOT public.finance_settings_keys(payload,ARRAY['public','private'])
 OR NOT public.finance_settings_keys(priv,ARRAY['protocol','transport','binding_sha256','request_sha256','workspace_id','patient_link_id','items','reader_snapshot_json','review_sha256'])
 OR priv->>'protocol' IS DISTINCT FROM 'fhir' OR priv->>'transport' IS DISTINCT FROM 'mock'
 OR priv->>'binding_sha256' IS DISTINCT FROM r.binding_digest OR priv->>'request_sha256' IS DISTINCT FROM r.request_hash
 OR priv->>'workspace_id' IS DISTINCT FROM r.workspace_id::text OR priv->>'patient_link_id' IS DISTINCT FROM r.patient_link_id::text
 OR pub->>'workspace_id' IS DISTINCT FROM r.workspace_id::text OR pub->>'display_label' IS DISTINCT FROM b.practice_name
 OR pub->>'provider' IS DISTINCT FROM b.vendor OR pub->>'protocol' IS DISTINCT FROM 'fhir' OR pub->>'mode' IS DISTINCT FROM 'synthetic'
 OR pub->>'kind' IS DISTINCT FROM r.kind OR NOT public.google_message_aware_time(pub->'observed_at')
 OR jsonb_typeof(priv->'items') IS DISTINCT FROM 'array' OR jsonb_array_length(priv->'items')>25
 THEN RETURN false; END IF;
 med_prefix:=public.ehr_fhir_medication_base(b.vendor)||'/Medication/';
 history_contract:=public.ehr_fhir_history_contract(b.vendor);
 review_contract:=public.ehr_fhir_review_contract(b.vendor);
 item_kind:=public.ehr_fhir_medications_item_kind(b.vendor);
 FOR item IN SELECT * FROM jsonb_array_elements(priv->'items') LOOP
  SELECT * INTO g FROM public.ehr_fhir_patient_grants WHERE id::text=item->>'grant_id';
  IF NOT public.finance_settings_keys(item,ARRAY['handle','grant_id','grant_sha256','patient_identity_json']) OR g.id IS NULL
   OR jsonb_typeof(item->'handle') IS DISTINCT FROM 'string' OR item->>'handle' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR item->>'handle'=ANY(handles) OR item->>'grant_id'=ANY(grants)
   OR (g.binding_id,g.box_id,g.owner_id,g.account_id,g.workspace_id,g.patient_link_id) IS DISTINCT FROM (r.binding_id,r.box_id,r.owner_id,r.account_id,r.workspace_id,r.patient_link_id)
   OR item->>'grant_sha256' IS DISTINCT FROM g.grant_digest OR g.grant_digest IS DISTINCT FROM public.ehr_fhir_grant_digest(g)
   OR item->>'patient_identity_json' IS DISTINCT FROM g.identity_json THEN RETURN false; END IF;
  handles:=array_append(handles,item->>'handle'); grants:=array_append(grants,item->>'grant_id');
  IF r.kind='fhir_patients' THEN
   shown:=pub->'items'->position; expected:=jsonb_build_object('handle',item->'handle','patient_identity_json',g.identity_json);
   expected:=expected||jsonb_build_object('sha256',public.google_calendar_json_digest(jsonb_build_object('kind','ehr_fhir_patient_item.v1','item',expected)));
   IF shown IS DISTINCT FROM expected THEN RETURN false; END IF;
  END IF;
  position:=position+1;
 END LOOP;
 IF r.kind='fhir_patients' THEN
  RETURN coalesce(public.finance_settings_keys(pub,ARRAY['provider','protocol','mode','kind','workspace_id','display_label','observed_at','coverage','items'])
   AND pub->>'coverage'='authorized_candidates_only' AND jsonb_typeof(pub->'items')='array' AND jsonb_array_length(pub->'items')=position
   AND priv->'reader_snapshot_json'='null'::jsonb AND priv->'review_sha256'='null'::jsonb,false);
 END IF;
 IF position<>1 OR NOT public.finance_settings_keys(pub,ARRAY['provider','protocol','mode','kind','workspace_id','display_label','observed_at','parent','item'])
 OR public.research_hash(priv->'review_sha256') IS NOT TRUE
 OR g.id IS DISTINCT FROM r.fhir_grant_id OR item->>'handle' IS DISTINCT FROM r.item_handle::text
 OR jsonb_typeof(priv->'reader_snapshot_json') IS DISTINCT FROM 'string' OR char_length(priv->>'reader_snapshot_json')>65536 THEN RETURN false; END IF;
 raw:=(priv->>'reader_snapshot_json')::jsonb;
 IF priv->>'reader_snapshot_json' IS DISTINCT FROM public.clinical_note_ascii_canonical(raw) OR public.ehr_fhir_reader_valid(raw,g,b.vendor) IS NOT TRUE THEN RETURN false; END IF;
 SELECT * INTO parent FROM public.ehr_read_snapshots WHERE id=r.parent_snapshot_id;
 SELECT * INTO prior FROM public.ehr_read_requests WHERE id=parent.observation_id;
 IF prior.kind IS DISTINCT FROM 'fhir_patients' OR NOT public.ehr_read_snapshot_valid(parent.id)
 OR (prior.binding_id,prior.workspace_id,prior.patient_link_id) IS DISTINCT FROM (r.binding_id,r.workspace_id,r.patient_link_id)
 OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent.payload->'private'->'items') old WHERE old=item)
 OR pub->'parent' IS DISTINCT FROM jsonb_build_object('observation_id',prior.id,'source_sha256',parent.source_sha256,'item_sha256',r.request_json->>'item_sha256')
 OR r.request_json->>'observation_id' IS DISTINCT FROM prior.id::text OR r.request_json->>'observation_sha256' IS DISTINCT FROM parent.source_sha256
 OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent.payload->'public'->'items') old WHERE old->>'handle'=r.item_handle::text AND old->>'sha256'=r.request_json->>'item_sha256')
 OR pub->>'observed_at' IS DISTINCT FROM replace(raw->>'observed_at','+00:00','Z')
 THEN RETURN false; END IF;
 content:=public.ehr_fhir_source_text(raw,b.vendor); contentsha:=encode(sha256(convert_to(content,'UTF8')),'hex');
 IF content IS NULL OR char_length(content)>5000 THEN RETURN false; END IF;
 expected:=jsonb_build_object('handle',item->'handle','patient_identity_json',g.identity_json,'coverage',raw->'coverage','reported_total',raw->'reported_total','warnings',raw->'warnings',
 'records',(SELECT coalesce(jsonb_agg(row-'record_id'-'patient_id' ORDER BY ordinal),'[]'::jsonb) FROM jsonb_array_elements(raw->'rows') WITH ORDINALITY rows(row,ordinal)),
 'source_content',content,'content_sha256',contentsha);
 expected:=expected||jsonb_build_object('sha256',public.google_calendar_json_digest(jsonb_build_object('kind',item_kind,'item',expected)));
 RETURN coalesce(pub->'item'=expected AND priv->>'review_sha256'=public.google_calendar_json_digest(jsonb_build_object('contract',review_contract,'scope_sha256',public.ehr_fhir_scope_digest(g),
 'observation_sha256',raw->>'source_sha256','patient_identity_sha256',g.identity_sha256,'source_content_sha256',contentsha,'completeness','bounded_recorded_history')),false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

# Reader validation needs the vendor for absolute Medication URLs and history contract.
# Replace ehr_fhir_reader_valid with a vendor-aware signature.
READER_VALID = r"""
CREATE OR REPLACE FUNCTION public.ehr_fhir_reader_valid(v jsonb,g public.ehr_fhir_patient_grants, vendor text) RETURNS boolean LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE row jsonb; choice jsonb; medication jsonb; context jsonb; reported jsonb; dosage jsonb; instruction jsonb; entry jsonb; key text; reference text; identifier text; ids text[]:=ARRAY[]::text[];
 med_prefix text:=public.ehr_fhir_medication_base(vendor)||'/Medication/'; history_contract text:=public.ehr_fhir_history_contract(vendor);
BEGIN
 IF NOT public.finance_settings_keys(v,ARRAY['scope','patient','observed_at','rows','coverage','reported_total','warnings','source_sha256','provider_sources'])
 OR public.research_hash(v->'source_sha256') IS NOT TRUE
 OR v->'scope' IS DISTINCT FROM public.ehr_fhir_scope(g)
 OR v->'patient' IS DISTINCT FROM jsonb_build_object('patient_id',g.fhir_patient_id,'identity_json',g.identity_json,'identity_sha256',g.identity_sha256)
 OR NOT public.google_message_aware_time(v->'observed_at')
 OR coalesce(v->>'coverage','') NOT IN ('returned_page_only','more_rows_available')
 OR jsonb_typeof(v->'rows') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'rows')>25
 OR (v->'reported_total'<>'null'::jsonb AND (jsonb_typeof(v->'reported_total')<>'number' OR v->>'reported_total' !~ '^[0-9]+$' OR (v->>'reported_total')::numeric NOT BETWEEN jsonb_array_length(v->'rows') AND 2147483647))
 OR jsonb_typeof(v->'warnings') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'warnings')>1500
 OR jsonb_typeof(v->'provider_sources') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'provider_sources') NOT BETWEEN 2 AND 27
 THEN RETURN false; END IF;
 FOR entry IN SELECT * FROM jsonb_array_elements(v->'warnings') LOOP IF NOT public.ehr_read_text(entry,64) THEN RETURN false; END IF; END LOOP;
 FOR entry IN SELECT * FROM jsonb_array_elements(v->'provider_sources') LOOP IF NOT public.research_hash(entry) THEN RETURN false; END IF; END LOOP;
 FOR row IN SELECT * FROM jsonb_array_elements(v->'rows') LOOP
  IF NOT public.finance_settings_keys(row,ARRAY['record_id','patient_id','status','intent','authored_on','do_not_perform','reported_json','request_medication_json','medication_name','medication_json','dosage_instructions_json','context_json'])
   OR NOT public.ehr_fhir_id(row->'record_id') OR row->>'record_id'=ANY(ids) OR row->>'patient_id' IS DISTINCT FROM g.fhir_patient_id
   OR coalesce(row->>'status','') NOT IN ('active','on-hold','cancelled','completed','entered-in-error','stopped','draft','unknown')
   OR coalesce(row->>'intent','') NOT IN ('order','plan') OR NOT public.ehr_fhir_date(row->'authored_on',true)
   OR (row->'do_not_perform'<>'null'::jsonb AND jsonb_typeof(row->'do_not_perform')<>'boolean')
   OR NOT public.ehr_fhir_json(row->>'request_medication_json','object') OR NOT public.ehr_fhir_json(row->>'medication_json','object') OR NOT public.ehr_fhir_json(row->>'context_json','object')
  THEN RETURN false; END IF;
  ids:=array_append(ids,row->>'record_id');
  choice:=(row->>'request_medication_json')::jsonb; medication:=(row->>'medication_json')::jsonb; context:=(row->>'context_json')::jsonb;
  IF context-ARRAY['statusReason','requester','encounter','category','note','reasonCode','reasonReference','courseOfTherapyType','dispenseRequest','substitution','priorPrescription','basedOn','groupIdentifier','insurance','supportingInformation','detectedIssue','eventHistory']<>'{}'::jsonb OR NOT public.ehr_fhir_concept(medication->'code')
   OR row->'medication_name' IS DISTINCT FROM coalesce(to_jsonb(public.ehr_fhir_concept_name(medication->'code')),'null'::jsonb)
  THEN RETURN false; END IF;
  IF public.finance_settings_keys(choice,ARRAY['medicationCodeableConcept']) THEN
   IF medication IS DISTINCT FROM jsonb_build_object('code',choice->'medicationCodeableConcept') THEN RETURN false; END IF;
  ELSIF public.finance_settings_keys(choice,ARRAY['medicationReference']) THEN
   IF jsonb_typeof(choice->'medicationReference')<>'object' OR NOT public.ehr_read_text(choice->'medicationReference'->'reference',512) THEN RETURN false; END IF;
   reference:=choice->'medicationReference'->>'reference';
   IF left(reference,1)='#' THEN identifier:=substr(reference,2);
   ELSIF left(reference,11)='Medication/' THEN identifier:=substr(reference,12);
   ELSIF left(reference,char_length(med_prefix))=med_prefix THEN identifier:=substr(reference,char_length(med_prefix)+1);
   ELSE RETURN false; END IF;
   IF NOT public.ehr_fhir_id(to_jsonb(identifier)) OR medication->>'resourceType' IS DISTINCT FROM 'Medication' OR medication->>'id' IS DISTINCT FROM identifier THEN RETURN false; END IF;
  ELSE RETURN false; END IF;
  IF row->'reported_json'<>'null'::jsonb THEN
   IF NOT public.ehr_fhir_json(row->>'reported_json','object') THEN RETURN false; END IF;
   reported:=(row->>'reported_json')::jsonb;
   IF public.finance_settings_keys(reported,ARRAY['reportedBoolean']) THEN IF jsonb_typeof(reported->'reportedBoolean')<>'boolean' THEN RETURN false; END IF;
   ELSIF public.finance_settings_keys(reported,ARRAY['reportedReference']) THEN IF jsonb_typeof(reported->'reportedReference')<>'object' THEN RETURN false; END IF;
   ELSE RETURN false; END IF;
  END IF;
  IF row->'dosage_instructions_json'<>'null'::jsonb THEN
   IF NOT public.ehr_fhir_json(row->>'dosage_instructions_json','array') THEN RETURN false; END IF;
   dosage:=(row->>'dosage_instructions_json')::jsonb;
   IF jsonb_array_length(dosage)>20 THEN RETURN false; END IF;
   FOR instruction IN SELECT * FROM jsonb_array_elements(dosage) LOOP
    IF jsonb_typeof(instruction)<>'object' OR instruction ? 'sequence' AND (jsonb_typeof(instruction->'sequence')<>'number' OR instruction->>'sequence' !~ '^[0-9]+$')
     OR instruction ? 'asNeededBoolean' AND jsonb_typeof(instruction->'asNeededBoolean')<>'boolean'
     OR instruction ? 'asNeededBoolean' AND instruction ? 'asNeededCodeableConcept'
    THEN RETURN false; END IF;
    FOREACH key IN ARRAY ARRAY['text','patientInstruction'] LOOP IF instruction ? key AND NOT public.ehr_medication_text(instruction->key,4000,true) THEN RETURN false; END IF; END LOOP;
    FOREACH key IN ARRAY ARRAY['route','site','method','asNeededCodeableConcept'] LOOP IF instruction ? key AND NOT public.ehr_fhir_concept(instruction->key) THEN RETURN false; END IF; END LOOP;
    IF instruction ? 'timing' AND jsonb_typeof(instruction->'timing')<>'object' THEN RETURN false; END IF;
    IF jsonb_typeof(coalesce(instruction->'additionalInstruction','[]'::jsonb))<>'array' OR jsonb_array_length(coalesce(instruction->'additionalInstruction','[]'::jsonb))>20
     OR jsonb_typeof(coalesce(instruction->'doseAndRate','[]'::jsonb))<>'array' OR jsonb_array_length(coalesce(instruction->'doseAndRate','[]'::jsonb))>20 THEN RETURN false; END IF;
    FOR entry IN SELECT * FROM jsonb_array_elements(coalesce(instruction->'additionalInstruction','[]'::jsonb)) LOOP IF NOT public.ehr_fhir_concept(entry) THEN RETURN false; END IF; END LOOP;
    FOR entry IN SELECT * FROM jsonb_array_elements(coalesce(instruction->'doseAndRate','[]'::jsonb)) LOOP IF jsonb_typeof(entry)<>'object' THEN RETURN false; END IF; END LOOP;
   END LOOP;
  END IF;
 END LOOP;
 RETURN coalesce(v->>'source_sha256'=public.google_calendar_json_digest((v-'scope'-'source_sha256')||jsonb_build_object('contract',history_contract,'scope_sha256',public.ehr_fhir_scope_digest(g))),false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

SOURCES = r"""
CREATE OR REPLACE FUNCTION public.ehr_fhir_source_valid(eid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.ehr_read_source_reviews v JOIN public.workspace_entries e ON e.id=v.entry_id
 JOIN public.encounter_workspaces w ON w.id=v.workspace_id JOIN public.ehr_read_snapshots z ON z.id=v.snapshot_id JOIN public.ehr_read_requests r ON r.id=z.observation_id
 JOIN public.ehr_read_bindings b ON b.id=r.binding_id
 WHERE e.id=eid AND e.kind='ehr_read_source' AND r.kind='fhir_medications'
 AND v.command_provider=b.vendor AND b.vendor IN ('tebra','athena') AND v.command_protocol='fhir' AND v.reviewed_visit IS NULL
 AND (e.workspace_id,e.box_id,e.actor_id,e.revision,e.request_hash,e.idempotency_key)=(v.workspace_id,v.box_id,v.owner_id,v.workspace_revision,v.request_hash,v.idempotency_key)
 AND (w.box_id,w.owner_id,w.patient_link_id)=(v.box_id,v.owner_id,v.patient_link_id)
 AND (r.box_id,r.owner_id,r.workspace_id,r.patient_link_id,z.box_id,z.owner_id)=(v.box_id,v.owner_id,v.workspace_id,v.patient_link_id,v.box_id,v.owner_id)
 AND public.ehr_read_snapshot_valid(z.id) AND v.workspace_revision=v.expected_revision+1 AND v.reviewed_patient_identity AND v.reviewed_exact_snapshot AND v.reviewed_untrusted_source
 AND v.item_handle=r.item_handle AND z.payload->'public'->'item'->>'handle'=v.item_handle::text AND v.item_sha256=z.payload->'public'->'item'->>'sha256' AND v.observation_sha256=z.source_sha256
 AND v.source_sha256=public.google_calendar_json_digest(jsonb_build_object('observation_sha256',v.observation_sha256,'item_handle',v.item_handle,'item_sha256',v.item_sha256))
 AND v.request_hash=public.google_calendar_json_digest(jsonb_build_object('provider',b.vendor,'protocol','fhir','workspace_id',v.workspace_id,'expected_revision',v.expected_revision,'idempotency_key',v.idempotency_key,
 'observation_id',r.id,'observation_sha256',v.observation_sha256,'item_handle',v.item_handle,'item_sha256',v.item_sha256,'reviewed_patient_identity',true,'reviewed_exact_snapshot',true,'reviewed_untrusted_source',true))
 AND e.content=public.ehr_read_source_content(z.payload->'public')
 AND e.source_label=CASE b.vendor WHEN 'athena' THEN 'Athena: reviewed medication records' ELSE 'Tebra: reviewed medication records' END
 AND v.content_sha256=encode(sha256(convert_to(e.content,'UTF8')),'hex') AND v.valid_until=r.valid_until)
$$;
"""
