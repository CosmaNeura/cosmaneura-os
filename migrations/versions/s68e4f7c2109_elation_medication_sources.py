"""Bounded Elation medication records retain exact visit and reviewed source custody."""

from alembic import op

revision = "s68e4f7c2109"
down_revision = "r57d3f6b1098"
branch_labels = None
depends_on = None


def definition(signature):
    return op.get_bind().exec_driver_sql("SELECT pg_get_functiondef(%s::regprocedure)", (signature,)).scalar_one()


def changed(sql, pairs):
    for before, after in pairs:
        if sql.count(before) != 1:
            raise RuntimeError("Prior EHR guard differs from reviewed medication extension: " + before)
        sql = sql.replace(before, after)
    return sql


def upgrade():
    op.drop_constraint("ck_ehr_read_request_kind", "ehr_read_requests")
    op.create_check_constraint("ck_ehr_read_request_kind", "ehr_read_requests",
        "(kind='window' AND parent_snapshot_id IS NULL AND item_handle IS NULL) OR "
        "(kind IN ('verify','problems','medications') AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL)")
    current = definition("public.ehr_read_request_current(uuid)")
    op.execute(current.replace("public.ehr_read_request_current(", "public.ehr_pre_medication_request_current(", 1))
    op.execute(CURRENT)
    request = definition("public.guard_ehr_read_request()")
    op.execute(changed(request, ((" END IF;\n RETURN NEW;", MEDICATION_REQUEST + " END IF;\n RETURN NEW;"),)))
    payload = definition("public.ehr_problem_payload_valid(jsonb,public.ehr_read_requests)")
    medication = changed(payload.replace("public.ehr_problem_payload_valid(", "public.ehr_medication_payload_valid(", 1), (
        ("ARRAY['binding_sha256','request_sha256','items','provider_sources','transport','problems']", "ARRAY['binding_sha256','request_sha256','items','provider_sources','transport','medications']"),
        ("pub->>'kind' IS DISTINCT FROM 'verified_problems'", "pub->>'kind' IS DISTINCT FROM 'verified_medications'"),
        ("ARRAY['handle','sha256','starts_at','ends_at','status','patient','problems']", "ARRAY['handle','sha256','starts_at','ends_at','status','patient','medications']"),
        ("'ehr_verified_problems_item.v1'", "'ehr_verified_medications_item.v1'"),
        ("public.ehr_problem_rows_valid(payload,r)", "public.ehr_medication_rows_valid(payload,r)"),
    ))
    op.execute(FIELDS)
    op.execute(ROWS)
    op.execute(medication)
    dispatch = definition("public.ehr_read_payload_valid(jsonb,public.ehr_read_requests)")
    op.execute(changed(dispatch, (("WHEN b.vendor='elation' THEN public.ehr_elation_payload_valid(payload,r)",
        "WHEN b.vendor='elation' AND r.kind='medications' THEN public.ehr_medication_payload_valid(payload,r) "
        "WHEN b.vendor='elation' THEN public.ehr_elation_payload_valid(payload,r)"),)))
    content = definition("public.ehr_read_source_content(jsonb)")
    op.execute(content.replace("public.ehr_read_source_content(", "public.ehr_pre_medication_source_content(", 1))
    op.execute(CONTENT)
    review = definition("public.guard_ehr_read_review()")
    op.execute(changed(review, (("r.kind NOT IN ('verify','problems')", "r.kind NOT IN ('verify','problems','medications')"),)))
    source = definition("public.ehr_read_source_valid(uuid)")
    op.execute(changed(source, (
        ("r.kind IN ('verify','problems')", "r.kind IN ('verify','problems','medications')"),
        ("e.source_label=CASE WHEN", "e.source_label=CASE WHEN z.payload->'public'->>'kind'='verified_medications' THEN 'Elation: reviewed medication records' WHEN"),
    )))


def downgrade():
    raise RuntimeError("Retain immutable reviewed medication source history")


