"""Private Core appointment references and source local time"""

import sqlalchemy as sa
from alembic import op

revision = 'a2da6f94324e'
down_revision = '55377e01a1e5'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('patient_links', sa.Column('source_owner_id', sa.UUID(), nullable=True))
    op.add_column('patient_links', sa.Column('source_account_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_patient_source_owner', 'patient_links', 'principals', ['source_owner_id', 'box_id'], ['id', 'box_id'])
    op.create_foreign_key('fk_patient_source_account', 'patient_links', 'core_capture_accounts', ['source_account_id'], ['id'])
    op.create_check_constraint('ck_patient_source_scope', 'patient_links', '(source_owner_id IS NULL) = (source_account_id IS NULL)')
    op.add_column('appointment_observations', sa.Column('source_owner_id', sa.UUID(), nullable=True))
    op.add_column('appointment_observations', sa.Column('source_local_start', sa.DateTime(timezone=False), nullable=True))
    op.add_column('appointment_observations', sa.Column('source_sha256', sa.String(64), nullable=True))
    op.alter_column('appointment_observations', 'start_at', existing_type=sa.DateTime(timezone=True), nullable=True)
    op.create_foreign_key('fk_appointment_source_owner', 'appointment_observations', 'principals', ['source_owner_id', 'box_id'], ['id', 'box_id'])
    op.create_unique_constraint('uq_private_source_appointment', 'appointment_observations', ['source_owner_id', 'source', 'external_id'])
    op.create_check_constraint('ck_appointment_source_time', 'appointment_observations', '(start_at IS NOT NULL) <> (source_local_start IS NOT NULL)')
    op.create_check_constraint('ck_appointment_private_source', 'appointment_observations', "(source_owner_id IS NULL AND source_local_start IS NULL AND source_sha256 IS NULL) OR (source_owner_id IS NOT NULL AND source = 'cosmaneura_core' AND patient_link_id IS NOT NULL AND source_sha256 IS NOT NULL AND source_sha256 ~ '^[a-f0-9]{64}$')")
    op.execute(GUARDS)


def downgrade() -> None:
    raise RuntimeError('Disable Core connection opening; retain private references and source times')


GUARDS = r"""
CREATE FUNCTION public.private_patient_reference_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND (
  NEW.source_owner_id IS DISTINCT FROM OLD.source_owner_id OR
  NEW.source_account_id IS DISTINCT FROM OLD.source_account_id OR
  (OLD.source_owner_id IS NOT NULL AND (NEW.id,NEW.box_id,NEW.source_pair_key)
     IS DISTINCT FROM (OLD.id,OLD.box_id,OLD.source_pair_key)))
 THEN RAISE EXCEPTION 'private_patient_reference_immutable'; END IF;
 IF NEW.source_owner_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM public.core_capture_accounts c JOIN public.external_identities e ON e.id=c.external_identity_id
  WHERE c.id=NEW.source_account_id AND e.box_id=NEW.box_id AND e.principal_id=NEW.source_owner_id)
 THEN RAISE EXCEPTION 'private_patient_reference_scope'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER private_patient_reference BEFORE INSERT OR UPDATE ON public.patient_links
 FOR EACH ROW EXECUTE FUNCTION public.private_patient_reference_guard();

CREATE FUNCTION public.private_appointment_reference_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE link_owner uuid; link_box uuid;
BEGIN
 IF TG_OP='UPDATE' AND (
  NEW.source_owner_id IS DISTINCT FROM OLD.source_owner_id OR
  (OLD.source_owner_id IS NOT NULL AND (NEW.id,NEW.box_id,NEW.source,NEW.external_id,NEW.patient_link_id)
    IS DISTINCT FROM (OLD.id,OLD.box_id,OLD.source,OLD.external_id,OLD.patient_link_id)))
 THEN RAISE EXCEPTION 'private_appointment_reference_immutable'; END IF;
 IF NEW.patient_link_id IS NOT NULL THEN
  SELECT source_owner_id,box_id INTO link_owner,link_box FROM public.patient_links
   WHERE id=NEW.patient_link_id FOR SHARE;
  IF (NEW.source_owner_id IS NOT NULL OR link_owner IS NOT NULL) AND
    (NEW.source_owner_id IS DISTINCT FROM link_owner OR NEW.box_id IS DISTINCT FROM link_box)
  THEN RAISE EXCEPTION 'private_appointment_reference_scope'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER private_appointment_reference BEFORE INSERT OR UPDATE ON public.appointment_observations
 FOR EACH ROW EXECUTE FUNCTION public.private_appointment_reference_guard();

CREATE FUNCTION public.private_workspace_reference_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE link_owner uuid;
BEGIN
 SELECT source_owner_id INTO link_owner FROM public.patient_links WHERE id=NEW.patient_link_id FOR SHARE;
 IF link_owner IS NOT NULL AND link_owner IS DISTINCT FROM NEW.owner_id
 THEN RAISE EXCEPTION 'private_workspace_reference_scope'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER private_workspace_reference BEFORE INSERT OR UPDATE ON public.encounter_workspaces
 FOR EACH ROW EXECUTE FUNCTION public.private_workspace_reference_guard();
"""
