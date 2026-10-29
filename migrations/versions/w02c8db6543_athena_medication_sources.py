"""Independent Athena medication authority and exact numeric source custody."""
from alembic import op

revision = "w02c8db6543"
down_revision = "v91b7ca5432"
branch_labels = None
depends_on = None


def definition(signature):
    return op.get_bind().exec_driver_sql("SELECT pg_get_functiondef(%s::regprocedure)", (signature,)).scalar_one()


def changed(sql, pairs):
    for before, after in pairs:
        if sql.count(before) != 1:
            raise RuntimeError("Prior EHR guard differs from medication extension: " + before)
        sql = sql.replace(before, after)
    return sql


def upgrade():
    op.execute("ALTER TABLE ehr_read_bindings ADD COLUMN clinical_scope varchar(16)")
    op.execute(TABLES)
    op.execute("ALTER TABLE ehr_read_requests ADD COLUMN clinical_scope varchar(16), ADD COLUMN athena_medication_grant_id uuid")
    op.execute("ALTER TABLE ehr_read_source_reviews ADD COLUMN command_clinical_scope varchar(16)")
    op.execute("ALTER TABLE ehr_read_requests ADD CONSTRAINT fk_ehr_read_athena_med_grant FOREIGN KEY(athena_medication_grant_id,box_id,owner_id,workspace_id,patient_link_id) REFERENCES ehr_athena_medication_patient_grants(id,box_id,owner_id,workspace_id,patient_link_id)")
    for name, table in (("ck_ehr_read_binding_clinical_scope", "ehr_read_bindings"), ("ck_ehr_read_request_kind", "ehr_read_requests"), ("ck_ehr_read_request_window", "ehr_read_requests"), ("ck_ehr_review_clinical_scope", "ehr_read_source_reviews")):
        if name in ("ck_ehr_read_request_kind", "ck_ehr_read_request_window"):
            op.drop_constraint(name, table)
        op.create_check_constraint(name, table, CHECKS[name])
    for signature in ("public.ehr_read_binding_digest(public.ehr_read_bindings)", "public.ehr_read_request_current(uuid)", "public.ehr_read_payload_valid(jsonb,public.ehr_read_requests)", "public.ehr_read_source_content(jsonb)", "public.ehr_read_source_valid(uuid)"):
        name = signature.split("(")[0]
        op.execute(definition(signature).replace(name + "(", name.replace("ehr_read_", "ehr_pre_athena_med_") + "(", 1))
    op.execute(AUTHORITY)
    op.execute(GRANTS)
    op.execute(CURRENT)
    op.execute(changed(definition("public.guard_ehr_athena_grant()"), (("IF b.id IS NULL", "IF b.clinical_scope IS NOT NULL OR b.id IS NULL"),)))
    op.execute(changed(definition("public.guard_ehr_read_request()"), ((" IF b.protocol='core' THEN", REQUEST + " IF b.protocol='core' THEN"),)))
    op.execute(CLINICAL_CODEC)
    op.execute(CLINICAL)
    op.execute(PAYLOAD)
    op.execute(SOURCES)
    op.execute(changed(definition("public.guard_ehr_read_snapshot()"), (
        ("IF r.kind IN ('core_patients','core_allergies') THEN", "IF r.kind IN ('core_patients','core_allergies') AND r.clinical_scope IS NULL THEN"),
        (" RETURN NEW;", SNAPSHOT_FENCE + " RETURN NEW;")
    )))
    op.execute(changed(definition("public.guard_ehr_read_review()"), (
        ("r.kind NOT IN ('verify','problems','medications','fhir_medications','core_allergies','lab_report')", "r.kind NOT IN ('verify','problems','medications','fhir_medications','core_allergies','lab_report','core_medications')"),
        ("r.kind IN ('fhir_medications','core_allergies','lab_report') AND", "r.kind IN ('fhir_medications','core_allergies','lab_report','core_medications') AND"),
        (" IF w.id IS NULL", " PERFORM 1 FROM public.ehr_athena_medication_patient_grants WHERE id=r.athena_medication_grant_id FOR SHARE;\n IF NEW.command_clinical_scope IS DISTINCT FROM r.clinical_scope THEN RAISE EXCEPTION 'Medication review scope mismatch' USING ERRCODE='23514'; END IF;\n IF w.id IS NULL")
    )))


def downgrade():
    raise RuntimeError("Retain medication grants and reviewed source history")


AUTHORITY = r"""
CREATE OR REPLACE FUNCTION public.ehr_read_binding_digest(b public.ehr_read_bindings) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN b.clinical_scope IS NULL THEN public.ehr_pre_athena_med_binding_digest(b)
 WHEN b.clinical_scope='medications' AND b.protocol='core' AND b.vendor='athena' THEN public.google_calendar_json_digest(jsonb_build_object(
 'contract','athena-medication-connection-scope.v1','clinical_scope','medications','origin',public.ehr_athena_origin(b.environment),
 'box_id',b.box_id,'owner_id',b.owner_id,'account_id',b.account_id,'connection_id',b.connection_id,'credential_generation',b.credential_generation,
 'practice_id',b.practice_id,'practice_label',b.practice_name,'environment',b.environment)) ELSE NULL END
$$;
CREATE FUNCTION public.ehr_athena_med_scope(g public.ehr_athena_medication_patient_grants) RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('box_id',g.box_id,'owner_id',g.owner_id,'account_id',g.account_id,'connection_id',b.connection_id,'credential_generation',b.credential_generation,
 'workspace_id',g.workspace_id,'patient_link_id',g.patient_link_id,'practice_id',b.practice_id,'department_id',g.department_id,'patient_id',g.patient_id,
 'practice_label',b.practice_name,'department_label',g.department_label,'authorization_sha256',g.authorization_sha256,'environment',b.environment,
 'medication_type','ACTIVE','includes_pending',true,'includes_ndc',true,'includes_rxnorm',true) FROM public.ehr_read_bindings b WHERE b.id=g.binding_id
$$;
CREATE FUNCTION public.ehr_athena_med_scope_digest(g public.ehr_athena_medication_patient_grants) RETURNS text LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT public.google_calendar_json_digest(public.ehr_athena_med_scope(g)||jsonb_build_object('contract','athena-medication-patient-scope.v1','origin',public.ehr_athena_origin(b.environment)))
 FROM public.ehr_read_bindings b WHERE b.id=g.binding_id
$$;
"""

