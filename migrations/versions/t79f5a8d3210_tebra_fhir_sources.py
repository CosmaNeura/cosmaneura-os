"""Independent FHIR grants and exact Tebra medication source custody."""

from alembic import op

revision = "t79f5a8d3210"
down_revision = "s68e4f7c2109"
branch_labels = None
depends_on = None


def definition(signature):
    return op.get_bind().exec_driver_sql("SELECT pg_get_functiondef(%s::regprocedure)", (signature,)).scalar_one()


def changed(sql, pairs):
    for before, after in pairs:
        if sql.count(before) != 1:
            raise RuntimeError("Prior EHR guard differs from the FHIR extension: " + before)
        sql = sql.replace(before, after)
    return sql


def upgrade():
    op.execute("ALTER TABLE ehr_read_bindings ADD COLUMN protocol varchar(4), ALTER COLUMN practice_id DROP NOT NULL")
    op.execute(TABLES)
    op.execute("ALTER TABLE ehr_read_requests ALTER COLUMN practice_id DROP NOT NULL, ALTER COLUMN window_start DROP NOT NULL, ALTER COLUMN window_end DROP NOT NULL, ADD COLUMN workspace_id uuid, ADD COLUMN patient_link_id uuid, ADD COLUMN fhir_grant_id uuid")
    op.execute("ALTER TABLE ehr_read_requests ADD CONSTRAINT fk_ehr_read_fhir_grant FOREIGN KEY(fhir_grant_id,box_id,owner_id,workspace_id,patient_link_id) REFERENCES ehr_fhir_patient_grants(id,box_id,owner_id,workspace_id,patient_link_id)")
    op.execute("ALTER TABLE ehr_read_source_reviews ADD COLUMN command_protocol varchar(4), ALTER COLUMN reviewed_visit DROP NOT NULL")
    op.create_check_constraint("ck_ehr_review_protocol", "ehr_read_source_reviews", "coalesce(command_protocol IS NULL OR (command_protocol='fhir' AND command_provider='tebra'),false)")
    for table, constraints in CONSTRAINTS.items():
        for name, sql in constraints.items():
            op.drop_constraint(name, table)
            op.create_check_constraint(name, table, sql)
    prior = definition("public.ehr_read_binding_digest(public.ehr_read_bindings)")
    op.execute(prior.replace("public.ehr_read_binding_digest(", "public.ehr_pre_fhir_binding_digest(", 1))
    op.execute(FIELDS)
    op.execute(GRANTS)
    op.execute(changed(definition("public.guard_ehr_read_binding()"), (("NEW.vendor='tebra' AND NOT EXISTS", "NEW.vendor='tebra' AND NEW.protocol IS NULL AND NOT EXISTS"),)))
    prior = definition("public.ehr_read_request_current(uuid)")
    op.execute(prior.replace("public.ehr_read_request_current(", "public.ehr_pre_fhir_request_current(", 1))
    op.execute(CURRENT)
    op.execute(changed(definition("public.guard_ehr_read_request()"), ((" IF NEW.kind='window' THEN", REQUEST + " IF NEW.kind='window' THEN"),)))
    op.execute(CLINICAL)
    op.execute(CONTENT)
    op.execute(PAYLOAD)
    prior = definition("public.ehr_read_payload_valid(jsonb,public.ehr_read_requests)")
    op.execute(prior.replace("public.ehr_read_payload_valid(", "public.ehr_pre_fhir_payload_valid(", 1))
    op.execute("""CREATE OR REPLACE FUNCTION public.ehr_read_payload_valid(payload jsonb,r public.ehr_read_requests) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$ SELECT CASE WHEN r.kind IN ('fhir_patients','fhir_medications') THEN coalesce(public.ehr_fhir_payload_valid(payload,r),false) ELSE public.ehr_pre_fhir_payload_valid(payload,r) END $$""")
    prior = definition("public.ehr_read_source_content(jsonb)")
    op.execute(prior.replace("public.ehr_read_source_content(", "public.ehr_pre_fhir_source_content(", 1))
    op.execute("""CREATE OR REPLACE FUNCTION public.ehr_read_source_content(pub jsonb) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$ SELECT CASE WHEN pub->>'protocol'='fhir' AND pub->>'kind'='fhir_medications' THEN pub->'item'->>'source_content' ELSE public.ehr_pre_fhir_source_content(pub) END $$""")
    prior = definition("public.ehr_read_source_valid(uuid)")
    op.execute(prior.replace("public.ehr_read_source_valid(", "public.ehr_pre_fhir_source_valid(", 1))
    op.execute(SOURCES)
    op.execute(changed(definition("public.guard_ehr_read_snapshot()"), ((" RETURN NEW;", """
 IF r.kind IN ('fhir_patients','fhir_medications') THEN
  PERFORM 1 FROM public.ehr_fhir_patient_grants WHERE id::text IN (SELECT item->>'grant_id' FROM jsonb_array_elements(NEW.payload->'private'->'items') item) FOR SHARE;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.payload->'private'->'items') item WHERE NOT public.ehr_fhir_grant_current((item->>'grant_id')::uuid)) THEN RAISE EXCEPTION 'FHIR snapshot grant changed' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;"""),)))
    op.execute(changed(definition("public.guard_ehr_read_review()"), (("r.kind NOT IN ('verify','problems','medications')", "r.kind NOT IN ('verify','problems','medications','fhir_medications')"),
        (" IF w.id IS NULL", " PERFORM 1 FROM public.ehr_fhir_patient_grants WHERE id=r.fhir_grant_id FOR SHARE;\n IF w.id IS NULL"),
        (" OR NOT public.ehr_read_request_current(r.id)", " OR NEW.command_protocol IS DISTINCT FROM (SELECT protocol FROM public.ehr_read_bindings WHERE id=r.binding_id) OR (r.kind='fhir_medications' AND (r.workspace_id,r.patient_link_id) IS DISTINCT FROM (NEW.workspace_id,NEW.patient_link_id)) OR NOT public.ehr_read_request_current(r.id)"))))


