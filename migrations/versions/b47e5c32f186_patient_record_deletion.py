"""Admin path to delete one patient's records through one definer function.

250-R: FK-ordered delete without session_replication_role or temp tables.
Coverage comes from pg_catalog with fail-closed PATIENT_OWNED /
EXCLUSIVE_CONTENT / PRESERVE / SHARED classification. Actor is bound to
session_user via patient_deletion_admin_bindings. Immutability triggers allow
changes only when current_user is the mutate-function owner and a
patient_deletion_in_progress row exists for txid_current().

Public entry: delete_patient_keyed_records(patient_id) RETURNS jsonb.
Read-only plan: delete_patient_keyed_records_plan(patient_id) RETURNS jsonb.

This migration never creates cosmas_patient_deletion. John runs
scripts/ensure-patient-deletion-role.sql himself.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "b47e5c32f186"
down_revision = "a46f2c09d853"
branch_labels = None
depends_on = None

_ROLE = "cosmas_patient_deletion"
_LOG = logging.getLogger("alembic.runtime.migration")
_SQL = Path(__file__).with_name("_b47e5c32f186_functions.sql")

_EHR_SNAPSHOT_FK = "ehr_read_snapshots_observation_id_box_id_owner_id_fkey"
_EHR_REQUEST_FK = "fk_ehr_read_request_parent"
_INBOX_ITEMS_FK = "fk_inbox_current_source"
_INBOX_SOURCES_FK = "inbox_sources_item_id_box_id_owner_id_fkey"
_VENDOR_WORK_FK = "fk_vendor_supersedes_scope"
_VENDOR_REV_FK = "vendor_work_revisions_ticket_id_workspace_id_box_id_owner__fkey"


def _guard(name: str, message: str, *, scheduling: bool = False) -> str:
    allow = """
          SELECT pd_role.rolname INTO v_owner
            FROM pg_proc pd_proc
            JOIN pg_roles pd_role ON pd_role.oid = pd_proc.proowner
           WHERE pd_proc.oid = to_regprocedure(
                   'public._cosmas_apply_patient_deletion_mutate(uuid)'
                 );
          -- Call active() only after the owner check so restricted runtime roles
          -- never need EXECUTE on the helper (runtime prep revokes PUBLIC execute).
          IF v_owner IS NOT NULL AND current_user = v_owner THEN
            IF public._cosmas_patient_deletion_active() THEN
              IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
              RETURN NEW;
            END IF;
          END IF;
"""
    if scheduling:
        body = f"""
        CREATE OR REPLACE FUNCTION public.{name}() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
          v_owner name;
        BEGIN
{allow}
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
        return body
    errcode = " USING ERRCODE = '23514'" if name == "immutable_patient_setup" else ""
    return f"""
        CREATE OR REPLACE FUNCTION public.{name}() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
          v_owner name;
        BEGIN
{allow}
          RAISE EXCEPTION '{message}'{errcode};
        END $$
        """



def _patch_owned_table_guards(connection) -> None:
    """Allow migrator-owned deletion to pass PATIENT_OWNED immutability triggers."""

    allow = """
          SELECT pd_role.rolname INTO v_pd_owner
            FROM pg_proc pd_proc
            JOIN pg_roles pd_role ON pd_role.oid = pd_proc.proowner
           WHERE pd_proc.oid = to_regprocedure(
                   'public._cosmas_apply_patient_deletion_mutate(uuid)'
                 );
          IF v_pd_owner IS NOT NULL AND current_user = v_pd_owner THEN
            IF public._cosmas_patient_deletion_active() THEN
              IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
              RETURN NEW;
            END IF;
          END IF;
"""
    rows = connection.execute(
        text(
            """
            SELECT DISTINCT p.oid::regprocedure::text AS identity, pg_get_functiondef(p.oid) AS src
              FROM pg_trigger t
              JOIN pg_class c ON c.oid = t.tgrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_proc p ON p.oid = t.tgfoid
             WHERE n.nspname = 'public'
               AND NOT t.tgisinternal
               AND c.relname IN (
                     SELECT table_name
                       FROM public._cosmas_patient_deletion_classes()
                      WHERE kind IN ('owned', 'exclusive')
                   )
               AND p.prokind = 'f'
            """
        )
    ).all()
    for identity, src in rows:
        if "_cosmas_patient_deletion_active()" in src:
            continue
        patched = src.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
        if re.search(r"(?i)\bdeclare\b", patched) and re.search(
            r"(?i)\bbegin\b", patched
        ):
            # Insert owner variable into the first DECLARE block.
            patched = re.sub(
                r"(?i)\bDECLARE\b",
                "DECLARE\n          v_pd_owner name;",
                patched,
                count=1,
            )
            patched = re.sub(
                r"(?i)\bBEGIN\b",
                "BEGIN\n" + allow,
                patched,
                count=1,
            )
        else:
            patched = re.sub(
                r"(?i)\bBEGIN\b",
                "DECLARE\n          v_pd_owner name;\nBEGIN\n" + allow,
                patched,
                count=1,
            )
        if "_cosmas_patient_deletion_active()" not in patched:
            raise RuntimeError(f"failed to patch trigger function {identity}")
        connection.execute(text(patched))



