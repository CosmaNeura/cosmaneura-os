"""Admin path to delete one patient's records through one definer function.

The public entry point is ``delete_patient_keyed_records(patient_id, actor_id)``.
It checks from database rows that the actor is the practice owner for that
patient, derives the deletion plan server-side, redacts older audit events,
deletes the planned rows, and writes ``patient.records_deleted`` (IDs only).
EXECUTE stays revoked from PUBLIC. ``search_path`` stays pinned.

Row mutations run through a migrator-owned helper with the same two-argument
signature so ``session_replication_role = replica`` can skip satellite
immutability triggers for one call. That helper also re-checks the actor.

The EHR read request/snapshot cycle FKs are DEFERRABLE INITIALLY IMMEDIATE;
the helper SETs them DEFERRED for the call so both sides delete in one
transaction without a one-off ordered delete.

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

_EHR_SNAPSHOT_FK = "ehr_read_snapshots_observation_id_box_id_owner_id_fkey"
_EHR_REQUEST_FK = "fk_ehr_read_request_parent"


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.reject_workspace_history_change() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
          IF TG_OP IN ('DELETE', 'UPDATE')
             AND CURRENT_USER = 'cosmas_patient_deletion' THEN
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
             AND CURRENT_USER = 'cosmas_patient_deletion' THEN
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
             AND CURRENT_USER = 'cosmas_patient_deletion' THEN
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
             AND CURRENT_USER = 'cosmas_patient_deletion' THEN
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

    # Break the EHR request/snapshot cycle without a one-off ordered delete.
    op.execute(
        f"""
        ALTER TABLE public.ehr_read_snapshots
          DROP CONSTRAINT {_EHR_SNAPSHOT_FK},
          ADD CONSTRAINT {_EHR_SNAPSHOT_FK}
            FOREIGN KEY (observation_id, box_id, owner_id)
            REFERENCES public.ehr_read_requests (id, box_id, owner_id)
            DEFERRABLE INITIALLY IMMEDIATE
        """
    )
    op.execute(
        f"""
        ALTER TABLE public.ehr_read_requests
          DROP CONSTRAINT {_EHR_REQUEST_FK},
          ADD CONSTRAINT {_EHR_REQUEST_FK}
            FOREIGN KEY (parent_snapshot_id, box_id, owner_id)
            REFERENCES public.ehr_read_snapshots (id, box_id, owner_id)
            DEFERRABLE INITIALLY IMMEDIATE
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.patient_deletion_pending_files (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          patient_link_id uuid NOT NULL,
          kind varchar(16) NOT NULL,
          relative_path text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT patient_deletion_pending_files_kind_check
            CHECK (kind IN ('audio', 'uploads', 'exports')),
          CONSTRAINT patient_deletion_pending_files_path_check
            CHECK (
              char_length(relative_path) BETWEEN 1 AND 1024
              AND relative_path !~ '^[/\\\\]'
              AND relative_path !~ '\\.\\.'
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_patient_deletion_pending_files_patient
          ON public.patient_deletion_pending_files (patient_link_id)
        """
    )

    # Migrator-owned helper: same (patient, actor) args, re-checks admin, no plan.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public._cosmas_apply_patient_deletion_mutate(
          p_patient uuid, p_actor uuid
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
          v_box uuid;
          v_owner boolean;
          rec record;
          pk_cols text[];
          pk_list text;
        BEGIN
          IF p_patient IS NULL OR p_actor IS NULL THEN
            RAISE EXCEPTION 'patient records could not be deleted';
          END IF;
          SELECT pl.box_id INTO v_box
            FROM public.patient_links pl WHERE pl.id = p_patient;
          IF v_box IS NULL THEN
            RAISE EXCEPTION 'patient not found';
          END IF;
          SELECT (p.principal_type = 'human'
                  AND p.state = 'active'
                  AND p.is_owner
                  AND p.box_id = v_box)
            INTO v_owner
            FROM public.principals p WHERE p.id = p_actor;
          IF v_owner IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'admin authority required';
          END IF;

          EXECUTE 'SET LOCAL session_replication_role = replica';
          EXECUTE format(
            'SET CONSTRAINTS %I, %I DEFERRED',
            'ehr_read_snapshots_observation_id_box_id_owner_id_fkey',
            'fk_ehr_read_request_parent'
          );

          CREATE TEMP TABLE _cosmas_del_ids (
            aggregate_id text PRIMARY KEY
          ) ON COMMIT DROP;
          INSERT INTO _cosmas_del_ids(aggregate_id) VALUES (p_patient::text)
          ON CONFLICT DO NOTHING;

          -- Scrub ids from every patient_link_id table PK, plus ticket/workspace
          -- children used as audit aggregate ids.
          FOR rec IN
            SELECT c.relname AS table_name,
                   (SELECT array_agg(a.attname ORDER BY k.ord)
                      FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                      JOIN pg_attribute a
                        ON a.attrelid = con.conrelid AND a.attnum = k.attnum) AS cols
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_attribute pl
                ON pl.attrelid = c.oid AND pl.attname = 'patient_link_id'
               AND pl.attnum > 0 AND NOT pl.attisdropped
              JOIN pg_constraint con
                ON con.conrelid = c.oid AND con.contype = 'p'
             WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
               AND c.relname <> 'patient_deletion_pending_files'
          LOOP
            pk_cols := rec.cols;
            IF pk_cols IS NULL THEN
              CONTINUE;
            END IF;
            pk_list := array_to_string(
              ARRAY(SELECT format('%I::text', col) FROM unnest(pk_cols) AS col),
              ', '
            );
            EXECUTE format(
              'INSERT INTO _cosmas_del_ids(aggregate_id) '
              'SELECT DISTINCT u FROM public.%I t, '
              'LATERAL unnest(ARRAY[%s]) AS u '
              'WHERE t.patient_link_id = $1 '
              'ON CONFLICT DO NOTHING',
              rec.table_name, pk_list
            ) USING p_patient;
          END LOOP;
          INSERT INTO _cosmas_del_ids(aggregate_id)
            SELECT pr.id::text FROM public.private_recordings pr
             JOIN public.encounter_workspaces ew ON ew.id = pr.workspace_id
            WHERE ew.patient_link_id = p_patient
            ON CONFLICT DO NOTHING;
          INSERT INTO _cosmas_del_ids(aggregate_id)
            SELECT prf.id::text FROM public.private_recording_finishes prf
             JOIN public.private_recordings pr ON pr.id = prf.recording_id
             JOIN public.encounter_workspaces ew ON ew.id = pr.workspace_id
            WHERE ew.patient_link_id = p_patient
            ON CONFLICT DO NOTHING;
          INSERT INTO _cosmas_del_ids(aggregate_id)
            SELECT wn.id::text FROM public.workspace_notes wn
             JOIN public.encounter_workspaces ew ON ew.id = wn.workspace_id
            WHERE ew.patient_link_id = p_patient
            ON CONFLICT DO NOTHING;
          INSERT INTO _cosmas_del_ids(aggregate_id)
            SELECT a.id::text FROM public.artifacts a
             JOIN public.tickets t ON t.id = a.ticket_id
            WHERE t.patient_link_id = p_patient
            ON CONFLICT DO NOTHING;
          INSERT INTO _cosmas_del_ids(aggregate_id)
            SELECT d.id::text FROM public.decisions d
             JOIN public.tickets t ON t.id = d.ticket_id
            WHERE t.patient_link_id = p_patient
            ON CONFLICT DO NOTHING;
          INSERT INTO _cosmas_del_ids(aggregate_id)
            SELECT o.id::text FROM public.operations o
             JOIN public.tickets t ON t.id = o.ticket_id
            WHERE t.patient_link_id = p_patient
            ON CONFLICT DO NOTHING;
          INSERT INTO _cosmas_del_ids(aggregate_id)
            SELECT ar.id::text FROM public.action_revisions ar
             JOIN public.tickets t ON t.id = ar.ticket_id
            WHERE t.patient_link_id = p_patient
            ON CONFLICT DO NOTHING;
          INSERT INTO _cosmas_del_ids(aggregate_id)
            SELECT s.id::text FROM public.ehr_read_snapshots s
             JOIN public.ehr_read_requests r ON r.id = s.observation_id
            WHERE r.patient_link_id = p_patient
            ON CONFLICT DO NOTHING;

          UPDATE public.audit_events ae
             SET aggregate_id = 'redacted', detail = '{}'::jsonb
           WHERE ae.event_type IS DISTINCT FROM 'patient.records_deleted'
             AND ae.aggregate_id IN (SELECT aggregate_id FROM _cosmas_del_ids);

          -- Dependents without patient_link_id, before their parents go away.
          DELETE FROM public.workspace_note_reviews wnr
            USING public.workspace_notes wn, public.encounter_workspaces ew
           WHERE ew.patient_link_id = p_patient
             AND wn.workspace_id = ew.id AND wnr.note_id = wn.id;
          DELETE FROM public.workspace_notes wn
            USING public.encounter_workspaces ew
           WHERE ew.patient_link_id = p_patient AND wn.workspace_id = ew.id;
          DELETE FROM public.workspace_replies wr
            USING public.encounter_workspaces ew
           WHERE ew.patient_link_id = p_patient AND wr.workspace_id = ew.id;
          DELETE FROM public.workspace_entries we
            USING public.encounter_workspaces ew
           WHERE ew.patient_link_id = p_patient AND we.workspace_id = ew.id;
          DELETE FROM public.private_recording_finishes prf
            USING public.private_recordings pr, public.encounter_workspaces ew
           WHERE ew.patient_link_id = p_patient
             AND pr.workspace_id = ew.id AND prf.recording_id = pr.id;
          DELETE FROM public.private_recordings pr
            USING public.encounter_workspaces ew
           WHERE ew.patient_link_id = p_patient AND pr.workspace_id = ew.id;
          DELETE FROM public.artifacts a
            USING public.tickets t
           WHERE t.patient_link_id = p_patient AND a.ticket_id = t.id;
          DELETE FROM public.operations o
            USING public.tickets t
           WHERE t.patient_link_id = p_patient AND o.ticket_id = t.id;
          DELETE FROM public.decisions d
            USING public.tickets t
           WHERE t.patient_link_id = p_patient AND d.ticket_id = t.id;
          DELETE FROM public.action_revisions ar
            USING public.tickets t
           WHERE t.patient_link_id = p_patient AND ar.ticket_id = t.id;
          -- EHR snapshots sit in the request/snapshot cycle; delete them while
          -- the two DEFERRABLE FKs are deferred so requests can leave too.
          DELETE FROM public.ehr_read_snapshots s
            USING public.ehr_read_requests r
           WHERE r.patient_link_id = p_patient AND s.observation_id = r.id;

          -- Every public clinical table with a patient_link_id column.
          -- Skip patient_deletion_pending_files: those rows are committed with
          -- the delete so a later run can finish leftover stored files.
          FOR rec IN
            SELECT c.relname AS table_name
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_attribute pl
                ON pl.attrelid = c.oid AND pl.attname = 'patient_link_id'
               AND pl.attnum > 0 AND NOT pl.attisdropped
             WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
               AND c.relname <> 'patient_deletion_pending_files'
             ORDER BY c.relname
          LOOP
            EXECUTE format(
              'DELETE FROM public.%I WHERE patient_link_id = $1',
              rec.table_name
            ) USING p_patient;
          END LOOP;

          DELETE FROM public.patient_links WHERE id = p_patient;

          INSERT INTO public.audit_events (
            id, box_id, aggregate_type, aggregate_id, event_type,
            actor_principal_id, outcome, detail, created_at
          ) VALUES (
            gen_random_uuid(), v_box, 'patient_link', p_patient::text,
            'patient.records_deleted', p_actor, 'deleted', '{}'::jsonb, now()
          );
        END $$
        """
    )

    # Public entry: owned by the deletion role when available. No plan argument.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.delete_patient_keyed_records(
          p_patient uuid, p_actor uuid
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
          v_box uuid;
          v_owner boolean;
        BEGIN
          IF p_patient IS NULL OR p_actor IS NULL THEN
            RAISE EXCEPTION 'patient records could not be deleted';
          END IF;
          SELECT pl.box_id INTO v_box
            FROM public.patient_links pl WHERE pl.id = p_patient;
          IF v_box IS NULL THEN
            RAISE EXCEPTION 'patient not found';
          END IF;
          SELECT (p.principal_type = 'human'
                  AND p.state = 'active'
                  AND p.is_owner
                  AND p.box_id = v_box)
            INTO v_owner
            FROM public.principals p WHERE p.id = p_actor;
          IF v_owner IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'admin authority required';
          END IF;
          PERFORM public._cosmas_apply_patient_deletion_mutate(p_patient, p_actor);
        END $$
        """
    )

    # Drop any leftover plan-argument overloads from earlier shapes of this revision.
    op.execute(
        """
        DO $$
        BEGIN
          IF to_regprocedure('public.delete_patient_keyed_records(uuid, jsonb)') IS NOT NULL THEN
            DROP FUNCTION public.delete_patient_keyed_records(uuid, jsonb);
          END IF;
          IF to_regprocedure('public._cosmas_apply_patient_deletion_plan(uuid, jsonb)') IS NOT NULL THEN
            DROP FUNCTION public._cosmas_apply_patient_deletion_plan(uuid, jsonb);
          END IF;
        END $$
        """
    )

    op.execute(
        "REVOKE ALL ON FUNCTION public._cosmas_apply_patient_deletion_mutate(uuid, uuid) FROM PUBLIC"
    )
    op.execute("REVOKE ALL ON FUNCTION public.delete_patient_keyed_records(uuid, uuid) FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records(uuid, uuid) TO CURRENT_USER"
    )

    bind = op.get_bind()
    role_exists = (
        bind.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": _ROLE}).scalar()
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
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_ROLE}"
        )
        op.execute(
            "GRANT EXECUTE ON FUNCTION public._cosmas_apply_patient_deletion_mutate(uuid, uuid) "
            f"TO {_ROLE}"
        )
        if can_handoff:
            op.execute(
                f"ALTER FUNCTION public.delete_patient_keyed_records(uuid, uuid) OWNER TO {_ROLE}"
            )
            op.execute(f"REVOKE CREATE ON SCHEMA public FROM {_ROLE}")
        else:
            _LOG.info("cosmas_patient_deletion grant skipped")
            op.execute(f"REVOKE CREATE ON SCHEMA public FROM {_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.delete_patient_keyed_records(uuid, uuid)")
    op.execute("DROP FUNCTION IF EXISTS public.delete_patient_keyed_records(uuid, jsonb)")
    op.execute("DROP FUNCTION IF EXISTS public._cosmas_apply_patient_deletion_mutate(uuid, uuid)")
    op.execute("DROP FUNCTION IF EXISTS public._cosmas_apply_patient_deletion_plan(uuid, jsonb)")
    op.execute("DROP TABLE IF EXISTS public.patient_deletion_pending_files")
    op.execute(
        f"""
        ALTER TABLE public.ehr_read_requests
          DROP CONSTRAINT {_EHR_REQUEST_FK},
          ADD CONSTRAINT {_EHR_REQUEST_FK}
            FOREIGN KEY (parent_snapshot_id, box_id, owner_id)
            REFERENCES public.ehr_read_snapshots (id, box_id, owner_id)
        """
    )
    op.execute(
        f"""
        ALTER TABLE public.ehr_read_snapshots
          DROP CONSTRAINT {_EHR_SNAPSHOT_FK},
          ADD CONSTRAINT {_EHR_SNAPSHOT_FK}
            FOREIGN KEY (observation_id, box_id, owner_id)
            REFERENCES public.ehr_read_requests (id, box_id, owner_id)
        """
    )
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