CURRENT = r"""
CREATE OR REPLACE FUNCTION public.ehr_read_request_current(rid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN r.kind<>'medications' THEN public.ehr_pre_medication_request_current(r.id)
 ELSE EXISTS(SELECT 1 FROM public.ehr_read_snapshots z JOIN public.ehr_read_requests p ON p.id=z.observation_id
  WHERE z.id=r.parent_snapshot_id AND p.kind='verify' AND public.ehr_pre_medication_request_current(p.id)
  AND (r.box_id,r.owner_id,r.account_id,r.binding_id,r.connection_id,r.credential_generation,r.practice_id,r.binding_digest,r.transport,r.window_start,r.window_end)
   =(p.box_id,p.owner_id,p.account_id,p.binding_id,p.connection_id,p.credential_generation,p.practice_id,p.binding_digest,p.transport,p.window_start,p.window_end)
  AND r.valid_until<=p.valid_until AND r.valid_until>clock_timestamp()) END
 FROM public.ehr_read_requests r WHERE r.id=rid
$$;
"""

MEDICATION_REQUEST = r"""
 ELSIF NEW.kind='medications' THEN
  SELECT * INTO parent FROM public.ehr_read_snapshots WHERE id=NEW.parent_snapshot_id;
  SELECT * INTO root FROM public.ehr_read_requests WHERE id=parent.observation_id;
  IF b.vendor<>'elation' OR parent.id IS NULL OR root.kind IS DISTINCT FROM 'verify' OR root.binding_id<>NEW.binding_id
   OR (root.box_id,root.owner_id,root.account_id,root.window_start,root.window_end,root.transport) IS DISTINCT FROM
    (NEW.box_id,NEW.owner_id,NEW.account_id,NEW.window_start,NEW.window_end,NEW.transport)
   OR NOT public.ehr_read_request_current(root.id) OR NEW.valid_until>root.valid_until
   OR NOT public.ehr_read_snapshot_valid(parent.id)
   OR NOT public.finance_settings_keys(NEW.request_json-'provider',ARRAY['action','connection_id','binding_sha256','idempotency_key','observation_id','observation_sha256','item_handle','item_sha256'])
   OR NEW.request_json->>'action' IS DISTINCT FROM 'medications'
   OR NEW.request_json->>'observation_id' IS DISTINCT FROM root.id::text
   OR NEW.request_json->>'observation_sha256' IS DISTINCT FROM parent.source_sha256
   OR NEW.request_json->>'item_handle' IS DISTINCT FROM NEW.item_handle::text
   OR parent.payload->'public'->'item'->>'handle' IS DISTINCT FROM NEW.item_handle::text
   OR parent.payload->'public'->'item'->>'sha256' IS DISTINCT FROM NEW.request_json->>'item_sha256'
  THEN RAISE EXCEPTION 'EHR exact medication parent invalid' USING ERRCODE='23514'; END IF;
"""

