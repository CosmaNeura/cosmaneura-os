"""Disambiguate Research result proof aliases.

Replace only the result/error aggregate aliases in the applied proof function.
Keep its request, provenance, source-count and uniqueness requirements intact.
"""

from alembic import op

revision = "55377e01a1e5"
down_revision = "b46568d6e6f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(GUARD_SQL)


def downgrade() -> None:
    raise RuntimeError("Research proof correction is forward-only")


GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.research_run_proof() RETURNS trigger LANGUAGE plpgsql AS $$
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
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.results) AS proof_results(result)
     GROUP BY proof_results.result->>'source' HAVING count(*)>5)
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.results) AS proof_results(result)
     GROUP BY proof_results.result->>'source',proof_results.result->>'id',proof_results.result->'version' HAVING count(*)>1)
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.results) AS proof_results(result)
     GROUP BY proof_results.result->>'sha256' HAVING count(*)>1)
   THEN RAISE EXCEPTION 'research_result_identity_invalid'; END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(NEW.errors) LOOP
   IF NOT public.finance_settings_keys(item,ARRAY['source','code'])
    OR NOT public.research_text(item->'source',1,32)
    OR NOT public.research_text(item->'code',1,64)
    OR NOT (NEW.request->'sources' @> jsonb_build_array(item->>'source'))
    OR item->>'code' NOT IN ('source_unavailable','source_timeout','source_rate_limited','invalid_source_response','source_not_configured','no_matching_record')
    THEN RAISE EXCEPTION 'research_error_proof_invalid'; END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.errors) AS proof_errors(result)
     GROUP BY proof_errors.result->>'source' HAVING count(*)>1)
   THEN RAISE EXCEPTION 'research_error_identity_invalid'; END IF;
 END IF;
 RETURN NEW;
END $$;
"""
