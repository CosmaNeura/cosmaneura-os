"""Independent Athena clinical grants and bounded recorded allergy source custody."""
from alembic import op

revision = "u80a6b9e4321"
down_revision = "t79f5a8d3210"
branch_labels = None
depends_on = None


def definition(signature):
    return op.get_bind().exec_driver_sql("SELECT pg_get_functiondef(%s::regprocedure)", (signature,)).scalar_one()


def changed(sql, pairs):
    for before, after in pairs:
        if sql.count(before) != 1:
            raise RuntimeError("Prior EHR guard differs from Athena extension: " + before)
        sql = sql.replace(before, after)
    return sql


def upgrade():
    op.execute(TABLES)
    op.execute("ALTER TABLE ehr_read_requests ADD COLUMN athena_grant_id uuid")
    op.execute("ALTER TABLE ehr_read_requests ADD CONSTRAINT fk_ehr_read_athena_grant FOREIGN KEY(athena_grant_id,box_id,owner_id,workspace_id,patient_link_id) REFERENCES ehr_athena_core_patient_grants(id,box_id,owner_id,workspace_id,patient_link_id)")
    for table, constraints in CONSTRAINTS.items():
        for name, sql in constraints.items():
            op.drop_constraint(name, table)
            op.create_check_constraint(name, table, sql)
    for signature in ("public.ehr_read_binding_digest(public.ehr_read_bindings)", "public.ehr_read_request_current(uuid)", "public.ehr_read_payload_valid(jsonb,public.ehr_read_requests)", "public.ehr_read_source_content(jsonb)", "public.ehr_read_source_valid(uuid)"):
        name=signature.split("(")[0]
        op.execute(definition(signature).replace(name+"(",name.replace("ehr_read_","ehr_pre_athena_")+"(",1))
    op.execute(FIELDS)
    op.execute(GRANTS)
    op.execute(CURRENT)
    op.execute(changed(definition("public.guard_ehr_read_request()"), ((" IF b.protocol='fhir' THEN", REQUEST + " IF b.protocol='fhir' THEN"),)))
    op.execute(CLINICAL)
    op.execute(CONTENT)
    op.execute(PAYLOAD)
    op.execute("""CREATE OR REPLACE FUNCTION public.ehr_read_payload_valid(payload jsonb,r public.ehr_read_requests) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$ SELECT CASE WHEN r.kind IN ('core_patients','core_allergies') THEN coalesce(public.ehr_athena_payload_valid(payload,r),false) ELSE public.ehr_pre_athena_payload_valid(payload,r) END $$""")
    op.execute("""CREATE OR REPLACE FUNCTION public.ehr_read_source_content(pub jsonb) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$ SELECT CASE WHEN pub->>'protocol'='core' AND pub->>'kind'='core_allergies' THEN pub->'item'->>'source_content' ELSE public.ehr_pre_athena_source_content(pub) END $$""")
    op.execute(SOURCES)
    op.execute(changed(definition("public.guard_ehr_read_snapshot()"), ((" RETURN NEW;", """
 IF r.kind IN ('core_patients','core_allergies') THEN
  PERFORM 1 FROM public.ehr_athena_core_patient_grants WHERE id::text IN (SELECT item->>'grant_id' FROM jsonb_array_elements(NEW.payload->'private'->'items') item) FOR SHARE;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.payload->'private'->'items') item WHERE public.ehr_athena_grant_current((item->>'grant_id')::uuid) IS NOT TRUE) THEN RAISE EXCEPTION 'Athena snapshot grant changed' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;"""),)))
    op.execute(changed(definition("public.guard_ehr_read_review()"), (("r.kind NOT IN ('verify','problems','medications','fhir_medications')", "r.kind NOT IN ('verify','problems','medications','fhir_medications','core_allergies')"),
        (" IF w.id IS NULL", " PERFORM 1 FROM public.ehr_athena_core_patient_grants WHERE id=r.athena_grant_id FOR SHARE;\n IF w.id IS NULL"),
        ("r.kind='fhir_medications' AND", "r.kind IN ('fhir_medications','core_allergies') AND"))))


def downgrade():
    raise RuntimeError("Retain Athena clinical grants and reviewed allergy history")

