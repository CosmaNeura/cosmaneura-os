from __future__ import annotations

import hmac
import json
import os
import secrets
from collections.abc import Iterator
from uuid import uuid4

import pytest
from psycopg import sql
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError

from cosmas_os.application import database_preparation
from cosmas_os.application.database_preparation import (
    DatabasePreparationError,
    prepare_beta_database,
)
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION


def test_database_preparation_is_idempotent_and_proves_denials() -> None:
    admin_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://cosmas:cosmas@localhost:54329/cosmas_os",
    )
    role = f"cosmas_runtime_test_{uuid4().hex[:12]}"
    password = "invented-test-password-1234"
    runtime_url = make_url(admin_url).set(username=role, password=password).render_as_string(
        hide_password=False
    )

    try:
        first = prepare_beta_database(admin_url, runtime_url, require_verify_full=False)
        second = prepare_beta_database(admin_url, runtime_url, require_verify_full=False)

        assert first == second
        assert first.schema_revision == EXPECTED_SCHEMA_REVISION
        assert first.schema_at_expected_head is True
        assert first.runtime_role_non_admin is True
        assert first.runtime_ddl_denied is True
        assert first.audit_update_denied is True
        assert first.audit_delete_denied is True

        evidence = json.loads(first.sanitized_json())
        assert evidence["status"] == "ready"
        assert len(evidence["evidence_sha256"]) == 64
        serialized = first.sanitized_json()
        assert password not in serialized
        assert role not in serialized
        admin_host = make_url(admin_url).host
        assert admin_host is not None
        assert admin_host not in serialized
        runtime_engine = create_engine(runtime_url)
        try:
            with runtime_engine.connect() as connection:
                permissions = connection.execute(text("SELECT "
                    "has_table_privilege(current_user,'public.practice_owner_reservations','SELECT') AS read, "
                    "has_table_privilege(current_user,'public.practice_owner_reservations','INSERT') AS insert, "
                    "has_table_privilege(current_user,'public.practice_owner_reservations','DELETE') AS delete, "
                    "has_column_privilege(current_user,'public.practice_owner_reservations','consumed_at','UPDATE') AS consume, "
                    "has_column_privilege(current_user,'public.practice_owner_reservations','subject','UPDATE') AS subject_update" )).mappings().one()
                assert dict(permissions) == {"read": True, "insert": False, "delete": False, "consume": True, "subject_update": False}
            for statement in ("DELETE FROM public.practice_owner_reservations WHERE false",
                              "UPDATE public.practice_owner_reservations SET subject='forged' WHERE false"):
                with pytest.raises(DBAPIError), runtime_engine.begin() as connection:
                    connection.execute(text(statement))
            # H1: runtime has zero rights on patient-deletion control tables after
            # prep runs twice. Re-running must not restore DML.
            with runtime_engine.connect() as connection:
                locked = connection.execute(
                    text(
                        "SELECT coalesce(bool_and("
                        "NOT has_table_privilege(current_user, format('public.%I', t), 'SELECT') AND "
                        "NOT has_table_privilege(current_user, format('public.%I', t), 'INSERT') AND "
                        "NOT has_table_privilege(current_user, format('public.%I', t), 'UPDATE') AND "
                        "NOT has_table_privilege(current_user, format('public.%I', t), 'DELETE') AND "
                        "NOT has_table_privilege(current_user, format('public.%I', t), 'TRUNCATE') AND "
                        "NOT has_table_privilege(current_user, format('public.%I', t), 'REFERENCES') AND "
                        "NOT has_table_privilege(current_user, format('public.%I', t), 'TRIGGER')"
                        "), false) FROM unnest(ARRAY["
                        "'patient_deletion_admin_bindings',"
                        "'patient_deletion_in_progress',"
                        "'patient_deletion_pending_files'"
                        "]::text[]) AS t"
                    )
                ).scalar_one()
                assert locked is True
                plan_ok = connection.execute(
                    text(
                        "SELECT has_function_privilege("
                        "current_user,"
                        "'public.delete_patient_keyed_records_plan(uuid)',"
                        "'EXECUTE')"
                    )
                ).scalar_one()
                delete_ok = connection.execute(
                    text(
                        "SELECT has_function_privilege("
                        "current_user,"
                        "'public.delete_patient_keyed_records(uuid)',"
                        "'EXECUTE')"
                    )
                ).scalar_one()
                assert plan_ok is True
                assert delete_ok is False
            for statement in (
                "UPDATE public.patient_deletion_admin_bindings "
                "SET principal_id = principal_id WHERE false",
                "INSERT INTO public.patient_deletion_admin_bindings "
                "(db_role, principal_id, box_id) VALUES "
                "('forged', '00000000-0000-4000-8000-000000000001'::uuid, "
                "'00000000-0000-4000-8000-000000000002'::uuid)",
                "INSERT INTO public.patient_deletion_in_progress "
                "(txid, patient_link_id) VALUES "
                "(txid_current(), '00000000-0000-4000-8000-000000000001'::uuid)",
                "INSERT INTO public.patient_deletion_pending_files "
                "(patient_link_id, box_id, kind, relative_path) VALUES "
                "('00000000-0000-4000-8000-000000000001'::uuid, "
                "'00000000-0000-4000-8000-000000000002'::uuid, "
                "'uploads', 'forged/front.png')",
            ):
                with pytest.raises(DBAPIError), runtime_engine.begin() as connection:
                    connection.execute(text(statement))
        finally:
            runtime_engine.dispose()
    finally:
        engine = create_engine(admin_url)
        try:
            with engine.begin() as connection:
                quoted_role = connection.dialect.identifier_preparer.quote_identifier(role)
                exists = connection.execute(
                    text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
                    {"role": role},
                ).scalar_one()
                if exists:
                    connection.execute(text(f"DROP OWNED BY {quoted_role}"))
                    connection.execute(text(f"DROP ROLE {quoted_role}"))
        finally:
            engine.dispose()


