"""Run CosmaBot standalone staging alembic as the migration peer user.

Invoked by the prepare entrypoint. Never uses the runtime login for alembic.
After migrate, reapplies owner and DML-only runtime grants from migrate_contract.
"""

from __future__ import annotations

import os
import sys

from migrate_contract import (
    MIGRATION_USER,
    RUNTIME_FORBIDDEN_TABLE_PRIVILEGES,
    RUNTIME_TABLE_PRIVILEGES,
    RUNTIME_USER,
    assert_migrate_roles_separated,
    repair_runtime_owned_objects_sql,
    runtime_grant_sql,
)
from sqlalchemy import create_engine, text


def _run_as_migration(migration_url: str, statements: tuple[str, ...]) -> None:
    engine = create_engine(migration_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            identity = connection.execute(
                text("SELECT current_user, session_user")
            ).one()
            if tuple(identity) != (MIGRATION_USER, MIGRATION_USER):
                raise RuntimeError("migrate_must_use_migration_user")
            for statement in statements:
                connection.execute(text(statement))
    finally:
        engine.dispose()


def main() -> int:
    migration_url = os.environ.get("DATABASE_ADMIN_URL", "")
    runtime_url = os.environ.get("DATABASE_URL", "")
    assert_migrate_roles_separated(migration_url, runtime_url)
    if RUNTIME_TABLE_PRIVILEGES & RUNTIME_FORBIDDEN_TABLE_PRIVILEGES:
        raise SystemExit("runtime_grants_include_ddl")

    # Repair tables left owned by the runtime login from a prior bad migrate.
    _run_as_migration(migration_url, (repair_runtime_owned_objects_sql(),))

    from cosmas_os.application.database_preparation import prepare_beta_database

    # Alembic and privilege verification run as MIGRATION_USER via DATABASE_ADMIN_URL.
    prepare_beta_database(migration_url, runtime_url)

    # Owner + DML-only runtime grants (never CREATE/REFERENCES/TRIGGER/TRUNCATE).
    _run_as_migration(migration_url, runtime_grant_sql(RUNTIME_USER))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        print(
            "CosmaBot staging migrate refused; inspect protected configuration locally.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
