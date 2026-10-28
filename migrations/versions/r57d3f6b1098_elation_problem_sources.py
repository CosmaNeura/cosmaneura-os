"""Optional Elation problem pages reuse exact EHR observation/source custody."""

from alembic import op

revision = "r57d3f6b1098"
down_revision = "q46c2e5a0987"
branch_labels = None
depends_on = None


def definition(signature):
    return op.get_bind().exec_driver_sql("SELECT pg_get_functiondef(%s::regprocedure)", (signature,)).scalar_one()


def changed(sql, pairs):
    for before, after in pairs:
        if sql.count(before) != 1:
            raise RuntimeError("Prior EHR guard differs from reviewed problem extension: " + before)
        sql = sql.replace(before, after)
    return sql


def upgrade():
    op.drop_constraint("ck_ehr_read_request_kind", "ehr_read_requests")
    op.create_check_constraint("ck_ehr_read_request_kind", "ehr_read_requests",
        "(kind='window' AND parent_snapshot_id IS NULL AND item_handle IS NULL) OR "
        "(kind IN ('verify','problems') AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL)")
    current = definition("public.ehr_read_request_current(uuid)")
    op.execute(current.replace("public.ehr_read_request_current(", "public.ehr_appointment_request_current(", 1))
    op.execute(CURRENT)
    request = definition("public.guard_ehr_read_request()")
    op.execute(changed(request, ((" END IF;\n RETURN NEW;", PROBLEM_REQUEST + " END IF;\n RETURN NEW;"),)))
    payload = definition("public.ehr_elation_payload_valid(jsonb,public.ehr_read_requests)")
    problem = changed(payload.replace("public.ehr_elation_payload_valid(", "public.ehr_problem_payload_valid(", 1), (
        ("ARRAY['binding_sha256','request_sha256','items','provider_sources','transport']", "ARRAY['binding_sha256','request_sha256','items','provider_sources','transport','problems']"),
        ("NOT BETWEEN 1 AND 2", "<>3"),
        ("ARRAY['kind','provider','mode','practice','observed_at','window','coverage','item']", "ARRAY['kind','provider','mode','practice','observed_at','window','coverage','item','parent']"),
        ("pub->>'kind' IS DISTINCT FROM 'verified_visit'", "pub->>'kind' IS DISTINCT FROM 'verified_problems'"),
        ("ARRAY['handle','sha256','starts_at','ends_at','status','patient']", "ARRAY['handle','sha256','starts_at','ends_at','status','patient','problems']"),
        ("parent_item->'appointment' IS DISTINCT FROM appt", "parent_item IS DISTINCT FROM row"),
        ("'ehr_verified_item.v1'", "'ehr_verified_problems_item.v1'"),
        (" RETURN true;", " RETURN public.ehr_problem_rows_valid(payload,r);"),
    ))
    op.execute(ROWS)
    op.execute(problem)
    dispatch = definition("public.ehr_read_payload_valid(jsonb,public.ehr_read_requests)")
    op.execute(changed(dispatch, (("WHEN b.vendor='elation' THEN public.ehr_elation_payload_valid(payload,r)",
        "WHEN b.vendor='elation' AND r.kind='problems' THEN public.ehr_problem_payload_valid(payload,r) "
        "WHEN b.vendor='elation' THEN public.ehr_elation_payload_valid(payload,r)"),)))
    content = definition("public.ehr_read_source_content(jsonb)")
    op.execute(content.replace("public.ehr_read_source_content(", "public.ehr_appointment_source_content(", 1))
    op.execute(CONTENT)
    review = definition("public.guard_ehr_read_review()")
    op.execute(changed(review, (("r.kind<>'verify'", "r.kind NOT IN ('verify','problems')"),)))
    source = definition("public.ehr_read_source_valid(uuid)")
    op.execute(changed(source, (
        ("r.kind='verify'", "r.kind IN ('verify','problems')"),
        ("e.source_label=CASE WHEN", "e.source_label=CASE WHEN z.payload->'public'->>'kind'='verified_problems' THEN 'Elation: reviewed problem list' WHEN"),
    )))


def downgrade():
    raise RuntimeError("Retain immutable reviewed problem source history")


CURRENT = r"""
CREATE OR REPLACE FUNCTION public.ehr_read_request_current(rid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN r.kind<>'problems' THEN public.ehr_appointment_request_current(r.id)
 ELSE EXISTS(SELECT 1 FROM public.ehr_read_snapshots z JOIN public.ehr_read_requests p ON p.id=z.observation_id
  WHERE z.id=r.parent_snapshot_id AND p.kind='verify' AND public.ehr_appointment_request_current(p.id)
  AND (r.box_id,r.owner_id,r.account_id,r.binding_id,r.connection_id,r.credential_generation,r.practice_id,r.binding_digest,r.transport,r.window_start,r.window_end)
   =(p.box_id,p.owner_id,p.account_id,p.binding_id,p.connection_id,p.credential_generation,p.practice_id,p.binding_digest,p.transport,p.window_start,p.window_end)
  AND r.valid_until<=p.valid_until AND r.valid_until>clock_timestamp()) END
 FROM public.ehr_read_requests r WHERE r.id=rid
$$;
"""

