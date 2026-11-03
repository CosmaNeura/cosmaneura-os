"""CosmaBot standalone migrate contract: derived roles, DML-only runtime grants."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.engine import make_url
from typer.testing import CliRunner

from cosmas_os.application import standalone_database as standalone
from cosmas_os.cli import app
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION

INSTANCE = UUID("e0a41418-4674-4f53-8c31-774b214bf612")
SHORT = "e0a414184674"
MIGRATOR = f"cbpg_{SHORT}"
RUNTIME = f"cosmabot_runtime_{SHORT}"
DB = f"cosmabot_standalone_{INSTANCE.hex}_r5r_deadbeef"
PACKAGE = Path(__file__).resolve().parents[2] / "infra/standalone/package"
ROOT = Path(__file__).resolve().parents[2]


def _url(user: str, database: str = DB, *, password: str | None = None) -> str:
    secret = password
    if secret is None:
        secret = (
            "invented-migrator-password-1234"
            if user == MIGRATOR
            else "invented-runtime-password-1234"
        )
    return (
        f"postgresql+psycopg://{user}:{secret}@"
        f"127.0.0.1:15432/{database}"
    )


def _peer_url(
    user: str = MIGRATOR,
    database: str = DB,
    socket: str = "/var/run/postgresql",
    *,
    port: int | None = None,
    port_in: str = "query",
) -> str:
    if port is None:
        return f"postgresql+psycopg://{user}@/{database}?host={socket}"
    if port_in == "query":
        return (
            f"postgresql+psycopg://{user}@/{database}"
            f"?host={socket}&port={port}"
        )
    if port_in == "url":
        return f"postgresql+psycopg://{user}@:{port}/{database}?host={socket}"
    raise AssertionError(port_in)


def test_standalone_roles_are_derived_from_instance_identity_not_hardcoded():
    migrator, runtime = standalone.standalone_role_names(INSTANCE)
    assert migrator == MIGRATOR
    assert runtime == RUNTIME
    assert migrator != runtime
    assert migrator.startswith("cbpg_")
    assert runtime.startswith("cosmabot_runtime_")
    assert SHORT in migrator and SHORT in runtime

    source = Path(standalone.__file__).read_text()
    assert 'MIGRATION_USER = "cbpg"' not in source
    assert 'RUNTIME_USER = "cosmas"' not in source
    assert 'MIGRATION_USER = "cbpg_' not in source
    assert 'RUNTIME_USER = "cosmabot_runtime_' not in source
    assert 'f"cbpg_{short}"' in source or "f'cbpg_{short}'" in source
    assert 'f"cosmabot_runtime_{short}"' in source or "f'cosmabot_runtime_{short}'" in source

    other = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    other_migrator, other_runtime = standalone.standalone_role_names(other)
    assert (other_migrator, other_runtime) != (migrator, runtime)
    assert other_migrator == "cbpg_aaaaaaaabbbb"
    assert other_runtime == "cosmabot_runtime_aaaaaaaabbbb"


def test_migrate_refuses_when_migrator_equals_runtime_role():
    migration = _url(MIGRATOR)
    runtime = _url(RUNTIME)
    standalone.assert_standalone_migrate_roles(migration, runtime, INSTANCE)

    with pytest.raises(
        standalone.StandaloneDatabaseError, match="migrate_must_not_use_runtime_login"
    ):
        standalone.assert_standalone_migrate_roles(runtime, runtime, INSTANCE)

    with pytest.raises(
        standalone.StandaloneDatabaseError, match="migrate_must_not_use_runtime_login"
    ):
        standalone.assert_standalone_migrate_roles(
            _url(RUNTIME), _url(RUNTIME), INSTANCE
        )

    with pytest.raises(
        standalone.StandaloneDatabaseError, match="migrate_must_use_migration_user"
    ):
        standalone.assert_standalone_migrate_roles(
            _url("postgres"), runtime, INSTANCE
        )

    with pytest.raises(
        standalone.StandaloneDatabaseError, match="migrate_must_use_migration_user"
    ):
        standalone.assert_standalone_migrate_roles(_url("cbpg"), runtime, INSTANCE)

    with pytest.raises(
        standalone.StandaloneDatabaseError, match="runtime_user_mismatch"
    ):
        standalone.assert_standalone_migrate_roles(
            migration, _url("cosmas"), INSTANCE
        )


def test_runtime_grants_exclude_ddl_and_schema_create():
    assert standalone.RUNTIME_TABLE_PRIVILEGES == {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
    }
    forbidden = standalone.RUNTIME_FORBIDDEN_TABLE_PRIVILEGES
    assert {"CREATE", "REFERENCES", "TRIGGER", "TRUNCATE"} <= forbidden
    assert not (standalone.RUNTIME_TABLE_PRIVILEGES & forbidden)

    statements = standalone.runtime_grant_sql(INSTANCE)
    joined = "\n".join(statements)
    assert (
        f"GRANT DELETE, INSERT, SELECT, UPDATE ON ALL TABLES IN SCHEMA public TO {RUNTIME}"
        in joined
    )
    assert f"REASSIGN OWNED BY {RUNTIME} TO {MIGRATOR}" in joined
    assert f"REVOKE CREATE ON SCHEMA public FROM {RUNTIME}" in joined
    for privilege in sorted(forbidden):
        assert f"GRANT {privilege} " not in joined
        assert f"REVOKE {privilege} " in joined
    assert "GRANT CREATE ON SCHEMA" not in joined
    assert "CREATE" not in standalone.RUNTIME_TABLE_PRIVILEGES
    assert "REFERENCES" not in standalone.RUNTIME_TABLE_PRIVILEGES


def test_runtime_grant_sql_reapplies_fine_grained_revokes_after_blanket_grant():
    """Fail if blanket GRANT UPDATE ON ALL TABLES is left as the final grant state."""

    statements = standalone.runtime_grant_sql(INSTANCE)
    grant_indexes = [
        index
        for index, statement in enumerate(statements)
        if statement.startswith("GRANT ")
        and "ON ALL TABLES IN SCHEMA public" in statement
        and "UPDATE" in statement
    ]
    assert grant_indexes, "expected a blanket DML GRANT ON ALL TABLES"
    grant_idx = grant_indexes[0]

    def after_grant(fragment: str) -> bool:
        return any(
            fragment in statement for statement in statements[grant_idx + 1 :]
        )

    assert after_grant("REVOKE UPDATE, DELETE, TRUNCATE ON TABLE public.audit_events")
    assert after_grant(
        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE public.alembic_version"
    )
    assert after_grant(
        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE "
        "public.practice_owner_reservations"
    )
    assert after_grant(
        "GRANT UPDATE (consumed_at) ON TABLE public.practice_owner_reservations"
    )
    assert after_grant("GRANT SELECT ON TABLE public.alembic_version")

    # Document the old broken order: blanket GRANT with no later audit/version revoke.
    old_broken = (
        f"REASSIGN OWNED BY {RUNTIME} TO {MIGRATOR}",
        f"GRANT DELETE, INSERT, SELECT, UPDATE ON ALL TABLES IN SCHEMA public TO {RUNTIME}",
        f"REVOKE CREATE ON SCHEMA public FROM {RUNTIME}",
        f"REVOKE REFERENCES ON ALL TABLES IN SCHEMA public FROM {RUNTIME}",
        f"REVOKE TRIGGER ON ALL TABLES IN SCHEMA public FROM {RUNTIME}",
        f"REVOKE TRUNCATE ON ALL TABLES IN SCHEMA public FROM {RUNTIME}",
    )
    old_grant_idx = 1
    assert not any(
        "audit_events" in statement and "REVOKE UPDATE" in statement
        for statement in old_broken[old_grant_idx + 1 :]
    )
    assert not any(
        "alembic_version" in statement and "REVOKE" in statement and "UPDATE" in statement
        for statement in old_broken[old_grant_idx + 1 :]
    )


def test_standalone_boundaries_accept_per_release_database_and_private_box_url():
    admin, runtime, migrator, runtime_role = standalone._validate_standalone_boundaries(
        _url(MIGRATOR), _url(RUNTIME), INSTANCE
    )
    assert admin.database == DB
    assert runtime.database == DB
    assert migrator == MIGRATOR
    assert runtime_role == RUNTIME
    assert not admin.query
    assert not runtime.query

    with pytest.raises(
        standalone.StandaloneDatabaseError, match="standalone_database_name_required"
    ):
        standalone._validate_standalone_boundaries(
            _url(MIGRATOR, "cosmas_os"),
            _url(RUNTIME, "cosmas_os"),
            INSTANCE,
        )


def test_standalone_boundaries_accept_peer_socket_migrator_without_password():
    peer = _peer_url()
    parsed = make_url(peer)
    assert standalone.is_peer_socket_migrator_url(parsed)
    assert parsed.password is None
    assert parsed.query.get("host") == "/var/run/postgresql"

    admin, runtime, migrator, runtime_role = standalone._validate_standalone_boundaries(
        peer, _url(RUNTIME), INSTANCE
    )
    assert migrator == MIGRATOR
    assert runtime_role == RUNTIME
    assert admin.database == runtime.database == DB
    assert standalone.is_peer_socket_migrator_url(admin)
    assert runtime.password is not None
    assert admin.host != runtime.host or admin.query != runtime.query

    # Peer migrator must not carry a password, and must not use a TCP password URL
    # that only matches the runtime host when a socket peer is intended.
    with pytest.raises(
        standalone.StandaloneDatabaseError, match="peer migrator URL must omit the password"
    ):
        standalone._safe_standalone_migrator_url(
            f"postgresql+psycopg://{MIGRATOR}:invented-peer-password-1234"
            f"@/{DB}?host=/var/run/postgresql"
        )

    # TCP migrator still requires a password and matching host with runtime.
    with pytest.raises(standalone.StandaloneDatabaseError):
        standalone._validate_standalone_boundaries(
            f"postgresql+psycopg://{MIGRATOR}:invented-standalone-password-1234@"
            f"10.0.0.1:15432/{DB}",
            _url(RUNTIME),
            INSTANCE,
        )


def test_peer_socket_migrator_accepts_port_in_query_or_url():
    """Box Postgres may listen as .s.PGSQL.54111; port must not require renaming."""

    for peer in (
        _peer_url(port=54111, port_in="query"),
        _peer_url(port=54111, port_in="url"),
    ):
        admin = standalone._safe_standalone_migrator_url(peer)
        assert standalone.is_peer_socket_migrator_url(admin)
        assert standalone.peer_socket_port(admin) == 54111
        assert admin.password is None
        validated = standalone._validate_standalone_boundaries(
            peer, _url(RUNTIME), INSTANCE
        )
        assert validated[0].database == DB
        assert standalone.peer_socket_port(validated[0]) == 54111

    with pytest.raises(
        standalone.StandaloneDatabaseError, match="unsupported query parameters"
    ):
        standalone._safe_standalone_migrator_url(
            f"postgresql+psycopg://{MIGRATOR}@/{DB}"
            f"?host=/var/run/postgresql&port=54111&sslmode=disable"
        )
    with pytest.raises(
        standalone.StandaloneDatabaseError, match="peer migrator port is invalid"
    ):
        standalone._safe_standalone_migrator_url(
            f"postgresql+psycopg://{MIGRATOR}@/{DB}"
            f"?host=/var/run/postgresql&port=not-a-port"
        )


def test_migrate_log_lines_are_credential_free_and_describe_alembic():
    no_op = standalone.credential_free_migrate_log_lines(
        connected_user=MIGRATOR,
        session_user=MIGRATOR,
        schema_before="bb57e3d10c964",
        schema_after="bb57e3d10c964",
    )
    assert no_op == (
        f"connected_user={MIGRATOR}",
        f"session_user={MIGRATOR}",
        "alembic_before=bb57e3d10c964",
        "alembic_after=bb57e3d10c964",
        "alembic_action=no-op",
    )
    upgrade = standalone.credential_free_migrate_log_lines(
        connected_user=MIGRATOR,
        session_user=MIGRATOR,
        schema_before="z35e1b98a742",
        schema_after="bb57e3d10c964",
    )
    assert upgrade[-1] == "alembic_action=upgrade"
    empty = standalone.credential_free_migrate_log_lines(
        connected_user=MIGRATOR,
        session_user=MIGRATOR,
        schema_before=None,
        schema_after="z35e1b98a742",
    )
    assert empty[2] == "alembic_before=none"
    assert empty[-1] == "alembic_action=upgrade"

    joined = "\n".join(no_op + upgrade + empty)
    assert "://" not in joined
    assert "password" not in joined.lower()
    assert "DATABASE_ADMIN_URL" not in joined
    assert "invented-" not in joined

    source = (PACKAGE / "migrate.py").read_text()
    assert "credential_free_migrate_log_lines" in source
    assert "alembic_action" in source or "credential_free_migrate_log_lines" in source
    assert "print(line)" in source
    # Never interpolate the admin/runtime URL into progress output.
    assert "print(migration_url" not in source
    assert "print(runtime_url" not in source
    assert "print(os.environ" not in source


def test_shipped_schema_head_reads_alembic_graph_not_hardcoded_constant():
    head = standalone.shipped_schema_head(ROOT / "alembic.ini")
    assert head == EXPECTED_SCHEMA_REVISION
    source = Path(standalone.__file__).read_text()
    assert "EXPECTED_SCHEMA_REVISION" not in source
    assert "bb57e3d10c964" not in source
    assert "aa46f2c09b853" not in source
    assert "z35e1b98a742" not in source
    assert "shipped_schema_head" in source
    assert "_run_standalone_forward_migrations" in source


def test_standalone_package_migrate_entrypoint_uses_derived_roles():
    source = (PACKAGE / "migrate.py").read_text()
    assert "prepare_standalone_database" in source
    assert "standalone_role_names" in source
    assert "assert_standalone_migrate_roles" in source
    assert "STANDALONE_INSTANCE_ID" in source
    assert "DATABASE_ADMIN_URL" in source
    assert 'MIGRATION_USER = "cbpg"' not in source
    assert 'RUNTIME_USER = "cosmas"' not in source
    assert "prepare_beta_database" not in source
    assert '"cbpg"' not in source
    assert '"cosmas"' not in source
    assert '"cosmabot_runtime_' not in source


def test_standalone_prepare_cli_never_reflects_credentials():
    secret = "do-not-print-this-standalone-secret"
    result = CliRunner().invoke(
        app,
        ["prepare-standalone-database", "--confirm-forward-only"],
        env={
            "COSMAS_ENV": "standalone_clerk_synthetic",
            "STANDALONE_INSTANCE_ID": str(INSTANCE),
            "DATABASE_ADMIN_URL": secret,
            "DATABASE_URL": _url(RUNTIME),
        },
    )
    assert result.exit_code == 1
    combined = (result.stdout + result.stderr).strip()
    assert combined == (
        '{"contract":"cosmabot-standalone-database-preparation-v1","status":"failed"}'
    )
    assert secret not in result.output
    assert "invented-standalone-password" not in result.output