CONSTRAINTS = {'ehr_read_bindings': {'ck_ehr_read_binding_vendor': "coalesce((protocol IS NULL AND vendor='elation' AND environment='sandbox' AND customer_id IS NULL AND practice_timezone IS NULL) OR (protocol IS NULL AND vendor='tebra' AND environment='synthetic' AND customer_id IS NOT NULL AND customer_id ~ '^[1-9][0-9]{0,9}$' AND customer_id::numeric<=2147483647 AND practice_id::numeric<=2147483647 AND practice_timezone IS NOT NULL) OR (protocol='fhir' AND vendor='tebra' AND environment='synthetic' AND practice_id IS NULL AND customer_id IS NULL AND practice_timezone IS NULL) OR (protocol='core' AND vendor='athena' AND environment IN ('preview','production') AND customer_id IS NULL AND practice_timezone IS NULL),false)", 'ck_ehr_read_binding_practice': "coalesce((protocol='fhir' AND practice_id IS NULL) OR (protocol IS NULL AND practice_id IS NOT NULL AND practice_id ~ '^[1-9][0-9]*$' AND char_length(practice_id)<=19 AND practice_id::numeric<=9223372036854775807) OR (protocol='core' AND practice_id IS NOT NULL AND practice_id ~ '^[1-9][0-9]{0,17}$'),false)"}, 'ehr_read_requests': {'ck_ehr_read_request_kind': "(((kind='window' AND parent_snapshot_id IS NULL AND item_handle IS NULL) OR (kind IN ('verify','problems','medications') AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL)) AND workspace_id IS NULL AND patient_link_id IS NULL AND fhir_grant_id IS NULL AND athena_grant_id IS NULL) OR (kind IN ('fhir_patients','core_patients') AND parent_snapshot_id IS NULL AND item_handle IS NULL AND fhir_grant_id IS NULL AND athena_grant_id IS NULL AND workspace_id IS NOT NULL AND patient_link_id IS NOT NULL) OR (kind='fhir_medications' AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL AND fhir_grant_id IS NOT NULL AND athena_grant_id IS NULL AND workspace_id IS NOT NULL AND patient_link_id IS NOT NULL) OR (kind='core_allergies' AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL AND athena_grant_id IS NOT NULL AND fhir_grant_id IS NULL AND workspace_id IS NOT NULL AND patient_link_id IS NOT NULL)", 'ck_ehr_read_request_window': "(kind IN ('fhir_patients','fhir_medications') AND window_start IS NULL AND window_end IS NULL AND practice_id IS NULL) OR (kind IN ('core_patients','core_allergies') AND window_start IS NULL AND window_end IS NULL AND practice_id IS NOT NULL) OR (kind NOT IN ('fhir_patients','fhir_medications','core_patients','core_allergies') AND window_start IS NOT NULL AND window_end IS NOT NULL AND practice_id IS NOT NULL AND isfinite(window_start) AND isfinite(window_end) AND window_end>window_start AND window_end<=window_start+interval '168 hours')"}, 'ehr_read_source_reviews': {'ck_ehr_review_provider': "command_provider IS NULL OR command_provider IN ('elation','tebra','athena')", 'ck_ehr_review_protocol': "coalesce(command_protocol IS NULL OR (command_protocol='fhir' AND command_provider='tebra') OR (command_protocol='core' AND command_provider='athena'),false)", 'ck_ehr_read_review_checks': "coalesce(((command_protocol IS NULL AND reviewed_visit IS TRUE) OR (command_protocol IN ('fhir','core') AND reviewed_visit IS NULL)) AND reviewed_patient_identity AND reviewed_exact_snapshot AND reviewed_untrusted_source,false)"}}

TABLES = "\nCREATE TABLE ehr_athena_core_patient_grants (\n\tid UUID NOT NULL, \n\tbinding_id UUID NOT NULL, \n\taccount_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tpatient_link_id UUID NOT NULL, \n\tpatient_id VARCHAR(18) NOT NULL,\n department_id VARCHAR(18) NOT NULL,\n department_label VARCHAR(200) NOT NULL, \n\tauthorization_sha256 VARCHAR(64) NOT NULL, \n\tidentity_json TEXT NOT NULL, \n\tidentity_sha256 VARCHAR(64) NOT NULL, \n\tgrant_digest VARCHAR(64) NOT NULL, \n\tstate VARCHAR(16) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(binding_id, box_id, owner_id, account_id) REFERENCES ehr_read_bindings (id, box_id, owner_id, account_id), \n\tFOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), \n\tFOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id), \n\tCONSTRAINT uq_ehr_athena_core_grant_scope UNIQUE (id, box_id, owner_id, workspace_id, patient_link_id), \n\tCONSTRAINT ck_ehr_athena_core_grant_patient CHECK (patient_id ~ '^[1-9][0-9]{0,17}$' AND department_id ~ '^[1-9][0-9]{0,17}$'), \n\tCONSTRAINT ck_ehr_athena_core_grant_identity_size CHECK (char_length(identity_json) BETWEEN 2 AND 20000), \n\tCONSTRAINT ck_ehr_athena_core_grant_state CHECK ((state='active' AND revoked_at IS NULL) OR (state='revoked' AND revoked_at IS NOT NULL)), \n CONSTRAINT ck_ehr_athena_core_department_label CHECK(char_length(department_label) BETWEEN 1 AND 200 AND department_label !~ '[[:cntrl:]]'),\n\tCHECK (authorization_sha256 ~ '^[a-f0-9]{64}$' AND identity_sha256 ~ '^[a-f0-9]{64}$' AND grant_digest ~ '^[a-f0-9]{64}$')\n)\n\n;\nCREATE UNIQUE INDEX uq_ehr_athena_core_grant_active ON ehr_athena_core_patient_grants (binding_id, workspace_id, patient_link_id, department_id, patient_id) WHERE state='active';"

