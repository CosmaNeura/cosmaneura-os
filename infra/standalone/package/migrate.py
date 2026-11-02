"""CosmaBot standalone staging migrate entrypoint.

The cosmabot-standalone-* API containers do not migrate on start. Operators
(and staging proof) invoke this module from the reviewed release/source as:

  STANDALONE_INSTANCE_ID=<uuid> \\
  DATABASE_ADMIN_URL=postgresql+psycopg://cbpg_<short>@/cosmabot_standalone_...?host=/var/run/postgresql \\
  DATABASE_URL=postgresql+psycopg://cosmabot_runtime_<short>:...@127.0.0.1:5432/cosmabot_standalone_... \\
  python infra/standalone/package/migrate.py

DATABASE_ADMIN_URL may be a Unix-socket peer login (socket directory in
``host=``, no password) when live pg_hba allows ``local ... peer`` for
``cbpg_*``. The runtime URL stays a password login. Alembic runs as the
derived peer migrator role. The runtime role receives DML only. Secrets are
never printed.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    instance_id = os.environ.get("STANDALONE_INSTANCE_ID", "")
    migration_url = os.environ.get("DATABASE_ADMIN_URL", "")
    runtime_url = os.environ.get("DATABASE_URL", "")
    if not instance_id or not migration_url or not runtime_url:
        print(
            "CosmaBot standalone migrate refused; protected instance and URL pair required.",
            file=sys.stderr,
        )
        return 1

    from cosmas_os.application.standalone_database import (
        RUNTIME_FORBIDDEN_TABLE_PRIVILEGES,
        RUNTIME_TABLE_PRIVILEGES,
        StandaloneDatabaseError,
        assert_standalone_migrate_roles,
        prepare_standalone_database,
        runtime_grant_sql,
        standalone_role_names,
    )

    try:
        migrator, runtime = assert_standalone_migrate_roles(
            migration_url, runtime_url, instance_id
        )
        if migrator == runtime:
            raise StandaloneDatabaseError("migrate_must_not_use_runtime_login")
        if RUNTIME_TABLE_PRIVILEGES & RUNTIME_FORBIDDEN_TABLE_PRIVILEGES:
            raise StandaloneDatabaseError("runtime_grants_include_ddl")
        for statement in runtime_grant_sql(instance_id):
            upper = statement.upper()
            for privilege in RUNTIME_FORBIDDEN_TABLE_PRIVILEGES:
                if upper.startswith(f"GRANT {privilege} ") or f" GRANT {privilege} " in f" {upper} ":
                    raise StandaloneDatabaseError("runtime_grants_include_ddl")
            if "GRANT CREATE ON SCHEMA" in upper:
                raise StandaloneDatabaseError("runtime_grants_include_ddl")
        expected_migrator, expected_runtime = standalone_role_names(instance_id)
        if (migrator, runtime) != (expected_migrator, expected_runtime):
            raise StandaloneDatabaseError("standalone_roles_must_be_derived")

        evidence = prepare_standalone_database(
            migration_url, runtime_url, instance_id
        )
        print(evidence.sanitized_json())
        return 0
    except StandaloneDatabaseError:
        print(
            "CosmaBot standalone migrate refused; inspect protected configuration locally.",
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            "CosmaBot standalone migrate refused; inspect protected configuration locally.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
