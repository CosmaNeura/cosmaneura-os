"""Closed synthetic Tebra provider and provider-bound source custody."""

from pathlib import Path
from runpy import run_path

from alembic import op

revision = "o24a0c3e8765"
down_revision = "n13f9b2d7654"
branch_labels = None
depends_on = None


def changed(sql, pairs):
    for before, after in pairs:
        if sql.count(before) != 1:
            raise RuntimeError("Prior EHR guard differs from reviewed provider extension: " + before)
        sql = sql.replace(before, after)
    return sql


def upgrade():
    op.execute("ALTER TABLE ehr_read_bindings ADD COLUMN customer_id varchar(10), ADD COLUMN practice_timezone varchar(100)")
    op.execute("ALTER TABLE ehr_read_source_reviews ADD COLUMN command_provider varchar(16)")
    op.create_check_constraint("ck_ehr_review_provider", "ehr_read_source_reviews", "command_provider IS NULL OR command_provider IN ('elation','tebra')")
    op.drop_constraint("ck_ehr_read_binding_vendor", "ehr_read_bindings")
    op.create_check_constraint("ck_ehr_read_binding_vendor", "ehr_read_bindings", "(vendor='elation' AND environment='sandbox' AND customer_id IS NULL AND practice_timezone IS NULL) OR (vendor='tebra' AND environment='synthetic' AND customer_id IS NOT NULL AND customer_id ~ '^[1-9][0-9]{0,9}$' AND customer_id::numeric<=2147483647 AND practice_id::numeric<=2147483647 AND practice_timezone IS NOT NULL)")
    prior = run_path(str(Path(__file__).with_name("m02e8a1c6543_ehr_read_custody.py")))["GUARDS"]
    transport = run_path(str(Path(__file__).with_name("n13f9b2d7654_elation_sandbox_installation.py")))
    install_guard = transport["GUARDS"].split("CREATE TRIGGER elation_sandbox_installation_guard")[0]
    op.execute(changed(install_guard.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1), (
        ("IF NOT public.ehr_read_binding_current(NEW.binding_id)",
         "IF NOT public.ehr_read_binding_current(NEW.binding_id) OR NOT EXISTS(SELECT 1 FROM public.ehr_read_bindings b WHERE b.id=NEW.binding_id AND b.vendor='elation')"),
    )))
    def part(start, finish):
        return prior[prior.index(start):prior.index(finish)]
    binding = part("CREATE FUNCTION public.ehr_read_binding_digest", "CREATE FUNCTION public.ehr_read_binding_current")
    op.execute(changed(binding.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1), (
        ("SELECT public.research_json_digest(", "SELECT CASE WHEN b.vendor='tebra' THEN public.research_json_digest(jsonb_build_object('contract','tebra-read-scope.v1','box_id',b.box_id,'owner_id',b.owner_id,'connection_id',b.connection_id,'credential_generation',b.credential_generation,'customer_id',b.customer_id::bigint,'practice_id',b.practice_id::bigint,'practice_name',b.practice_name,'timezone',b.practice_timezone)) ELSE public.research_json_digest("),
        ("'environment',b.environment))", "'environment',b.environment)) END"),
    )))
    binding_guard = part("CREATE FUNCTION public.guard_ehr_read_binding", "CREATE TRIGGER ehr_read_binding_guard")
    op.execute(changed(binding_guard.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1), (
        ("OR NEW.binding_digest IS DISTINCT FROM public.ehr_read_binding_digest(NEW)", "OR NEW.binding_digest IS DISTINCT FROM public.ehr_read_binding_digest(NEW) OR (NEW.vendor='tebra' AND NOT EXISTS(SELECT 1 FROM pg_timezone_names WHERE name=NEW.practice_timezone))"),
    )))
    request = changed(part("CREATE FUNCTION public.guard_ehr_read_request", "CREATE TRIGGER ehr_read_request_guard"), transport["REQUEST_CHANGES"])
    request = changed(request, (
        ("OR NEW.request_hash IS DISTINCT FROM", "OR coalesce(NEW.request_json->>'provider','elation') IS DISTINCT FROM b.vendor OR (NEW.request_json ? 'provider' AND jsonb_typeof(NEW.request_json->'provider') IS DISTINCT FROM 'string') OR (b.vendor='tebra' AND NEW.transport<>'mock')\n  OR NEW.request_hash IS DISTINCT FROM"),
        ("finance_settings_keys(NEW.request_json,ARRAY['action','connection_id','binding_sha256','idempotency_key','starts_at','ends_at'])", "finance_settings_keys(NEW.request_json-'provider',ARRAY['action','connection_id','binding_sha256','idempotency_key','starts_at','ends_at'])"),
        ("finance_settings_keys(NEW.request_json,ARRAY['action','connection_id','binding_sha256','idempotency_key','observation_id','observation_sha256','item_handle','item_sha256'])", "finance_settings_keys(CASE WHEN b.vendor='tebra' THEN NEW.request_json-'provider'-'last_name'-'birth_date' ELSE NEW.request_json-'provider' END,ARRAY['action','connection_id','binding_sha256','idempotency_key','observation_id','observation_sha256','item_handle','item_sha256']) OR (b.vendor='tebra' AND (NOT public.ehr_read_text(NEW.request_json->'last_name',255) OR btrim(NEW.request_json->>'last_name') IS DISTINCT FROM NEW.request_json->>'last_name' OR NOT public.google_calendar_date(NEW.request_json->'birth_date') OR (NEW.request_json->>'birth_date')::date NOT BETWEEN date '1850-01-01' AND current_date))"),
    ))
    op.execute(request.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    payload = changed(part("CREATE FUNCTION public.ehr_read_payload_valid", "CREATE FUNCTION public.ehr_read_snapshot_valid"), transport["PAYLOAD_CHANGES"])
    op.execute(payload.replace("public.ehr_read_payload_valid", "public.ehr_elation_payload_valid", 1))
    tebra = changed(payload.replace("public.ehr_read_payload_valid", "public.ehr_tebra_payload_valid", 1), TEBRA_PAYLOAD)
    op.execute(tebra)
    op.execute("""CREATE OR REPLACE FUNCTION public.ehr_read_payload_valid(payload jsonb, r public.ehr_read_requests) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT coalesce((SELECT CASE WHEN b.vendor='elation' THEN public.ehr_elation_payload_valid(payload,r)
 WHEN b.vendor='tebra' THEN r.transport='mock' AND payload->'public'->'practice'->>'timezone'=b.practice_timezone AND public.ehr_tebra_payload_valid(payload,r)
 ELSE false END FROM public.ehr_read_bindings b WHERE b.id=r.binding_id AND payload->'public'->>'provider'=b.vendor),false) $$;""")
    content = part("CREATE FUNCTION public.ehr_read_source_content", "CREATE FUNCTION public.ehr_read_source_valid")
    content = changed(content, (
        ("'Elation selected visit (synthetic frozen observation)'", "CASE WHEN pub->>'provider'='tebra' THEN 'Tebra selected visit (synthetic frozen observation)' ELSE 'Elation selected visit (synthetic frozen observation)' END"),
        ("(pub->'item'->'patient'->>'first_name')||' '||(pub->'item'->'patient'->>'last_name')", "CASE WHEN pub->>'provider'='tebra' THEN pub->'item'->'patient'->>'full_name' ELSE (pub->'item'->'patient'->>'first_name')||' '||(pub->'item'->'patient'->>'last_name') END"),
        ("CASE WHEN pub->>'coverage'='more_rows_available'", "CASE WHEN pub->>'provider'='tebra' THEN 'Showing returned appointments only; this is not a complete schedule.' WHEN pub->>'coverage'='more_rows_available'"),
    ))
    op.execute(content.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    source = part("CREATE FUNCTION public.ehr_read_source_valid", "CREATE FUNCTION public.ehr_read_source_current")
    source = changed(source, (
        ("AND public.ehr_read_snapshot_valid(z.id)", "AND coalesce(v.command_provider,'elation')=z.payload->'public'->>'provider' AND public.ehr_read_snapshot_valid(z.id)"),
        ("'reviewed_untrusted_source',v.reviewed_untrusted_source))", "'reviewed_untrusted_source',v.reviewed_untrusted_source) || CASE WHEN v.command_provider IS NULL THEN '{}'::jsonb ELSE jsonb_build_object('provider',v.command_provider) END)"),
        ("e.source_label='Elation: reviewed appointment'", "e.source_label=CASE WHEN z.payload->'public'->>'provider'='tebra' THEN 'Tebra: reviewed appointment' ELSE 'Elation: reviewed appointment' END"),
    ))
    op.execute(source.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))


def downgrade():
    raise RuntimeError("Retain provider-bound EHR read and source history")


TEBRA_PAYLOAD = (
    ("pub->>'provider' IS DISTINCT FROM 'elation'", "pub->>'provider' IS DISTINCT FROM 'tebra'"),
    ("coalesce(pub->>'coverage','') NOT IN ('end_of_results','more_rows_available')", "pub->>'coverage' IS DISTINCT FROM 'returned_rows_only'"),
    ("ARRAY['appointment_id','patient_id','physician_id','starts_at','ends_at','status','scheduled_date_raw','deleted_at']", "ARRAY['appointment_id','patient_id','starts_at','ends_at','status']"),
    ("   OR NOT public.ehr_read_provider_id(appt->'physician_id')\n", ""),
    ("(appt->'patient_id'<>'null'::jsonb AND NOT public.ehr_read_provider_id(appt->'patient_id'))", "NOT public.ehr_read_provider_id(appt->'patient_id')"),
    ("   OR NOT public.ehr_read_text(appt->'scheduled_date_raw',40)\n", ""),
    ("   OR (appt->>'scheduled_date_raw')::timestamptz IS DISTINCT FROM (appt->>'starts_at')::timestamptz\n", ""),
    ("   OR (appt->'deleted_at'<>'null'::jsonb AND NOT public.google_message_aware_time(appt->'deleted_at'))\n", ""),
    ("(appt->>'starts_at')::timestamptz NOT BETWEEN r.window_start AND r.window_end", "((appt->>'starts_at')::timestamptz<r.window_start OR (appt->>'starts_at')::timestamptz>=r.window_end)"),
    ("(appt->'status'<>'null'::jsonb AND appt->>'status' NOT IN\n    ('Scheduled','Confirmed','Checked Out','Cancelled','With Doctor','In Room','Checked In','In Room - Vitals Taken','Not Seen','Billed'))", "(jsonb_typeof(appt->'status') IS DISTINCT FROM 'string' OR appt->>'status' NOT IN ('Confirmed','Check-in','No-show','Check-out','Rescheduled','Scheduled','Cancelled'))"),
    ("(appt->'patient_id'<>'null'::jsonb AND appt->'deleted_at'='null'::jsonb\n     AND appt->'status'<>'null'::jsonb AND appt->>'status'<>'Cancelled')", "(appt->>'status'<>'Cancelled')"),
    ("ARRAY['patient_id','first_name','last_name','birth_date','primary_physician_id','deleted_at']", "ARRAY['patient_id','full_name','birth_date']"),
    (" OR NOT public.ehr_read_provider_id(patient->'primary_physician_id')", ""),
    ("NOT public.ehr_read_text(patient->'first_name',70) OR NOT public.ehr_read_text(patient->'last_name',70)", "NOT public.ehr_read_text(patient->'full_name',255)"),
    (" OR patient->'deleted_at'<>'null'::jsonb", " OR patient->'birth_date' IS DISTINCT FROM r.request_json->'birth_date'"),
    ("appt->'deleted_at'<>'null'::jsonb OR ", ""),
    ("(patient-'patient_id'-'primary_physician_id'-'deleted_at')", "(patient-'patient_id')"),
)
