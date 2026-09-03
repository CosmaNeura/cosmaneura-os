from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from base64 import b64encode
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import sql
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError

from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION

DATABASE_PREPARATION_CONTRACT = "cosmas-os-d3-database-preparation-v1"
_LOCK_KEY = "cosmas-os-d3-database-preparation-v1"
_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
_RUNTIME_PASSWORD_PATTERN = re.compile(r"^[\x21-\x7e]{24,}$")
_EXPECTED_DENIAL_SQLSTATE = "42501"
_SCRAM_ITERATIONS = 4096


class DatabasePreparationError(RuntimeError):
    """Fail-closed preparation error whose text is always credential-free."""


@dataclass(frozen=True)
class DatabasePreparationEvidence:
    contract: str
    status: str
    schema_revision: str
    schema_at_expected_head: bool
    runtime_role_non_admin: bool
    runtime_ddl_denied: bool
    audit_update_denied: bool
    audit_delete_denied: bool

    def sanitized_payload(self) -> dict[str, str | bool]:
        return asdict(self)

    def sanitized_json(self) -> str:
        payload = self.sanitized_payload()
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload["evidence_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _safe_url(value: str, *, label: str) -> URL:
    try:
        parsed = make_url(value)
    except Exception:
        raise DatabasePreparationError(f"{label} is invalid") from None
    if parsed.drivername != "postgresql+psycopg":
        raise DatabasePreparationError(f"{label} must use PostgreSQL psycopg")
    if not parsed.username or parsed.password is None or not parsed.host or not parsed.database:
        raise DatabasePreparationError(f"{label} is incomplete")
    return parsed


def _validate_boundaries(admin_url: str, runtime_url: str, *, require_verify_full: bool) -> tuple[URL, URL]:
    admin = _safe_url(admin_url, label="administrator database URL")
    runtime = _safe_url(runtime_url, label="runtime database URL")
    if (
        admin.host,
        admin.port or 5432,
        admin.database,
    ) != (
        runtime.host,
        runtime.port or 5432,
        runtime.database,
    ):
        raise DatabasePreparationError("database URLs do not target the same database")
    if admin.username == runtime.username:
        raise DatabasePreparationError("runtime role must differ from the administrator")
    admin_password = admin.password
    runtime_password = runtime.password
    if admin_password is None or runtime_password is None:  # guarded by _safe_url
        raise DatabasePreparationError("database URL is incomplete")
    if hmac.compare_digest(admin_password.encode("utf-8"), runtime_password.encode("utf-8")):
        raise DatabasePreparationError("runtime credential must differ from the administrator")
    if not _RUNTIME_PASSWORD_PATTERN.fullmatch(runtime_password):
        raise DatabasePreparationError(
            "runtime credential must contain at least 24 printable ASCII characters"
        )
    runtime_username = runtime.username
    if runtime_username is None or not _ROLE_PATTERN.fullmatch(runtime_username):
        raise DatabasePreparationError("runtime role name is invalid")
    if runtime.database != "cosmas_os":
        raise DatabasePreparationError("database name must be cosmas_os")
    if require_verify_full and (
        set(admin.query) != {"sslmode", "sslrootcert"}
        or set(runtime.query) != {"sslmode", "sslrootcert"}
        or admin.query.get("sslmode") != "verify-full"
        or runtime.query.get("sslmode") != "verify-full"
        or admin.query.get("sslrootcert") != "system"
        or runtime.query.get("sslrootcert") != "system"
    ):
        raise DatabasePreparationError(
            "database URLs must use verify-full TLS with the system trust store"
        )
    return admin, runtime


def _quoted_identifier(connection: Connection, value: str) -> str:
    return connection.dialect.identifier_preparer.quote_identifier(value)


def _scram_sha_256_verifier(password: str, *, salt: bytes | None = None) -> str:
    """Create a PostgreSQL-compatible verifier without sending plaintext in SQL."""

    scram_salt = salt if salt is not None else secrets.token_bytes(16)
    if len(scram_salt) < 16:
        raise DatabasePreparationError("runtime credential salt is invalid")
    salted_password = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        scram_salt,
        _SCRAM_ITERATIONS,
    )
    client_key = hmac.new(salted_password, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted_password, b"Server Key", hashlib.sha256).digest()
    return (
        f"SCRAM-SHA-256${_SCRAM_ITERATIONS}:{b64encode(scram_salt).decode('ascii')}"
        f"${b64encode(stored_key).decode('ascii')}:{b64encode(server_key).decode('ascii')}"
    )


