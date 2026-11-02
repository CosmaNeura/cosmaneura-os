"""CosmaBot standalone staging database migrate and runtime grant contract.

Alembic runs as the per-release peer migrator role derived from the Box /
instance identity (`cbpg_<short>`), never as the runtime login
(`cosmabot_runtime_<short>`). After migrate, the runtime role receives
table DML only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from cosmas_os.application.database_preparation import (
    DatabasePreparationError,
    _apply_runtime_privileges,
    _ensure_unprivileged_role,
    _run_forward_migrations,
    _safe_url,
    _verify_runtime_role,
)
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION

STANDALONE_DATABASE_CONTRACT = "cosmabot-standalone-database-preparation-v1"
_LOCK_KEY = "cosmabot-standalone-database-preparation-v1"
_DATABASE_NAME = re.compile(r"^cosmabot_standalone_[a-z0-9_]+$")
_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

RUNTIME_TABLE_PRIVILEGES = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})
RUNTIME_FORBIDDEN_TABLE_PRIVILEGES = frozenset(
    {"CREATE", "REFERENCES", "TRIGGER", "TRUNCATE"}
)


class StandaloneDatabaseError(RuntimeError):
    """Fail-closed standalone migrate error; text stays credential-free."""


@dataclass(frozen=True)
class StandaloneDatabaseEvidence:
    contract: str
    status: str
    schema_revision: str
    schema_at_expected_head: bool
    runtime_role_non_admin: bool
    runtime_ddl_denied: bool
    audit_update_denied: bool
    audit_delete_denied: bool
    migrator_role_derived: bool
    runtime_role_derived: bool

    def sanitized_payload(self) -> dict[str, str | bool]:
        return asdict(self)

    def sanitized_json(self) -> str:
        payload = self.sanitized_payload()
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload["evidence_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def standalone_identity_short(instance_id: str | UUID) -> str:
    """First 12 hex characters of the instance UUID (no dashes)."""

    try:
        value = UUID(str(instance_id))
    except (TypeError, ValueError) as exc:
        raise StandaloneDatabaseError("standalone_instance_id_invalid") from exc
    if value.version != 4 or str(value) != str(instance_id):
        raise StandaloneDatabaseError("standalone_instance_id_invalid")
    return value.hex[:12]


def standalone_role_names(instance_id: str | UUID) -> tuple[str, str]:
    """Derive peer migrator and runtime role names from the release/box identity.

    Returns ``(cbpg_<short>, cosmabot_runtime_<short>)``. Names are never
    hard-coded constants; callers must pass the instance UUID.
    """

    short = standalone_identity_short(instance_id)
    migrator = f"cbpg_{short}"
    runtime = f"cosmabot_runtime_{short}"
    if migrator == runtime:
        raise StandaloneDatabaseError("migrate_must_not_use_runtime_login")
    if not _ROLE_PATTERN.fullmatch(migrator) or not _ROLE_PATTERN.fullmatch(runtime):
        raise StandaloneDatabaseError("standalone_role_name_invalid")
    return migrator, runtime


def assert_standalone_migrate_roles(
    migration_url: str,
    runtime_url: str,
    instance_id: str | UUID,
) -> tuple[str, str]:
    """Refuse a migrate step that would run alembic as the runtime login."""

    migrator, runtime = standalone_role_names(instance_id)
    if migrator == runtime:
        raise StandaloneDatabaseError("migrate_must_not_use_runtime_login")
    try:
        migration_user = make_url(migration_url).username
        runtime_user = make_url(runtime_url).username
    except Exception as exc:
        raise StandaloneDatabaseError("standalone_database_url_invalid") from exc
    if migration_user == runtime_user or migration_user == runtime:
        raise StandaloneDatabaseError("migrate_must_not_use_runtime_login")
    if migration_user != migrator:
        raise StandaloneDatabaseError("migrate_must_use_migration_user")
    if runtime_user != runtime:
        raise StandaloneDatabaseError("runtime_user_mismatch")
    return migrator, runtime


def runtime_grant_sql(instance_id: str | UUID) -> tuple[str, ...]:
    """Owner repair + DML-only runtime grants derived from the instance identity."""

    if RUNTIME_TABLE_PRIVILEGES & RUNTIME_FORBIDDEN_TABLE_PRIVILEGES:
        raise StandaloneDatabaseError("runtime_grants_include_ddl")
    migrator, runtime = standalone_role_names(instance_id)
    privileges = ", ".join(sorted(RUNTIME_TABLE_PRIVILEGES))
    return (
        f"REASSIGN OWNED BY {runtime} TO {migrator}",
        f"GRANT {privileges} ON ALL TABLES IN SCHEMA public TO {runtime}",
        f"REVOKE CREATE ON SCHEMA public FROM {runtime}",
        f"REVOKE REFERENCES ON ALL TABLES IN SCHEMA public FROM {runtime}",
        f"REVOKE TRIGGER ON ALL TABLES IN SCHEMA public FROM {runtime}",
        f"REVOKE TRUNCATE ON ALL TABLES IN SCHEMA public FROM {runtime}",
    )


def _validate_standalone_boundaries(
    admin_url: str,
    runtime_url: str,
    instance_id: str | UUID,
) -> tuple[URL, URL, str, str]:
    migrator, runtime_role = assert_standalone_migrate_roles(
        admin_url, runtime_url, instance_id
    )
    try:
        admin = _safe_url(admin_url, label="administrator database URL")
        runtime = _safe_url(runtime_url, label="runtime database URL")
    except DatabasePreparationError as exc:
        raise StandaloneDatabaseError(str(exc)) from None
    if (
        admin.host,
        admin.port or 5432,
        admin.database,
    ) != (
        runtime.host,
        runtime.port or 5432,
        runtime.database,
    ):
        raise StandaloneDatabaseError("database URLs do not target the same database")
    if admin.username != migrator or runtime.username != runtime_role:
        raise StandaloneDatabaseError("migrate_must_use_migration_user")
    if admin.username == runtime.username:
        raise StandaloneDatabaseError("migrate_must_not_use_runtime_login")
    database = admin.database
    if database is None or not _DATABASE_NAME.fullmatch(database):
        raise StandaloneDatabaseError("standalone_database_name_required")
    # Private Box / loopback URLs are accepted. verify-full is not required and
    # must not be forced onto standalone staging.
    if set(admin.query) != set(runtime.query):
        raise StandaloneDatabaseError("database URLs do not target the same database")
    return admin, runtime, migrator, runtime_role


def _repair_runtime_owned_objects(connection: Any, migrator: str, runtime: str) -> None:
    exists = connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
        {"role": runtime},
    ).scalar_one()
    if exists:
        connection.execute(
            text(f"REASSIGN OWNED BY {runtime} TO {migrator}")
        )


def prepare_standalone_database(
    admin_url: str,
    runtime_url: str,
    instance_id: str | UUID,
    *,
    alembic_config_path: Path | None = None,
) -> StandaloneDatabaseEvidence:
    """Migrate as the derived peer migrator and grant the runtime role DML only."""

    admin, runtime, migrator, runtime_role = _validate_standalone_boundaries(
        admin_url, runtime_url, instance_id
    )
    if RUNTIME_TABLE_PRIVILEGES & RUNTIME_FORBIDDEN_TABLE_PRIVILEGES:
        raise StandaloneDatabaseError("runtime_grants_include_ddl")
    for statement in runtime_grant_sql(instance_id):
        upper = " " + statement.upper() + " "
        if " GRANT CREATE ON SCHEMA " in upper:
            raise StandaloneDatabaseError("runtime_grants_include_ddl")
        for privilege in RUNTIME_FORBIDDEN_TABLE_PRIVILEGES:
            if f" GRANT {privilege} " in upper:
                raise StandaloneDatabaseError("runtime_grants_include_ddl")

    config_path = alembic_config_path or Path(__file__).resolve().parents[3] / "alembic.ini"
    if not config_path.is_file():
        raise StandaloneDatabaseError("Alembic configuration is unavailable")

    admin_engine = create_engine(admin_url, pool_pre_ping=True)
    try:
        with admin_engine.connect() as connection:
            identity = connection.execute(
                text("SELECT current_user, session_user")
            ).one()
            if tuple(identity) != (migrator, migrator):
                raise StandaloneDatabaseError("migrate_must_use_migration_user")
            connection.execute(
                text("SELECT pg_advisory_lock(hashtext(:key))"), {"key": _LOCK_KEY}
            )
            connection.commit()
            try:
                with connection.begin():
                    _repair_runtime_owned_objects(connection, migrator, runtime_role)
                    try:
                        _ensure_unprivileged_role(connection, runtime)
                        _run_forward_migrations(connection, config_path)
                        _apply_runtime_privileges(connection, runtime)
                        for statement in runtime_grant_sql(instance_id):
                            connection.execute(text(statement))
                    except DatabasePreparationError as exc:
                        raise StandaloneDatabaseError(str(exc)) from None
            finally:
                connection.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:key))"),
                    {"key": _LOCK_KEY},
                )
                connection.commit()
    finally:
        admin_engine.dispose()

    try:
        verification = _verify_runtime_role(runtime_url, runtime)
    except DatabasePreparationError as exc:
        raise StandaloneDatabaseError(str(exc)) from None
    if verification["revision"] != EXPECTED_SCHEMA_REVISION:
        raise StandaloneDatabaseError("schema is not at the expected head")
    if not verification["non_admin"] or not verification["ddl_denied"]:
        raise StandaloneDatabaseError("runtime role retained elevated privileges")

    return StandaloneDatabaseEvidence(
        contract=STANDALONE_DATABASE_CONTRACT,
        status="ready",
        schema_revision=EXPECTED_SCHEMA_REVISION,
        schema_at_expected_head=True,
        runtime_role_non_admin=bool(verification["non_admin"]),
        runtime_ddl_denied=bool(verification["ddl_denied"]),
        audit_update_denied=bool(verification["audit_update_denied"]),
        audit_delete_denied=bool(verification["audit_delete_denied"]),
        migrator_role_derived=True,
        runtime_role_derived=True,
    )
