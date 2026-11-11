"""CosmaBot standalone staging database migrate and runtime grant contract.

Alembic runs as the per-release peer migrator role derived from the Box /
instance identity (`cbpg_<short>`), never as the runtime login
(`cosmabot_runtime_<short>`). After migrate, the runtime role receives
table DML only. The migrator may authenticate over a Unix-socket peer
URL (socket directory host, no password); the runtime login stays on its
password URL.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from cosmas_os.application.database_preparation import (
    DatabasePreparationError,
    _alembic_config,
    _apply_runtime_privileges,
    _ensure_unprivileged_role,
    _safe_url,
    _verify_runtime_role,
)

STANDALONE_DATABASE_CONTRACT = "cosmabot-standalone-database-preparation-v1"
_LOCK_KEY = "cosmabot-standalone-database-preparation-v1"
_DATABASE_NAME = re.compile(r"^cosmabot_standalone_[a-z0-9_]+$")
_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

RUNTIME_TABLE_PRIVILEGES = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})
RUNTIME_FORBIDDEN_TABLE_PRIVILEGES = frozenset({"CREATE", "REFERENCES", "TRIGGER", "TRUNCATE"})

# Tables where the blanket DML grant must be narrowed again to match
# database_preparation._apply_runtime_privileges.
_RUNTIME_RESTRICTED_AFTER_GRANT = (
    "REVOKE UPDATE, DELETE, TRUNCATE ON TABLE public.audit_events FROM {runtime}",
    "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE "
    "public.practice_owner_reservations FROM {runtime}",
    "GRANT UPDATE (consumed_at) ON TABLE public.practice_owner_reservations TO {runtime}",
    "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE public.alembic_version FROM {runtime}",
    "GRANT SELECT ON TABLE public.alembic_version TO {runtime}",
    "REVOKE ALL ON TABLE public.patient_deletion_admin_bindings FROM {runtime}",
    "REVOKE ALL ON TABLE public.patient_deletion_in_progress FROM {runtime}",
)


class StandaloneDatabaseError(RuntimeError):
    """Fail-closed standalone migrate error; text stays credential-free."""


@dataclass(frozen=True)
class StandaloneDatabaseEvidence:
    contract: str
    status: str
    schema_revision: str
    schema_before: str
    alembic_action: str
    connected_user: str
    session_user: str
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


def credential_free_migrate_log_lines(
    *,
    connected_user: str,
    session_user: str,
    schema_before: str | None,
    schema_after: str,
) -> tuple[str, ...]:
    """Progress lines for migrate.py. Never include URLs or passwords."""

    if not connected_user or not session_user or not schema_after:
        raise StandaloneDatabaseError("migrate_log_identity_required")
    before = schema_before if schema_before else "none"
    action = "no-op" if schema_before == schema_after else "upgrade"
    lines = (
        f"connected_user={connected_user}",
        f"session_user={session_user}",
        f"alembic_before={before}",
        f"alembic_after={schema_after}",
        f"alembic_action={action}",
    )
    joined = "\n".join(lines)
    if "://" in joined or "password" in joined.lower():
        raise StandaloneDatabaseError("migrate_log_must_be_credential_free")
    return lines


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


def shipped_schema_head(alembic_config_path: Path) -> str:
    """Return the single Alembic head actually shipped with this tree/image."""

    if not alembic_config_path.is_file():
        raise StandaloneDatabaseError("Alembic configuration is unavailable")
    config = _alembic_config_file(alembic_config_path)
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1 or not heads[0]:
        raise StandaloneDatabaseError("migration graph does not have a single head")
    return heads[0]


def _alembic_config_file(config_path: Path):
    from alembic.config import Config

    config = Config(str(config_path))
    config.attributes["configure_logger"] = False
    return config


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
    """Owner repair + DML-only runtime grants derived from the instance identity.

    The blanket table GRANT is followed by the same fine-grained revokes that
    ``_apply_runtime_privileges`` applies, so UPDATE is not left on
    ``audit_events`` / ``alembic_version``.
    """

    if RUNTIME_TABLE_PRIVILEGES & RUNTIME_FORBIDDEN_TABLE_PRIVILEGES:
        raise StandaloneDatabaseError("runtime_grants_include_ddl")
    migrator, runtime = standalone_role_names(instance_id)
    privileges = ", ".join(sorted(RUNTIME_TABLE_PRIVILEGES))
    narrowed = tuple(
        statement.format(runtime=runtime) for statement in _RUNTIME_RESTRICTED_AFTER_GRANT
    )
    return (
        f"REASSIGN OWNED BY {runtime} TO {migrator}",
        f"GRANT {privileges} ON ALL TABLES IN SCHEMA public TO {runtime}",
        f"REVOKE CREATE ON SCHEMA public FROM {runtime}",
        f"REVOKE REFERENCES ON ALL TABLES IN SCHEMA public FROM {runtime}",
        f"REVOKE TRIGGER ON ALL TABLES IN SCHEMA public FROM {runtime}",
        f"REVOKE TRUNCATE ON ALL TABLES IN SCHEMA public FROM {runtime}",
        *narrowed,
    )


def _socket_directory(url: URL) -> str | None:
    """Return the Unix socket directory if this URL is a peer-socket login."""

    candidate = url.query.get("host") if url.query else None
    if isinstance(candidate, str) and candidate.startswith("/"):
        return candidate
    if isinstance(url.host, str) and url.host.startswith("/"):
        return url.host
    return None


def peer_socket_port(url: URL) -> int | None:
    """Optional Postgres socket port (``.s.PGSQL.<port>``), from URL or query."""

    if url.port is not None:
        if not 1 <= int(url.port) <= 65535:
            raise StandaloneDatabaseError("peer migrator port is invalid")
        return int(url.port)
    raw = url.query.get("port") if url.query else None
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.isdigit():
        raise StandaloneDatabaseError("peer migrator port is invalid")
    port = int(raw)
    if not 1 <= port <= 65535:
        raise StandaloneDatabaseError("peer migrator port is invalid")
    return port


def is_peer_socket_migrator_url(url: URL) -> bool:
    """True when the migrator URL is a passwordless Unix-socket peer login."""

    return (
        url.password is None
        and _socket_directory(url) is not None
        and bool(url.username)
        and bool(url.database)
    )


def _safe_standalone_migrator_url(value: str) -> URL:
    try:
        parsed = make_url(value)
    except Exception:
        raise StandaloneDatabaseError("administrator database URL is invalid") from None
    if parsed.drivername != "postgresql+psycopg":
        raise StandaloneDatabaseError("administrator database URL must use PostgreSQL psycopg")
    if not parsed.username or not parsed.database:
        raise StandaloneDatabaseError("administrator database URL is incomplete")
    if _socket_directory(parsed) is not None:
        # Live pg_hba admits cbpg_* only as local peer. A socket URL must not
        # carry a password, and must not fall through to the TCP password path.
        # Optional port selects .s.PGSQL.<port> without renaming the socket file.
        if parsed.password is not None:
            raise StandaloneDatabaseError("peer migrator URL must omit the password")
        if not set(parsed.query) <= {"host", "port"}:
            raise StandaloneDatabaseError("peer migrator URL has unsupported query parameters")
        peer_socket_port(parsed)
        return parsed
    # TCP / private-Box migrator still uses a password URL.
    try:
        return _safe_url(value, label="administrator database URL")
    except DatabasePreparationError as exc:
        raise StandaloneDatabaseError(str(exc)) from None


def _validate_standalone_boundaries(
    admin_url: str,
    runtime_url: str,
    instance_id: str | UUID,
) -> tuple[URL, URL, str, str]:
    migrator, runtime_role = assert_standalone_migrate_roles(admin_url, runtime_url, instance_id)
    admin = _safe_standalone_migrator_url(admin_url)
    try:
        runtime = _safe_url(runtime_url, label="runtime database URL")
    except DatabasePreparationError as exc:
        raise StandaloneDatabaseError(str(exc)) from None
    if admin.username != migrator or runtime.username != runtime_role:
        raise StandaloneDatabaseError("migrate_must_use_migration_user")
    if admin.username == runtime.username:
        raise StandaloneDatabaseError("migrate_must_not_use_runtime_login")
    database = admin.database
    if database is None or not _DATABASE_NAME.fullmatch(database):
        raise StandaloneDatabaseError("standalone_database_name_required")
    if runtime.database != database:
        raise StandaloneDatabaseError("database URLs do not target the same database")

    peer = is_peer_socket_migrator_url(admin)
    if peer:
        # Peer socket migrator authenticates locally without a password. The
        # runtime login stays on its own TCP/private-Box password URL; hosts
        # need not match, and query strings intentionally differ.
        if admin.password is not None:
            raise StandaloneDatabaseError("peer migrator URL must omit the password")
        if runtime.password is None:
            raise StandaloneDatabaseError("runtime database URL is incomplete")
    else:
        if (
            admin.host,
            admin.port or 5432,
        ) != (
            runtime.host,
            runtime.port or 5432,
        ):
            raise StandaloneDatabaseError("database URLs do not target the same database")
        if set(admin.query) != set(runtime.query):
            raise StandaloneDatabaseError("database URLs do not target the same database")
        if admin.password is None or runtime.password is None:
            raise StandaloneDatabaseError("database URL is incomplete")
        if admin.password == runtime.password:
            raise StandaloneDatabaseError("runtime credential must differ from the administrator")
    return admin, runtime, migrator, runtime_role


def _repair_runtime_owned_objects(connection: Any, migrator: str, runtime: str) -> None:
    exists = connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
        {"role": runtime},
    ).scalar_one()
    if exists:
        connection.execute(text(f"REASSIGN OWNED BY {runtime} TO {migrator}"))


def _current_schema_revision(connection: Any) -> str | None:
    exists = connection.execute(
        text(
            "SELECT EXISTS ("
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'alembic_version')"
        )
    ).scalar_one()
    if not exists:
        return None
    revisions = tuple(
        connection.execute(
            text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
        ).scalars()
    )
    if not revisions:
        return None
    if len(revisions) != 1 or not revisions[0]:
        raise StandaloneDatabaseError("alembic_version is inconsistent")
    return str(revisions[0])


def _run_standalone_forward_migrations(connection: Any, config_path: Path) -> str:
    """Upgrade to the single head shipped in this tree; do not pin a constant."""

    config = _alembic_config(connection, config_path)
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1 or not heads[0]:
        raise StandaloneDatabaseError("migration graph does not have a single head")
    command.upgrade(config, "head")
    return heads[0]


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
    expected_head = shipped_schema_head(config_path)

    schema_before: str | None = None
    connected_user = ""
    session_user = ""
    admin_engine = create_engine(admin_url, pool_pre_ping=True)
    try:
        with admin_engine.connect() as connection:
            identity = connection.execute(text("SELECT current_user, session_user")).one()
            connected_user, session_user = str(identity[0]), str(identity[1])
            if (connected_user, session_user) != (migrator, migrator):
                raise StandaloneDatabaseError("migrate_must_use_migration_user")
            connection.execute(text("SELECT pg_advisory_lock(hashtext(:key))"), {"key": _LOCK_KEY})
            connection.commit()
            try:
                with connection.begin():
                    _repair_runtime_owned_objects(connection, migrator, runtime_role)
                    try:
                        _ensure_unprivileged_role(connection, runtime)
                        schema_before = _current_schema_revision(connection)
                        shipped_head = _run_standalone_forward_migrations(connection, config_path)
                        if shipped_head != expected_head:
                            raise StandaloneDatabaseError(
                                "migration graph does not have a single head"
                            )
                        schema_after = _current_schema_revision(connection)
                        if schema_after != expected_head:
                            raise StandaloneDatabaseError("schema is not at the expected head")
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
    if verification["revision"] != expected_head:
        raise StandaloneDatabaseError("schema is not at the expected head")
    if not verification["non_admin"] or not verification["ddl_denied"]:
        raise StandaloneDatabaseError("runtime role retained elevated privileges")

    alembic_action = "no-op" if schema_before == expected_head else "upgrade"
    return StandaloneDatabaseEvidence(
        contract=STANDALONE_DATABASE_CONTRACT,
        status="ready",
        schema_revision=expected_head,
        schema_before=schema_before or "none",
        alembic_action=alembic_action,
        connected_user=connected_user,
        session_user=session_user,
        schema_at_expected_head=True,
        runtime_role_non_admin=bool(verification["non_admin"]),
        runtime_ddl_denied=bool(verification["ddl_denied"]),
        audit_update_denied=bool(verification["audit_update_denied"]),
        audit_delete_denied=bool(verification["audit_delete_denied"]),
        migrator_role_derived=True,
        runtime_role_derived=True,
    )