CURRENT = r"""
CREATE OR REPLACE FUNCTION public.ehr_read_request_current(rid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT coalesce((SELECT CASE WHEN r.clinical_scope IS NULL THEN public.ehr_pre_athena_med_request_current(r.id)
 WHEN r.clinical_scope='medications' THEN EXISTS(
 SELECT 1 FROM public.ehr_read_bindings b JOIN public.encounter_workspaces w ON (w.id,w.box_id,w.owner_id,w.patient_link_id)=(r.workspace_id,r.box_id,r.owner_id,r.patient_link_id)
 JOIN public.patient_links link ON (link.id,link.box_id)=(r.patient_link_id,r.box_id)
 LEFT JOIN public.ehr_read_snapshots z ON z.id=r.parent_snapshot_id LEFT JOIN public.ehr_read_requests p ON p.id=z.observation_id
 WHERE b.id=r.binding_id AND b.protocol='core' AND b.vendor='athena' AND b.clinical_scope='medications' AND public.ehr_read_binding_current(b.id)
 AND r.kind IN ('core_patients','core_medications') AND r.transport='mock' AND r.valid_until>clock_timestamp()
 AND (r.box_id,r.owner_id,r.account_id,r.connection_id,r.credential_generation,r.binding_digest)=(b.box_id,b.owner_id,b.account_id,b.connection_id,b.credential_generation,b.binding_digest)
 AND link.state='confirmed' AND link.revoked_at IS NULL
 AND NOT EXISTS(SELECT 1 FROM public.ehr_read_requests newer WHERE newer.binding_id=r.binding_id AND newer.workspace_id=r.workspace_id AND newer.kind='core_patients' AND newer.ordinal>CASE WHEN r.kind='core_patients' THEN r.ordinal ELSE p.ordinal END)
 AND (r.kind='core_patients' OR (p.kind='core_patients' AND p.clinical_scope='medications' AND (p.binding_id,p.workspace_id,p.patient_link_id)=(r.binding_id,r.workspace_id,r.patient_link_id)
 AND p.valid_until>=r.valid_until AND public.ehr_athena_med_grant_current(r.athena_medication_grant_id)))) ELSE false END
 FROM public.ehr_read_requests r WHERE r.id=rid),false)
$$;
"""

SNAPSHOT_FENCE = r"""
 IF r.clinical_scope='medications' THEN
  PERFORM 1 FROM public.ehr_athena_medication_patient_grants WHERE id::text IN (SELECT item->>'grant_id' FROM jsonb_array_elements(NEW.payload->'private'->'items') item) FOR SHARE;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.payload->'private'->'items') item WHERE public.ehr_athena_med_grant_current((item->>'grant_id')::uuid) IS NOT TRUE) THEN
   RAISE EXCEPTION 'Medication snapshot grant changed' USING ERRCODE='23514';
  END IF;
 END IF;
"""

CLINICAL_CODEC = r"""
CREATE FUNCTION public.ehr_athena_med_json_nodes(v json,depth integer DEFAULT 0) RETURNS integer
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog AS $$
DECLARE kind text:=json_typeof(v); result integer:=1; row record; child json; n integer; token text; decoded text;
BEGIN
 IF depth>16 THEN RAISE EXCEPTION 'Medication JSON depth'; END IF;
 IF kind='object' THEN
  SELECT count(*),count(DISTINCT key COLLATE "C") INTO n,result FROM json_each(v);
  IF n>64 OR result<>n THEN RAISE EXCEPTION 'Medication JSON object'; END IF;
  result:=1;
  FOR row IN SELECT * FROM json_each(v) LOOP
   IF char_length(row.key)>128 THEN RAISE EXCEPTION 'Medication JSON key'; END IF;
   result:=result+public.ehr_athena_med_json_nodes(row.value,depth+1);
   IF result>4096 THEN RAISE EXCEPTION 'Medication JSON nodes'; END IF;
  END LOOP;
 ELSIF kind='array' THEN
  IF json_array_length(v)>256 THEN RAISE EXCEPTION 'Medication JSON array'; END IF;
  FOR child IN SELECT * FROM json_array_elements(v) LOOP
   result:=result+public.ehr_athena_med_json_nodes(child,depth+1);
   IF result>4096 THEN RAISE EXCEPTION 'Medication JSON nodes'; END IF;
  END LOOP;
 ELSIF kind='number' THEN
  token:=btrim(v::text,E' \t\r\n');
  IF char_length(token)>128 OR token !~ '^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$' THEN RAISE EXCEPTION 'Medication JSON number'; END IF;
 ELSIF kind='string' THEN
  decoded:=v#>>'{}';
  IF char_length(decoded)>4096 THEN RAISE EXCEPTION 'Medication JSON string'; END IF;
 ELSIF kind NOT IN ('boolean','null') THEN RAISE EXCEPTION 'Medication JSON kind';
 END IF;
 -- PostgreSQL text extraction refuses NUL and unpaired surrogate escapes.
 -- Escaped non-NUL controls remain intact; no clinical string filter strips them.
 RETURN result;
END $$;
CREATE FUNCTION public.ehr_athena_med_canonical(v json,depth integer DEFAULT 0) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog AS $$
DECLARE kind text:=json_typeof(v); result text;
BEGIN
 IF depth=0 THEN PERFORM public.ehr_athena_med_json_nodes(v); END IF;
 IF depth>16 THEN RAISE EXCEPTION 'Medication JSON depth'; END IF;
 IF kind='object' THEN
  SELECT '{'||coalesce(string_agg(public.clinical_note_ascii_canonical(to_jsonb(key))||':'||public.ehr_athena_med_canonical(value,depth+1),',' ORDER BY key COLLATE "C"),'')||'}'
  INTO result FROM json_each(v);
 ELSIF kind='array' THEN
  SELECT '['||coalesce(string_agg(public.ehr_athena_med_canonical(value,depth+1),',' ORDER BY ordinal),'')||']'
  INTO result FROM json_array_elements(v) WITH ORDINALITY items(value,ordinal);
 ELSIF kind='string' THEN
  result:=public.clinical_note_ascii_canonical(to_jsonb(v#>>'{}'));
 ELSIF kind='number' THEN result:=btrim(v::text,E' \t\r\n');
 ELSIF kind='boolean' THEN result:=btrim(v::text,E' \t\r\n');
 ELSIF kind='null' THEN result:='null';
 ELSE RAISE EXCEPTION 'Medication JSON kind';
 END IF;
 RETURN result;
END $$;
CREATE FUNCTION public.ehr_athena_med_json(raw text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
BEGIN
 IF raw IS NULL OR octet_length(raw)>65536 THEN RETURN false; END IF;
 RETURN raw=public.ehr_athena_med_canonical(raw::json);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.ehr_athena_med_text(v json,maximum integer DEFAULT 4096,nullable boolean DEFAULT false) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
BEGIN
 RETURN coalesce((nullable AND json_typeof(v)='null') OR (json_typeof(v)='string' AND char_length(v#>>'{}')<=maximum),false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.ehr_athena_med_integer(v json) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE token text:=btrim(v::text,E' \t\r\n');
BEGIN
 IF json_typeof(v) IS DISTINCT FROM 'number' OR char_length(token)>128 OR token !~ '^-?(0|[1-9][0-9]*)$' THEN RETURN false; END IF;
 RETURN token::numeric BETWEEN -9223372036854775808 AND 9223372036854775807;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

CLINICAL = r"""
CREATE FUNCTION public.ehr_athena_med_section(raw text) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE v json; sectionrow record; groupvalue json; row json; field record; nested json; nestedfield record;
 count integer:=0; allowed text[]:=ARRAY['approvedby','billingndc','createdby','earliestfilldate','encounterid','events','filldate','futuresubmitdate','isdiscontinued','issafetorenew','isstructuredsig','medication','medicationentryid','medicationid','ndcoptions','newindicator','orderingmode','organclass','patientnote','pharmacy','pharmacyncpdpid','prescribedby','providernote','quantity','quantityunit','refillsallowed','route','rxnorm','source','status','stopreason','structuredsig','therapeuticclass','unstructuredsig'];
