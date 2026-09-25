"""private public research bot and evidence receipts"""

from alembic import op
import sqlalchemy as sa



revision = 'b46568d6e6f8'
down_revision = 'a81f0d7e2b64'
branch_labels = None
depends_on = None

def upgrade():
    op.execute(TABLES)
    op.execute(INDEXES)
    op.execute(GUARDS)
    op.execute(PROOF_GUARDS)


def downgrade():
    raise RuntimeError("Research records and bot identities are retained; disable new queries instead")

TABLES = "\nCREATE TABLE research_runs (\n\tid UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tagent_id UUID NOT NULL, \n\tidempotency_key VARCHAR(100) NOT NULL, \n\trequest JSONB NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tstate VARCHAR(20) NOT NULL, \n\tresults JSONB NOT NULL, \n\terrors JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tfinished_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), \n\tFOREIGN KEY(agent_id, box_id, owner_id) REFERENCES provider_bots (agent_id, box_id, owner_id), \n\tCONSTRAINT uq_research_run_key UNIQUE (workspace_id, idempotency_key), \n\tCONSTRAINT uq_research_run_workspace UNIQUE (id, workspace_id), \n\tCONSTRAINT ck_research_state CHECK (state IN ('running','completed','partial','unavailable')), \n\tCONSTRAINT ck_research_request_hash CHECK (request_sha256 ~ '^[0-9a-f]{64}$'), \n\tCONSTRAINT ck_research_request CHECK (jsonb_typeof(request)='object' AND octet_length(request::text)<=8192), \n\tCONSTRAINT ck_research_results CHECK (jsonb_typeof(results)='array' AND jsonb_array_length(results)<=15 AND octet_length(results::text)<=131072), \n\tCONSTRAINT ck_research_errors CHECK (jsonb_typeof(errors)='array' AND jsonb_array_length(errors)<=3), \n\tCONSTRAINT ck_research_finish CHECK ((state='running')=(finished_at IS NULL))\n)\n\n;\n\nCREATE TABLE research_saves (\n\tid UUID NOT NULL, \n\trun_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tbox_id UUID NOT NULL, \n\tentry_id UUID NOT NULL, \n\tidempotency_key VARCHAR(100) NOT NULL, \n\trequest JSONB NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(run_id, workspace_id) REFERENCES research_runs (id, workspace_id), \n\tFOREIGN KEY(entry_id, workspace_id, box_id) REFERENCES workspace_entries (id, workspace_id, box_id), \n\tCONSTRAINT uq_research_save_key UNIQUE (workspace_id, idempotency_key), \n\tCONSTRAINT ck_research_save_hash CHECK (request_sha256 ~ '^[0-9a-f]{64}$'), \n\tCONSTRAINT ck_research_save_request CHECK (jsonb_typeof(request)='object' AND octet_length(request::text)<=8192)\n)\n\n;"
INDEXES = 'CREATE INDEX ix_research_recent ON research_runs (workspace_id, created_at);'
GUARDS = "ALTER TABLE provider_bots DROP CONSTRAINT ck_provider_bot_role;\nALTER TABLE provider_bots ADD CONSTRAINT ck_provider_bot_role CHECK (role IN ('scribe','visit_prep','follow_up','chief','custom','research'));\nALTER TABLE provider_bots ADD CONSTRAINT ck_provider_bot_research_identity CHECK (role <> 'research' OR instance_id IS NOT NULL);\nALTER TABLE workspace_handoffs DROP CONSTRAINT ck_handoff_role;\nALTER TABLE workspace_handoffs ADD CONSTRAINT ck_handoff_role CHECK (recipient_role IN ('scribe','visit_prep','follow_up','custom','research'));\nCREATE FUNCTION research_run_guard() RETURNS trigger LANGUAGE plpgsql AS $$\nBEGIN\n IF TG_OP='DELETE' THEN RAISE EXCEPTION 'research_history_retained'; END IF;\n IF TG_OP='INSERT' THEN\n  IF NEW.state<>'running' OR NEW.finished_at IS NOT NULL OR NEW.results<>'[]'::jsonb OR NEW.errors<>'[]'::jsonb\n   OR NOT EXISTS(SELECT 1 FROM provider_bots b WHERE b.agent_id=NEW.agent_id AND b.box_id=NEW.box_id AND b.owner_id=NEW.owner_id\n      AND b.role='research' AND b.instance_id::text=NEW.request->>'bot')\n   OR NEW.request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key OR NEW.request->'public_query_confirmed' IS DISTINCT FROM 'true'::jsonb\n  THEN RAISE EXCEPTION 'research_initial_intent_invalid'; END IF;\n ELSE\n  IF OLD.state<>'running' OR NEW.state='running' OR NEW.finished_at IS NULL OR NEW.finished_at<OLD.created_at\n   OR ROW(NEW.id,NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.agent_id,NEW.idempotency_key,NEW.request,NEW.request_sha256,NEW.created_at)\n     IS DISTINCT FROM ROW(OLD.id,OLD.workspace_id,OLD.box_id,OLD.owner_id,OLD.agent_id,OLD.idempotency_key,OLD.request,OLD.request_sha256,OLD.created_at)\n  THEN RAISE EXCEPTION 'research_intent_immutable'; END IF;\n END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER research_run_guard BEFORE INSERT OR UPDATE OR DELETE ON research_runs FOR EACH ROW EXECUTE FUNCTION research_run_guard();\nCREATE TRIGGER research_save_immutable BEFORE UPDATE OR DELETE ON research_saves FOR EACH ROW EXECUTE FUNCTION reject_workspace_history_change();\n"

