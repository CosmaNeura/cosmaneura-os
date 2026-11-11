-- Operator precondition for patient-record deletion (John owns this in real
-- environments). The Alembic migration never creates or grants this role. Local
-- synth CI and check-backend-local.py run this before `alembic upgrade head`.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cosmas_patient_deletion') THEN
    CREATE ROLE cosmas_patient_deletion NOLOGIN NOINHERIT;
  END IF;
END $$;