def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.patient_deletion_in_progress (
          txid bigint PRIMARY KEY,
          patient_link_id uuid NOT NULL,
          started_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("REVOKE ALL ON TABLE public.patient_deletion_in_progress FROM PUBLIC")
    op.execute(
        """
        DO $$
        DECLARE r record;
        BEGIN
          FOR r IN
            SELECT rolname FROM pg_roles
             WHERE rolname <> current_user AND NOT rolsuper
          LOOP
            BEGIN
              EXECUTE format(
                'REVOKE ALL ON TABLE public.patient_deletion_in_progress FROM %I',
                r.rolname
              );
            EXCEPTION WHEN insufficient_privilege THEN
              NULL;
            END;
          END LOOP;
        END $$
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.patient_deletion_admin_bindings (
          db_role name PRIMARY KEY,
          principal_id uuid NOT NULL,
          box_id uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT patient_deletion_admin_bindings_principal_fk
            FOREIGN KEY (principal_id, box_id)
            REFERENCES public.principals (id, box_id)
        )
        """
    )
    op.execute("REVOKE ALL ON TABLE public.patient_deletion_admin_bindings FROM PUBLIC")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.patient_deletion_pending_files (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          patient_link_id uuid NOT NULL,
          box_id uuid NOT NULL,
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
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.tables
             WHERE table_schema = 'public'
               AND table_name = 'patient_deletion_pending_files'
          ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = 'patient_deletion_pending_files'
               AND column_name = 'box_id'
          ) THEN
            ALTER TABLE public.patient_deletion_pending_files ADD COLUMN box_id uuid;
            DELETE FROM public.patient_deletion_pending_files WHERE box_id IS NULL;
            ALTER TABLE public.patient_deletion_pending_files
              ALTER COLUMN box_id SET NOT NULL;
          END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_patient_deletion_pending_files_patient
          ON public.patient_deletion_pending_files (patient_link_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_patient_deletion_pending_files_box
          ON public.patient_deletion_pending_files (box_id)
        """
    )

    op.execute(
        f"""
        ALTER TABLE public.ehr_read_snapshots
          DROP CONSTRAINT IF EXISTS {_EHR_SNAPSHOT_FK},
          ADD CONSTRAINT {_EHR_SNAPSHOT_FK}
            FOREIGN KEY (observation_id, box_id, owner_id)
            REFERENCES public.ehr_read_requests (id, box_id, owner_id)
            DEFERRABLE INITIALLY IMMEDIATE
        """
    )
    op.execute(
        f"""
        ALTER TABLE public.ehr_read_requests
          DROP CONSTRAINT IF EXISTS {_EHR_REQUEST_FK},
          ADD CONSTRAINT {_EHR_REQUEST_FK}
            FOREIGN KEY (parent_snapshot_id, box_id, owner_id)
            REFERENCES public.ehr_read_snapshots (id, box_id, owner_id)
            DEFERRABLE INITIALLY IMMEDIATE
        """
    )

    op.execute(
        f"""
        ALTER TABLE public.inbox_items
          DROP CONSTRAINT IF EXISTS {_INBOX_ITEMS_FK},
          ADD CONSTRAINT {_INBOX_ITEMS_FK}
            FOREIGN KEY (current_source_id, id)
            REFERENCES public.inbox_sources (id, item_id)
            DEFERRABLE INITIALLY IMMEDIATE
        """
    )
    op.execute(
        f"""
        ALTER TABLE public.inbox_sources
          DROP CONSTRAINT IF EXISTS {_INBOX_SOURCES_FK},
          ADD CONSTRAINT {_INBOX_SOURCES_FK}
            FOREIGN KEY (item_id, box_id, owner_id)
            REFERENCES public.inbox_items (id, box_id, owner_id)
            DEFERRABLE INITIALLY IMMEDIATE
        """
    )
    op.execute(
        f"""
        ALTER TABLE public.vendor_work
          DROP CONSTRAINT IF EXISTS {_VENDOR_WORK_FK},
          ADD CONSTRAINT {_VENDOR_WORK_FK}
            FOREIGN KEY (
              supersedes_operation_id, workspace_id, box_id, owner_id, patient_link_id
            )
            REFERENCES public.vendor_work_revisions (
              intended_operation_id, workspace_id, box_id, owner_id, patient_link_id
            )
            DEFERRABLE INITIALLY IMMEDIATE
        """
    )
    op.execute(
        f"""
        ALTER TABLE public.vendor_work_revisions
          DROP CONSTRAINT IF EXISTS {_VENDOR_REV_FK},
          ADD CONSTRAINT {_VENDOR_REV_FK}
            FOREIGN KEY (ticket_id, workspace_id, box_id, owner_id, patient_link_id)
            REFERENCES public.vendor_work (
              ticket_id, workspace_id, box_id, owner_id, patient_link_id
            )
            DEFERRABLE INITIALLY IMMEDIATE
        """
    )

    # Drop legacy signatures before loading the new bodies.
    op.execute("DROP FUNCTION IF EXISTS public.delete_patient_keyed_records(uuid, uuid)")
    op.execute("DROP FUNCTION IF EXISTS public.delete_patient_keyed_records(uuid, jsonb)")
    op.execute("DROP FUNCTION IF EXISTS public._cosmas_apply_patient_deletion_mutate(uuid, uuid)")
    op.execute("DROP FUNCTION IF EXISTS public._cosmas_apply_patient_deletion_plan(uuid, jsonb)")

    op.execute(_SQL.read_text(encoding="utf-8"))

    op.execute(_guard("reject_workspace_history_change", "workspace history is immutable"))
    op.execute(_guard("reject_provider_history_change", "provider history is immutable"))
    op.execute(_guard("immutable_patient_setup", "patient setup history is immutable"))
    op.execute(
        _guard(
            "reject_scheduling_account_change",
            "Scheduling correspondence is immutable",
            scheduling=True,
        )
    )
    _patch_owned_table_guards(op.get_bind())

    for fn in (
        "public._cosmas_pk_text_expr(text, text[])",
        "public._cosmas_patient_deletion_classes()",
        "public._cosmas_patient_deletion_exclusive_refs()",
        "public._cosmas_patient_deletion_active()",
        "public._cosmas_patient_deletion_build_plan(uuid)",
        "public.delete_patient_keyed_records_plan(uuid)",
        "public._cosmas_apply_patient_deletion_mutate(uuid)",
        "public.delete_patient_keyed_records(uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")

    op.execute(
        "GRANT EXECUTE ON FUNCTION public._cosmas_patient_deletion_active() TO PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records_plan(uuid) TO PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records(uuid) TO CURRENT_USER"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public._cosmas_patient_deletion_classes() TO PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public._cosmas_patient_deletion_exclusive_refs() TO PUBLIC"
    )

    bind = op.get_bind()
    role_exists = (
        bind.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": _ROLE}).scalar()
        is not None
    )
    if not role_exists:
        _LOG.info("cosmas_patient_deletion is missing; grant skipped")
    else:
        op.execute(
            "GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records(uuid) "
            f"TO {_ROLE}"
        )
        op.execute(
            "REVOKE ALL ON FUNCTION public._cosmas_apply_patient_deletion_mutate(uuid) "
            f"FROM {_ROLE}"
        )
        op.execute(
            f"REVOKE ALL ON TABLE public.patient_deletion_in_progress FROM {_ROLE}"
        )
        op.execute(
            f"REVOKE ALL ON TABLE public.patient_deletion_admin_bindings FROM {_ROLE}"
        )
        op.execute(
            f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {_ROLE}"
        )
        op.execute(f"GRANT USAGE ON SCHEMA public TO {_ROLE}")
        op.execute(
            "GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records(uuid) "
            f"TO {_ROLE}"
        )



def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.delete_patient_keyed_records(uuid)")
    op.execute("DROP FUNCTION IF EXISTS public.delete_patient_keyed_records_plan(uuid)")
    op.execute("DROP FUNCTION IF EXISTS public._cosmas_apply_patient_deletion_mutate(uuid)")
    op.execute("DROP FUNCTION IF EXISTS public._cosmas_patient_deletion_build_plan(uuid)")
    op.execute("DROP FUNCTION IF EXISTS public._cosmas_patient_deletion_active()")
    op.execute("DROP FUNCTION IF EXISTS public._cosmas_patient_deletion_exclusive_refs()")
    op.execute("DROP FUNCTION IF EXISTS public._cosmas_patient_deletion_classes()")
    op.execute("DROP FUNCTION IF EXISTS public._cosmas_pk_text_expr(text, text[])")
    op.execute("DROP FUNCTION IF EXISTS public.delete_patient_keyed_records(uuid, uuid)")
    op.execute("DROP FUNCTION IF EXISTS public._cosmas_apply_patient_deletion_mutate(uuid, uuid)")
    op.execute("DROP TABLE IF EXISTS public.patient_deletion_pending_files")
    op.execute("DROP TABLE IF EXISTS public.patient_deletion_admin_bindings")
    op.execute("DROP TABLE IF EXISTS public.patient_deletion_in_progress")
    op.execute(
        f"""
        ALTER TABLE public.ehr_read_requests
          DROP CONSTRAINT IF EXISTS {_EHR_REQUEST_FK},
          ADD CONSTRAINT {_EHR_REQUEST_FK}
            FOREIGN KEY (parent_snapshot_id, box_id, owner_id)
            REFERENCES public.ehr_read_snapshots (id, box_id, owner_id)
        """
    )
    op.execute(
        f"""
        ALTER TABLE public.ehr_read_snapshots
          DROP CONSTRAINT IF EXISTS {_EHR_SNAPSHOT_FK},
          ADD CONSTRAINT {_EHR_SNAPSHOT_FK}
            FOREIGN KEY (observation_id, box_id, owner_id)
            REFERENCES public.ehr_read_requests (id, box_id, owner_id)
        """
    )
    op.execute(
        f"""
        ALTER TABLE public.inbox_items
          DROP CONSTRAINT IF EXISTS {_INBOX_ITEMS_FK},
          ADD CONSTRAINT {_INBOX_ITEMS_FK}
            FOREIGN KEY (current_source_id, id)
            REFERENCES public.inbox_sources (id, item_id)
            DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        f"""
        ALTER TABLE public.inbox_sources
          DROP CONSTRAINT IF EXISTS {_INBOX_SOURCES_FK},
          ADD CONSTRAINT {_INBOX_SOURCES_FK}
            FOREIGN KEY (item_id, box_id, owner_id)
            REFERENCES public.inbox_items (id, box_id, owner_id)
        """
    )
    op.execute(
        f"""
        ALTER TABLE public.vendor_work
          DROP CONSTRAINT IF EXISTS {_VENDOR_WORK_FK},
          ADD CONSTRAINT {_VENDOR_WORK_FK}
            FOREIGN KEY (
              supersedes_operation_id, workspace_id, box_id, owner_id, patient_link_id
            )
            REFERENCES public.vendor_work_revisions (
              intended_operation_id, workspace_id, box_id, owner_id, patient_link_id
            )
            DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        f"""
        ALTER TABLE public.vendor_work_revisions
          DROP CONSTRAINT IF EXISTS {_VENDOR_REV_FK},
          ADD CONSTRAINT {_VENDOR_REV_FK}
            FOREIGN KEY (ticket_id, workspace_id, box_id, owner_id, patient_link_id)
            REFERENCES public.vendor_work (
              ticket_id, workspace_id, box_id, owner_id, patient_link_id
            )
            DEFERRABLE INITIALLY DEFERRED
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
    for name, message, scheduling in (
        ("reject_workspace_history_change", "workspace history is immutable", False),
        ("reject_provider_history_change", "provider history is immutable", False),
        ("immutable_patient_setup", "patient setup history is immutable", False),
        ("reject_scheduling_account_change", "Scheduling correspondence is immutable", True),
    ):
        if scheduling:
            op.execute(
                f"""
                CREATE OR REPLACE FUNCTION public.{name}() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                  IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'Scheduling correspondence is immutable';
                  END IF;
                  IF (to_jsonb(NEW) - 'revoked_at') IS DISTINCT FROM (to_jsonb(OLD) - 'revoked_at')
                     OR OLD.revoked_at IS NOT NULL
                     AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
                    RAISE EXCEPTION 'Scheduling correspondence is immutable';
                  END IF;
                  RETURN NEW;
                END $$
                """
            )
        elif name == "immutable_patient_setup":
            op.execute(
                f"""
                CREATE OR REPLACE FUNCTION public.{name}() RETURNS trigger
                LANGUAGE plpgsql SET search_path = pg_catalog AS $$
                BEGIN
                  RAISE EXCEPTION '{message}' USING ERRCODE = '23514';
                END $$
                """
            )
        else:
            op.execute(
                f"""
                CREATE OR REPLACE FUNCTION public.{name}() RETURNS trigger
                LANGUAGE plpgsql SET search_path = pg_catalog AS $$
                BEGIN RAISE EXCEPTION '{message}'; END $$
                """
            )
