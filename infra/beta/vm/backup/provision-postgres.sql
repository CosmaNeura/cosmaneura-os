-- Operator-only, one-time provisioning on the exact separate VM cluster.
-- psql -X --set=ON_ERROR_STOP=1 --set=expected_system_identifier=ACTUAL --file=...
-- Supply the generated password separately through a protected administrator session.
\set ON_ERROR_STOP on
SELECT (pg_control_system()).system_identifier::text = :'expected_system_identifier'
       AND current_user = 'postgres' AND NOT pg_is_in_recovery()
       AND current_setting('server_version_num')::int BETWEEN 160000 AND 169999 AS target_ok \gset
\if :target_ok
\else
  DO $$ BEGIN RAISE EXCEPTION 'Backup provisioning refused: wrong source cluster or administrator'; END $$;
\endif
-- Reserve WAL only after the reviewed runtime's bounded retention is active.
-- PostgreSQL defaults to -1 (unlimited); provisioning against that profile can
-- exhaust the VM disk before the first receiver starts.
SELECT current_setting('wal_level') = 'replica'
       AND current_setting('archive_mode') = 'off'
       AND current_setting('max_wal_senders')::int >= 3
       AND current_setting('max_replication_slots')::int >= 2
       AND CASE WHEN current_setting('max_slot_wal_keep_size') = '-1' THEN false
                ELSE pg_size_bytes(current_setting('max_slot_wal_keep_size')) = 4294967296
           END AS retention_ok \gset
\if :retention_ok
\else
  DO $$ BEGIN RAISE EXCEPTION 'Backup provisioning refused: bounded replication runtime required'; END $$;
\endif
SELECT EXISTS(SELECT FROM pg_roles WHERE rolname = 'cosmabot_backup')
       OR EXISTS(SELECT FROM pg_replication_slots WHERE slot_name = 'cosmabot_backup') AS already_exists \gset
\if :already_exists
  -- Never alter an existing role or recreate/drop a slot and silently claim continuity.
  DO $$ BEGIN RAISE EXCEPTION 'Backup provisioning refused: role or slot already exists'; END $$;
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