def test_database_preparation_rolls_back_password_and_schema_on_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://cosmas:cosmas@localhost:54329/cosmas_os",
    )
    role = f"cosmas_runtime_rollback_{uuid4().hex[:10]}"
    first_password = "invented-first-password-1234"
    candidate_password = "invented-candidate-password-5678"
    runtime_url = make_url(admin_url).set(username=role, password=first_password).render_as_string(
        hide_password=False
    )
    candidate_url = make_url(admin_url).set(
        username=role,
        password=candidate_password,
    ).render_as_string(hide_password=False)
    original_run_forward_migrations = database_preparation._run_forward_migrations

    try:
        prepare_beta_database(admin_url, runtime_url, require_verify_full=False)
        admin_engine = create_engine(admin_url)
        try:
            with admin_engine.connect() as connection:
                initial_password_verifier = connection.execute(
                    text("SELECT rolpassword FROM pg_authid WHERE rolname = :role"),
                    {"role": role},
                ).scalar_one()
        finally:
            admin_engine.dispose()
        assert isinstance(initial_password_verifier, str)
        assert initial_password_verifier.startswith("SCRAM-SHA-256$")

        def fail_after_transactional_ddl(connection: Connection, _config_path: object) -> None:
            connection.execute(text("CREATE TABLE public.cosmas_prep_rollback_probe (id integer)"))
            raise DatabasePreparationError("injected migration failure")

        monkeypatch.setattr(
            database_preparation,
            "_run_forward_migrations",
            fail_after_transactional_ddl,
        )
        with pytest.raises(DatabasePreparationError, match="injected migration failure"):
            prepare_beta_database(admin_url, candidate_url, require_verify_full=False)

        # Inspect the role catalog directly: a test cluster may deliberately use
        # host=trust, where connecting with either password proves nothing.
        admin_engine = create_engine(admin_url)
        try:
            with admin_engine.connect() as connection:
                rolled_back_password_verifier = connection.execute(
                    text("SELECT rolpassword FROM pg_authid WHERE rolname = :role"),
                    {"role": role},
                ).scalar_one()
                assert connection.execute(
                    text("SELECT to_regclass('public.cosmas_prep_rollback_probe')")
                ).scalar_one_or_none() is None
        finally:
            admin_engine.dispose()
        assert hmac.compare_digest(
            rolled_back_password_verifier,
            initial_password_verifier,
        )

        monkeypatch.setattr(
            database_preparation,
            "_run_forward_migrations",
            original_run_forward_migrations,
        )
        evidence = prepare_beta_database(admin_url, candidate_url, require_verify_full=False)
        assert evidence.status == "ready"
        admin_engine = create_engine(admin_url)
        try:
            with admin_engine.connect() as connection:
                rotated_password_verifier = connection.execute(
                    text("SELECT rolpassword FROM pg_authid WHERE rolname = :role"),
                    {"role": role},
                ).scalar_one()
        finally:
            admin_engine.dispose()
        assert not hmac.compare_digest(
            rotated_password_verifier,
            initial_password_verifier,
        )
    finally:
        monkeypatch.setattr(
            database_preparation,
            "_run_forward_migrations",
            original_run_forward_migrations,
        )
        engine = create_engine(admin_url)
        try:
            with engine.begin() as connection:
                connection.execute(text("DROP TABLE IF EXISTS public.cosmas_prep_rollback_probe"))
                quoted_role = connection.dialect.identifier_preparer.quote_identifier(role)
                exists = connection.execute(
                    text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
                    {"role": role},
                ).scalar_one()
                if exists:
                    connection.execute(text(f"DROP OWNED BY {quoted_role}"))
                    connection.execute(text(f"DROP ROLE {quoted_role}"))
        finally:
            engine.dispose()