GRANTS = r"""
CREATE FUNCTION public.ehr_athena_grant_digest(g public.ehr_athena_core_patient_grants) RETURNS text LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT public.google_calendar_json_digest(jsonb_build_object('contract','athena-allergy-patient-grant.v1','grant_id',g.id,'scope_sha256',public.ehr_athena_scope_digest(g),'patient_identity_sha256',g.identity_sha256))
$$;
CREATE FUNCTION public.ehr_athena_grant_current(gid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.ehr_athena_core_patient_grants g JOIN public.ehr_read_bindings b ON b.id=g.binding_id
 JOIN public.encounter_workspaces w ON (w.id,w.box_id,w.owner_id,w.patient_link_id)=(g.workspace_id,g.box_id,g.owner_id,g.patient_link_id)
 JOIN public.patient_links p ON (p.id,p.box_id)=(g.patient_link_id,g.box_id)
 WHERE g.id=gid AND g.state='active' AND g.revoked_at IS NULL AND b.protocol='core' AND b.vendor='athena' AND public.ehr_read_binding_current(b.id)
 AND p.state='confirmed' AND p.revoked_at IS NULL AND g.grant_digest=public.ehr_athena_grant_digest(g))
$$;
CREATE FUNCTION public.guard_ehr_athena_grant() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE b public.ehr_read_bindings;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Retain Athena grant history' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF to_jsonb(NEW)-'state'-'revoked_at' IS DISTINCT FROM to_jsonb(OLD)-'state'-'revoked_at' OR OLD.state<>'active' OR NEW.state<>'revoked' OR NEW.revoked_at IS NULL OR NOT isfinite(NEW.revoked_at) OR NEW.revoked_at<OLD.created_at THEN RAISE EXCEPTION 'Athena grant immutable' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO b FROM public.ehr_read_bindings WHERE id=NEW.binding_id FOR UPDATE;
 PERFORM 1 FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 IF b.id IS NULL OR b.protocol IS DISTINCT FROM 'core' OR b.vendor<>'athena' OR NOT public.ehr_read_binding_current(b.id)
 OR (NEW.box_id,NEW.owner_id,NEW.account_id) IS DISTINCT FROM (b.box_id,b.owner_id,b.account_id)
 OR NEW.state<>'active' OR NEW.revoked_at IS NOT NULL OR NOT isfinite(NEW.created_at)
 OR NOT EXISTS(SELECT 1 FROM public.encounter_workspaces w JOIN public.patient_links p ON (p.id,p.box_id)=(w.patient_link_id,w.box_id) WHERE (w.id,w.box_id,w.owner_id,w.patient_link_id)=(NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.patient_link_id) AND p.state='confirmed' AND p.revoked_at IS NULL)
 OR octet_length(NEW.identity_json)>16384 OR public.ehr_athena_identity(NEW.identity_json,NEW.patient_id) IS NOT TRUE
 THEN RAISE EXCEPTION 'Athena grant authority invalid' USING ERRCODE='23514'; END IF;
 IF NEW.identity_sha256 IS DISTINCT FROM encode(sha256(convert_to(NEW.identity_json,'UTF8')),'hex')
 OR NEW.grant_digest IS DISTINCT FROM public.ehr_athena_grant_digest(NEW)
 THEN RAISE EXCEPTION 'Athena grant identity invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ehr_athena_grant_guard BEFORE INSERT OR UPDATE OR DELETE ON public.ehr_athena_core_patient_grants FOR EACH ROW EXECUTE FUNCTION public.guard_ehr_athena_grant();
"""

CURRENT = r"""
CREATE OR REPLACE FUNCTION public.ehr_read_request_current(rid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN r.kind NOT IN ('core_patients','core_allergies') THEN public.ehr_pre_athena_request_current(r.id) ELSE EXISTS(
 SELECT 1 FROM public.ehr_read_bindings b JOIN public.encounter_workspaces w ON (w.id,w.box_id,w.owner_id,w.patient_link_id)=(r.workspace_id,r.box_id,r.owner_id,r.patient_link_id)
 JOIN public.patient_links link ON (link.id,link.box_id)=(r.patient_link_id,r.box_id)
 LEFT JOIN public.ehr_read_snapshots z ON z.id=r.parent_snapshot_id LEFT JOIN public.ehr_read_requests p ON p.id=z.observation_id
 WHERE b.id=r.binding_id AND b.protocol='core' AND public.ehr_read_binding_current(b.id) AND r.transport='mock' AND r.valid_until>clock_timestamp()
 AND (r.box_id,r.owner_id,r.account_id,r.connection_id,r.credential_generation,r.binding_digest)=(b.box_id,b.owner_id,b.account_id,b.connection_id,b.credential_generation,b.binding_digest)
 AND link.state='confirmed' AND link.revoked_at IS NULL
 AND NOT EXISTS(SELECT 1 FROM public.ehr_read_requests newer WHERE newer.binding_id=r.binding_id AND newer.workspace_id=r.workspace_id AND newer.kind='core_patients' AND newer.ordinal>CASE WHEN r.kind='core_patients' THEN r.ordinal ELSE p.ordinal END)
 AND (r.kind='core_patients' OR (p.kind='core_patients' AND (p.binding_id,p.workspace_id,p.patient_link_id)=(r.binding_id,r.workspace_id,r.patient_link_id) AND p.valid_until>=r.valid_until AND public.ehr_athena_grant_current(r.athena_grant_id)))) END FROM public.ehr_read_requests r WHERE r.id=rid
$$;
"""

