-- Operator-only, one-time provisioning on the exact separate VM cluster.
-- psql -X --set=ON_ERROR_STOP=1 --set=expected_system_identifier=ACTUAL --file=...
-- Supply the generated password separately through a protected administrator session.
\set ON_ERROR_STOP on
SELECT (pg_control_system()).system_identifier::text = :'expected_system_identifier'
       AND current_user = 'postgres' AND NOT pg_is_in_recovery()
       AND current_setting('server_version_num')::int BETWEEN 160000 AND 169999 AS target_ok \gset
\if :target_ok
\else
  \quit 3
\endif
SELECT EXISTS(SELECT FROM pg_roles WHERE rolname = 'cosmabot_backup')
       OR EXISTS(SELECT FROM pg_replication_slots WHERE slot_name = 'cosmabot_backup') AS already_exists \gset
\if :already_exists
  -- Never alter an existing role or recreate/drop a slot and silently claim continuity.
  \quit 3
\endif
BEGIN;
CREATE ROLE cosmabot_backup LOGIN REPLICATION NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
GRANT pg_read_all_settings TO cosmabot_backup;
GRANT CONNECT ON DATABASE postgres TO cosmabot_backup;
GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system() TO cosmabot_backup;
GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_checkpoint() TO cosmabot_backup;
GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_init() TO cosmabot_backup;
GRANT EXECUTE ON FUNCTION pg_catalog.pg_switch_wal() TO cosmabot_backup;
COMMIT;
-- Reserve immediately: a slot with NULL restart_lsn is unsafe for the pinned receiver.
SELECT slot_name, lsn FROM pg_create_physical_replication_slot('cosmabot_backup', true);