PROOF_GUARDS = r"""
CREATE FUNCTION public.research_json_digest(value jsonb)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT encode(sha256(convert_to(public.vendor_public_canonical(value),'UTF8')),'hex')
$$;

-- Match Python's str.isspace()/strip(), independently of database locale.
CREATE FUNCTION public.research_whitespace()
RETURNS text LANGUAGE sql IMMUTABLE AS $$
 SELECT U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
$$;
CREATE FUNCTION public.research_text(value jsonb, minimum integer, maximum integer)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_typeof(value)='string'
  AND length(value#>>'{}') BETWEEN minimum AND maximum
  AND (value#>>'{}') !~ U&'[\0001-\0008\000B-\001F\007F]',false)
$$;
CREATE FUNCTION public.research_hash(value jsonb)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_typeof(value)='string' AND length(value#>>'{}')=64
  AND (value#>>'{}') ~ '^[0-9a-f]{64}$',false)
$$;

CREATE FUNCTION public.research_source_valid(value jsonb)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE field jsonb; origin text; url text; stamp timestamp without time zone;
BEGIN
 IF NOT public.finance_settings_keys(value,ARRAY['source','id','title','url','source_updated_at','version','retrieved_at','excerpt','fields','truncated','raw_response_sha256','query_sha256','result_scope','attribution','sha256'])
  OR octet_length(value::text)>131072
  OR NOT public.research_text(value->'source',1,32)
  OR value->>'source' NOT IN ('pubmed','clinical_trials','dailymed','rxnorm','openfda','cms_coverage','cms_open_data','medicare_care_compare','npi_registry')
  OR NOT public.research_text(value->'id',1,128)
  OR NOT public.research_text(value->'title',1,500)
  OR NOT public.research_text(value->'url',1,2048)
  OR NOT public.research_text(value->'retrieved_at',1,80)
  OR NOT public.research_text(value->'excerpt',0,2500)
  OR NOT public.research_text(value->'attribution',1,200)
  OR jsonb_typeof(value->'truncated') IS DISTINCT FROM 'boolean'
  OR NOT public.research_hash(value->'raw_response_sha256')
  OR NOT public.research_hash(value->'query_sha256')
  OR NOT public.research_hash(value->'sha256')
  OR jsonb_typeof(value->'result_scope') IS DISTINCT FROM 'string'
  OR value->>'result_scope' NOT IN ('limited','complete','unknown')
  OR jsonb_typeof(value->'fields') IS DISTINCT FROM 'array'
 THEN RETURN false; END IF;
 IF value->'source_updated_at'<>'null'::jsonb AND (
   NOT public.research_text(value->'source_updated_at',1,80)
   OR btrim(value->>'source_updated_at',public.research_whitespace())='')
  THEN RETURN false; END IF;
 IF value->'version'<>'null'::jsonb AND (
   NOT public.research_text(value->'version',1,128)
   OR btrim(value->>'version',public.research_whitespace())='')
  THEN RETURN false; END IF;
 IF jsonb_array_length(value->'fields')>12 THEN RETURN false; END IF;
 FOR field IN SELECT item FROM jsonb_array_elements(value->'fields') item LOOP
  IF NOT public.finance_settings_keys(field,ARRAY['label','text'])
   OR NOT public.research_text(field->'label',1,80)
   OR NOT public.research_text(field->'text',0,1500)
   THEN RETURN false; END IF;
 END LOOP;
 origin:='https://'||CASE value->>'source'
  WHEN 'pubmed' THEN 'pubmed.ncbi.nlm.nih.gov'
  WHEN 'clinical_trials' THEN 'clinicaltrials.gov'
  WHEN 'dailymed' THEN 'dailymed.nlm.nih.gov'
  WHEN 'rxnorm' THEN 'mor.nlm.nih.gov'
  WHEN 'openfda' THEN 'api.fda.gov'
  WHEN 'cms_coverage' THEN 'www.cms.gov'
  WHEN 'cms_open_data' THEN 'data.cms.gov'
  WHEN 'medicare_care_compare' THEN 'data.cms.gov'
  WHEN 'npi_registry' THEN 'npiregistry.cms.hhs.gov' END;
 url:=value->>'url';
 IF left(url,length(origin))<>origin OR substring(url FROM length(origin)+1 FOR 1)<>'/'
  OR position('#' IN url)>0 OR position(chr(92) IN url)>0
  OR translate(url,public.research_whitespace(),'')<>url THEN RETURN false; END IF;
 -- The accepted explicit ISO form is also checked by SourceRecord. This avoids
 -- DateStyle/session-timezone-dependent interpretation or naive timestamps.
 IF value->>'retrieved_at' !~ '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,9})?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])$'
  THEN RETURN false; END IF;
 BEGIN
  -- Validate the calendar independently of PostgreSQL's narrower offset range;
  -- the explicit offset syntax/range was checked above, as in Python datetime.
  stamp:=substring(value->>'retrieved_at' FROM 1 FOR 19)::timestamp without time zone;
 EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format OR invalid_parameter_value THEN
  RETURN false;
 END;
 RETURN value->>'sha256'=public.research_json_digest(value-'sha256');
END $$;

CREATE FUNCTION public.research_run_proof() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item jsonb; source text;
BEGIN
 IF NOT public.finance_settings_keys(NEW.request,ARRAY['contract_version','idempotency_key','expected_revision','team_revision','bot','topic','sources','query','public_query_confirmed'])
  OR NEW.request->'contract_version' IS DISTINCT FROM '1'::jsonb
  OR NEW.request->'public_query_confirmed' IS DISTINCT FROM 'true'::jsonb
  OR NOT public.research_text(NEW.request->'query',1,500)
  OR btrim(NEW.request->>'query',public.research_whitespace()) IS DISTINCT FROM NEW.request->>'query'
  OR translate(NEW.request->>'query',chr(9)||chr(10),'') IS DISTINCT FROM NEW.request->>'query'
  OR jsonb_typeof(NEW.request->'idempotency_key') IS DISTINCT FROM 'string'
  OR NEW.request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
  OR NEW.idempotency_key !~ '^[A-Za-z0-9:_-]{8,100}$'
  OR jsonb_typeof(NEW.request->'expected_revision') IS DISTINCT FROM 'number'
  OR jsonb_typeof(NEW.request->'team_revision') IS DISTINCT FROM 'number'
  OR (NEW.request->>'expected_revision') !~ '^[1-9][0-9]*$'
  OR (NEW.request->>'team_revision') !~ '^[1-9][0-9]*$'
  OR jsonb_typeof(NEW.request->'bot') IS DISTINCT FROM 'string'
  OR (NEW.request->>'bot') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
  OR jsonb_typeof(NEW.request->'topic') IS DISTINCT FROM 'string'
  OR NEW.request->>'topic' NOT IN ('literature','drug_safety','trials','coverage','provider_data')
  OR jsonb_typeof(NEW.request->'sources') IS DISTINCT FROM 'array'
  OR NEW.request_sha256 IS DISTINCT FROM public.research_json_digest(NEW.request)
 THEN RAISE EXCEPTION 'research_request_proof_invalid'; END IF;
 IF jsonb_array_length(NEW.request->'sources') NOT BETWEEN 1 AND 3
  OR (SELECT count(DISTINCT v) FROM jsonb_array_elements(NEW.request->'sources') v) <> jsonb_array_length(NEW.request->'sources')
 THEN RAISE EXCEPTION 'research_sources_invalid'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(NEW.request->'sources') LOOP
  source:=item#>>'{}';
  IF jsonb_typeof(item)<>'string' OR source NOT IN ('pubmed','clinical_trials','dailymed','rxnorm','openfda','cms_coverage','cms_open_data','medicare_care_compare','npi_registry')
   THEN RAISE EXCEPTION 'research_source_invalid'; END IF;
  IF NOT (CASE NEW.request->>'topic'
   WHEN 'literature' THEN source='pubmed'
   WHEN 'drug_safety' THEN source IN ('dailymed','rxnorm','openfda')
   WHEN 'trials' THEN source='clinical_trials'
   WHEN 'coverage' THEN source IN ('cms_coverage','cms_open_data')
   WHEN 'provider_data' THEN source IN ('cms_open_data','medicare_care_compare','npi_registry')
   ELSE false END) THEN RAISE EXCEPTION 'research_source_topic_invalid'; END IF;
 END LOOP;
 IF TG_OP='UPDATE' THEN
  IF jsonb_typeof(NEW.results) IS DISTINCT FROM 'array'
   OR jsonb_typeof(NEW.errors) IS DISTINCT FROM 'array'
   THEN RAISE EXCEPTION 'research_result_collection_invalid'; END IF;
  IF jsonb_array_length(NEW.results)>15 OR octet_length(NEW.results::text)>131072
   OR jsonb_array_length(NEW.errors)>3 OR octet_length(NEW.errors::text)>1024
   THEN RAISE EXCEPTION 'research_result_size_invalid'; END IF;
  IF (NEW.state='completed' AND NEW.errors<>'[]'::jsonb)
   OR (NEW.state='partial' AND (NEW.errors='[]'::jsonb OR NEW.results='[]'::jsonb))
   OR (NEW.state='unavailable' AND (NEW.errors='[]'::jsonb OR NEW.results<>'[]'::jsonb))
   THEN RAISE EXCEPTION 'research_result_state_invalid'; END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(NEW.results) LOOP
   IF NOT public.research_source_valid(item)
    OR NOT (NEW.request->'sources' @> jsonb_build_array(item->>'source'))
    OR item->>'query_sha256' IS DISTINCT FROM public.research_json_digest(jsonb_build_object('source',item->>'source','query',NEW.request->>'query'))
    THEN RAISE EXCEPTION 'research_result_proof_invalid'; END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.results) item
     GROUP BY item->>'source' HAVING count(*)>5)
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.results) item
     GROUP BY item->>'source',item->>'id',item->'version' HAVING count(*)>1)
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.results) item
     GROUP BY item->>'sha256' HAVING count(*)>1)
   THEN RAISE EXCEPTION 'research_result_identity_invalid'; END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(NEW.errors) LOOP
   IF NOT public.finance_settings_keys(item,ARRAY['source','code'])
    OR NOT public.research_text(item->'source',1,32)
    OR NOT public.research_text(item->'code',1,64)
    OR NOT (NEW.request->'sources' @> jsonb_build_array(item->>'source'))
    OR item->>'code' NOT IN ('source_unavailable','source_timeout','source_rate_limited','invalid_source_response','source_not_configured','no_matching_record')
    THEN RAISE EXCEPTION 'research_error_proof_invalid'; END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.errors) item
     GROUP BY item->>'source' HAVING count(*)>1)
   THEN RAISE EXCEPTION 'research_error_identity_invalid'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER research_run_proof BEFORE INSERT OR UPDATE ON research_runs
 FOR EACH ROW EXECUTE FUNCTION public.research_run_proof();

CREATE FUNCTION public.research_save_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r research_runs%ROWTYPE; e workspace_entries%ROWTYPE; selected jsonb;
 item jsonb; hash_value text; matches integer; blocks text[]:=ARRAY[]::text[]; expected_content text;
BEGIN
 IF NOT public.finance_settings_keys(NEW.request,ARRAY['contract_version','idempotency_key','expected_revision','source_hashes'])
  OR NEW.request->'contract_version' IS DISTINCT FROM '1'::jsonb
  OR jsonb_typeof(NEW.request->'idempotency_key') IS DISTINCT FROM 'string'
  OR NEW.request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
  OR NEW.idempotency_key !~ '^[A-Za-z0-9:_-]{8,100}$'
  OR jsonb_typeof(NEW.request->'expected_revision') IS DISTINCT FROM 'number'
  OR (NEW.request->>'expected_revision') !~ '^[1-9][0-9]*$'
  OR jsonb_typeof(NEW.request->'source_hashes') IS DISTINCT FROM 'array'
  OR NEW.request_sha256 IS DISTINCT FROM public.research_json_digest(NEW.request)
 THEN RAISE EXCEPTION 'research_save_request_invalid'; END IF;
 IF jsonb_array_length(NEW.request->'source_hashes') NOT BETWEEN 1 AND 5
  OR (SELECT count(DISTINCT v) FROM jsonb_array_elements(NEW.request->'source_hashes') v) <> jsonb_array_length(NEW.request->'source_hashes')
 THEN RAISE EXCEPTION 'research_save_selection_invalid'; END IF;
 SELECT * INTO r FROM research_runs WHERE id=NEW.run_id AND workspace_id=NEW.workspace_id AND box_id=NEW.box_id FOR SHARE;
 IF NOT FOUND OR r.state NOT IN ('completed','partial') THEN RAISE EXCEPTION 'research_save_run_invalid'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(NEW.request->'source_hashes') LOOP
  hash_value:=item#>>'{}';
  IF jsonb_typeof(item)<>'string' OR hash_value !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'research_save_hash_invalid'; END IF;
  SELECT count(*) INTO matches FROM jsonb_array_elements(r.results) value WHERE value->>'sha256'=hash_value;
  IF matches<>1 THEN RAISE EXCEPTION 'research_save_source_absent'; END IF;
  SELECT value INTO selected FROM jsonb_array_elements(r.results) value WHERE value->>'sha256'=hash_value;
  IF NOT public.research_source_valid(selected)
   OR NOT (r.request->'sources' @> jsonb_build_array(selected->>'source'))
   OR selected->>'query_sha256' IS DISTINCT FROM public.research_json_digest(jsonb_build_object('source',selected->>'source','query',r.request->>'query'))
   THEN RAISE EXCEPTION 'research_save_source_invalid'; END IF;
  blocks:=array_append(blocks,concat_ws(E'\n',selected->>'title',selected->>'url',
   'Source: '||(selected->>'source')||' / '||(selected->>'id'),
   'Retrieved: '||(selected->>'retrieved_at'),
   'Source updated: '||coalesce(nullif(selected->>'source_updated_at',''),'Not supplied'),
   'Version: '||coalesce(nullif(selected->>'version',''),'Not supplied'),
   'Excerpt shortened: '||CASE WHEN selected->'truncated'='true'::jsonb THEN 'Yes; open the source for full details' ELSE 'No' END,
   'Content SHA-256: '||hash_value,selected->>'excerpt'));
 END LOOP;
 expected_content:='Public research source excerpts. Source claims require clinician review.'||E'\n\n'||array_to_string(blocks,E'\n\n---\n\n');
 SELECT * INTO e FROM workspace_entries WHERE id=NEW.entry_id AND workspace_id=NEW.workspace_id AND box_id=NEW.box_id FOR SHARE;
 IF NOT FOUND OR e.actor_id IS DISTINCT FROM r.owner_id OR e.kind IS DISTINCT FROM 'evidence'
  OR e.source_label IS DISTINCT FROM 'Research · public source excerpts'
  OR e.idempotency_key IS DISTINCT FROM 'research:'||NEW.id::text
  OR e.request_hash IS DISTINCT FROM NEW.request_sha256
  OR e.revision IS DISTINCT FROM (NEW.request->>'expected_revision')::integer+1
  OR e.content IS DISTINCT FROM expected_content OR length(expected_content)>20000
 THEN RAISE EXCEPTION 'research_saved_evidence_invalid'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER research_save_guard BEFORE INSERT ON research_saves
 FOR EACH ROW EXECUTE FUNCTION public.research_save_guard();
"""
