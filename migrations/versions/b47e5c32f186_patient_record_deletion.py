"""Admin path to delete one patient's records through one definer function.

Ordinary updates and deletes still fail. Append-only history deletes and the
redaction update are allowed only while the local ``cosmas.patient_deletion``
flag is on and ``current_user`` is ``cosmas_patient_deletion``. That role owns
the security-definer entry function, cannot log in, and is never granted to the
application runtime role.

Planned row changes run through a second security-definer helper owned by the
migrator. That helper sets ``session_replication_role = replica`` locally so
satellite immutability guards cannot block a confirmed patient delete.

This migration never creates ``cosmas_patient_deletion``. When that role already
exists, the migration applies the grants and ownership handoff. When it is
missing, the migration still succeeds and skips the grant. John runs
``scripts/ensure-patient-deletion-role.sql`` himself.
"""

from __future__ import annotations

import logging

from alembic import op
from sqlalchemy import text

revision = "b47e5c32f186"
down_revision = "a46f2c09d853"
branch_labels = None
depends_on = None

_ROLE = "cosmas_patient_deletion"
_LOG = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.reject_workspace_history_change() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
          IF TG_OP IN ('DELETE', 'UPDATE')
             AND CURRENT_USER = 'cosmas_patient_deletion'
             AND pg_catalog.current_setting('cosmas.patient_deletion', true) = 'on' THEN
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
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
          IF TG_OP IN ('DELETE', 'UPDATE')
             AND CURRENT_USER = 'cosmas_patient_deletion'
             AND pg_catalog.current_setting('cosmas.patient_deletion', true) = 'on' THEN
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
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
          IF TG_OP IN ('DELETE', 'UPDATE')
             AND CURRENT_USER = 'cosmas_patient_deletion'
             AND pg_catalog.current_setting('cosmas.patient_deletion', true) = 'on' THEN
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
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
          IF TG_OP IN ('DELETE', 'UPDATE')
             AND CURRENT_USER = 'cosmas_patient_deletion'
             AND pg_catalog.current_setting('cosmas.patient_deletion', true) = 'on' THEN
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
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
    # Table-owner helper: disable user triggers around each planned change so
    # satellite immutability guards cannot block a confirmed patient delete.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public._cosmas_apply_patient_deletion_plan(
          p_patient uuid, p_plan jsonb
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
          spec jsonb;
          rec jsonb;
          tbl text;
          col text;
          cols text[];
          conds text[];
          preds text[];
          sets text;
          bad integer;
          i integer;
        BEGIN
          IF pg_catalog.current_setting('cosmas.patient_deletion', true) IS DISTINCT FROM 'on'
             OR p_patient IS NULL
             OR jsonb_typeof(p_plan) IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'patient records could not be deleted';
          END IF;
          -- Owned by the migrator (superuser in normal installs). Skip user
          -- triggers for this call so satellite immutability guards cannot
          -- block a confirmed patient delete. LOCAL ends with the function.
          EXECUTE 'SET LOCAL session_replication_role = replica';
          -- Scrub older audit rows keyed to the patient or to any row id in the
          -- deletion plan (tickets, visits, recordings, and the rest). Never
          -- delete audit_events; clear detail and replace the aggregate id.
          WITH plan_ids AS (
            SELECT DISTINCT pk_val AS aggregate_id
              FROM jsonb_array_elements(p_plan) AS spec(value),
                   jsonb_array_elements(spec.value->'rows') AS row_arr(value),
                   jsonb_array_elements_text(row_arr.value) AS pk_val
          )
          UPDATE public.audit_events
             SET aggregate_id = 'redacted', detail = '{}'::jsonb
           WHERE event_type IS DISTINCT FROM 'patient.records_deleted'
             AND (
               aggregate_id = p_patient::text
               OR aggregate_id IN (SELECT aggregate_id FROM plan_ids)
             );
          FOR spec IN SELECT value FROM jsonb_array_elements(p_plan) LOOP
            tbl := spec->>'table';
            IF tbl IS NULL OR tbl !~ '^[a-z_][a-z0-9_]*$'
               OR tbl IN ('audit_events', 'alembic_version') THEN
              RAISE EXCEPTION 'patient records could not be deleted';
            END IF;
            SELECT coalesce(array_agg(value ORDER BY ord), ARRAY[]::text[]) INTO cols
              FROM jsonb_array_elements_text(spec->'pk') WITH ORDINALITY AS item(value, ord);
            IF cols = ARRAY[]::text[] THEN
              RAISE EXCEPTION 'patient records could not be deleted';
            END IF;
            FOREACH col IN ARRAY cols LOOP
              IF col !~ '^[a-z_][a-z0-9_]*$' THEN
                RAISE EXCEPTION 'patient records could not be deleted';
              END IF;
            END LOOP;
            -- One statement for every row of a table. A note that points at
            -- another note in the same table can be removed only when both
            -- rows disappear together.
            preds := ARRAY[]::text[];
            FOR rec IN SELECT value FROM jsonb_array_elements(spec->'rows') LOOP
              IF jsonb_typeof(rec) IS DISTINCT FROM 'array'
                 OR jsonb_array_length(rec) IS DISTINCT FROM array_length(cols, 1) THEN
                RAISE EXCEPTION 'patient records could not be deleted';
              END IF;
              conds := ARRAY[]::text[];
              FOR i IN 1..array_length(cols, 1) LOOP
                IF rec->>(i - 1) IS NULL THEN
                  RAISE EXCEPTION 'patient records could not be deleted';
                END IF;
                conds := conds || format('%I::text = %L', cols[i], rec->>(i - 1));
              END LOOP;
              preds := preds || format('(%s)', array_to_string(conds, ' AND '));
            END LOOP;
            IF preds = ARRAY[]::text[] THEN
              CONTINUE;
            END IF;
            IF spec->>'op' = 'null' THEN
              IF jsonb_typeof(spec->'columns') IS DISTINCT FROM 'array'
                 OR jsonb_array_length(spec->'columns') < 1 THEN
                RAISE EXCEPTION 'patient records could not be deleted';
              END IF;
              SELECT count(*) INTO bad
                FROM jsonb_array_elements_text(spec->'columns') AS item(value)
               WHERE value !~ '^[a-z_][a-z0-9_]*$';
              IF bad <> 0 THEN
                RAISE EXCEPTION 'patient records could not be deleted';
              END IF;
              SELECT string_agg(format('%I = NULL', value), ', ') INTO sets
                FROM jsonb_array_elements_text(spec->'columns') AS item(value);
              EXECUTE format(
                'UPDATE public.%I SET %s WHERE %s',
                tbl, sets, array_to_string(preds, ' OR ')
              );
            ELSIF spec->>'op' = 'delete' THEN
              EXECUTE format(
                'DELETE FROM public.%I WHERE %s',
                tbl, array_to_string(preds, ' OR ')
              );
            ELSE
              RAISE EXCEPTION 'patient records could not be deleted';
            END IF;
          END LOOP;
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.delete_patient_keyed_records(
          p_patient uuid, p_plan jsonb
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
          IF p_patient IS NULL OR jsonb_typeof(p_plan) IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'patient records could not be deleted';
          END IF;
          PERFORM pg_catalog.set_config('cosmas.patient_deletion', 'on', true);
          PERFORM public._cosmas_apply_patient_deletion_plan(p_patient, p_plan);
        END $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public._cosmas_apply_patient_deletion_plan(uuid, jsonb) FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.delete_patient_keyed_records(uuid, jsonb) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records(uuid, jsonb) TO CURRENT_USER"
    )
    # Soft-grant: only when John's role already exists. Never CREATE ROLE here.
    # Ownership handoff needs SET privilege on the role (or a superuser). A
    # restricted non-superuser migrator without SET must still succeed; a
    # cluster-wide role left by synthetic fixtures must not break a later
    # non-superuser compact migrate.
    bind = op.get_bind()
    role_exists = (
        bind.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": _ROLE}
        ).scalar()
        is not None
    )
    if not role_exists:
        _LOG.info("cosmas_patient_deletion is missing; grant skipped")
    else:
        can_handoff = bool(
            bind.execute(
                text(
                    """
                    SELECT EXISTS (
                      SELECT 1 FROM pg_roles
                       WHERE rolname = current_user AND rolsuper
                    ) OR pg_has_role(current_user, :role, 'SET')
                    """
                ),
                {"role": _ROLE},
            ).scalar()
        )
        op.execute(f"GRANT USAGE, CREATE ON SCHEMA public TO {_ROLE}")
        op.execute(
            f"GRANT SELECT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_ROLE}"
        )
        op.execute(
            "GRANT EXECUTE ON FUNCTION public._cosmas_apply_patient_deletion_plan(uuid, jsonb) "
            f"TO {_ROLE}"
        )
        if can_handoff:
            op.execute(
                f"ALTER FUNCTION public.delete_patient_keyed_records(uuid, jsonb) "
                f"OWNER TO {_ROLE}"
            )
            op.execute(f"REVOKE CREATE ON SCHEMA public FROM {_ROLE}")
        else:
            # Role exists (often from an earlier synth fixture on this cluster) but
            # this migrator cannot SET ROLE to it. Skip ownership; keep grants.
            _LOG.info("cosmas_patient_deletion grant skipped")
            op.execute(f"REVOKE CREATE ON SCHEMA public FROM {_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.delete_patient_keyed_records(uuid, jsonb)")
    op.execute("DROP FUNCTION IF EXISTS public._cosmas_apply_patient_deletion_plan(uuid, jsonb)")
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_ROLE}') THEN
            REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {_ROLE};
            REVOKE ALL ON SCHEMA public FROM {_ROLE};
          END IF;
        END $$
        """
    )
    # The role stays. John owns create/drop of cosmas_patient_deletion.
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
        BEGIN
          RAISE EXCEPTION 'patient setup history is immutable' USING ERRCODE = '23514';
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.reject_scheduling_account_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
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