def downgrade():
    raise RuntimeError("Retain FHIR patient grants and reviewed medication history")

CONSTRAINTS = {'ehr_read_bindings': {'ck_ehr_read_binding_vendor': "coalesce((protocol IS NULL AND vendor='elation' AND environment='sandbox' AND customer_id IS NULL AND practice_timezone IS NULL) OR (protocol IS NULL AND vendor='tebra' AND environment='synthetic' AND customer_id IS NOT NULL AND customer_id ~ '^[1-9][0-9]{0,9}$' AND customer_id::numeric<=2147483647 AND practice_id::numeric<=2147483647 AND practice_timezone IS NOT NULL) OR (protocol='fhir' AND vendor='tebra' AND environment='synthetic' AND practice_id IS NULL AND customer_id IS NULL AND practice_timezone IS NULL),false)", 'ck_ehr_read_binding_practice': "coalesce((protocol='fhir' AND practice_id IS NULL) OR (protocol IS NULL AND practice_id IS NOT NULL AND practice_id ~ '^[1-9][0-9]*$' AND char_length(practice_id)<=19 AND practice_id::numeric<=9223372036854775807),false)"}, 'ehr_read_requests': {'ck_ehr_read_request_kind': "((kind='window' AND parent_snapshot_id IS NULL AND item_handle IS NULL) OR (kind IN ('verify','problems','medications') AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL)) AND workspace_id IS NULL AND patient_link_id IS NULL AND fhir_grant_id IS NULL OR (kind='fhir_patients' AND parent_snapshot_id IS NULL AND item_handle IS NULL AND fhir_grant_id IS NULL AND workspace_id IS NOT NULL AND patient_link_id IS NOT NULL) OR (kind='fhir_medications' AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL AND fhir_grant_id IS NOT NULL AND workspace_id IS NOT NULL AND patient_link_id IS NOT NULL)", 'ck_ehr_read_request_window': "(kind IN ('fhir_patients','fhir_medications') AND window_start IS NULL AND window_end IS NULL AND practice_id IS NULL) OR (kind NOT IN ('fhir_patients','fhir_medications') AND window_start IS NOT NULL AND window_end IS NOT NULL AND practice_id IS NOT NULL AND isfinite(window_start) AND isfinite(window_end) AND window_end>window_start AND window_end<=window_start+interval '168 hours')"}, 'ehr_read_source_reviews': {'ck_ehr_read_review_checks': "coalesce(((command_protocol IS NULL AND reviewed_visit IS TRUE) OR (command_protocol='fhir' AND reviewed_visit IS NULL)) AND reviewed_patient_identity AND reviewed_exact_snapshot AND reviewed_untrusted_source,false)"}}