def _ensure_unprivileged_role(connection: Connection, runtime: URL) -> None:
    role = runtime.username
    password = runtime.password
    if role is None or password is None:  # guarded by _safe_url; keeps type checkers honest
        raise DatabasePreparationError("runtime database URL is incomplete")
    password_verifier = _scram_sha_256_verifier(password)
    exists = connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
        {"role": role},
    ).scalar_one()
    if not exists:
        driver_connection = connection.connection.driver_connection
        if driver_connection is None:
            raise DatabasePreparationError("database driver connection is unavailable")
        with driver_connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(role),
                    sql.Literal(password_verifier),
                )
            )
    else:
        memberships = connection.execute(
            text(
                "SELECT count(*) FROM pg_auth_members m "
                "JOIN pg_roles member_role ON member_role.oid = m.member "
                "WHERE member_role.rolname = :role"
            ),
            {"role": role},
        ).scalar_one()
        if memberships:
            raise DatabasePreparationError("runtime role has unexpected role memberships")

    # Re-running rotates the protected runtime password and restores every
    # non-administrator role attribute without widening access.
    driver_connection = connection.connection.driver_connection
    if driver_connection is None:
        raise DatabasePreparationError("database driver connection is unavailable")
    with driver_connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "ALTER ROLE {} WITH LOGIN PASSWORD {} "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(role), sql.Literal(password_verifier))
        )


def _alembic_config(connection: Connection, config_path: Path) -> Config:
    config = Config(str(config_path))
    config.attributes["connection"] = connection
    # The job emits one credential-free evidence object. Suppress Alembic's
    # ordinary migration chatter so that stdout/stderr never become an
    # accidental evidence or connection-detail channel.
    config.attributes["configure_logger"] = False
    return config


def _run_forward_migrations(connection: Connection, config_path: Path) -> None:
    config = _alembic_config(connection, config_path)
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if heads != [EXPECTED_SCHEMA_REVISION]:
        raise DatabasePreparationError("migration graph does not match the expected schema head")
    command.upgrade(config, "head")


def _apply_runtime_privileges(connection: Connection, runtime: URL) -> None:
    role = runtime.username
    database = runtime.database
    if role is None or database is None:  # guarded by _safe_url
        raise DatabasePreparationError("runtime database URL is incomplete")
    quoted_role = _quoted_identifier(connection, role)
    quoted_database = _quoted_identifier(connection, database)
    admin_role = str(connection.execute(text("SELECT current_user")).scalar_one())
    quoted_admin = _quoted_identifier(connection, admin_role)

    statements = (
        f"REVOKE CREATE, TEMPORARY ON DATABASE {quoted_database} FROM PUBLIC",
        f"REVOKE CREATE, TEMPORARY ON DATABASE {quoted_database} FROM {quoted_role}",
        f"GRANT CONNECT ON DATABASE {quoted_database} TO {quoted_role}",
        "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
        f"REVOKE CREATE ON SCHEMA public FROM {quoted_role}",
        f"GRANT USAGE ON SCHEMA public TO {quoted_role}",
        f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM PUBLIC, {quoted_role}",
        f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, {quoted_role}",
        f"REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, {quoted_role}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {quoted_role}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {quoted_role}",
        f"REVOKE UPDATE, DELETE, TRUNCATE ON TABLE public.audit_events FROM {quoted_role}",
        f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE public.alembic_version FROM {quoted_role}",
        f"GRANT SELECT ON TABLE public.alembic_version TO {quoted_role}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {quoted_admin} IN SCHEMA public "
        "REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {quoted_admin} IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {quoted_role}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {quoted_admin} IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {quoted_role}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {quoted_admin} IN SCHEMA public "
        "REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {quoted_admin} IN SCHEMA public "
        "REVOKE ALL PRIVILEGES ON FUNCTIONS FROM PUBLIC",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {quoted_admin} IN SCHEMA public "
        f"REVOKE ALL PRIVILEGES ON FUNCTIONS FROM {quoted_role}",
        f"ALTER ROLE {quoted_role} SET search_path = public",
    )
    for statement in statements:
        connection.execute(text(statement))


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)