def test_database_preparation_requires_every_ordinary_table_dml_privilege() -> None:
    admin_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://cosmas:cosmas@localhost:54329/cosmas_os",
    )
    role = f"cosmas_runtime_dml_{uuid4().hex[:12]}"
    password = "invented-runtime-password-1234"
    runtime_url = make_url(admin_url).set(username=role, password=password).render_as_string(
        hide_password=False
    )

    try:
        prepare_beta_database(admin_url, runtime_url, require_verify_full=False)
        admin_engine = create_engine(admin_url)
        try:
            quoted_role = admin_engine.dialect.identifier_preparer.quote_identifier(role)
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                with admin_engine.begin() as connection:
                    connection.execute(
                        text(f"REVOKE {privilege} ON TABLE public.tickets FROM {quoted_role}")
                    )
                verification = database_preparation._verify_runtime_role(
                    runtime_url,
                    make_url(runtime_url),
                )
                assert verification["non_admin"] is False
                with admin_engine.begin() as connection:
                    connection.execute(
                        text(f"GRANT {privilege} ON TABLE public.tickets TO {quoted_role}")
                    )

            verification = database_preparation._verify_runtime_role(
                runtime_url,
                make_url(runtime_url),
            )
            assert verification["non_admin"] is True
        finally:
            admin_engine.dispose()
    finally:
        engine = create_engine(admin_url)
        try:
            with engine.begin() as connection:
                quoted_role = connection.dialect.identifier_preparer.quote_identifier(role)
                exists = connection.execute(
                    text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
                    {"role": role},
                ).scalar_one()
                if exists:
                    connection.execute(text(f"DROP OWNED BY {quoted_role}"))
                    connection.execute(text(f"DROP ROLE {quoted_role}"))
        finally:
            engine.dispose()