TABLES = "\nCREATE TABLE ehr_fhir_patient_grants (\n\tid UUID NOT NULL, \n\tbinding_id UUID NOT NULL, \n\taccount_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tpatient_link_id UUID NOT NULL, \n\tfhir_patient_id VARCHAR(64) NOT NULL, \n\tauthorization_sha256 VARCHAR(64) NOT NULL, \n\tidentity_json TEXT NOT NULL, \n\tidentity_sha256 VARCHAR(64) NOT NULL, \n\tgrant_digest VARCHAR(64) NOT NULL, \n\tstate VARCHAR(16) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(binding_id, box_id, owner_id, account_id) REFERENCES ehr_read_bindings (id, box_id, owner_id, account_id), \n\tFOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), \n\tFOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id), \n\tCONSTRAINT uq_ehr_fhir_grant_scope UNIQUE (id, box_id, owner_id, workspace_id, patient_link_id), \n\tCONSTRAINT ck_ehr_fhir_grant_patient CHECK (fhir_patient_id ~ '^[A-Za-z0-9.-]{1,64}$' AND fhir_patient_id NOT IN ('.','..')), \n\tCONSTRAINT ck_ehr_fhir_grant_identity_size CHECK (char_length(identity_json) BETWEEN 2 AND 20000), \n\tCONSTRAINT ck_ehr_fhir_grant_state CHECK ((state='active' AND revoked_at IS NULL) OR (state='revoked' AND revoked_at IS NOT NULL)), \n\tCHECK (authorization_sha256 ~ '^[a-f0-9]{64}$' AND identity_sha256 ~ '^[a-f0-9]{64}$' AND grant_digest ~ '^[a-f0-9]{64}$')\n)\n\n;\nCREATE UNIQUE INDEX uq_ehr_fhir_grant_active ON ehr_fhir_patient_grants (binding_id, workspace_id, patient_link_id, fhir_patient_id) WHERE state='active';"

