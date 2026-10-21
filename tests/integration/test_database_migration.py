from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from cosmas_os.application import database_migration as migration

ROOT = Path(__file__).resolve().parents[2]
GUARD = "public.selected_google_model_sources_current(public.model_work_admissions)"


@pytest.fixture
def case():
    # This setup is restricted to the fresh cluster created by the local helper.
    url = make_url(os.environ["DATABASE_URL"])
    token = os.environ["COSMAS_TEST_DATABASE_TOKEN"]
    assert url.host == "127.0.0.1" and url.database == "w1a_local_checks"
    proof_engine = create_engine(url)
    try:
        with proof_engine.connect() as connection:
            marker = connection.scalar(text(
                "SELECT shobj_description(oid,'pg_database') FROM pg_database "
                "WHERE datname=current_database()"
            ))
            assert marker == "cosmas-local-workspace:" + token
    finally:
        proof_engine.dispose()
    owner_engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    admin_url = url.set(database="cosmas_os")
    engine = create_engine(admin_url)
    role = "migration_runtime_" + uuid4().hex[:12]
    runtime_url = admin_url.set(username=role, password="invented-runtime-password-123456789")
    try:
        with owner_engine.connect() as connection:
            assert not connection.scalar(text("SELECT EXISTS(SELECT FROM pg_database WHERE datname='cosmas_os')"))
            connection.exec_driver_sql("CREATE DATABASE cosmas_os")
            connection.exec_driver_sql(f"CREATE ROLE {role} LOGIN PASSWORD 'invented-runtime-password-123456789'")
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        config.attributes["configure_logger"] = False
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, migration.FROM_REVISION)
            connection.exec_driver_sql(f"GRANT CONNECT ON DATABASE cosmas_os TO {role}")
            connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {role}")
            connection.exec_driver_sql(f"GRANT SELECT ON public.alembic_version TO {role}")
        yield SimpleNamespace(engine=engine, admin_url=admin_url, role=role,
                              runtime_url=runtime_url.render_as_string(hide_password=False))
    finally:
        engine.dispose()
        with owner_engine.connect() as connection:
            connection.exec_driver_sql("DROP DATABASE IF EXISTS cosmas_os WITH (FORCE)")
            connection.exec_driver_sql(f"DROP ROLE IF EXISTS {role}")
        owner_engine.dispose()