PROBLEM_REQUEST = r"""
 ELSIF NEW.kind='problems' THEN
  SELECT * INTO parent FROM public.ehr_read_snapshots WHERE id=NEW.parent_snapshot_id;
  SELECT * INTO root FROM public.ehr_read_requests WHERE id=parent.observation_id;
  IF b.vendor<>'elation' OR parent.id IS NULL OR root.kind IS DISTINCT FROM 'verify' OR root.binding_id<>NEW.binding_id
   OR (root.box_id,root.owner_id,root.account_id,root.window_start,root.window_end,root.transport) IS DISTINCT FROM
    (NEW.box_id,NEW.owner_id,NEW.account_id,NEW.window_start,NEW.window_end,NEW.transport)
   OR NOT public.ehr_read_request_current(root.id) OR NEW.valid_until>root.valid_until
   OR NOT public.ehr_read_snapshot_valid(parent.id)
   OR NOT public.finance_settings_keys(NEW.request_json-'provider',ARRAY['action','connection_id','binding_sha256','idempotency_key','observation_id','observation_sha256','item_handle','item_sha256'])
   OR NEW.request_json->>'action' IS DISTINCT FROM 'problems'
   OR NEW.request_json->>'observation_id' IS DISTINCT FROM root.id::text
   OR NEW.request_json->>'observation_sha256' IS DISTINCT FROM parent.source_sha256
   OR NEW.request_json->>'item_handle' IS DISTINCT FROM NEW.item_handle::text
   OR parent.payload->'public'->'item'->>'handle' IS DISTINCT FROM NEW.item_handle::text
   OR parent.payload->'public'->'item'->>'sha256' IS DISTINCT FROM NEW.request_json->>'item_sha256'
  THEN RAISE EXCEPTION 'EHR exact problem parent invalid' USING ERRCODE='23514'; END IF;
"""