FIELDS = r"""
CREATE FUNCTION public.ehr_fhir_id(v jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT coalesce(jsonb_typeof(v)='string' AND v#>>'{}' ~ '^[A-Za-z0-9.-]{1,64}$' AND v#>>'{}' NOT IN ('.','..'),false)
$$;
CREATE FUNCTION public.ehr_fhir_tree(v json,depth integer DEFAULT 0) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE entry record; item json; kind text:=json_typeof(v); t text;
BEGIN
 IF depth>24 THEN RETURN false; END IF;
 IF kind='object' THEN
  IF (SELECT count(*)<>count(DISTINCT key) FROM json_each(v)) THEN RETURN false; END IF;
  FOR entry IN SELECT * FROM json_each(v) LOOP
   IF entry.key IN ('modifierExtension','implicitRules') OR char_length(entry.key) NOT BETWEEN 1 AND 100 OR NOT public.ehr_fhir_tree(entry.value,depth+1) THEN RETURN false; END IF;
  END LOOP;
 ELSIF kind='array' THEN
  FOR item IN SELECT * FROM json_array_elements(v) LOOP IF NOT public.ehr_fhir_tree(item,depth+1) THEN RETURN false; END IF; END LOOP;
 ELSIF kind='string' THEN
  t:=v::jsonb#>>'{}';
  IF char_length(t) NOT BETWEEN 1 AND 12000 OR NOT public.ehr_medication_text(v::jsonb,12000,true) THEN RETURN false; END IF;
 ELSIF kind='number' THEN IF v::text ~ '[.eE]' THEN PERFORM (v::text)::double precision; END IF;
 ELSIF kind<>'boolean' THEN RETURN false;
 END IF;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.ehr_fhir_json(raw text,kind text) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
BEGIN
 RETURN coalesce(octet_length(raw)<=65536 AND json_typeof(raw::json)=kind AND public.ehr_fhir_tree(raw::json),false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.ehr_fhir_date(v jsonb,times boolean DEFAULT false) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE t text:=v#>>'{}';
BEGIN
 IF jsonb_typeof(v) IS DISTINCT FROM 'string' OR char_length(t)>64 THEN RETURN false; END IF;
 IF t ~ '^[0-9]{4}$' THEN RETURN public.google_calendar_date(to_jsonb(t||'-01-01'));
 ELSIF t ~ '^[0-9]{4}-[0-9]{2}$' THEN RETURN public.google_calendar_date(to_jsonb(t||'-01'));
 ELSIF t ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN RETURN public.google_calendar_date(v);
 ELSE RETURN times AND t ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\.[0-9]+)?(Z|[+-]((0[0-9]|1[0-3]):[0-5][0-9]|14:00))$' AND public.google_calendar_date(to_jsonb(left(t,10)));
 END IF;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.ehr_fhir_identity(v jsonb) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE name jsonb; part jsonb; identifier jsonb; key text;
BEGIN
 IF jsonb_typeof(v->'name') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'name') NOT BETWEEN 1 AND 20 THEN RETURN false; END IF;
 FOREACH key IN ARRAY ARRAY['active','deceasedBoolean'] LOOP
  IF v ? key AND jsonb_typeof(v->key) IS DISTINCT FROM 'boolean' THEN RETURN false; END IF;
 END LOOP;
 IF v ? 'deceasedDateTime' AND (v ? 'deceasedBoolean' OR public.ehr_fhir_date(v->'deceasedDateTime',true) IS NOT TRUE) THEN RETURN false; END IF;
 IF v ? 'birthDate' AND public.ehr_fhir_date(v->'birthDate') IS NOT TRUE THEN RETURN false; END IF;
 IF v ? 'gender' AND coalesce(v->>'gender','') NOT IN ('male','female','other','unknown') THEN RETURN false; END IF;
 FOR name IN SELECT * FROM jsonb_array_elements(v->'name') LOOP
  IF jsonb_typeof(name) IS DISTINCT FROM 'object' OR NOT coalesce(name ? 'text' OR name ? 'family' OR jsonb_typeof(name->'given')='array' AND jsonb_array_length(name->'given')>0,false) THEN RETURN false; END IF;
  FOREACH key IN ARRAY ARRAY['text','family','use'] LOOP
   IF name ? key AND (public.ehr_medication_text(name->key,300,false) IS NOT TRUE OR char_length(name->>key)=0) THEN RETURN false; END IF;
  END LOOP;
  FOREACH key IN ARRAY ARRAY['given','prefix','suffix'] LOOP
   IF name ? key THEN
    IF jsonb_typeof(name->key) IS DISTINCT FROM 'array' OR jsonb_array_length(name->key)>20 THEN RETURN false; END IF;
    FOR part IN SELECT * FROM jsonb_array_elements(name->key) LOOP
     IF public.ehr_medication_text(part,100,false) IS NOT TRUE OR char_length(part#>>'{}')=0 THEN RETURN false; END IF;
    END LOOP;
   END IF;
  END LOOP;
 END LOOP;
 IF v ? 'identifier' THEN
  IF jsonb_typeof(v->'identifier') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'identifier')>30 THEN RETURN false; END IF;
  FOR identifier IN SELECT * FROM jsonb_array_elements(v->'identifier') LOOP
   IF jsonb_typeof(identifier) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
   FOREACH key IN ARRAY ARRAY['value','system'] LOOP
    IF identifier ? key AND (public.ehr_medication_text(identifier->key,CASE WHEN key='value' THEN 300 ELSE 512 END,false) IS NOT TRUE OR char_length(identifier->>key)=0) THEN RETURN false; END IF;
   END LOOP;
  END LOOP;
 END IF;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.ehr_fhir_concept(v jsonb) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE c jsonb;
BEGIN
 IF jsonb_typeof(v) IS DISTINCT FROM 'object' OR NOT (v ? 'text' OR v ? 'coding') THEN RETURN false; END IF;
 IF v ? 'text' AND (NOT public.ehr_medication_text(v->'text',1000,true) OR char_length(v->>'text')=0) THEN RETURN false; END IF;
 IF jsonb_typeof(coalesce(v->'coding','[]'::jsonb))<>'array' OR jsonb_array_length(coalesce(v->'coding','[]'::jsonb))>20 THEN RETURN false; END IF;
 IF NOT v ? 'text' AND jsonb_array_length(coalesce(v->'coding','[]'::jsonb))=0 THEN RETURN false; END IF;
 FOR c IN SELECT * FROM jsonb_array_elements(coalesce(v->'coding','[]'::jsonb)) LOOP
  IF jsonb_typeof(c)<>'object' OR NOT public.ehr_read_text(c->'code',256)
   OR c ? 'system' AND NOT public.ehr_read_text(c->'system',512)
   OR c ? 'display' AND (NOT public.ehr_medication_text(c->'display',1000,true) OR char_length(c->>'display')=0) THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.ehr_fhir_concept_name(v jsonb) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN v ? 'text' THEN v->>'text' ELSE (SELECT CASE WHEN count(DISTINCT c->>'display')=1 THEN min(c->>'display') END FROM jsonb_array_elements(coalesce(v->'coding','[]'::jsonb)) c WHERE c ? 'display') END
$$;
CREATE OR REPLACE FUNCTION public.ehr_read_binding_digest(b public.ehr_read_bindings) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN b.protocol='fhir' THEN public.google_calendar_json_digest(jsonb_build_object('contract','tebra-fhir-connection-scope.v1','fhir_base','https://fhir.prd.cloud.tebra.com/fhir-request',
 'box_id',b.box_id,'owner_id',b.owner_id,'account_id',b.account_id,'connection_id',b.connection_id,'credential_generation',b.credential_generation,'display_label',b.practice_name)) ELSE public.ehr_pre_fhir_binding_digest(b) END
$$;
CREATE FUNCTION public.ehr_fhir_scope(g public.ehr_fhir_patient_grants) RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('box_id',g.box_id,'owner_id',g.owner_id,'connection_id',b.connection_id,'credential_generation',b.credential_generation,'patient_id',g.fhir_patient_id,'authorization_sha256',g.authorization_sha256) FROM public.ehr_read_bindings b WHERE b.id=g.binding_id
$$;
CREATE FUNCTION public.ehr_fhir_scope_digest(g public.ehr_fhir_patient_grants) RETURNS text LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT public.google_calendar_json_digest(public.ehr_fhir_scope(g)||jsonb_build_object('contract','tebra-fhir-patient-scope.v1','fhir_base','https://fhir.prd.cloud.tebra.com/fhir-request'))
$$;
"""

