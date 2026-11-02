"""CosmaBot standalone staging migrate identity and runtime grant contract.

The prepare entrypoint imports these names. Alembic must run as the migration
peer login, never the runtime login. Runtime table grants stay DML-only.
"""

from __future__ import annotations

# Peer/migration login used for alembic and table ownership on CosmaBot staging.
MIGRATION_USER = "cbpg"
# Application runtime login. DML only; never DDL.
RUNTIME_USER = "cosmas"

RUNTIME_TABLE_PRIVILEGES = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})
# Table/schema DDL-shaped privileges the runtime login must never receive.
RUNTIME_FORBIDDEN_TABLE_PRIVILEGES = frozenset(
    {"CREATE", "REFERENCES", "TRIGGER", "TRUNCATE"}
)


def migration_database_url(password: str, suffix: str) -> str:
    """Build the administrator URL for alembic. Username is always MIGRATION_USER."""

    if not password:
        raise ValueError("migration_password_required")
    return f"postgresql+psycopg://{MIGRATION_USER}:{password}{suffix}"


def runtime_database_url(password: str, suffix: str) -> str:
    """Build the runtime URL used only for post-migrate verification."""

    if not password:
        raise ValueError("runtime_password_required")
    return f"postgresql+psycopg://{RUNTIME_USER}:{password}{suffix}"


def assert_migrate_roles_separated(migration_url: str, runtime_url: str) -> None:
    """Refuse a migrate step that would run alembic as the runtime login."""

    migration_user = migration_url.split("://", 1)[1].split(":", 1)[0]
    runtime_user = runtime_url.split("://", 1)[1].split(":", 1)[0]
    if runtime_user != RUNTIME_USER:
        raise ValueError("runtime_user_mismatch")
    if migration_user == runtime_user or migration_user == RUNTIME_USER:
        raise ValueError("migrate_must_not_use_runtime_login")
    if migration_user != MIGRATION_USER:
        raise ValueError("migrate_must_use_migration_user")


def repair_runtime_owned_objects_sql() -> str:
    """Move any relations the runtime login still owns back to the migration user."""

    return f"""
DO $migrate$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RUNTIME_USER}') THEN
    REASSIGN OWNED BY {RUNTIME_USER} TO {MIGRATION_USER};
  END IF;
END
$migrate$;
""".strip()


def runtime_grant_sql(role: str = RUNTIME_USER) -> tuple[str, ...]:
    """Post-migrate owner + runtime grants. Runtime receives DML only, never DDL."""

    if role != RUNTIME_USER:
        raise ValueError("runtime_user_mismatch")
    if RUNTIME_TABLE_PRIVILEGES & RUNTIME_FORBIDDEN_TABLE_PRIVILEGES:
        raise ValueError("runtime_grants_include_ddl")
    privileges = ", ".join(sorted(RUNTIME_TABLE_PRIVILEGES))
    return (
        repair_runtime_owned_objects_sql(),
        f"GRANT {privileges} ON ALL TABLES IN SCHEMA public TO {role}",
        f"REVOKE CREATE ON SCHEMA public FROM {role}",
        f"REVOKE REFERENCES ON ALL TABLES IN SCHEMA public FROM {role}",
        f"REVOKE TRIGGER ON ALL TABLES IN SCHEMA public FROM {role}",
        f"REVOKE TRUNCATE ON ALL TABLES IN SCHEMA public FROM {role}",
    )