FIELDS = r"""
CREATE FUNCTION public.ehr_medication_text(value jsonb,maximum integer,instructions boolean DEFAULT false) RETURNS boolean
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE value_text text:=value#>>'{}'; code integer; position integer;
BEGIN
 IF jsonb_typeof(value) IS DISTINCT FROM 'string' OR char_length(value_text)>maximum THEN RETURN false; END IF;
 FOR position IN 1..char_length(value_text) LOOP
  code:=ascii(substr(value_text,position,1));
  IF (code<32 AND NOT (instructions AND code IN (9,10,13))) OR code=127 OR code BETWEEN 55296 AND 57343 THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;
CREATE FUNCTION public.ehr_medication_time(value jsonb) RETURNS boolean
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT coalesce(jsonb_typeof(value)='string' AND char_length(value#>>'{}')<=40
  AND value#>>'{}' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,6})?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])?$'
  AND public.google_calendar_date(to_jsonb(left(value#>>'{}',10))),false)
$$;
CREATE FUNCTION public.ehr_medication_fields_valid(record_value jsonb) RETURNS boolean
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE key text; state text; maximum integer;
BEGIN
 IF NOT public.finance_settings_keys(record_value,ARRAY['medication_name','strength','route','form','directions','medication_type','order_type','is_doc_med','is_permanent','start_date','document_date','signed_date','deleted_date','discontinue_date','signature_state','discontinuation_state','deletion_state'])
  OR NOT public.ehr_medication_text(record_value->'medication_name',300)
  OR btrim(record_value->>'medication_name', U&' \0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000')=''
 THEN RETURN false; END IF;
 FOREACH key IN ARRAY ARRAY['strength','route','form','directions','medication_type','order_type'] LOOP
  maximum:=CASE key WHEN 'strength' THEN 255 WHEN 'directions' THEN 1000 WHEN 'route' THEN 100 WHEN 'form' THEN 100 ELSE 40 END;
  IF record_value->key<>'null'::jsonb AND NOT public.ehr_medication_text(record_value->key,maximum,key='directions') THEN RETURN false; END IF;
 END LOOP;
 FOREACH key IN ARRAY ARRAY['is_doc_med','is_permanent'] LOOP
  IF record_value->key<>'null'::jsonb AND jsonb_typeof(record_value->key)<>'boolean' THEN RETURN false; END IF;
 END LOOP;
 IF record_value->'start_date'<>'null'::jsonb AND NOT public.google_calendar_date(record_value->'start_date') THEN RETURN false; END IF;
 FOREACH key IN ARRAY ARRAY['document_date','signed_date','deleted_date','discontinue_date'] LOOP
  IF record_value->key<>'null'::jsonb AND NOT (public.ehr_medication_time(record_value->key) OR (key='discontinue_date' AND public.google_calendar_date(record_value->key))) THEN RETURN false; END IF;
 END LOOP;
 FOREACH key IN ARRAY ARRAY['signature_state','discontinuation_state','deletion_state'] LOOP
  state:=record_value->>key;
  IF coalesce(state,'') NOT IN ('date_recorded','no_date_recorded','unknown') THEN RETURN false; END IF;
  IF (state='date_recorded') IS DISTINCT FROM (record_value->(CASE key WHEN 'signature_state' THEN 'signed_date' WHEN 'discontinuation_state' THEN 'discontinue_date' ELSE 'deleted_date' END)<>'null'::jsonb) THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

ROWS = r"""
CREATE FUNCTION public.ehr_medication_rows_valid(payload jsonb,r public.ehr_read_requests) RETURNS boolean
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE pub jsonb:=payload->'public'; priv jsonb:=payload->'private'; list jsonb:=pub->'item'->'medications';
 parent public.ehr_read_snapshots; prior public.ehr_read_requests; row jsonb; shown jsonb; position integer:=0; ids text[]:=ARRAY[]::text[];
BEGIN
 SELECT * INTO parent FROM public.ehr_read_snapshots WHERE id=r.parent_snapshot_id;
 SELECT * INTO prior FROM public.ehr_read_requests WHERE id=parent.observation_id;
 IF r.kind<>'medications' OR prior.kind IS DISTINCT FROM 'verify' OR NOT public.ehr_read_snapshot_valid(parent.id)
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
  OR jsonb_typeof(priv->'medications') IS DISTINCT FROM 'array' OR jsonb_array_length(priv->'medications')<>jsonb_array_length(list->'items')
  OR (list->'total_count'<>'null'::jsonb AND (jsonb_typeof(list->'total_count')<>'number' OR list->>'total_count' !~ '^[0-9]+$'
   OR (list->>'total_count')::numeric>2147483647 OR (list->>'total_count')::numeric<jsonb_array_length(list->'items')))
  OR (list->>'coverage'='end_of_results' AND list->'total_count'<>'null'::jsonb AND (list->>'total_count')::integer<>jsonb_array_length(list->'items'))
  OR (list->>'coverage'='more_rows_available' AND (jsonb_array_length(list->'items')=0 OR (list->'total_count'<>'null'::jsonb AND (list->>'total_count')::integer<=jsonb_array_length(list->'items'))))
  OR char_length(public.ehr_read_source_content(pub))>5000
 THEN RETURN false; END IF;
 FOR row IN SELECT * FROM jsonb_array_elements(priv->'medications') LOOP
  shown:=list->'items'->position;
  IF NOT public.finance_settings_keys(row,ARRAY['medication_id','patient_id','practice_id','medication_name','strength','route','form','directions','medication_type','order_type','is_doc_med','is_permanent','start_date','document_date','signed_date','deleted_date','discontinue_date','signature_state','discontinuation_state','deletion_state'])
   OR NOT public.ehr_read_provider_id(row->'medication_id') OR NOT public.ehr_read_provider_id(row->'patient_id') OR NOT public.ehr_read_provider_id(row->'practice_id')
   OR row->>'medication_id'=ANY(ids) OR row->>'practice_id' IS DISTINCT FROM r.practice_id
   OR row->'patient_id' IS DISTINCT FROM priv->'items'->0->'patient'->'patient_id'
   OR shown IS DISTINCT FROM row-'medication_id'-'patient_id'-'practice_id'
   OR NOT public.ehr_medication_fields_valid(row-'medication_id'-'patient_id'-'practice_id')
  THEN RETURN false; END IF;
  ids:=array_append(ids,row->>'medication_id'); position:=position+1;
 END LOOP;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