GRANTS = r"""
CREATE FUNCTION public.ehr_fhir_grant_digest(g public.ehr_fhir_patient_grants) RETURNS text LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT public.google_calendar_json_digest(jsonb_build_object('contract','tebra-fhir-patient-grant.v1','grant_id',g.id,'connection_sha256',b.binding_digest,'workspace_id',g.workspace_id,'patient_link_id',g.patient_link_id,'read_scope_sha256',public.ehr_fhir_scope_digest(g),'patient_identity_sha256',g.identity_sha256)) FROM public.ehr_read_bindings b WHERE b.id=g.binding_id
$$;
CREATE FUNCTION public.ehr_fhir_grant_current(gid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.ehr_fhir_patient_grants g JOIN public.ehr_read_bindings b ON b.id=g.binding_id
 JOIN public.encounter_workspaces w ON (w.id,w.box_id,w.owner_id,w.patient_link_id)=(g.workspace_id,g.box_id,g.owner_id,g.patient_link_id)
 JOIN public.patient_links p ON (p.id,p.box_id)=(g.patient_link_id,g.box_id)
 WHERE g.id=gid AND g.state='active' AND g.revoked_at IS NULL AND b.protocol='fhir' AND b.vendor='tebra' AND public.ehr_read_binding_current(b.id)
 AND p.state='confirmed' AND p.revoked_at IS NULL AND g.grant_digest=public.ehr_fhir_grant_digest(g))
$$;
CREATE FUNCTION public.guard_ehr_fhir_grant() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE b public.ehr_read_bindings; identity jsonb;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Retain FHIR grant history' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF to_jsonb(NEW)-'state'-'revoked_at' IS DISTINCT FROM to_jsonb(OLD)-'state'-'revoked_at' OR OLD.state<>'active' OR NEW.state<>'revoked' OR NEW.revoked_at IS NULL OR NOT isfinite(NEW.revoked_at) OR NEW.revoked_at<OLD.created_at THEN RAISE EXCEPTION 'FHIR grant immutable' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO b FROM public.ehr_read_bindings WHERE id=NEW.binding_id FOR UPDATE;
 PERFORM 1 FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 IF b.id IS NULL OR b.protocol IS DISTINCT FROM 'fhir' OR b.vendor<>'tebra' OR NOT public.ehr_read_binding_current(b.id)
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
CREATE TRIGGER ehr_fhir_grant_guard BEFORE INSERT OR UPDATE OR DELETE ON public.ehr_fhir_patient_grants FOR EACH ROW EXECUTE FUNCTION public.guard_ehr_fhir_grant();
"""

