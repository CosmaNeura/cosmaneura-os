-- Optional follow-on for John's admin LOGIN. Run as the database owner /
-- superuser with CREATEROLE (RETENTION.md steps 1–3). Exact NOLOGIN role is
-- cosmas_patient_deletion; LOGIN name comes from -v admin_login=... :
--   psql "$ADMIN_URL" -v admin_login=cosmas_patient_deletion_admin \
--     -v ON_ERROR_STOP=1 -f scripts/ensure-patient-deletion-admin-login.sql
-- Suggested example login name only; do not hard-code a single role in the product.
-- The LOGIN needs membership + EXECUTE only (no table DML). Pending-file and
-- binding reads run inside SECURITY DEFINER helpers.

\if :{?admin_login}
GRANT cosmas_patient_deletion TO :"admin_login";
GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records(uuid) TO :"admin_login";
GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records_plan(uuid) TO :"admin_login";
GRANT EXECUTE ON FUNCTION public.patient_deletion_resolve_admin() TO :"admin_login";
GRANT EXECUTE ON FUNCTION public.patient_deletion_patient_box(uuid) TO :"admin_login";
GRANT EXECUTE ON FUNCTION public.patient_deletion_collect_file_keys(jsonb) TO :"admin_login";
GRANT EXECUTE ON FUNCTION public.patient_deletion_pending_list(uuid) TO :"admin_login";
GRANT EXECUTE ON FUNCTION public.patient_deletion_pending_record(uuid, uuid, jsonb) TO :"admin_login";
GRANT EXECUTE ON FUNCTION public.patient_deletion_pending_clear(uuid, text[]) TO :"admin_login";
GRANT EXECUTE ON FUNCTION public.patient_deletion_pending_delete(uuid) TO :"admin_login";
\else
\echo 'Set -v admin_login=... (example: cosmas_patient_deletion_admin)'
\quit 1
\endif