def test_database_preparation_removes_public_table_and_sequence_privileges() -> None:
    admin_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://cosmas:cosmas@localhost:54329/cosmas_os",
    )
    role = f"cosmas_runtime_public_{uuid4().hex[:10]}"
    password = "invented-runtime-password-1234"
    runtime_url = make_url(admin_url).set(username=role, password=password).render_as_string(
        hide_password=False
    )
    sequence_name = f"cosmas_privilege_probe_{uuid4().hex[:10]}"
    admin_engine = create_engine(admin_url)

    try:
        with admin_engine.begin() as connection:
            quoted_sequence = connection.dialect.identifier_preparer.quote_identifier(sequence_name)
            connection.execute(text(f"CREATE SEQUENCE public.{quoted_sequence}"))
            connection.execute(text("GRANT TRUNCATE ON TABLE public.tickets TO PUBLIC"))
            connection.execute(text(f"GRANT UPDATE ON SEQUENCE public.{quoted_sequence} TO PUBLIC"))

        prepare_beta_database(admin_url, runtime_url, require_verify_full=False)

        runtime_engine = create_engine(runtime_url)
        try:
            with runtime_engine.connect() as connection:
                assert connection.execute(
                    text(
                        "SELECT has_table_privilege(current_user, 'public.tickets', 'TRUNCATE')"
                    )
                ).scalar_one() is False
                assert connection.execute(
                    text(
                        "SELECT has_sequence_privilege(current_user, :sequence, 'UPDATE')"
                    ),
                    {"sequence": f"public.{sequence_name}"},
                ).scalar_one() is False
        finally:
            runtime_engine.dispose()
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text("REVOKE TRUNCATE ON TABLE public.tickets FROM PUBLIC"))
            quoted_sequence = connection.dialect.identifier_preparer.quote_identifier(sequence_name)
            connection.execute(text(f"DROP SEQUENCE IF EXISTS public.{quoted_sequence}"))
            quoted_role = connection.dialect.identifier_preparer.quote_identifier(role)
            exists = connection.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
                {"role": role},
            ).scalar_one()
            if exists:
                connection.execute(text(f"DROP OWNED BY {quoted_role}"))
                connection.execute(text(f"DROP ROLE {quoted_role}"))
        admin_engine.dispose()


@pytest.fixture
def role_preparation_owner() -> Iterator[tuple[URL, URL, str, str]]:
    control_url = make_url(
        os.environ.get(
            "DATABASE_PREPARATION_SUPERUSER_URL",
            os.environ.get(
                "DATABASE_URL",
                "postgresql+psycopg://cosmas:cosmas@localhost:54329/cosmas_os",
            ),
        )
    ).set(database="postgres")
    suffix = uuid4().hex[:12]
    owner = f"cosmas_prep_owner_{suffix}"
    runtime = f"cosmas_prep_runtime_{suffix}"
    member = f"cosmas_prep_member_{suffix}"
    database = f"cosmas_prep_db_{suffix}"
    owner_url = control_url.set(
        username=owner, password=secrets.token_urlsafe(36), database=database
    )
    control_engine = create_engine(control_url)
    try:
        with control_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            driver = connection.connection.driver_connection
            assert driver is not None
            with driver.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE ROLE {} LOGIN CREATEDB CREATEROLE PASSWORD {}").format(
                        sql.Identifier(owner), sql.Literal(owner_url.password)
                    )
                )
                cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(member)))
                cursor.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(database), sql.Identifier(owner)
                    )
                )
        yield control_url, owner_url, runtime, member
    finally:
        with control_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            driver = connection.connection.driver_connection
            assert driver is not None
            with driver.cursor() as cursor:
                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database)))
                for role in (runtime, member, owner):
                    cursor.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
        control_engine.dispose()