CURRENT = r"""
CREATE OR REPLACE FUNCTION public.ehr_read_request_current(rid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN r.kind NOT IN ('fhir_patients','fhir_medications') THEN public.ehr_pre_fhir_request_current(r.id) ELSE EXISTS(
 SELECT 1 FROM public.ehr_read_bindings b JOIN public.encounter_workspaces w ON (w.id,w.box_id,w.owner_id,w.patient_link_id)=(r.workspace_id,r.box_id,r.owner_id,r.patient_link_id)
 JOIN public.patient_links link ON (link.id,link.box_id)=(r.patient_link_id,r.box_id)
 LEFT JOIN public.ehr_read_snapshots z ON z.id=r.parent_snapshot_id LEFT JOIN public.ehr_read_requests p ON p.id=z.observation_id
 WHERE b.id=r.binding_id AND b.protocol='fhir' AND public.ehr_read_binding_current(b.id) AND r.transport='mock' AND r.valid_until>clock_timestamp()
 AND (r.box_id,r.owner_id,r.account_id,r.connection_id,r.credential_generation,r.binding_digest)=(b.box_id,b.owner_id,b.account_id,b.connection_id,b.credential_generation,b.binding_digest)
 AND link.state='confirmed' AND link.revoked_at IS NULL
 AND NOT EXISTS(SELECT 1 FROM public.ehr_read_requests newer WHERE newer.binding_id=r.binding_id AND newer.workspace_id=r.workspace_id AND newer.kind='fhir_patients' AND newer.ordinal>CASE WHEN r.kind='fhir_patients' THEN r.ordinal ELSE p.ordinal END)
 AND (r.kind='fhir_patients' OR (p.kind='fhir_patients' AND (p.binding_id,p.workspace_id,p.patient_link_id)=(r.binding_id,r.workspace_id,r.patient_link_id) AND p.valid_until>=r.valid_until AND public.ehr_fhir_grant_current(r.fhir_grant_id)))) END FROM public.ehr_read_requests r WHERE r.id=rid
$$;
"""

REQUEST = r"""
 IF b.protocol='fhir' THEN
  IF NEW.kind NOT IN ('fhir_patients','fhir_medications') OR NEW.request_json->>'protocol' IS DISTINCT FROM 'fhir' OR NEW.request_json->>'provider' IS DISTINCT FROM 'tebra'
   OR NEW.request_json->>'workspace_id' IS DISTINCT FROM NEW.workspace_id::text
   OR NEW.request_json->>'action' IS DISTINCT FROM NEW.kind
   OR NOT EXISTS(SELECT 1 FROM public.encounter_workspaces w JOIN public.patient_links p ON (p.id,p.box_id)=(w.patient_link_id,w.box_id) WHERE (w.id,w.box_id,w.owner_id,w.patient_link_id)=(NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.patient_link_id) AND p.state='confirmed' AND p.revoked_at IS NULL)
  THEN RAISE EXCEPTION 'FHIR read authority invalid' USING ERRCODE='23514'; END IF;
  IF NEW.kind='fhir_patients' THEN
   IF NOT public.finance_settings_keys(NEW.request_json,ARRAY['provider','protocol','action','workspace_id','connection_id','binding_sha256','idempotency_key']) THEN RAISE EXCEPTION 'FHIR selection request invalid' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT * INTO parent FROM public.ehr_read_snapshots WHERE id=NEW.parent_snapshot_id;
   SELECT * INTO root FROM public.ehr_read_requests WHERE id=parent.observation_id;
   IF root.kind IS DISTINCT FROM 'fhir_patients' OR (root.binding_id,root.box_id,root.owner_id,root.account_id,root.workspace_id,root.patient_link_id) IS DISTINCT FROM (NEW.binding_id,NEW.box_id,NEW.owner_id,NEW.account_id,NEW.workspace_id,NEW.patient_link_id)
    OR NOT public.ehr_read_request_current(root.id) OR NOT public.ehr_read_snapshot_valid(parent.id) OR NEW.valid_until>root.valid_until
    OR NOT public.ehr_fhir_grant_current(NEW.fhir_grant_id)
    OR NOT public.finance_settings_keys(NEW.request_json,ARRAY['provider','protocol','action','workspace_id','connection_id','binding_sha256','idempotency_key','observation_id','observation_sha256','item_handle','item_sha256'])
    OR NEW.request_json->>'observation_id' IS DISTINCT FROM root.id::text OR NEW.request_json->>'observation_sha256' IS DISTINCT FROM parent.source_sha256
    OR NEW.request_json->>'item_handle' IS DISTINCT FROM NEW.item_handle::text
    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent.payload->'private'->'items') item WHERE item->>'handle'=NEW.item_handle::text AND item->>'grant_id'=NEW.fhir_grant_id::text)
    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent.payload->'public'->'items') item WHERE item->>'handle'=NEW.item_handle::text AND item->>'sha256'=NEW.request_json->>'item_sha256')
   THEN RAISE EXCEPTION 'FHIR exact parent invalid' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF NEW.kind IN ('fhir_patients','fhir_medications') OR NEW.request_json ? 'protocol' THEN RAISE EXCEPTION 'Unexpected FHIR protocol' USING ERRCODE='23514'; END IF;
"""

