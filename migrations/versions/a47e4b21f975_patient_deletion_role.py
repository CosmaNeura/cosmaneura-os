"""Restrict patient-record deletes to one definer function.

The local flag is not enough, because any session can set it. Append-only
history deletes and the redaction update are allowed only while that flag is
on and current_user is cosmas_patient_deletion. That role owns the function,
cannot log in, and is not granted to the application runtime role.
"""

from alembic import op

revision = "a47e4b21f975"
down_revision = "z35c2d09e853"
branch_labels = None
depends_on = None

_ROLE = "cosmas_patient_deletion"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_ROLE}') THEN
            CREATE ROLE {_ROLE} NOLOGIN NOINHERIT;
          END IF;
        END $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_ROLE}")
    op.execute(
        f"GRANT SELECT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_ROLE}"
    )
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
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.delete_patient_keyed_records(
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
          IF p_patient IS NULL OR jsonb_typeof(p_plan) IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'patient records could not be deleted';
          END IF;
          PERFORM pg_catalog.set_config('cosmas.patient_deletion', 'on', true);
          UPDATE public.audit_events
             SET aggregate_id = 'redacted', detail = '{}'::jsonb
           WHERE aggregate_id = p_patient::text
             AND event_type IS DISTINCT FROM 'patient.records_deleted';
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
        f"ALTER FUNCTION public.delete_patient_keyed_records(uuid, jsonb) OWNER TO {_ROLE}"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.delete_patient_keyed_records(uuid, jsonb) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records(uuid, jsonb) TO CURRENT_USER"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.delete_patient_keyed_records(uuid, jsonb)")
    op.execute(
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {_ROLE}"
    )
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {_ROLE}")
    # The role is cluster-wide. Another database may still hold grants, and
    # DROP ROLE cannot succeed until those are gone. This database's functions
    # and grants are already reversed above.
    op.execute(
        f"""
        DO $$
        BEGIN
          DROP ROLE IF EXISTS {_ROLE};
        EXCEPTION
          WHEN dependent_objects_still_exist THEN
            NULL;
        END $$
        """
    )
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