REQUEST = r"""
 IF b.protocol='core' THEN
  IF NEW.kind NOT IN ('core_patients','core_allergies') OR NEW.request_json->>'protocol' IS DISTINCT FROM 'core' OR NEW.request_json->>'provider' IS DISTINCT FROM 'athena'
   OR NEW.request_json->>'workspace_id' IS DISTINCT FROM NEW.workspace_id::text
   OR NEW.request_json->>'action' IS DISTINCT FROM NEW.kind
   OR NOT EXISTS(SELECT 1 FROM public.encounter_workspaces w JOIN public.patient_links p ON (p.id,p.box_id)=(w.patient_link_id,w.box_id) WHERE (w.id,w.box_id,w.owner_id,w.patient_link_id)=(NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.patient_link_id) AND p.state='confirmed' AND p.revoked_at IS NULL)
  THEN RAISE EXCEPTION 'Athena read authority invalid' USING ERRCODE='23514'; END IF;
  IF NEW.kind='core_patients' THEN
   IF NOT public.finance_settings_keys(NEW.request_json,ARRAY['provider','protocol','action','workspace_id','connection_id','binding_sha256','idempotency_key']) THEN RAISE EXCEPTION 'Athena selection request invalid' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT * INTO parent FROM public.ehr_read_snapshots WHERE id=NEW.parent_snapshot_id;
   SELECT * INTO root FROM public.ehr_read_requests WHERE id=parent.observation_id;
   IF root.kind IS DISTINCT FROM 'core_patients' OR (root.binding_id,root.box_id,root.owner_id,root.account_id,root.workspace_id,root.patient_link_id) IS DISTINCT FROM (NEW.binding_id,NEW.box_id,NEW.owner_id,NEW.account_id,NEW.workspace_id,NEW.patient_link_id)
    OR NOT public.ehr_read_request_current(root.id) OR NOT public.ehr_read_snapshot_valid(parent.id) OR NEW.valid_until>root.valid_until
    OR NOT public.ehr_athena_grant_current(NEW.athena_grant_id)
    OR NOT public.finance_settings_keys(NEW.request_json,ARRAY['provider','protocol','action','workspace_id','connection_id','binding_sha256','idempotency_key','observation_id','observation_sha256','item_handle','item_sha256'])
    OR NEW.request_json->>'observation_id' IS DISTINCT FROM root.id::text OR NEW.request_json->>'observation_sha256' IS DISTINCT FROM parent.source_sha256
    OR NEW.request_json->>'item_handle' IS DISTINCT FROM NEW.item_handle::text
    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent.payload->'private'->'items') item WHERE item->>'handle'=NEW.item_handle::text AND item->>'grant_id'=NEW.athena_grant_id::text)
    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent.payload->'public'->'items') item WHERE item->>'handle'=NEW.item_handle::text AND item->>'sha256'=NEW.request_json->>'item_sha256')
   THEN RAISE EXCEPTION 'Athena exact parent invalid' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF NEW.kind IN ('core_patients','core_allergies') THEN RAISE EXCEPTION 'Unexpected Athena protocol' USING ERRCODE='23514'; END IF;
"""