CLINICAL = r"""
CREATE FUNCTION public.ehr_fhir_reader_valid(v jsonb,g public.ehr_fhir_patient_grants) RETURNS boolean LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE row jsonb; choice jsonb; medication jsonb; context jsonb; reported jsonb; dosage jsonb; instruction jsonb; entry jsonb; key text; reference text; identifier text; ids text[]:=ARRAY[]::text[];
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
   ELSIF left(reference,char_length('https://fhir.prd.cloud.tebra.com/fhir-request/Medication/'))='https://fhir.prd.cloud.tebra.com/fhir-request/Medication/' THEN identifier:=substr(reference,char_length('https://fhir.prd.cloud.tebra.com/fhir-request/Medication/')+1);
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
 RETURN coalesce(v->>'source_sha256'=public.google_calendar_json_digest((v-'scope'-'source_sha256')||jsonb_build_object('contract','tebra-fhir-medication-history.v1','scope_sha256',public.ehr_fhir_scope_digest(g))),false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

CONTENT = r"""
CREATE FUNCTION public.ehr_fhir_source_text(v jsonb) RETURNS text LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE result text; row jsonb; position integer:=0; title text;
BEGIN
 result:='Tebra medication records (bounded synthetic snapshot)'||chr(10)||'Patient identity: '||(v->'patient'->>'identity_json')||chr(10)||'Observed: '||(v->>'observed_at')||chr(10)
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

