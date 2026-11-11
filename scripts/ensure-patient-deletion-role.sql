-- John's idempotent operator step for patient-record deletion.
-- Agents and CI must never run this against a real database.
--
-- Run as the database owner / superuser with CREATEROLE (CREATEROLE alone is
-- not enough for the REVOKE/GRANT on existing tables and SECURITY DEFINER
-- functions owned by the migrator). Exact NOLOGIN role: cosmas_patient_deletion.
--
-- Create cosmas_patient_deletion if missing, revoke table rights (including
-- patient_deletion_pending_files), and grant EXECUTE on the public delete +
-- admin helper functions. Next admin LOGIN grant:
--   psql ... -v admin_login=cosmas_patient_deletion_admin -f scripts/ensure-patient-deletion-admin-login.sql
-- Binding rows are inserted separately (see docs/RETENTION.md).

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cosmas_patient_deletion') THEN
    CREATE ROLE cosmas_patient_deletion NOLOGIN NOINHERIT;
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO cosmas_patient_deletion;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM cosmas_patient_deletion;

DO $$
BEGIN
  IF to_regclass('public.patient_deletion_in_progress') IS NOT NULL THEN
    REVOKE ALL ON TABLE public.patient_deletion_in_progress FROM cosmas_patient_deletion;
  END IF;
  IF to_regclass('public.patient_deletion_admin_bindings') IS NOT NULL THEN
    REVOKE ALL ON TABLE public.patient_deletion_admin_bindings FROM cosmas_patient_deletion;
  END IF;
  IF to_regclass('public.patient_deletion_pending_files') IS NOT NULL THEN
    REVOKE ALL ON TABLE public.patient_deletion_pending_files FROM cosmas_patient_deletion;
  END IF;
  IF to_regclass('public.alembic_version') IS NOT NULL THEN
    REVOKE ALL ON TABLE public.alembic_version FROM cosmas_patient_deletion;
  END IF;
  IF to_regclass('public.audit_events') IS NOT NULL THEN
    REVOKE ALL ON TABLE public.audit_events FROM cosmas_patient_deletion;
  END IF;
END $$;

DO $$
BEGIN
  IF to_regprocedure('public._cosmas_apply_patient_deletion_mutate(uuid)') IS NOT NULL THEN
    REVOKE ALL ON FUNCTION public._cosmas_apply_patient_deletion_mutate(uuid)
      FROM PUBLIC, cosmas_patient_deletion;
  END IF;
  IF to_regprocedure('public.delete_patient_keyed_records(uuid)') IS NOT NULL THEN
    REVOKE ALL ON FUNCTION public.delete_patient_keyed_records(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records(uuid)
      TO cosmas_patient_deletion;
  END IF;
  IF to_regprocedure('public.delete_patient_keyed_records_plan(uuid)') IS NOT NULL THEN
    REVOKE ALL ON FUNCTION public.delete_patient_keyed_records_plan(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records_plan(uuid)
      TO cosmas_patient_deletion;
  END IF;
  IF to_regprocedure('public.patient_deletion_resolve_admin()') IS NOT NULL THEN
    GRANT EXECUTE ON FUNCTION public.patient_deletion_resolve_admin()
      TO cosmas_patient_deletion;
  END IF;
  IF to_regprocedure('public.patient_deletion_patient_box(uuid)') IS NOT NULL THEN
    REVOKE ALL ON FUNCTION public.patient_deletion_patient_box(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION public.patient_deletion_patient_box(uuid)
      TO cosmas_patient_deletion;
  END IF;
  IF to_regprocedure('public.patient_deletion_collect_file_keys(jsonb)') IS NOT NULL THEN
    REVOKE ALL ON FUNCTION public.patient_deletion_collect_file_keys(jsonb) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION public.patient_deletion_collect_file_keys(jsonb)
      TO cosmas_patient_deletion;
  END IF;
  IF to_regprocedure('public.patient_deletion_pending_list(uuid)') IS NOT NULL THEN
    GRANT EXECUTE ON FUNCTION public.patient_deletion_pending_list(uuid)
      TO cosmas_patient_deletion;
  END IF;
  IF to_regprocedure('public.patient_deletion_pending_record(uuid, uuid, jsonb)') IS NOT NULL THEN
    GRANT EXECUTE ON FUNCTION public.patient_deletion_pending_record(uuid, uuid, jsonb)
      TO cosmas_patient_deletion;
  END IF;
  IF to_regprocedure('public.patient_deletion_pending_clear(uuid, text[])') IS NOT NULL THEN
    GRANT EXECUTE ON FUNCTION public.patient_deletion_pending_clear(uuid, text[])
      TO cosmas_patient_deletion;
  END IF;
  IF to_regprocedure('public.patient_deletion_pending_delete(uuid)') IS NOT NULL THEN
    GRANT EXECUTE ON FUNCTION public.patient_deletion_pending_delete(uuid)
      TO cosmas_patient_deletion;
  END IF;
  IF to_regprocedure('public.delete_patient_keyed_records(uuid, uuid)') IS NOT NULL THEN
    REVOKE ALL ON FUNCTION public.delete_patient_keyed_records(uuid, uuid)
      FROM PUBLIC, cosmas_patient_deletion;
  END IF;
END $$;