PAYLOAD = r"""
CREATE FUNCTION public.ehr_athena_payload_valid(payload jsonb,r public.ehr_read_requests) RETURNS boolean LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE pub jsonb:=payload->'public'; priv jsonb:=payload->'private'; b public.ehr_read_bindings; g public.ehr_athena_core_patient_grants;
 parent public.ehr_read_snapshots; prior public.ehr_read_requests; item jsonb; shown jsonb; raw jsonb; expected jsonb; content text; contentsha text;
 position integer:=0; handles text[]:=ARRAY[]::text[]; grants text[]:=ARRAY[]::text[];
BEGIN
 SELECT * INTO b FROM public.ehr_read_bindings WHERE id=r.binding_id;
 IF b.protocol IS DISTINCT FROM 'core' OR b.vendor<>'athena' OR r.transport<>'mock' OR r.kind NOT IN ('core_patients','core_allergies')
 OR NOT public.finance_settings_keys(payload,ARRAY['public','private'])
 OR NOT public.finance_settings_keys(priv,ARRAY['protocol','transport','binding_sha256','request_sha256','workspace_id','patient_link_id','items','reader_snapshot_json','review_sha256'])
 OR priv->>'protocol' IS DISTINCT FROM 'core' OR priv->>'transport' IS DISTINCT FROM 'mock'
 OR priv->>'binding_sha256' IS DISTINCT FROM r.binding_digest OR priv->>'request_sha256' IS DISTINCT FROM r.request_hash
 OR priv->>'workspace_id' IS DISTINCT FROM r.workspace_id::text OR priv->>'patient_link_id' IS DISTINCT FROM r.patient_link_id::text
 OR pub->>'workspace_id' IS DISTINCT FROM r.workspace_id::text OR pub->>'practice_label' IS DISTINCT FROM b.practice_name
 OR pub->>'provider' IS DISTINCT FROM 'athena' OR pub->>'protocol' IS DISTINCT FROM 'core' OR pub->>'mode' IS DISTINCT FROM 'synthetic'
 OR pub->>'kind' IS DISTINCT FROM r.kind OR NOT public.google_message_aware_time(pub->'observed_at')
 OR jsonb_typeof(priv->'items') IS DISTINCT FROM 'array' OR jsonb_array_length(priv->'items')>25
 THEN RETURN false; END IF;
 FOR item IN SELECT * FROM jsonb_array_elements(priv->'items') LOOP
  SELECT * INTO g FROM public.ehr_athena_core_patient_grants WHERE id::text=item->>'grant_id';
  IF NOT public.finance_settings_keys(item,ARRAY['handle','grant_id','grant_sha256','patient_identity_json']) OR g.id IS NULL
   OR jsonb_typeof(item->'handle') IS DISTINCT FROM 'string' OR item->>'handle' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR item->>'handle'=ANY(handles) OR item->>'grant_id'=ANY(grants)
   OR (g.binding_id,g.box_id,g.owner_id,g.account_id,g.workspace_id,g.patient_link_id) IS DISTINCT FROM (r.binding_id,r.box_id,r.owner_id,r.account_id,r.workspace_id,r.patient_link_id)
   OR item->>'grant_sha256' IS DISTINCT FROM g.grant_digest OR g.grant_digest IS DISTINCT FROM public.ehr_athena_grant_digest(g)
   OR item->>'patient_identity_json' IS DISTINCT FROM g.identity_json THEN RETURN false; END IF;
  handles:=array_append(handles,item->>'handle'); grants:=array_append(grants,item->>'grant_id');
  IF r.kind='core_patients' THEN
   shown:=pub->'items'->position; expected:=jsonb_build_object('handle',item->'handle','patient_identity_json',public.ehr_athena_public_identity(g.identity_json),'department_label',g.department_label);
   expected:=expected||jsonb_build_object('sha256',public.google_calendar_json_digest(jsonb_build_object('kind','ehr_athena_core_patient_item.v1','item',expected)));
   IF shown IS DISTINCT FROM expected THEN RETURN false; END IF;
  END IF;
  position:=position+1;
 END LOOP;
 IF r.kind='core_patients' THEN
  RETURN coalesce(public.finance_settings_keys(pub,ARRAY['provider','protocol','mode','kind','workspace_id','practice_label','observed_at','coverage','items'])
   AND pub->>'coverage'='authorized_candidates_only' AND jsonb_typeof(pub->'items')='array' AND jsonb_array_length(pub->'items')=position
   AND priv->'reader_snapshot_json'='null'::jsonb AND priv->'review_sha256'='null'::jsonb,false);
 END IF;
 IF position<>1 OR NOT public.finance_settings_keys(pub,ARRAY['provider','protocol','mode','kind','workspace_id','practice_label','observed_at','parent','item'])
 OR public.research_hash(priv->'review_sha256') IS NOT TRUE
 OR g.id IS DISTINCT FROM r.athena_grant_id OR item->>'handle' IS DISTINCT FROM r.item_handle::text
 OR jsonb_typeof(priv->'reader_snapshot_json') IS DISTINCT FROM 'string' OR char_length(priv->>'reader_snapshot_json')>65536 THEN RETURN false; END IF;
 raw:=(priv->>'reader_snapshot_json')::jsonb;
 IF priv->>'reader_snapshot_json' IS DISTINCT FROM public.clinical_note_ascii_canonical(raw) OR public.ehr_athena_reader_valid(raw,g) IS NOT TRUE THEN RETURN false; END IF;
 SELECT * INTO parent FROM public.ehr_read_snapshots WHERE id=r.parent_snapshot_id;
 SELECT * INTO prior FROM public.ehr_read_requests WHERE id=parent.observation_id;
 IF prior.kind IS DISTINCT FROM 'core_patients' OR NOT public.ehr_read_snapshot_valid(parent.id)
 OR (prior.binding_id,prior.workspace_id,prior.patient_link_id) IS DISTINCT FROM (r.binding_id,r.workspace_id,r.patient_link_id)
 OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent.payload->'private'->'items') old WHERE old=item)
 OR pub->'parent' IS DISTINCT FROM jsonb_build_object('observation_id',prior.id,'source_sha256',parent.source_sha256,'item_sha256',r.request_json->>'item_sha256')
 OR r.request_json->>'observation_id' IS DISTINCT FROM prior.id::text OR r.request_json->>'observation_sha256' IS DISTINCT FROM parent.source_sha256
 OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent.payload->'public'->'items') old WHERE old->>'handle'=r.item_handle::text AND old->>'sha256'=r.request_json->>'item_sha256')
 OR pub->>'observed_at' IS DISTINCT FROM replace(raw->>'observed_at','+00:00','Z')
 THEN RETURN false; END IF;
 content:=public.ehr_athena_source_text(raw); contentsha:=encode(sha256(convert_to(content,'UTF8')),'hex');
 IF content IS NULL OR char_length(content)>5000 THEN RETURN false; END IF;
 expected:=jsonb_build_object('handle',item->'handle','patient_identity_json',public.ehr_athena_public_identity(g.identity_json),'department_label',g.department_label,'coverage',raw->'coverage','includes_inactive',raw->'includes_inactive','section_json',raw->'section_json','source_content',content,'content_sha256',contentsha);
 expected:=expected||jsonb_build_object('sha256',public.google_calendar_json_digest(jsonb_build_object('kind','ehr_athena_core_allergies_item.v1','item',expected)));
 RETURN coalesce(pub->'item'=expected AND priv->>'review_sha256'=public.google_calendar_json_digest(jsonb_build_object('contract','athena-allergy-review-snapshot.v1','scope_sha256',public.ehr_athena_scope_digest(g),
 'observation_sha256',raw->>'source_sha256','patient_identity_sha256',g.identity_sha256,'source_content_sha256',contentsha,'completeness','bounded_recorded_allergy_section')),false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

SOURCES = r"""
CREATE FUNCTION public.ehr_athena_source_valid(eid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.ehr_read_source_reviews v JOIN public.workspace_entries e ON e.id=v.entry_id
 JOIN public.encounter_workspaces w ON w.id=v.workspace_id JOIN public.ehr_read_snapshots z ON z.id=v.snapshot_id JOIN public.ehr_read_requests r ON r.id=z.observation_id
 WHERE e.id=eid AND e.kind='ehr_read_source' AND r.kind='core_allergies' AND v.command_provider='athena' AND v.command_protocol='core' AND v.reviewed_visit IS NULL
 AND (e.workspace_id,e.box_id,e.actor_id,e.revision,e.request_hash,e.idempotency_key)=(v.workspace_id,v.box_id,v.owner_id,v.workspace_revision,v.request_hash,v.idempotency_key)
 AND (w.box_id,w.owner_id,w.patient_link_id)=(v.box_id,v.owner_id,v.patient_link_id)
 AND (r.box_id,r.owner_id,r.workspace_id,r.patient_link_id,z.box_id,z.owner_id)=(v.box_id,v.owner_id,v.workspace_id,v.patient_link_id,v.box_id,v.owner_id)
 AND public.ehr_read_snapshot_valid(z.id) AND v.workspace_revision=v.expected_revision+1 AND v.reviewed_patient_identity AND v.reviewed_exact_snapshot AND v.reviewed_untrusted_source
 AND v.item_handle=r.item_handle AND z.payload->'public'->'item'->>'handle'=v.item_handle::text AND v.item_sha256=z.payload->'public'->'item'->>'sha256' AND v.observation_sha256=z.source_sha256
 AND v.source_sha256=public.google_calendar_json_digest(jsonb_build_object('observation_sha256',v.observation_sha256,'item_handle',v.item_handle,'item_sha256',v.item_sha256))
 AND v.request_hash=public.google_calendar_json_digest(jsonb_build_object('provider','athena','protocol','core','workspace_id',v.workspace_id,'expected_revision',v.expected_revision,'idempotency_key',v.idempotency_key,
 'observation_id',r.id,'observation_sha256',v.observation_sha256,'item_handle',v.item_handle,'item_sha256',v.item_sha256,'reviewed_patient_identity',true,'reviewed_exact_snapshot',true,'reviewed_untrusted_source',true))
 AND e.content=public.ehr_read_source_content(z.payload->'public') AND e.source_label='Athena: reviewed allergy records'
 AND v.content_sha256=encode(sha256(convert_to(e.content,'UTF8')),'hex') AND v.valid_until=r.valid_until)
