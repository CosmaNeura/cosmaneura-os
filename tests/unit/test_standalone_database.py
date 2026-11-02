"""CosmaBot standalone migrate contract: derived roles, DML-only runtime grants."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from typer.testing import CliRunner

from cosmas_os.application import standalone_database as standalone
from cosmas_os.cli import app

INSTANCE = UUID("e0a41418-4674-4f53-8c31-774b214bf612")
SHORT = "e0a414184674"
MIGRATOR = f"cbpg_{SHORT}"
RUNTIME = f"cosmabot_runtime_{SHORT}"
DB = f"cosmabot_standalone_{INSTANCE.hex}_r5r_deadbeef"
PACKAGE = Path(__file__).resolve().parents[2] / "infra/standalone/package"


def _url(user: str, database: str = DB) -> str:
    return (
        f"postgresql+psycopg://{user}:invented-standalone-password-1234@"
        f"127.0.0.1:15432/{database}"
    )


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
