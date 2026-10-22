"""Fixed forward migration using an existing administrator connection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, text

from cosmas_os.application.database_preparation import (
    _LOCK_KEY,
    _alembic_config,
    _validate_boundaries,
)
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION

FROM_REVISION = "j79f1d5a2340"
TO_REVISION = "k80e6a9d4321"
FAILURE = "database migration failed"


class DatabaseMigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabaseMigrationEvidence:
    contract: str
    status: str
    schema_before: str
    schema_revision: str
    schema_at_expected_head: bool
    migration_lock_acquired: bool
    runtime_role_non_admin: bool
    runtime_role_attributes_unchanged: bool
    runtime_memberships_unchanged: bool
    public_acl_owner_security_unchanged: bool
    transaction_committed: bool

    def sanitized_json(self) -> str:
        payload = asdict(self)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload["evidence_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _role_state(connection: Connection, role: str) -> tuple:
    row = connection.execute(text(
        "SELECT oid, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, "
        "rolcanlogin, rolinherit, rolconnlimit, rolvaliduntil, rolconfig "
        "FROM pg_roles WHERE rolname=:role"
    ), {"role": role}).one_or_none()
    if row is None or any(row[1:6]) or row[6] is not True:
        raise DatabaseMigrationError(FAILURE)
    memberships = tuple(connection.execute(text(
        "SELECT roleid, member, grantor, admin_option, inherit_option, set_option "
        "FROM pg_auth_members WHERE member=:oid ORDER BY roleid, grantor"
    ), {"oid": row[0]}).tuples())
    if memberships:
        raise DatabaseMigrationError(FAILURE)
    return tuple(row), memberships


def _catalog_state(connection: Connection) -> tuple:
    # Function bodies are the reviewed change. Owners, ACLs, signatures and
    # security attributes must stay exact, as must existing relation metadata.
    namespace = tuple(connection.execute(text(
        "SELECT oid, nspowner, nspacl::text FROM pg_namespace "
        "WHERE nspname='public' ORDER BY oid"
    )).tuples())
    relations = tuple(connection.execute(text(
        "SELECT c.oid, c.relkind, c.relowner, c.relacl::text "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' ORDER BY c.oid"
    )).tuples())
    functions = tuple(connection.execute(text(
        "SELECT p.oid, p.proowner, p.proacl::text, p.prolang, p.prosecdef, "
        "p.provolatile, p.prokind, p.proleakproof, p.proisstrict, p.proparallel, "
        "p.proretset, p.prorettype, p.proargtypes::text, p.proargnames, p.proconfig "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' ORDER BY p.oid"
    )).tuples())
    return namespace, relations, functions


def migrate_beta_database_forward(
    connection: Connection,
    runtime_url: str,
    *,
    require_verify_full: bool = True,
    alembic_config_path: Path | None = None,
) -> DatabaseMigrationEvidence:
    """Apply only j79 -> k80, without preparation or credential/role writes.

    The caller supplies an idle administrator connection and retains ownership
    of it. An existing caller transaction is refused before any SQL is issued.
    """
    try:
        if (not isinstance(connection, Connection) or connection.closed
                or connection.invalidated or connection.in_transaction()
                or connection.dialect.name != "postgresql" or connection.engine.echo):
            raise DatabaseMigrationError(FAILURE)
        admin, runtime = _validate_boundaries(
            connection.engine.url.render_as_string(hide_password=False),
            runtime_url,
            require_verify_full=require_verify_full,
        )
        runtime_role = runtime.username
        if not isinstance(runtime_role, str) or not runtime_role:
            raise DatabaseMigrationError(FAILURE)
        if EXPECTED_SCHEMA_REVISION != TO_REVISION:
            raise DatabaseMigrationError(FAILURE)
        config_path = alembic_config_path or Path(__file__).resolve().parents[3] / "alembic.ini"
        if not config_path.is_file():
            raise DatabaseMigrationError(FAILURE)

        with connection.begin():
            # Transaction locks conflict with the retained preparation session
            # lock in the same namespace, and release on commit or rollback.
            locked = connection.scalar(text(
                "SELECT pg_try_advisory_xact_lock(hashtext(:key))"
            ), {"key": _LOCK_KEY})
            if locked is not True:
                raise DatabaseMigrationError(FAILURE)
            identity = connection.execute(text(
                "SELECT current_database(), current_user, session_user"
            )).one()
            if tuple(identity) != (admin.database, admin.username, admin.username):
                raise DatabaseMigrationError(FAILURE)
            config = _alembic_config(connection, config_path)
            config.set_main_option("script_location", str(config_path.resolve().parent / "migrations"))
            script = ScriptDirectory.from_config(config)
            if script.get_heads() != [TO_REVISION]:
                raise DatabaseMigrationError(FAILURE)
            target = script.get_revision(TO_REVISION)
            if target is None or target.down_revision != FROM_REVISION or target.dependencies:
                raise DatabaseMigrationError(FAILURE)
            if tuple(connection.execute(text(
                "SELECT version_num FROM public.alembic_version ORDER BY version_num"
            )).scalars()) != (FROM_REVISION,):
                raise DatabaseMigrationError(FAILURE)
            role_before, memberships_before = _role_state(connection, runtime_role)
            catalog_before = _catalog_state(connection)

            command.upgrade(config, TO_REVISION)

            current = tuple(connection.execute(text(
                "SELECT version_num FROM public.alembic_version ORDER BY version_num"
            )).scalars())
            role_after, memberships_after = _role_state(connection, runtime_role)
            catalog_after = _catalog_state(connection)
            role_equal = role_before == role_after
            memberships_equal = memberships_before == memberships_after
            catalog_equal = catalog_before == catalog_after
            if current != (TO_REVISION,) or not all((role_equal, memberships_equal, catalog_equal)):
                raise DatabaseMigrationError(FAILURE)

        return DatabaseMigrationEvidence(
            contract="cosmas-os-d3-database-migration-only-v1", status="ready",
            schema_before=FROM_REVISION, schema_revision=TO_REVISION,
            schema_at_expected_head=current == (TO_REVISION,), migration_lock_acquired=locked,
            runtime_role_non_admin=True, runtime_role_attributes_unchanged=role_equal,
            runtime_memberships_unchanged=memberships_equal,
            public_acl_owner_security_unchanged=catalog_equal, transaction_committed=True,
        )
    except Exception:
        raise DatabaseMigrationError(FAILURE) from None
