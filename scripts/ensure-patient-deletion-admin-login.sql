-- Optional follow-on for John's admin LOGIN. Run with psql:
--   psql "$ADMIN_URL" -v admin_login=cosmas_patient_deletion_admin \
--     -v ON_ERROR_STOP=1 -f scripts/ensure-patient-deletion-admin-login.sql
-- Suggested example login name only; do not hard-code a single role in the product.

\if :{?admin_login}
GRANT cosmas_patient_deletion TO :"admin_login";
GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records(uuid) TO :"admin_login";
\else
\echo 'Set -v admin_login=... (example: cosmas_patient_deletion_admin)'
\quit 1
\endif