BEGIN
 IF public.ehr_athena_med_json(raw) IS NOT TRUE THEN RETURN false; END IF;
 v:=raw::json;
 IF json_typeof(v) IS DISTINCT FROM 'object' OR json_typeof(v->'medications') IS DISTINCT FROM 'array' OR json_array_length(v->'medications')>25 THEN RETURN false; END IF;
 FOR sectionrow IN SELECT * FROM json_each(v) LOOP
  IF NOT sectionrow.key=ANY(ARRAY['lastdownloaddenialreason','lastdownloaddenied','lastdownloadeddate','lastupdated','medications','nomedicationsreported','patientdownloadconsent','patientneedsdownloadconsent','sectionnote']) THEN RETURN false; END IF;
  IF sectionrow.key=ANY(ARRAY['lastdownloaddenied','nomedicationsreported','patientdownloadconsent','patientneedsdownloadconsent']) THEN
   IF json_typeof(sectionrow.value) IS DISTINCT FROM 'boolean' THEN RETURN false; END IF;
  ELSIF sectionrow.key<>'medications' AND public.ehr_athena_med_text(sectionrow.value) IS NOT TRUE THEN RETURN false;
  END IF;
 END LOOP;
 FOR groupvalue IN SELECT * FROM json_array_elements(v->'medications') LOOP
  IF json_typeof(groupvalue) IS DISTINCT FROM 'array' OR json_array_length(groupvalue)>25 THEN RETURN false; END IF;
  FOR row IN SELECT * FROM json_array_elements(groupvalue) LOOP
   count:=count+1;
   IF count>25 OR json_typeof(row) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
   FOR field IN SELECT * FROM json_each(row) LOOP
    IF NOT field.key=ANY(allowed) THEN RETURN false; END IF;
    IF field.key=ANY(ARRAY['isdiscontinued','issafetorenew','isstructuredsig']) THEN
     IF json_typeof(field.value) IS DISTINCT FROM 'boolean' THEN RETURN false; END IF;
    ELSIF field.key=ANY(ARRAY['encounterid','medicationid','refillsallowed']) THEN
     IF public.ehr_athena_med_integer(field.value) IS NOT TRUE THEN RETURN false; END IF;
    ELSIF field.key='quantity' THEN
     IF json_typeof(field.value) IS DISTINCT FROM 'number' THEN RETURN false; END IF;
    ELSIF field.key='structuredsig' THEN
     IF json_typeof(field.value) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
    ELSIF field.key=ANY(ARRAY['events','ndcoptions','rxnorm']) THEN
     IF json_typeof(field.value) IS DISTINCT FROM 'array' OR json_array_length(field.value)>100 THEN RETURN false; END IF;
     FOR nested IN SELECT * FROM json_array_elements(field.value) LOOP
      IF json_typeof(nested) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
      FOR nestedfield IN SELECT * FROM json_each(nested) LOOP
       IF field.key='events' THEN
        IF NOT nestedfield.key=ANY(ARRAY['eventdate','type','userdisplayname']) OR public.ehr_athena_med_text(nestedfield.value,4096,nestedfield.key='userdisplayname') IS NOT TRUE THEN RETURN false; END IF;
       ELSIF nestedfield.key IS DISTINCT FROM (CASE WHEN field.key='ndcoptions' THEN 'ndcoption' ELSE 'rxnormidentifier' END) OR public.ehr_athena_med_text(nestedfield.value) IS NOT TRUE THEN RETURN false;
       END IF;
      END LOOP;
     END LOOP;
    ELSIF public.ehr_athena_med_text(field.value,CASE WHEN field.key='medicationentryid' THEN 300 ELSE 4096 END) IS NOT TRUE THEN RETURN false;
    END IF;
   END LOOP;
  END LOOP;
 END LOOP;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.ehr_athena_med_reader_valid(v jsonb,g public.ehr_athena_medication_patient_grants) RETURNS boolean LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE section json; expected jsonb; proof jsonb;