def read_state(case):
    with case.engine.connect() as connection:
        revision = tuple(connection.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num")).scalars())
        role = tuple(connection.execute(text(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolcanlogin,rolconfig "
            "FROM pg_roles WHERE rolname=:role"
        ), {"role": case.role}).one())
        namespace_acl = connection.scalar(text("SELECT nspacl::text FROM pg_namespace WHERE nspname='public'"))
        guard = tuple(connection.execute(text(
            "SELECT oid,proowner,proacl::text,prosecdef,provolatile,proconfig,pg_get_functiondef(oid) "
            "FROM pg_proc WHERE oid=to_regprocedure(:guard)"
        ), {"guard": GUARD}).one())
        return revision, role, namespace_acl, guard


def run(case, **kwargs):
    with case.engine.connect() as connection:
        return migration.migrate_beta_database_forward(connection, case.runtime_url,
                                                       require_verify_full=False, **kwargs)


def assert_lock_released(case):
    with case.engine.begin() as connection:
        assert connection.scalar(text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
                                 {"key": migration._LOCK_KEY}) is True


def test_actual_forward_transaction_keeps_role_acl_and_guard_identity(case):
    before = read_state(case)
    statements = []
    event.listen(case.engine, "before_cursor_execute", lambda c, cursor, stmt, params, ctx, many: statements.append(stmt))
    result = run(case)
    after = read_state(case)
    assert before[0] == (migration.FROM_REVISION,) and after[0] == (migration.TO_REVISION,)
    assert after[1:3] == before[1:3] and after[3][:-1] == before[3][:-1]
    assert "clinical-team-drafts.request.v2" not in before[3][-1]
    assert "clinical-team-drafts.request.v2" in after[3][-1] and "owner_directions" in after[3][-1]
    payload = json.loads(result.sanitized_json())
    assert payload["status"] == "ready" and payload["schema_before"] == migration.FROM_REVISION
    assert payload["schema_revision"] == migration.TO_REVISION
    assert all(v is True for k, v in payload.items() if k not in {
        "contract", "status", "schema_before", "schema_revision", "evidence_sha256"})
    serialized = result.sanitized_json()
    assert all(value not in serialized for value in (case.role, case.runtime_url, "invented-runtime-password", "127.0.0.1"))
    assert "password" not in serialized
    assert not any(stmt.lstrip().upper().startswith(("ALTER ROLE", "CREATE ROLE", "GRANT ", "REVOKE ")) for stmt in statements)
    assert not any("pg_authid" in stmt or "rolpassword" in stmt for stmt in statements)
    assert_lock_released(case)
    # Replaying after success is refused, never treated as an uncertain retry.
    with pytest.raises(migration.DatabaseMigrationError, match=migration.FAILURE):
        run(case)


@pytest.mark.parametrize("change", ["ddl_failure", "role_change", "acl_change"])
def test_failed_or_broadened_migration_rolls_back_all_owned_work(case, monkeypatch, change):
    before = read_state(case)
    upgrade = migration.command.upgrade

    def injected(config, target):
        upgrade(config, target)
        connection = config.attributes["connection"]
        if change == "ddl_failure":
            connection.exec_driver_sql("CREATE TABLE public.migration_rollback_probe(id integer)")
            raise RuntimeError("invented-private-driver-message")
        if change == "role_change":
            connection.exec_driver_sql(f"ALTER ROLE {case.role} CREATEDB")
        else:
            connection.exec_driver_sql(f"GRANT CREATE ON SCHEMA public TO {case.role}")

    monkeypatch.setattr(migration.command, "upgrade", injected)
    with case.engine.connect() as connection:
        with pytest.raises(migration.DatabaseMigrationError) as error:
            migration.migrate_beta_database_forward(connection, case.runtime_url,
                                                   require_verify_full=False)
        assert not connection.in_transaction()
        assert not connection.closed and not connection.invalidated
        assert connection.scalar(text("SELECT 1")) == 1
        connection.rollback()
    assert str(error.value) == migration.FAILURE and error.value.__suppress_context__
    assert read_state(case) == before
    with case.engine.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('public.migration_rollback_probe')")) is None
    assert_lock_released(case)


def test_existing_preparation_session_lock_blocks_migration_without_wait_or_mutation(case):
    before = read_state(case)
    with case.engine.connect() as holder:
        holder.execute(text("SELECT pg_advisory_lock(hashtext(:key))"), {"key": migration._LOCK_KEY})
        holder.commit()
        try:
            with pytest.raises(migration.DatabaseMigrationError):
                run(case)
            assert read_state(case) == before
        finally:
            holder.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": migration._LOCK_KEY})
            holder.commit()
    assert_lock_released(case)


def test_active_caller_transaction_is_refused_before_any_sql_and_left_owned(case):
    statements = []
    event.listen(case.engine, "before_cursor_execute", lambda c, cursor, stmt, params, ctx, many: statements.append(stmt))
    with case.engine.connect() as connection, connection.begin() as transaction:
        with pytest.raises(migration.DatabaseMigrationError):
            migration.migrate_beta_database_forward(connection, case.runtime_url, require_verify_full=False)
        assert transaction.is_active and connection.in_transaction()
        assert statements == []


@pytest.mark.parametrize("boundary", ["same_role", "same_password", "other_host", "other_database", "short_password", "tls_required"])
def test_existing_administrator_runtime_boundary_refuses_before_any_sql(case, boundary):
    url = make_url(case.runtime_url)
    if boundary == "same_role":
        url = url.set(username=case.admin_url.username)
    elif boundary == "same_password":
        url = url.set(password=case.admin_url.password)
    elif boundary == "other_host":
        url = url.set(host="other.invalid")
    elif boundary == "other_database":
        url = url.set(database="another_database")
    elif boundary == "short_password":
        url = url.set(password="short")
    statements = []
    event.listen(case.engine, "before_cursor_execute", lambda c, cursor, stmt, params, ctx, many: statements.append(stmt))
    with case.engine.connect() as connection:
        with pytest.raises(migration.DatabaseMigrationError):
            migration.migrate_beta_database_forward(connection, url.render_as_string(hide_password=False),
                                                   require_verify_full=boundary == "tls_required")
        assert not connection.in_transaction() and statements == []


@pytest.mark.parametrize("revision", ["missing", "ambiguous", "already_k80", "unknown"])
def test_live_revision_is_rechecked_under_lock_and_must_be_exact_j79(case, revision):
    with case.engine.begin() as connection:
        if revision == "missing":
            connection.execute(text("DELETE FROM alembic_version"))
        elif revision == "ambiguous":
            connection.execute(text("INSERT INTO alembic_version VALUES ('unknown')"))
        else:
            connection.execute(text("UPDATE alembic_version SET version_num=:revision"),
                               {"revision": migration.TO_REVISION if revision == "already_k80" else "unknown"})
    before = read_state(case)
    with pytest.raises(migration.DatabaseMigrationError):
        run(case)
    assert read_state(case) == before
    assert_lock_released(case)


@pytest.mark.parametrize("graph", ["wrong_head", "wrong_parent", "multiple_heads"])
def test_packaged_sole_head_and_direct_parent_must_match_before_upgrade(case, tmp_path, graph):
    versions = tmp_path / "migrations/versions"
    versions.mkdir(parents=True)
    config_path = tmp_path / "alembic.ini"
    config_path.write_text("[alembic]\nscript_location=migrations\n")
    (versions / "base.py").write_text(f"revision={migration.FROM_REVISION!r}\ndown_revision=None\n")
    parent = migration.FROM_REVISION
    if graph == "wrong_parent":
        parent = "other_parent"
        (versions / "other.py").write_text(f"revision={parent!r}\ndown_revision={migration.FROM_REVISION!r}\n")
    head = "other_head" if graph == "wrong_head" else migration.TO_REVISION
    (versions / "head.py").write_text(f"revision={head!r}\ndown_revision={parent!r}\n")
    if graph == "multiple_heads":
        (versions / "extra.py").write_text("revision='extra_head'\ndown_revision=None\n")
    before = read_state(case)
    with pytest.raises(migration.DatabaseMigrationError):
        run(case, alembic_config_path=config_path)
    assert read_state(case) == before
    assert_lock_released(case)


@pytest.mark.parametrize("state", ["missing", "privileged"])
def test_runtime_role_must_already_exist_without_administrator_attributes(case, state):
    if state == "missing":
        case.runtime_url = make_url(case.runtime_url).set(username="missing_runtime_role").render_as_string(hide_password=False)
    else:
        with case.engine.begin() as connection:
            connection.exec_driver_sql(f"ALTER ROLE {case.role} CREATEDB")
    before = read_state(case)
    with pytest.raises(migration.DatabaseMigrationError):
        run(case)
    assert read_state(case) == before
    assert_lock_released(case)


def test_effective_role_must_match_supplied_administrator_connection(case):
    before = read_state(case)
    with case.engine.connect() as connection:
        connection.exec_driver_sql(f"SET ROLE {case.role}")
        connection.commit()
        try:
            with pytest.raises(migration.DatabaseMigrationError):
                migration.migrate_beta_database_forward(connection, case.runtime_url, require_verify_full=False)
        finally:
            connection.exec_driver_sql("RESET ROLE")
            connection.commit()
    assert read_state(case) == before
    assert_lock_released(case)


@pytest.mark.parametrize("state", ["closed", "invalidated"])
def test_unusable_supplied_connection_is_not_reopened(case, state):
    connection = case.engine.connect()
    if state == "closed":
        connection.close()
    else:
        connection.invalidate()
    statements = []
    event.listen(case.engine, "before_cursor_execute", lambda c, cursor, stmt, params, ctx, many: statements.append(stmt))
    try:
        with pytest.raises(migration.DatabaseMigrationError):
            migration.migrate_beta_database_forward(connection, case.runtime_url, require_verify_full=False)
        assert statements == []
    finally:
        connection.close()


def test_non_postgres_connection_is_refused_without_sql():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    statements = []
    event.listen(engine, "before_cursor_execute", lambda c, cursor, stmt, params, ctx, many: statements.append(stmt))
    try:
        with engine.connect() as connection, pytest.raises(migration.DatabaseMigrationError):
            migration.migrate_beta_database_forward(connection, "invalid")
        assert statements == []
    finally:
        engine.dispose()
