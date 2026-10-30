"""Let one confirmed patient-record delete pass immutability triggers.

Ordinary updates and deletes still fail. A transaction that sets the local
`cosmas.patient_deletion` flag may delete. The flag is not a grant and does not
survive the transaction.
"""

from alembic import op

revision = "z35c2d09e853"
down_revision = "y24f0a87c631"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.reject_workspace_history_change() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND pg_catalog.current_setting('cosmas.patient_deletion', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'workspace history is immutable';
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.reject_provider_history_change() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND pg_catalog.current_setting('cosmas.patient_deletion', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'provider history is immutable';
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.immutable_patient_setup() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND pg_catalog.current_setting('cosmas.patient_deletion', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'patient setup history is immutable' USING ERRCODE = '23514';
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.reject_scheduling_account_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND pg_catalog.current_setting('cosmas.patient_deletion', true) = 'on' THEN
            RETURN OLD;
          END IF;
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Scheduling correspondence is immutable';
          END IF;
          IF (to_jsonb(NEW) - 'revoked_at') IS DISTINCT FROM (to_jsonb(OLD) - 'revoked_at')
             OR OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
            RAISE EXCEPTION 'Scheduling correspondence is immutable';
          END IF;
          RETURN NEW;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.reject_workspace_history_change() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN RAISE EXCEPTION 'workspace history is immutable'; END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.reject_provider_history_change() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN RAISE EXCEPTION 'provider history is immutable'; END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.immutable_patient_setup() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN RAISE EXCEPTION 'patient setup history is immutable' USING ERRCODE = '23514'; END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.reject_scheduling_account_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Scheduling correspondence is immutable'; END IF;
          IF (to_jsonb(NEW) - 'revoked_at') IS DISTINCT FROM (to_jsonb(OLD) - 'revoked_at')
             OR OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
            RAISE EXCEPTION 'Scheduling correspondence is immutable';
          END IF;
          RETURN NEW;
        END $$
        """
    )
