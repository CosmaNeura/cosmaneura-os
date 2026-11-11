-- John's idempotent operator step for patient-record deletion.
-- Agents and CI must never run this against a real database.
-- Create the NOLOGIN role if missing, then apply the grants the deletion
-- function needs. If the migration already created delete_patient_keyed_records
-- before this role existed, reassign ownership here as well.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cosmas_patient_deletion') THEN
    CREATE ROLE cosmas_patient_deletion NOLOGIN NOINHERIT;
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO cosmas_patient_deletion;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cosmas_patient_deletion;

DO $$
BEGIN
  IF to_regprocedure('public._cosmas_apply_patient_deletion_mutate(uuid, uuid)') IS NOT NULL THEN
    GRANT EXECUTE ON FUNCTION public._cosmas_apply_patient_deletion_mutate(uuid, uuid)
      TO cosmas_patient_deletion;
  END IF;
  IF to_regprocedure('public.delete_patient_keyed_records(uuid, uuid)') IS NOT NULL THEN
    ALTER FUNCTION public.delete_patient_keyed_records(uuid, uuid)
      OWNER TO cosmas_patient_deletion;
  END IF;
END $$;