BEGIN
 IF public.finance_settings_keys(v,ARRAY['scope','patient','observed_at','groups','section_json','provider_sources','source_sha256','coverage','medication_type','includes_pending','includes_ndc','includes_rxnorm']) IS NOT TRUE
 OR v->'scope' IS DISTINCT FROM public.ehr_athena_med_scope(g)
 OR v->'patient' IS DISTINCT FROM jsonb_build_object('patient_id',g.patient_id,'identity_json',g.identity_json,'identity_sha256',g.identity_sha256)
 OR public.ehr_athena_observed_time(v->'observed_at') IS NOT TRUE OR v->>'coverage' IS DISTINCT FROM 'returned_section_only'
 OR v->>'medication_type' IS DISTINCT FROM 'ACTIVE' OR v->'includes_pending' IS DISTINCT FROM 'true'::jsonb OR v->'includes_ndc' IS DISTINCT FROM 'true'::jsonb OR v->'includes_rxnorm' IS DISTINCT FROM 'true'::jsonb
 OR jsonb_typeof(v->'section_json') IS DISTINCT FROM 'string' OR public.ehr_athena_med_section(v->>'section_json') IS NOT TRUE
 OR jsonb_typeof(v->'provider_sources') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'provider_sources')<>2
 OR public.research_hash(v->'source_sha256') IS NOT TRUE THEN RETURN false; END IF;
 FOR proof IN SELECT * FROM jsonb_array_elements(v->'provider_sources') LOOP IF public.research_hash(proof) IS NOT TRUE THEN RETURN false; END IF; END LOOP;
 section:=(v->>'section_json')::json;
 SELECT coalesce(jsonb_agg(rowsvalue ORDER BY groupordinal),'[]'::jsonb) INTO expected FROM (
  SELECT groupordinal,coalesce((SELECT jsonb_agg(jsonb_build_object('medication_entry_id',row->>'medicationentryid','medication_name',row->>'medication','original_json',public.ehr_athena_med_canonical(row)) ORDER BY rowordinal)
   FROM json_array_elements(groupvalue) WITH ORDINALITY records(row,rowordinal)),'[]'::jsonb) rowsvalue
  FROM json_array_elements(section->'medications') WITH ORDINALITY groups(groupvalue,groupordinal)) rendered;
 RETURN coalesce(v->'groups'=expected AND v->>'source_sha256'=public.google_calendar_json_digest(jsonb_build_object('contract','athena-medication-observation.v1','scope_sha256',public.ehr_athena_med_scope_digest(g),
 'patient',v->'patient','observed_at',v->'observed_at','section_json',v->'section_json','provider_sources',v->'provider_sources','coverage',v->'coverage','medication_type',v->'medication_type',
 'includes_pending',v->'includes_pending','includes_ndc',v->'includes_ndc','includes_rxnorm',v->'includes_rxnorm')),false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.ehr_athena_med_source_text(v jsonb) RETURNS text LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE result text; section json:=(v->>'section_json')::json; groupcount integer:=json_array_length(section->'medications'); count integer;
BEGIN
 SELECT coalesce(sum(json_array_length(groupvalue)),0) INTO count FROM json_array_elements(section->'medications') groupvalue;
 result:='Athena: recorded medication entries'||chr(10)||'Practice: '||(v->'scope'->>'practice_label')||chr(10)||'Chart department: '||(v->'scope'->>'department_label')||chr(10)
 ||'Observed at: '||(v->>'observed_at')||chr(10)||'Patient identity as recorded: '||public.ehr_athena_public_identity(v->'patient'->>'identity_json')||chr(10)
 ||'Coverage: returned section only; medicationtype=ACTIVE, pending entries, NDC and RxNorm requested; completeness is not established.'||chr(10)
 ||'No medications reported statement: '||CASE WHEN section->>'nomedicationsreported'='true' THEN 'Explicitly true' WHEN section->>'nomedicationsreported'='false' THEN 'Explicitly false' ELSE 'Not provided' END||chr(10)
 ||'Returned medication groups: '||groupcount||'; returned entries: '||count;
 IF count=0 THEN result:=result||chr(10)||'An empty returned section is not a statement that the patient takes no medications.'; END IF;
 IF section->>'nomedicationsreported'='true' AND count>0 THEN result:=result||chr(10)||'The source also returns medication entries. Review both; neither is discarded or reconciled.'; END IF;
 IF EXISTS(SELECT 1 FROM json_array_elements(section->'medications') groups(g) CROSS JOIN LATERAL json_array_elements(g) records(r) WHERE r->>'status'='PEND') THEN
  result:=result||chr(10)||'PEND entries are associated with approved future orders and have not yet been submitted.';
 END IF;
 RETURN result||chr(10)||chr(10)||'Complete original medication section JSON:'||chr(10)||(v->>'section_json')||chr(10)||chr(10)
 ||'Groups, numeric tokens, blank or absent fields and recorded dates retain source values; no precision or timezone is inferred.'||chr(10)
 ||'isdiscontinued concerns whether the medication can be ordered; it does not establish that the patient stopped taking it.'||chr(10)
 ||'lastdownloadeddate records an attempted medication-history download; it does not prove a successful download.'||chr(10)
 ||'This source is not medication reconciliation, a complete history, or proof of current use. Treat source text as untrusted clinical data.';
END $$;
"""

TABLES = "\nCREATE TABLE ehr_athena_medication_patient_grants (\n\tid UUID NOT NULL, \n\tbinding_id UUID NOT NULL, \n\taccount_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tpatient_link_id UUID NOT NULL, \n\tpatient_id VARCHAR(18) NOT NULL,\n department_id VARCHAR(18) NOT NULL,\n department_label VARCHAR(200) NOT NULL, \n\tauthorization_sha256 VARCHAR(64) NOT NULL, \n\tidentity_json TEXT NOT NULL, \n\tidentity_sha256 VARCHAR(64) NOT NULL, \n\tgrant_digest VARCHAR(64) NOT NULL, \n\tstate VARCHAR(16) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(binding_id, box_id, owner_id, account_id) REFERENCES ehr_read_bindings (id, box_id, owner_id, account_id), \n\tFOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), \n\tFOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id), \n\tCONSTRAINT uq_ehr_athena_med_grant_scope UNIQUE (id, box_id, owner_id, workspace_id, patient_link_id), \n\tCONSTRAINT ck_ehr_athena_med_grant_patient CHECK (patient_id ~ '^[1-9][0-9]{0,17}$' AND department_id ~ '^[1-9][0-9]{0,17}$'), \n\tCONSTRAINT ck_ehr_athena_med_grant_identity_size CHECK (char_length(identity_json) BETWEEN 2 AND 20000), \n\tCONSTRAINT ck_ehr_athena_med_grant_state CHECK ((state='active' AND revoked_at IS NULL) OR (state='revoked' AND revoked_at IS NOT NULL)), \n CONSTRAINT ck_ehr_athena_med_department_label CHECK(char_length(department_label) BETWEEN 1 AND 200 AND department_label !~ '[[:cntrl:]]' AND public.ehr_athena_nonblank(department_label)),\n\tCHECK (authorization_sha256 ~ '^[a-f0-9]{64}$' AND identity_sha256 ~ '^[a-f0-9]{64}$' AND grant_digest ~ '^[a-f0-9]{64}$')\n)\n\n;\nCREATE UNIQUE INDEX uq_ehr_athena_med_grant_active ON ehr_athena_medication_patient_grants (binding_id, workspace_id, patient_link_id, department_id, patient_id) WHERE state='active';"

CHECKS = {'ck_ehr_read_binding_clinical_scope': "coalesce(clinical_scope IS NULL OR (clinical_scope='medications' AND vendor='athena' AND protocol='core' AND public.ehr_athena_nonblank(practice_name)),false)", 'ck_ehr_read_request_kind': "coalesce((clinical_scope IS NULL AND athena_medication_grant_id IS NULL AND ((((kind='window' AND parent_snapshot_id IS NULL AND item_handle IS NULL) OR (kind IN ('verify','problems','medications') AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL)) AND workspace_id IS NULL AND patient_link_id IS NULL AND fhir_grant_id IS NULL AND athena_grant_id IS NULL) OR (kind IN ('fhir_patients','core_patients') AND parent_snapshot_id IS NULL AND item_handle IS NULL AND fhir_grant_id IS NULL AND athena_grant_id IS NULL AND workspace_id IS NOT NULL AND patient_link_id IS NOT NULL) OR (kind='fhir_medications' AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL AND fhir_grant_id IS NOT NULL AND athena_grant_id IS NULL AND workspace_id IS NOT NULL AND patient_link_id IS NOT NULL) OR (kind='core_allergies' AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL AND athena_grant_id IS NOT NULL AND fhir_grant_id IS NULL AND workspace_id IS NOT NULL AND patient_link_id IS NOT NULL) OR (kind IN ('lab_reports','lab_report') AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL AND fhir_grant_id IS NULL AND athena_grant_id IS NULL AND workspace_id IS NOT NULL AND patient_link_id IS NOT NULL))) OR (clinical_scope='medications' AND fhir_grant_id IS NULL AND athena_grant_id IS NULL AND workspace_id IS NOT NULL AND patient_link_id IS NOT NULL AND ((kind='core_patients' AND parent_snapshot_id IS NULL AND item_handle IS NULL AND athena_medication_grant_id IS NULL) OR (kind='core_medications' AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL AND athena_medication_grant_id IS NOT NULL))),false)", 'ck_ehr_read_request_window': "(kind IN ('fhir_patients','fhir_medications') AND window_start IS NULL AND window_end IS NULL AND practice_id IS NULL) OR (kind IN ('core_patients','core_allergies','core_medications') AND window_start IS NULL AND window_end IS NULL AND practice_id IS NOT NULL) OR (kind NOT IN ('fhir_patients','fhir_medications','core_patients','core_allergies','core_medications') AND window_start IS NOT NULL AND window_end IS NOT NULL AND practice_id IS NOT NULL AND isfinite(window_start) AND isfinite(window_end) AND window_end>window_start AND window_end<=window_start+interval '168 hours')", 'ck_ehr_review_clinical_scope': "coalesce(command_clinical_scope IS NULL OR (command_clinical_scope='medications' AND command_protocol='core' AND command_provider='athena'),false)"}


GRANTS = "\nCREATE FUNCTION public.ehr_athena_med_grant_digest(g public.ehr_athena_medication_patient_grants) RETURNS text LANGUAGE sql STABLE SET search_path=pg_catalog AS $$\n SELECT public.google_calendar_json_digest(jsonb_build_object('contract','athena-medication-patient-grant.v1','grant_id',g.id,'scope_sha256',public.ehr_athena_med_scope_digest(g),'patient_identity_sha256',g.identity_sha256))\n$$;\nCREATE FUNCTION public.ehr_athena_med_grant_current(gid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$\n SELECT EXISTS(SELECT 1 FROM public.ehr_athena_medication_patient_grants g JOIN public.ehr_read_bindings b ON b.id=g.binding_id\n JOIN public.encounter_workspaces w ON (w.id,w.box_id,w.owner_id,w.patient_link_id)=(g.workspace_id,g.box_id,g.owner_id,g.patient_link_id)\n JOIN public.patient_links p ON (p.id,p.box_id)=(g.patient_link_id,g.box_id)\n WHERE g.id=gid AND g.state='active' AND g.revoked_at IS NULL AND b.protocol='core' AND b.vendor='athena' AND b.clinical_scope='medications' AND public.ehr_read_binding_current(b.id)\n AND p.state='confirmed' AND p.revoked_at IS NULL AND g.grant_digest=public.ehr_athena_med_grant_digest(g))\n$$;\nCREATE FUNCTION public.guard_ehr_athena_med_grant() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$\nDECLARE b public.ehr_read_bindings;\nBEGIN\n IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Retain Athena grant history' USING ERRCODE='23514'; END IF;\n IF TG_OP='UPDATE' THEN\n  IF to_jsonb(NEW)-'state'-'revoked_at' IS DISTINCT FROM to_jsonb(OLD)-'state'-'revoked_at' OR OLD.state<>'active' OR NEW.state<>'revoked' OR NEW.revoked_at IS NULL OR NOT isfinite(NEW.revoked_at) OR NEW.revoked_at<OLD.created_at THEN RAISE EXCEPTION 'Athena grant immutable' USING ERRCODE='23514'; END IF;\n  RETURN NEW;\n END IF;\n SELECT * INTO b FROM public.ehr_read_bindings WHERE id=NEW.binding_id FOR UPDATE;\n PERFORM 1 FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;\n IF b.clinical_scope IS DISTINCT FROM 'medications' OR b.id IS NULL OR b.protocol IS DISTINCT FROM 'core' OR b.vendor<>'athena' OR NOT public.ehr_read_binding_current(b.id)\n OR (NEW.box_id,NEW.owner_id,NEW.account_id) IS DISTINCT FROM (b.box_id,b.owner_id,b.account_id)\n OR NEW.state<>'active' OR NEW.revoked_at IS NOT NULL OR NOT isfinite(NEW.created_at)\n OR NOT EXISTS(SELECT 1 FROM public.encounter_workspaces w JOIN public.patient_links p ON (p.id,p.box_id)=(w.patient_link_id,w.box_id) WHERE (w.id,w.box_id,w.owner_id,w.patient_link_id)=(NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.patient_link_id) AND p.state='confirmed' AND p.revoked_at IS NULL)\n OR octet_length(NEW.identity_json)>16384 OR public.ehr_athena_identity(NEW.identity_json,NEW.patient_id) IS NOT TRUE\n THEN RAISE EXCEPTION 'Athena grant authority invalid' USING ERRCODE='23514'; END IF;\n IF NEW.identity_sha256 IS DISTINCT FROM encode(sha256(convert_to(NEW.identity_json,'UTF8')),'hex')\n OR NEW.grant_digest IS DISTINCT FROM public.ehr_athena_med_grant_digest(NEW)\n THEN RAISE EXCEPTION 'Athena grant identity invalid' USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER ehr_athena_med_grant_guard BEFORE INSERT OR UPDATE OR DELETE ON public.ehr_athena_medication_patient_grants FOR EACH ROW EXECUTE FUNCTION public.guard_ehr_athena_med_grant();\n"

REQUEST = "\n IF NEW.clinical_scope IS DISTINCT FROM b.clinical_scope THEN RAISE EXCEPTION 'Read clinical scope differs from binding' USING ERRCODE='23514'; END IF;\n IF b.clinical_scope='medications' THEN\n  IF NEW.kind NOT IN ('core_patients','core_medications') OR NEW.request_json->>'clinical_scope' IS DISTINCT FROM 'medications' OR NEW.request_json->>'protocol' IS DISTINCT FROM 'core' OR NEW.request_json->>'provider' IS DISTINCT FROM 'athena'\n   OR NEW.request_json->>'workspace_id' IS DISTINCT FROM NEW.workspace_id::text\n   OR NEW.request_json->>'action' IS DISTINCT FROM NEW.kind\n   OR NOT EXISTS(SELECT 1 FROM public.encounter_workspaces w JOIN public.patient_links p ON (p.id,p.box_id)=(w.patient_link_id,w.box_id) WHERE (w.id,w.box_id,w.owner_id,w.patient_link_id)=(NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.patient_link_id) AND p.state='confirmed' AND p.revoked_at IS NULL)\n  THEN RAISE EXCEPTION 'Athena read authority invalid' USING ERRCODE='23514'; END IF;\n  IF NEW.kind='core_patients' THEN\n   IF NOT public.finance_settings_keys(NEW.request_json,ARRAY['provider','protocol','clinical_scope','action','workspace_id','connection_id','binding_sha256','idempotency_key']) THEN RAISE EXCEPTION 'Athena selection request invalid' USING ERRCODE='23514'; END IF;\n  ELSE\n   SELECT * INTO parent FROM public.ehr_read_snapshots WHERE id=NEW.parent_snapshot_id;\n   SELECT * INTO root FROM public.ehr_read_requests WHERE id=parent.observation_id;\n   IF root.clinical_scope IS DISTINCT FROM 'medications' OR root.kind IS DISTINCT FROM 'core_patients' OR (root.binding_id,root.box_id,root.owner_id,root.account_id,root.workspace_id,root.patient_link_id) IS DISTINCT FROM (NEW.binding_id,NEW.box_id,NEW.owner_id,NEW.account_id,NEW.workspace_id,NEW.patient_link_id)\n    OR NOT public.ehr_read_request_current(root.id) OR NOT public.ehr_read_snapshot_valid(parent.id) OR NEW.valid_until>root.valid_until\n    OR NOT public.ehr_athena_med_grant_current(NEW.athena_medication_grant_id)\n    OR NOT public.finance_settings_keys(NEW.request_json,ARRAY['provider','protocol','clinical_scope','action','workspace_id','connection_id','binding_sha256','idempotency_key','observation_id','observation_sha256','item_handle','item_sha256'])\n    OR NEW.request_json->>'observation_id' IS DISTINCT FROM root.id::text OR NEW.request_json->>'observation_sha256' IS DISTINCT FROM parent.source_sha256\n    OR NEW.request_json->>'item_handle' IS DISTINCT FROM NEW.item_handle::text\n    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent.payload->'private'->'items') item WHERE item->>'handle'=NEW.item_handle::text AND item->>'grant_id'=NEW.athena_medication_grant_id::text)\n    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent.payload->'public'->'items') item WHERE item->>'handle'=NEW.item_handle::text AND item->>'sha256'=NEW.request_json->>'item_sha256')\n   THEN RAISE EXCEPTION 'Athena exact parent invalid' USING ERRCODE='23514'; END IF;\n  END IF;\n  RETURN NEW;\n END IF;\n IF NEW.kind='core_medications' OR NEW.request_json ? 'clinical_scope' THEN RAISE EXCEPTION 'Unexpected Athena protocol' USING ERRCODE='23514'; END IF;\n"


PAYLOAD = r"""

CREATE FUNCTION public.ehr_athena_med_payload_valid(payload jsonb,r public.ehr_read_requests) RETURNS boolean LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE pub jsonb:=payload->'public'; priv jsonb:=payload->'private'; b public.ehr_read_bindings; g public.ehr_athena_medication_patient_grants;
 parent public.ehr_read_snapshots; prior public.ehr_read_requests; item jsonb; shown jsonb; raw jsonb; expected jsonb; content text; contentsha text;
 position integer:=0; handles text[]:=ARRAY[]::text[]; grants text[]:=ARRAY[]::text[];
BEGIN
 SELECT * INTO b FROM public.ehr_read_bindings WHERE id=r.binding_id;
 IF b.clinical_scope IS DISTINCT FROM 'medications' OR r.clinical_scope IS DISTINCT FROM 'medications' OR b.protocol IS DISTINCT FROM 'core' OR b.vendor<>'athena' OR r.transport<>'mock' OR r.kind NOT IN ('core_patients','core_medications')
 OR NOT public.finance_settings_keys(payload,ARRAY['public','private'])
 OR NOT public.finance_settings_keys(priv,ARRAY['protocol','clinical_scope','transport','binding_sha256','request_sha256','workspace_id','patient_link_id','items','reader_snapshot_json','review_sha256'])
 OR priv->>'clinical_scope' IS DISTINCT FROM 'medications' OR priv->>'protocol' IS DISTINCT FROM 'core' OR priv->>'transport' IS DISTINCT FROM 'mock'
 OR priv->>'binding_sha256' IS DISTINCT FROM r.binding_digest OR priv->>'request_sha256' IS DISTINCT FROM r.request_hash
 OR priv->>'workspace_id' IS DISTINCT FROM r.workspace_id::text OR priv->>'patient_link_id' IS DISTINCT FROM r.patient_link_id::text
 OR pub->>'workspace_id' IS DISTINCT FROM r.workspace_id::text OR pub->>'practice_label' IS DISTINCT FROM b.practice_name
 OR pub->>'clinical_scope' IS DISTINCT FROM 'medications' OR pub->>'provider' IS DISTINCT FROM 'athena' OR pub->>'protocol' IS DISTINCT FROM 'core' OR pub->>'mode' IS DISTINCT FROM 'synthetic'
 OR pub->>'kind' IS DISTINCT FROM r.kind OR NOT public.google_message_aware_time(pub->'observed_at')
 OR jsonb_typeof(priv->'items') IS DISTINCT FROM 'array' OR jsonb_array_length(priv->'items')>25
 THEN RETURN false; END IF;
 FOR item IN SELECT * FROM jsonb_array_elements(priv->'items') LOOP
  SELECT * INTO g FROM public.ehr_athena_medication_patient_grants WHERE id::text=item->>'grant_id';
  IF NOT public.finance_settings_keys(item,ARRAY['handle','grant_id','grant_sha256','patient_identity_json']) OR g.id IS NULL
   OR jsonb_typeof(item->'handle') IS DISTINCT FROM 'string' OR item->>'handle' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR item->>'handle'=ANY(handles) OR item->>'grant_id'=ANY(grants)
   OR (g.binding_id,g.box_id,g.owner_id,g.account_id,g.workspace_id,g.patient_link_id) IS DISTINCT FROM (r.binding_id,r.box_id,r.owner_id,r.account_id,r.workspace_id,r.patient_link_id)
   OR item->>'grant_sha256' IS DISTINCT FROM g.grant_digest OR g.grant_digest IS DISTINCT FROM public.ehr_athena_med_grant_digest(g)
   OR item->>'patient_identity_json' IS DISTINCT FROM g.identity_json THEN RETURN false; END IF;
  handles:=array_append(handles,item->>'handle'); grants:=array_append(grants,item->>'grant_id');
  IF r.kind='core_patients' THEN
   shown:=pub->'items'->position; expected:=jsonb_build_object('handle',item->'handle','patient_identity_json',public.ehr_athena_public_identity(g.identity_json),'department_label',g.department_label);
   expected:=expected||jsonb_build_object('sha256',public.google_calendar_json_digest(jsonb_build_object('kind','ehr_athena_medication_patient_item.v1','item',expected)));
   IF shown IS DISTINCT FROM expected THEN RETURN false; END IF;
  END IF;
  position:=position+1;
 END LOOP;
 IF r.kind='core_patients' THEN
  RETURN coalesce(public.finance_settings_keys(pub,ARRAY['provider','protocol','clinical_scope','mode','kind','workspace_id','practice_label','observed_at','coverage','items'])
   AND pub->>'coverage'='authorized_candidates_only' AND jsonb_typeof(pub->'items')='array' AND jsonb_array_length(pub->'items')=position
   AND priv->'reader_snapshot_json'='null'::jsonb AND priv->'review_sha256'='null'::jsonb,false);
 END IF;
 IF position<>1 OR NOT public.finance_settings_keys(pub,ARRAY['provider','protocol','clinical_scope','mode','kind','workspace_id','practice_label','observed_at','parent','item'])
 OR public.research_hash(priv->'review_sha256') IS NOT TRUE
 OR g.id IS DISTINCT FROM r.athena_medication_grant_id OR item->>'handle' IS DISTINCT FROM r.item_handle::text
 OR jsonb_typeof(priv->'reader_snapshot_json') IS DISTINCT FROM 'string' OR char_length(priv->>'reader_snapshot_json')>65536 THEN RETURN false; END IF;
 raw:=(priv->>'reader_snapshot_json')::jsonb;
 IF priv->>'reader_snapshot_json' IS DISTINCT FROM public.clinical_note_ascii_canonical(raw) OR public.ehr_athena_med_reader_valid(raw,g) IS NOT TRUE THEN RETURN false; END IF;
 SELECT * INTO parent FROM public.ehr_read_snapshots WHERE id=r.parent_snapshot_id;
 SELECT * INTO prior FROM public.ehr_read_requests WHERE id=parent.observation_id;
 IF prior.clinical_scope IS DISTINCT FROM 'medications' OR prior.kind IS DISTINCT FROM 'core_patients' OR NOT public.ehr_read_snapshot_valid(parent.id)
 OR (prior.binding_id,prior.workspace_id,prior.patient_link_id) IS DISTINCT FROM (r.binding_id,r.workspace_id,r.patient_link_id)
 OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent.payload->'private'->'items') old WHERE old=item)
 OR pub->'parent' IS DISTINCT FROM jsonb_build_object('observation_id',prior.id,'source_sha256',parent.source_sha256,'item_sha256',r.request_json->>'item_sha256')
 OR r.request_json->>'observation_id' IS DISTINCT FROM prior.id::text OR r.request_json->>'observation_sha256' IS DISTINCT FROM parent.source_sha256
 OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent.payload->'public'->'items') old WHERE old->>'handle'=r.item_handle::text AND old->>'sha256'=r.request_json->>'item_sha256')
 OR pub->>'observed_at' IS DISTINCT FROM replace(raw->>'observed_at','+00:00','Z')
 THEN RETURN false; END IF;
 content:=public.ehr_athena_med_source_text(raw); contentsha:=encode(sha256(convert_to(content,'UTF8')),'hex');
 IF content IS NULL OR char_length(content)>5000 THEN RETURN false; END IF;
 expected:=jsonb_build_object('handle',item->'handle','patient_identity_json',public.ehr_athena_public_identity(g.identity_json),'department_label',g.department_label,'coverage',raw->'coverage','medication_type',raw->'medication_type','includes_pending',raw->'includes_pending','includes_ndc',raw->'includes_ndc','includes_rxnorm',raw->'includes_rxnorm','section_json',raw->'section_json','source_content',content,'content_sha256',contentsha);
 expected:=expected||jsonb_build_object('sha256',public.google_calendar_json_digest(jsonb_build_object('kind','ehr_athena_medications_item.v1','item',expected)));
 RETURN coalesce(pub->'item'=expected AND priv->>'review_sha256'=public.google_calendar_json_digest(jsonb_build_object('contract','athena-medication-review-snapshot.v1','scope_sha256',public.ehr_athena_med_scope_digest(g),
 'observation_sha256',raw->>'source_sha256','patient_identity_sha256',g.identity_sha256,'source_content_sha256',contentsha,'completeness','bounded_recorded_medication_section')),false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;

CREATE OR REPLACE FUNCTION public.ehr_read_payload_valid(payload jsonb,r public.ehr_read_requests) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN r.clinical_scope IS NULL THEN public.ehr_pre_athena_med_payload_valid(payload,r)
 WHEN r.clinical_scope='medications' THEN coalesce(public.ehr_athena_med_payload_valid(payload,r),false) ELSE false END
$$;
CREATE OR REPLACE FUNCTION public.ehr_read_source_content(pub jsonb) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN NOT pub ? 'clinical_scope' THEN public.ehr_pre_athena_med_source_content(pub)
 WHEN pub->>'clinical_scope'='medications' AND pub->>'provider'='athena' AND pub->>'protocol'='core' AND pub->>'kind'='core_medications' THEN pub->'item'->>'source_content' ELSE NULL END
$$;

"""

SOURCES = r"""

CREATE FUNCTION public.ehr_athena_med_source_valid(eid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.ehr_read_source_reviews v JOIN public.workspace_entries e ON e.id=v.entry_id
 JOIN public.encounter_workspaces w ON w.id=v.workspace_id JOIN public.ehr_read_snapshots z ON z.id=v.snapshot_id JOIN public.ehr_read_requests r ON r.id=z.observation_id
 WHERE e.id=eid AND e.kind='ehr_read_source' AND r.kind='core_medications' AND r.clinical_scope='medications' AND v.command_clinical_scope='medications' AND v.command_provider='athena' AND v.command_protocol='core' AND v.reviewed_visit IS NULL
 AND (e.workspace_id,e.box_id,e.actor_id,e.revision,e.request_hash,e.idempotency_key)=(v.workspace_id,v.box_id,v.owner_id,v.workspace_revision,v.request_hash,v.idempotency_key)
 AND (w.box_id,w.owner_id,w.patient_link_id)=(v.box_id,v.owner_id,v.patient_link_id)
 AND (r.box_id,r.owner_id,r.workspace_id,r.patient_link_id,z.box_id,z.owner_id)=(v.box_id,v.owner_id,v.workspace_id,v.patient_link_id,v.box_id,v.owner_id)
 AND public.ehr_read_snapshot_valid(z.id) AND v.workspace_revision=v.expected_revision+1 AND v.reviewed_patient_identity AND v.reviewed_exact_snapshot AND v.reviewed_untrusted_source
 AND v.item_handle=r.item_handle AND z.payload->'public'->'item'->>'handle'=v.item_handle::text AND v.item_sha256=z.payload->'public'->'item'->>'sha256' AND v.observation_sha256=z.source_sha256
 AND v.source_sha256=public.google_calendar_json_digest(jsonb_build_object('observation_sha256',v.observation_sha256,'item_handle',v.item_handle,'item_sha256',v.item_sha256))
 AND v.request_hash=public.google_calendar_json_digest(jsonb_build_object('provider','athena','protocol','core','clinical_scope','medications','workspace_id',v.workspace_id,'expected_revision',v.expected_revision,'idempotency_key',v.idempotency_key,
 'observation_id',r.id,'observation_sha256',v.observation_sha256,'item_handle',v.item_handle,'item_sha256',v.item_sha256,'reviewed_patient_identity',true,'reviewed_exact_snapshot',true,'reviewed_untrusted_source',true))
 AND e.content=public.ehr_read_source_content(z.payload->'public') AND e.source_label='Athena: reviewed medication records'
 AND v.content_sha256=encode(sha256(convert_to(e.content,'UTF8')),'hex') AND v.valid_until=r.valid_until)
$$;
CREATE OR REPLACE FUNCTION public.ehr_read_source_valid(eid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM public.ehr_read_source_reviews WHERE entry_id=eid AND command_clinical_scope IS NOT NULL) THEN public.ehr_athena_med_source_valid(eid) ELSE public.ehr_pre_athena_med_source_valid(eid) END
$$;

"""