def _operation_is_denied(runtime_url: str, statement: str) -> bool:
    engine = create_engine(runtime_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(statement))
            except DBAPIError as error:
                transaction.rollback()
                return _sqlstate(error) == _EXPECTED_DENIAL_SQLSTATE
            else:
                transaction.rollback()
                return False
    finally:
        engine.dispose()


def _verify_runtime_role(runtime_url: str, runtime: URL) -> dict[str, Any]:
    role = runtime.username
    if role is None:  # guarded by _safe_url
        raise DatabasePreparationError("runtime database URL is incomplete")
    engine = create_engine(runtime_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            attributes = connection.execute(
                text(
                    "SELECT r.rolsuper, r.rolcreatedb, r.rolcreaterole, r.rolreplication, "
                    "r.rolbypassrls, "
                    "has_database_privilege(current_user, current_database(), 'CREATE') AS db_create, "
                    "has_database_privilege(current_user, current_database(), 'TEMPORARY') AS db_temp, "
                    "has_schema_privilege(current_user, 'public', 'CREATE') AS schema_create, "
                    "has_schema_privilege(current_user, 'public', 'USAGE') AS schema_usage, "
                    "has_table_privilege(current_user, 'public.audit_events', 'INSERT') AS audit_insert, "
                    "has_table_privilege(current_user, 'public.audit_events', 'UPDATE') AS audit_update, "
                    "has_table_privilege(current_user, 'public.audit_events', 'DELETE') AS audit_delete, "
                    "has_table_privilege(current_user, 'public.audit_events', 'TRUNCATE') AS audit_truncate, "
                    "has_table_privilege(current_user, 'public.alembic_version', 'SELECT') AS version_select, "
                    "has_table_privilege(current_user, 'public.alembic_version', 'UPDATE') AS version_update "
                    "FROM pg_roles r WHERE r.rolname = current_user"
                )
            ).mappings().one()
            revision = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            runtime_dml = connection.execute(
                text(
                    "SELECT coalesce(bool_and("
                    "has_table_privilege(current_user, format('%I.%I', schemaname, tablename), 'SELECT') AND "
                    "has_table_privilege(current_user, format('%I.%I', schemaname, tablename), 'INSERT') AND "
                    "has_table_privilege(current_user, format('%I.%I', schemaname, tablename), 'UPDATE') AND "
                    "has_table_privilege(current_user, format('%I.%I', schemaname, tablename), 'DELETE') AND "
                    "NOT has_table_privilege(current_user, format('%I.%I', schemaname, tablename), 'TRUNCATE') AND "
                    "NOT has_table_privilege(current_user, format('%I.%I', schemaname, tablename), 'REFERENCES') AND "
                    "NOT has_table_privilege(current_user, format('%I.%I', schemaname, tablename), 'TRIGGER')"
                    "), false) "
                    "FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename NOT IN ('alembic_version', 'audit_events')"
                )
            ).scalar_one()
            runtime_sequences = connection.execute(
                text(
                    "SELECT coalesce(bool_and("
                    "has_sequence_privilege(current_user, format('%I.%I', schemaname, sequencename), 'USAGE') AND "
                    "has_sequence_privilege(current_user, format('%I.%I', schemaname, sequencename), 'SELECT') AND "
                    "NOT has_sequence_privilege(current_user, format('%I.%I', schemaname, sequencename), 'UPDATE')"
                    "), true) FROM pg_sequences WHERE schemaname = 'public'"
                )
            ).scalar_one()
            owned_objects = connection.execute(
                text(
                    "SELECT count(*) FROM pg_class c "
                    "JOIN pg_roles r ON r.oid = c.relowner "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE r.rolname = current_user AND n.nspname = 'public'"
                )
            ).scalar_one()
    finally:
        engine.dispose()

    non_admin = not any(
        (
            attributes["rolsuper"],
            attributes["rolcreatedb"],
            attributes["rolcreaterole"],
            attributes["rolreplication"],
            attributes["rolbypassrls"],
            attributes["db_create"],
            attributes["db_temp"],
            attributes["schema_create"],
            owned_objects,
        )
    )
    privilege_contract = all(
        (
            attributes["schema_usage"],
            attributes["audit_insert"],
            not attributes["audit_update"],
            not attributes["audit_delete"],
            not attributes["audit_truncate"],
            attributes["version_select"],
            not attributes["version_update"],
        )
    )
    return {
        "revision": revision,
        "non_admin": non_admin and privilege_contract and runtime_dml and runtime_sequences,
        "ddl_denied": _operation_is_denied(
            runtime_url,
            "CREATE TABLE public.cosmas_runtime_ddl_probe (id integer)",
        ),
        "audit_update_denied": _operation_is_denied(
            runtime_url,
            "UPDATE public.audit_events SET event_type = event_type WHERE false",
        ),
        "audit_delete_denied": _operation_is_denied(
            runtime_url,
            "DELETE FROM public.audit_events WHERE false",
        ),
    }


def prepare_beta_database(
    admin_url: str,
    runtime_url: str,
    *,
    require_verify_full: bool = True,
    alembic_config_path: Path | None = None,
) -> DatabasePreparationEvidence:
    """Idempotently migrate and prove the isolated D3 runtime database boundary."""

    _, runtime = _validate_boundaries(
        admin_url,
        runtime_url,
        require_verify_full=require_verify_full,
    )
    config_path = alembic_config_path or Path(__file__).resolve().parents[3] / "alembic.ini"
    if not config_path.is_file():
        raise DatabasePreparationError("Alembic configuration is unavailable")

    admin_engine = create_engine(admin_url, pool_pre_ping=True)
    try:
        with admin_engine.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(hashtext(:key))"), {"key": _LOCK_KEY})
            connection.commit()
            try:
                with connection.begin():
                    _ensure_unprivileged_role(connection, runtime)
                    _run_forward_migrations(connection, config_path)
                    _apply_runtime_privileges(connection, runtime)
            finally:
                if connection.in_transaction():
                    connection.rollback()
                connection.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": _LOCK_KEY}
                )
                connection.commit()
    except DatabasePreparationError:
        raise
    except Exception:
        raise DatabasePreparationError("database preparation failed") from None
    finally:
        admin_engine.dispose()

    try:
        verification = _verify_runtime_role(runtime_url, runtime)
    except Exception:
        raise DatabasePreparationError("runtime database verification failed") from None

    evidence = DatabasePreparationEvidence(
        contract=DATABASE_PREPARATION_CONTRACT,
        status="ready",
        schema_revision=EXPECTED_SCHEMA_REVISION,
        schema_at_expected_head=verification["revision"] == EXPECTED_SCHEMA_REVISION,
        runtime_role_non_admin=bool(verification["non_admin"]),
        runtime_ddl_denied=bool(verification["ddl_denied"]),
        audit_update_denied=bool(verification["audit_update_denied"]),
        audit_delete_denied=bool(verification["audit_delete_denied"]),
    )
    if not all(
        (
            evidence.schema_at_expected_head,
            evidence.runtime_role_non_admin,
            evidence.runtime_ddl_denied,
            evidence.audit_update_denied,
            evidence.audit_delete_denied,
        )
    ):
        raise DatabasePreparationError("runtime database verification failed")
    return evidence