$$;
CREATE OR REPLACE FUNCTION public.ehr_read_source_valid(eid uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM public.ehr_read_source_reviews WHERE entry_id=eid AND command_protocol='core') THEN public.ehr_athena_source_valid(eid) ELSE public.ehr_pre_athena_source_valid(eid) END
$$;
"""

FIELDS = r"""
CREATE FUNCTION public.ehr_athena_text(v jsonb,maximum integer,multiline boolean DEFAULT false) RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT coalesce(jsonb_typeof(v)='string' AND public.ehr_medication_text(v,maximum,multiline),false)
$$;
CREATE FUNCTION public.ehr_athena_nonblank(v text) RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT coalesce(btrim(v,U&' \0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000')<>'',false)
$$;
CREATE FUNCTION public.ehr_athena_identity(raw text,patient text) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE v jsonb; item record; d text;
BEGIN
 v:=raw::jsonb;
 IF octet_length(raw)>16384 OR raw IS DISTINCT FROM public.clinical_note_ascii_canonical(v)
 OR jsonb_typeof(v) IS DISTINCT FROM 'object' OR v-ARRAY['patientid','firstname','middlename','lastname','dob','status','deceaseddate','departmentid','primarydepartmentid']<>'{}'::jsonb
 OR v->>'patientid' IS DISTINCT FROM patient OR patient !~ '^[1-9][0-9]{0,17}$'
 OR public.ehr_athena_nonblank(v->>'firstname') IS NOT TRUE OR public.ehr_athena_nonblank(v->>'lastname') IS NOT TRUE
 THEN RETURN false; END IF;
 FOR item IN SELECT * FROM jsonb_each(v) LOOP IF public.ehr_athena_text(item.value,300) IS NOT TRUE THEN RETURN false; END IF; END LOOP;
 d:=v->>'dob';
 IF d IS NOT NULL AND d<>'' AND (d !~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' OR public.google_calendar_date(to_jsonb(substring(d,7,4)||'-'||left(d,2)||'-'||substring(d,4,2))) IS NOT TRUE) THEN RETURN false; END IF;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.ehr_athena_public_identity(raw text) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT public.clinical_note_ascii_canonical(raw::jsonb-ARRAY['patientid','departmentid','primarydepartmentid'])
$$;
CREATE FUNCTION public.ehr_athena_origin(environment text) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE environment WHEN 'preview' THEN 'https://api.preview.platform.athenahealth.com' WHEN 'production' THEN 'https://api.platform.athenahealth.com' END
$$;
CREATE OR REPLACE FUNCTION public.ehr_read_binding_digest(b public.ehr_read_bindings) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN b.protocol='core' THEN public.google_calendar_json_digest(jsonb_build_object('contract','athena-allergy-connection-scope.v1','origin',public.ehr_athena_origin(b.environment),
 'box_id',b.box_id,'owner_id',b.owner_id,'account_id',b.account_id,'connection_id',b.connection_id,'credential_generation',b.credential_generation,'practice_id',b.practice_id,'practice_label',b.practice_name,'environment',b.environment)) ELSE public.ehr_pre_athena_binding_digest(b) END
$$;
CREATE FUNCTION public.ehr_athena_scope(g public.ehr_athena_core_patient_grants) RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('box_id',g.box_id,'owner_id',g.owner_id,'account_id',g.account_id,'connection_id',b.connection_id,'credential_generation',b.credential_generation,
 'workspace_id',g.workspace_id,'patient_link_id',g.patient_link_id,'practice_id',b.practice_id,'department_id',g.department_id,'patient_id',g.patient_id,
 'practice_label',b.practice_name,'department_label',g.department_label,'authorization_sha256',g.authorization_sha256,'environment',b.environment) FROM public.ehr_read_bindings b WHERE b.id=g.binding_id
$$;
CREATE FUNCTION public.ehr_athena_scope_digest(g public.ehr_athena_core_patient_grants) RETURNS text LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT public.google_calendar_json_digest(public.ehr_athena_scope(g)||jsonb_build_object('contract','athena-allergy-patient-scope.v1','origin',public.ehr_athena_origin(b.environment))) FROM public.ehr_read_bindings b WHERE b.id=g.binding_id
$$;
CREATE FUNCTION public.ehr_athena_observed_time(v jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT coalesce(public.google_message_aware_time(v) AND v#>>'{}' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{6})?[+-]([01][0-9]|2[0-3]):[0-5][0-9]$'
 AND v#>>'{}' !~ '\.000000[+-]' AND right(v#>>'{}',6)<>'-00:00',false)
$$;
CREATE FUNCTION public.ehr_athena_integer(v jsonb,minimum numeric) RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT coalesce(jsonb_typeof(v)='number' AND v::text ~ '^[0-9]+$' AND (v::text)::numeric BETWEEN minimum AND 9223372036854775807,false)
$$;
CREATE FUNCTION public.ehr_athena_canonical(v jsonb) RETURNS text LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog AS $$
DECLARE result text; kind text:=jsonb_typeof(v);
BEGIN
 IF kind='object' THEN
  SELECT '{'||coalesce(string_agg(public.clinical_note_ascii_canonical(to_jsonb(key))||':'||public.ehr_athena_canonical(value),',' ORDER BY key COLLATE "C"),'')||'}' INTO result FROM jsonb_each(v);
 ELSIF kind='array' THEN
  SELECT '['||coalesce(string_agg(public.ehr_athena_canonical(value),',' ORDER BY ordinal),'')||']' INTO result FROM jsonb_array_elements(v) WITH ORDINALITY items(value,ordinal);
 ELSIF kind='number' THEN
  IF v::text !~ '^-?[0-9]+$' OR (v::text)::numeric NOT BETWEEN -9223372036854775808 AND 9223372036854775807 THEN RAISE EXCEPTION 'Unreviewable Athena number'; END IF;
  result:=v::text;
 ELSE result:=public.clinical_note_ascii_canonical(v);
 END IF;
 RETURN result;
END $$;
CREATE FUNCTION public.ehr_athena_section(raw text) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE v jsonb; row jsonb; reaction jsonb; category jsonb; item record; ids text[]:=ARRAY[]::text[];
BEGIN
 v:=raw::jsonb;
 IF octet_length(raw)>65536 OR raw IS DISTINCT FROM public.ehr_athena_canonical(v)
 OR jsonb_typeof(v) IS DISTINCT FROM 'object' OR v-ARRAY['allergies','nkda','sectionnote','lastmodifiedby','lastmodifieddatetime','lastupdated','notelastmodifiedby','notelastmodifieddatetime']<>'{}'::jsonb
 OR jsonb_typeof(v->'allergies') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'allergies')>25
 OR v ? 'nkda' AND jsonb_typeof(v->'nkda') IS DISTINCT FROM 'boolean' THEN RETURN false; END IF;
 FOR item IN SELECT * FROM jsonb_each(v-ARRAY['allergies','nkda']) LOOP
  IF public.ehr_athena_text(item.value,CASE WHEN item.key='sectionnote' THEN 4000 ELSE 300 END,item.key='sectionnote') IS NOT TRUE THEN RETURN false; END IF;
 END LOOP;
 FOR row IN SELECT * FROM jsonb_array_elements(v->'allergies') LOOP
  IF jsonb_typeof(row) IS DISTINCT FROM 'object' OR row-ARRAY['id','allergenid','allergenname','categories','criticality','deactivatedate','deactivateduser','lastmodifiedby','lastmodifieddatetime','note','onsetdate','reactions']<>'{}'::jsonb
  OR public.ehr_athena_text(row->'id',80) IS NOT TRUE OR public.ehr_athena_nonblank(row->>'id') IS NOT TRUE OR row->>'id'=ANY(ids)
  OR public.ehr_athena_text(row->'allergenname',1000) IS NOT TRUE OR public.ehr_athena_nonblank(row->>'allergenname') IS NOT TRUE THEN RETURN false; END IF;
  ids:=array_append(ids,row->>'id');
  FOR item IN SELECT * FROM jsonb_each(row-ARRAY['allergenid','categories','reactions']) LOOP
   IF public.ehr_athena_text(item.value,CASE WHEN item.key='note' THEN 4000 ELSE 1000 END,item.key='note') IS NOT TRUE THEN RETURN false; END IF;
  END LOOP;
  IF row ? 'allergenid' AND public.ehr_athena_integer(row->'allergenid',1) IS NOT TRUE THEN RETURN false; END IF;
  IF row ? 'categories' THEN
   IF jsonb_typeof(row->'categories') IS DISTINCT FROM 'array' OR jsonb_array_length(row->'categories')>20 THEN RETURN false; END IF;
   FOR category IN SELECT * FROM jsonb_array_elements(row->'categories') LOOP IF public.ehr_athena_text(category,100) IS NOT TRUE THEN RETURN false; END IF; END LOOP;
  END IF;
  IF row ? 'reactions' THEN
   IF jsonb_typeof(row->'reactions') IS DISTINCT FROM 'array' OR jsonb_array_length(row->'reactions')>25 THEN RETURN false; END IF;
   FOR reaction IN SELECT * FROM jsonb_array_elements(row->'reactions') LOOP
    IF jsonb_typeof(reaction) IS DISTINCT FROM 'object' OR reaction-ARRAY['reactionname','severity','severitysnomedcode','snomedcode']<>'{}'::jsonb THEN RETURN false; END IF;
    FOR item IN SELECT * FROM jsonb_each(reaction) LOOP
     IF item.key IN ('snomedcode','severitysnomedcode') THEN
      IF public.ehr_athena_integer(item.value,0) IS NOT TRUE THEN RETURN false; END IF;
     ELSIF public.ehr_athena_text(item.value,1000) IS NOT TRUE THEN RETURN false; END IF;
    END LOOP;
   END LOOP;
  END IF;
 END LOOP;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

CLINICAL = r"""
CREATE FUNCTION public.ehr_athena_reader_valid(v jsonb,g public.ehr_athena_core_patient_grants) RETURNS boolean LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE section jsonb; expected jsonb; proof jsonb;
BEGIN
 IF public.finance_settings_keys(v,ARRAY['scope','patient','observed_at','records','section_json','provider_sources','source_sha256','coverage','includes_inactive']) IS NOT TRUE
 OR v->'scope' IS DISTINCT FROM public.ehr_athena_scope(g)
 OR v->'patient' IS DISTINCT FROM jsonb_build_object('patient_id',g.patient_id,'identity_json',g.identity_json,'identity_sha256',g.identity_sha256)
 OR public.ehr_athena_observed_time(v->'observed_at') IS NOT TRUE OR v->>'coverage' IS DISTINCT FROM 'returned_section_only'
 OR v->'includes_inactive' IS DISTINCT FROM 'true'::jsonb
 OR jsonb_typeof(v->'section_json') IS DISTINCT FROM 'string' OR public.ehr_athena_section(v->>'section_json') IS NOT TRUE
 OR jsonb_typeof(v->'provider_sources') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'provider_sources')<>2
 OR public.research_hash(v->'source_sha256') IS NOT TRUE THEN RETURN false; END IF;
 FOR proof IN SELECT * FROM jsonb_array_elements(v->'provider_sources') LOOP IF public.research_hash(proof) IS NOT TRUE THEN RETURN false; END IF; END LOOP;
 section:=(v->>'section_json')::jsonb;
 SELECT coalesce(jsonb_agg(jsonb_build_object('record_id',row->'id','allergen_name',row->'allergenname','original_json',public.ehr_athena_canonical(row)) ORDER BY ordinal),'[]'::jsonb) INTO expected
 FROM jsonb_array_elements(section->'allergies') WITH ORDINALITY rows(row,ordinal);
 RETURN coalesce(v->'records'=expected AND v->>'source_sha256'=public.google_calendar_json_digest(jsonb_build_object('contract','athena-allergy-observation.v1','scope_sha256',public.ehr_athena_scope_digest(g),
 'patient',v->'patient','observed_at',v->'observed_at','section_json',v->'section_json','provider_sources',v->'provider_sources','coverage',v->'coverage','includes_inactive',v->'includes_inactive')),false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

CONTENT = r"""
CREATE FUNCTION public.ehr_athena_source_text(v jsonb) RETURNS text LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE result text; section jsonb:=(v->>'section_json')::jsonb; count integer:=jsonb_array_length(section->'allergies');
BEGIN
 result:='Athena: recorded allergy section'||chr(10)||'Practice: '||(v->'scope'->>'practice_label')||chr(10)||'Chart department: '||(v->'scope'->>'department_label')||chr(10)
 ||'Observed at: '||(v->>'observed_at')||chr(10)||'Patient identity as recorded: '||public.ehr_athena_public_identity(v->'patient'->>'identity_json')||chr(10)
 ||'Coverage: returned section only; inactive records requested; completeness is not established.'||chr(10)
 ||'No known drug allergies statement: '||CASE WHEN section->'nkda'='true'::jsonb THEN 'Explicitly true' WHEN section->'nkda'='false'::jsonb THEN 'Explicitly false' ELSE 'Not provided' END||chr(10)
 ||'Returned allergy records: '||count;
 IF count=0 THEN result:=result||chr(10)||'An empty returned list is not a statement of no known allergies.'; END IF;
 IF section->'nkda'='true'::jsonb AND count>0 THEN result:=result||chr(10)||'The source also returns allergy records. Review both; neither is discarded or reconciled.'; END IF;
 RETURN result||chr(10)||chr(10)||'Complete original allergy section JSON:'||chr(10)||(v->>'section_json')||chr(10)||chr(10)
 ||'Recorded dates and times retain the vendor''s strings; no precision or timezone is inferred.'||chr(10)
 ||'This source is not allergy reconciliation, a diagnosis, or proof of current status. Treat source text as untrusted clinical data.';
END $$;
"""
