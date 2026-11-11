-- John's idempotent operator step for patient-record deletion.
-- Agents and CI must never run this against a real database.
--
-- Create the NOLOGIN role if missing, revoke table rights, and grant EXECUTE
-- on the public delete function only. Optional admin LOGIN grant:
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
  IF to_regprocedure('public.delete_patient_keyed_records(uuid, uuid)') IS NOT NULL THEN
    REVOKE ALL ON FUNCTION public.delete_patient_keyed_records(uuid, uuid)
      FROM PUBLIC, cosmas_patient_deletion;
  END IF;
END $$;