def test_role_preparation_supports_non_superuser_database_owner(
    role_preparation_owner: tuple[URL, URL, str, str],
) -> None:
    _, owner_url, role, _ = role_preparation_owner
    runtime = owner_url.set(username=role, password=secrets.token_urlsafe(36))
    engine = create_engine(owner_url)
    try:
        with engine.begin() as connection:
            assert tuple(
                connection.execute(
                    text("SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user")
                ).one()
            ) == (False, True, True)
            assert connection.execute(
                text("SELECT pg_get_userbyid(datdba)=current_user FROM pg_database WHERE datname=current_database()")
            ).scalar_one() is True
            database_preparation._ensure_unprivileged_role(connection, runtime)
            driver = connection.connection.driver_connection
            assert driver is not None
            with driver.cursor() as cursor:
                cursor.execute(sql.SQL("ALTER ROLE {} NOLOGIN NOINHERIT").format(sql.Identifier(role)))
        with engine.begin() as connection:
            database_preparation._ensure_unprivileged_role(
                connection, runtime.set(password=secrets.token_urlsafe(36))
            )
            assert tuple(
                connection.execute(
                    text("SELECT rolcanlogin, rolinherit, rolsuper, rolcreatedb, rolcreaterole, "
                         "rolreplication, rolbypassrls FROM pg_roles WHERE rolname=:role"),
                    {"role": role},
                ).one()
            ) == (True, True, False, False, False, False, False)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "unsafe_attribute", ["SUPERUSER", "CREATEDB", "CREATEROLE", "REPLICATION", "BYPASSRLS", "membership"]
)
def test_non_superuser_owner_refuses_unsafe_existing_runtime_role(
    role_preparation_owner: tuple[URL, URL, str, str], unsafe_attribute: str
) -> None:
    control_url, owner_url, role, member = role_preparation_owner
    runtime = owner_url.set(username=role, password=secrets.token_urlsafe(36))
    owner_engine = create_engine(owner_url)
    control_engine = create_engine(control_url)
    try:
        with owner_engine.begin() as connection:
            driver = connection.connection.driver_connection
            assert driver is not None
            with driver.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE ROLE {} NOLOGIN NOINHERIT PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(runtime.password)
                    )
                )
        with control_engine.begin() as connection:
            driver = connection.connection.driver_connection
            assert driver is not None
            with driver.cursor() as cursor:
                if unsafe_attribute == "membership":
                    cursor.execute(
                        sql.SQL("GRANT {} TO {}").format(sql.Identifier(member), sql.Identifier(role))
                    )
                else:
                    cursor.execute(
                        sql.SQL("ALTER ROLE {} {}").format(
                            sql.Identifier(role), sql.SQL(unsafe_attribute)
                        )
                    )
        message = (
            "unexpected role memberships"
            if unsafe_attribute == "membership"
            else "privileged attributes"
        )
        flags_query = text(
            "SELECT rolcanlogin, rolinherit, rolsuper, rolcreatedb, rolcreaterole, "
            "rolreplication, rolbypassrls FROM pg_roles WHERE rolname=:role"
        )
        with owner_engine.begin() as connection:
            before = tuple(connection.execute(flags_query, {"role": role}).one())
            with pytest.raises(DatabasePreparationError, match=message):
                database_preparation._ensure_unprivileged_role(connection, runtime)
            assert tuple(connection.execute(flags_query, {"role": role}).one()) == before
    finally:
        owner_engine.dispose()
        control_engine.dispose()


def test_true_dba_can_restore_existing_runtime_role_flags(
    role_preparation_owner: tuple[URL, URL, str, str],
) -> None:
    control_url, owner_url, role, _ = role_preparation_owner
    runtime = owner_url.set(username=role, password=secrets.token_urlsafe(36))
    engine = create_engine(control_url)
    try:
        with engine.begin() as connection:
            driver = connection.connection.driver_connection
            assert driver is not None
            with driver.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE ROLE {} LOGIN SUPERUSER CREATEDB CREATEROLE REPLICATION BYPASSRLS PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(runtime.password)
                    )
                )
            database_preparation._ensure_unprivileged_role(connection, runtime)
            assert tuple(
                connection.execute(
                    text("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                         "FROM pg_roles WHERE rolname=:role"),
                    {"role": role},
                ).one()
            ) == (False, False, False, False, False)
    finally:
        engine.dispose()