CONTENT = r"""
CREATE OR REPLACE FUNCTION public.ehr_read_source_content(pub jsonb) RETURNS text
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE item jsonb:=pub->'item'; patient jsonb:=item->'patient'; list jsonb:=item->'medications'; row jsonb; result text;
 key text; label text; state text; detail text;
BEGIN
 IF pub->>'kind'<>'verified_medications' THEN RETURN public.ehr_pre_medication_source_content(pub); END IF;
 result:='Elation medication records (synthetic frozen observation)'||chr(10)||'Practice: '||(pub->'practice'->>'label')||chr(10)
  ||'Patient: '||(patient->>'first_name')||' '||(patient->>'last_name')||chr(10)||'Birth date: '||(patient->>'birth_date')||chr(10)
  ||'Visit starts: '||(item->>'starts_at')||chr(10)||'Visit ends: '||(item->>'ends_at')||chr(10)||'Observed: '||(pub->>'observed_at')||chr(10)
  ||'Coverage: '||CASE list->>'coverage' WHEN 'end_of_results' THEN 'End of returned results; not a complete chart.' WHEN 'more_rows_available' THEN 'More medication records are available; only this page was read.' ELSE 'The provider did not establish whether more medication records exist.' END||chr(10)
  ||'Returned rows: '||jsonb_array_length(list->'items')||'; reported total: '||coalesce(list->>'total_count','not provided')||'.'||chr(10)
  ||'Optional details not listed were not provided. Dates are preserved as recorded; no timezone or current medication status is inferred.'||chr(10)||chr(10);
 FOR row IN SELECT * FROM jsonb_array_elements(list->'items') LOOP
  result:=result||'- '||(row->>'medication_name')||chr(10);
  FOREACH key IN ARRAY ARRAY['strength','route','form','directions','medication_type','order_type','is_doc_med','is_permanent','start_date','document_date'] LOOP
   label:=CASE key WHEN 'strength' THEN 'Strength' WHEN 'route' THEN 'Route' WHEN 'form' THEN 'Form' WHEN 'directions' THEN 'Directions' WHEN 'medication_type' THEN 'Medication type' WHEN 'order_type' THEN 'Order type' WHEN 'is_doc_med' THEN 'Documentation flag' WHEN 'is_permanent' THEN 'Permanent flag' WHEN 'start_date' THEN 'Start date' ELSE 'Document date' END;
   IF row->key<>'null'::jsonb THEN result:=result||'  '||label||': '||coalesce(nullif(row->>key,''),'(blank)')||chr(10); END IF;
  END LOOP;
  FOREACH key IN ARRAY ARRAY['signed_date','discontinue_date','deleted_date'] LOOP
   label:=CASE key WHEN 'signed_date' THEN 'Signed date' WHEN 'discontinue_date' THEN 'Discontinuation date' ELSE 'Deleted date' END;
   state:=row->>(CASE key WHEN 'signed_date' THEN 'signature_state' WHEN 'discontinue_date' THEN 'discontinuation_state' ELSE 'deletion_state' END);
   detail:=CASE state WHEN 'date_recorded' THEN row->>key WHEN 'no_date_recorded' THEN 'no date recorded' ELSE 'unknown' END;
   result:=result||'  '||label||': '||detail||chr(10);
  END LOOP;
 END LOOP;
 IF jsonb_array_length(list->'items')=0 THEN result:=result||'No medication records returned; this does not establish absence of medications.'||chr(10); END IF;
 RETURN result||chr(10)||'These are medication records, not a reconciled current medication list or proof of dispensing, transmission or use.'||chr(10)||'This reviewed snapshot does not prescribe or update the EHR.';
END $$;
"""