ROWS = r"""
CREATE FUNCTION public.ehr_problem_rows_valid(payload jsonb,r public.ehr_read_requests) RETURNS boolean
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE pub jsonb:=payload->'public'; priv jsonb:=payload->'private'; list jsonb:=pub->'item'->'problems';
 parent public.ehr_read_snapshots; prior public.ehr_read_requests; row jsonb; shown jsonb; position integer:=0; ids text[]:=ARRAY[]::text[];
BEGIN
 SELECT * INTO parent FROM public.ehr_read_snapshots WHERE id=r.parent_snapshot_id;
 SELECT * INTO prior FROM public.ehr_read_requests WHERE id=parent.observation_id;
 IF r.kind<>'problems' OR prior.kind IS DISTINCT FROM 'verify' OR NOT public.ehr_read_snapshot_valid(parent.id)
  OR NOT public.finance_settings_keys(pub->'parent',ARRAY['observation_id','source_sha256','item_sha256'])
  OR pub->'parent' IS DISTINCT FROM jsonb_build_object('observation_id',prior.id,'source_sha256',parent.source_sha256,'item_sha256',parent.payload->'public'->'item'->>'sha256')
  OR pub->'parent'->>'observation_id' IS DISTINCT FROM r.request_json->>'observation_id'
  OR pub->'parent'->>'source_sha256' IS DISTINCT FROM r.request_json->>'observation_sha256'
  OR pub->'parent'->>'item_sha256' IS DISTINCT FROM r.request_json->>'item_sha256'
  OR priv->'items' IS DISTINCT FROM parent.payload->'private'->'items'
  OR pub->'practice' IS DISTINCT FROM parent.payload->'public'->'practice'
  OR pub->'window' IS DISTINCT FROM parent.payload->'public'->'window'
  OR pub->'coverage' IS DISTINCT FROM parent.payload->'public'->'coverage'
  OR NOT public.finance_settings_keys(list,ARRAY['coverage','total_count','items'])
  OR coalesce(list->>'coverage','') NOT IN ('end_of_results','more_rows_available','unknown')
  OR jsonb_typeof(list->'items') IS DISTINCT FROM 'array' OR jsonb_array_length(list->'items')>25
  OR jsonb_typeof(priv->'problems') IS DISTINCT FROM 'array' OR jsonb_array_length(priv->'problems')<>jsonb_array_length(list->'items')
  OR (list->'total_count'<>'null'::jsonb AND (jsonb_typeof(list->'total_count')<>'number' OR list->>'total_count' !~ '^[0-9]+$'
   OR (list->>'total_count')::numeric>2147483647 OR (list->>'total_count')::numeric<jsonb_array_length(list->'items')))
  OR (list->>'coverage'='end_of_results' AND list->'total_count'<>'null'::jsonb AND (list->>'total_count')::integer<>jsonb_array_length(list->'items'))
  OR (list->>'coverage'='more_rows_available' AND (jsonb_array_length(list->'items')=0 OR (list->'total_count'<>'null'::jsonb AND (list->>'total_count')::integer<=jsonb_array_length(list->'items'))))
  OR char_length(public.ehr_read_source_content(pub))>5000
 THEN RETURN false; END IF;
 FOR row IN SELECT * FROM jsonb_array_elements(priv->'problems') LOOP
  shown:=list->'items'->position;
  IF NOT public.finance_settings_keys(row,ARRAY['problem_id','patient_id','practice_id','description','status','start_date','resolved_date','verification_status'])
   OR NOT public.ehr_read_provider_id(row->'problem_id') OR NOT public.ehr_read_provider_id(row->'patient_id') OR NOT public.ehr_read_provider_id(row->'practice_id')
   OR row->>'problem_id'=ANY(ids) OR row->>'practice_id' IS DISTINCT FROM r.practice_id
   OR row->'patient_id' IS DISTINCT FROM priv->'items'->0->'patient'->'patient_id'
   OR shown IS DISTINCT FROM row-'problem_id'-'patient_id'-'practice_id'
   OR NOT public.ehr_read_text(row->'description',200) OR btrim(row->>'description', U&' \0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000')=''
   OR coalesce(row->>'status','') NOT IN ('Active','Controlled','Resolved')
   OR NOT public.google_calendar_date(row->'start_date')
   OR (row->'resolved_date'<>'null'::jsonb AND (NOT public.google_calendar_date(row->'resolved_date') OR row->>'status'<>'Resolved'))
   OR (row->'verification_status'<>'null'::jsonb AND (jsonb_typeof(row->'verification_status')<>'string' OR row->>'verification_status' NOT IN ('confirmed','differential','entered_in_error','provisional','refuted','unconfirmed','')))
  THEN RETURN false; END IF;
  ids:=array_append(ids,row->>'problem_id'); position:=position+1;
 END LOOP;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

CONTENT = r"""
CREATE OR REPLACE FUNCTION public.ehr_read_source_content(pub jsonb) RETURNS text
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE item jsonb:=pub->'item'; patient jsonb:=item->'patient'; list jsonb:=item->'problems'; row jsonb; result text;
BEGIN
 IF pub->>'kind'<>'verified_problems' THEN RETURN public.ehr_appointment_source_content(pub); END IF;
 result:='Elation problem list (synthetic frozen observation)'||chr(10)||'Practice: '||(pub->'practice'->>'label')||chr(10)
  ||'Patient: '||(patient->>'first_name')||' '||(patient->>'last_name')||chr(10)||'Birth date: '||(patient->>'birth_date')||chr(10)
  ||'Visit starts: '||(item->>'starts_at')||chr(10)||'Visit ends: '||(item->>'ends_at')||chr(10)||'Observed: '||(pub->>'observed_at')||chr(10)
  ||'Coverage: '||CASE list->>'coverage' WHEN 'end_of_results' THEN 'End of returned results; not a complete chart.' WHEN 'more_rows_available' THEN 'More problem rows are available; only this page was read.' ELSE 'The provider did not establish whether more problem rows exist.' END||chr(10)
  ||'Returned rows: '||jsonb_array_length(list->'items')||'; reported total: '||coalesce(list->>'total_count','not provided')||'.'||chr(10)
  ||'Description, status, dates and verification only; diagnosis codes and synopsis are not included.'||chr(10)||chr(10);
 FOR row IN SELECT * FROM jsonb_array_elements(list->'items') LOOP
  result:=result||'- '||(row->>'description')||' | Status: '||(row->>'status')||' | Start: '||(row->>'start_date')
   ||' | Resolved: '||coalesce(row->>'resolved_date','not provided')||' | Verification: '||coalesce(nullif(row->>'verification_status',''),'not provided')||chr(10);
 END LOOP;
 IF jsonb_array_length(list->'items')=0 THEN result:=result||'No problem rows returned; this does not establish absence of conditions.'||chr(10); END IF;
 RETURN result||chr(10)||'Provider statuses and verification are recorded as supplied, not confirmed diagnoses.'||chr(10)||'This reviewed snapshot does not prescribe or update the EHR.';
END $$;
"""
