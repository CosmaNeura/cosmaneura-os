from __future__ import annotations

import hmac
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import make_url

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