PAYLOAD = r"""
CREATE FUNCTION public.ehr_fhir_payload_valid(payload jsonb,r public.ehr_read_requests) RETURNS boolean LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE pub jsonb:=payload->'public'; priv jsonb:=payload->'private'; b public.ehr_read_bindings; g public.ehr_fhir_patient_grants;
 parent public.ehr_read_snapshots; prior public.ehr_read_requests; item jsonb; shown jsonb; raw jsonb; expected jsonb; content text; contentsha text;
 position integer:=0; handles text[]:=ARRAY[]::text[]; grants text[]:=ARRAY[]::text[];
BEGIN
 SELECT * INTO b FROM public.ehr_read_bindings WHERE id=r.binding_id;
 IF b.protocol IS DISTINCT FROM 'fhir' OR b.vendor<>'tebra' OR r.transport<>'mock' OR r.kind NOT IN ('fhir_patients','fhir_medications')
 OR NOT public.finance_settings_keys(payload,ARRAY['public','private'])
 OR NOT public.finance_settings_keys(priv,ARRAY['protocol','transport','binding_sha256','request_sha256','workspace_id','patient_link_id','items','reader_snapshot_json','review_sha256'])
 OR priv->>'protocol' IS DISTINCT FROM 'fhir' OR priv->>'transport' IS DISTINCT FROM 'mock'
 OR priv->>'binding_sha256' IS DISTINCT FROM r.binding_digest OR priv->>'request_sha256' IS DISTINCT FROM r.request_hash
 OR priv->>'workspace_id' IS DISTINCT FROM r.workspace_id::text OR priv->>'patient_link_id' IS DISTINCT FROM r.patient_link_id::text
 OR pub->>'workspace_id' IS DISTINCT FROM r.workspace_id::text OR pub->>'display_label' IS DISTINCT FROM b.practice_name
 OR pub->>'provider' IS DISTINCT FROM 'tebra' OR pub->>'protocol' IS DISTINCT FROM 'fhir' OR pub->>'mode' IS DISTINCT FROM 'synthetic'
 OR pub->>'kind' IS DISTINCT FROM r.kind OR NOT public.google_message_aware_time(pub->'observed_at')
 OR jsonb_typeof(priv->'items') IS DISTINCT FROM 'array' OR jsonb_array_length(priv->'items')>25
 THEN RETURN false; END IF;
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
 IF priv->>'reader_snapshot_json' IS DISTINCT FROM public.clinical_note_ascii_canonical(raw) OR public.ehr_fhir_reader_valid(raw,g) IS NOT TRUE THEN RETURN false; END IF;
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
 content:=public.ehr_fhir_source_text(raw); contentsha:=encode(sha256(convert_to(content,'UTF8')),'hex');
 IF content IS NULL OR char_length(content)>5000 THEN RETURN false; END IF;
 expected:=jsonb_build_object('handle',item->'handle','patient_identity_json',g.identity_json,'coverage',raw->'coverage','reported_total',raw->'reported_total','warnings',raw->'warnings',
 'records',(SELECT coalesce(jsonb_agg(row-'record_id'-'patient_id' ORDER BY ordinal),'[]'::jsonb) FROM jsonb_array_elements(raw->'rows') WITH ORDINALITY rows(row,ordinal)),
 'source_content',content,'content_sha256',contentsha);
 expected:=expected||jsonb_build_object('sha256',public.google_calendar_json_digest(jsonb_build_object('kind','ehr_tebra_fhir_medications_item.v1','item',expected)));
 RETURN coalesce(pub->'item'=expected AND priv->>'review_sha256'=public.google_calendar_json_digest(jsonb_build_object('contract','tebra-fhir-review-snapshot.v1','scope_sha256',public.ehr_fhir_scope_digest(g),
 'observation_sha256',raw->>'source_sha256','patient_identity_sha256',g.identity_sha256,'source_content_sha256',contentsha,'completeness','bounded_recorded_history')),false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

SOURCES = r"""
CREATE FUNCTION public.ehr_fhir_source_valid(eid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.ehr_read_source_reviews v JOIN public.workspace_entries e ON e.id=v.entry_id
 JOIN public.encounter_workspaces w ON w.id=v.workspace_id JOIN public.ehr_read_snapshots z ON z.id=v.snapshot_id JOIN public.ehr_read_requests r ON r.id=z.observation_id
 WHERE e.id=eid AND e.kind='ehr_read_source' AND r.kind='fhir_medications' AND v.command_provider='tebra' AND v.command_protocol='fhir' AND v.reviewed_visit IS NULL
 AND (e.workspace_id,e.box_id,e.actor_id,e.revision,e.request_hash,e.idempotency_key)=(v.workspace_id,v.box_id,v.owner_id,v.workspace_revision,v.request_hash,v.idempotency_key)
 AND (w.box_id,w.owner_id,w.patient_link_id)=(v.box_id,v.owner_id,v.patient_link_id)
 AND (r.box_id,r.owner_id,r.workspace_id,r.patient_link_id,z.box_id,z.owner_id)=(v.box_id,v.owner_id,v.workspace_id,v.patient_link_id,v.box_id,v.owner_id)
 AND public.ehr_read_snapshot_valid(z.id) AND v.workspace_revision=v.expected_revision+1 AND v.reviewed_patient_identity AND v.reviewed_exact_snapshot AND v.reviewed_untrusted_source
 AND v.item_handle=r.item_handle AND z.payload->'public'->'item'->>'handle'=v.item_handle::text AND v.item_sha256=z.payload->'public'->'item'->>'sha256' AND v.observation_sha256=z.source_sha256
 AND v.source_sha256=public.google_calendar_json_digest(jsonb_build_object('observation_sha256',v.observation_sha256,'item_handle',v.item_handle,'item_sha256',v.item_sha256))
 AND v.request_hash=public.google_calendar_json_digest(jsonb_build_object('provider','tebra','protocol','fhir','workspace_id',v.workspace_id,'expected_revision',v.expected_revision,'idempotency_key',v.idempotency_key,
 'observation_id',r.id,'observation_sha256',v.observation_sha256,'item_handle',v.item_handle,'item_sha256',v.item_sha256,'reviewed_patient_identity',true,'reviewed_exact_snapshot',true,'reviewed_untrusted_source',true))
 AND e.content=public.ehr_read_source_content(z.payload->'public') AND e.source_label='Tebra: reviewed medication records'
 AND v.content_sha256=encode(sha256(convert_to(e.content,'UTF8')),'hex') AND v.valid_until=r.valid_until)
$$;
CREATE OR REPLACE FUNCTION public.ehr_read_source_valid(eid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM public.ehr_read_source_reviews WHERE entry_id=eid AND command_protocol='fhir') THEN public.ehr_fhir_source_valid(eid) ELSE public.ehr_pre_fhir_source_valid(eid) END
$$;
"""
