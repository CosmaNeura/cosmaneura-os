"""Independent enrollment-only role bootstrap/migration/grant qualification.

Production inputs arrive from selected versioned Key Vault secrets, not CLI
arguments. This module is added to a one-purpose image; it is not an API route.
"""

from __future__ import annotations

import json
import os
import re
import sys

from psycopg import sql
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool

from cosmas_os.enrollment.migration import SCHEMA_VERSION, schema_ready, upgrade
from cosmas_os.enrollment.models import EnrollmentBase

DATABASE = "cosmabot_enrollment"
LOGINS = {"admin": "enrollment_bootstrap", "migration": "enrollment_migrator", "runtime": "enrollment_runtime"}
BAA = "enrollment_baa_acceptances"


def database_names(connection) -> set[str]:
    names = set(connection.execute(text("SELECT datname FROM pg_database")).scalars())
    required = {DATABASE, "postgres", "template0", "template1"}
    if not required.issubset(names) or names - required - {"azure_maintenance", "azure_sys"}:
        raise ValueError("server contains an unrelated database")
    return names


def engines_from_environment(operation: str) -> dict[str, Engine]:
    host = os.environ.get("ENROLLMENT_DATABASE_HOST", "")
    if not re.fullmatch(r"psql-cosmabot-enrollment-staging-[a-z0-9]{6,8}\.postgres\.database\.azure\.com", host):
        raise ValueError("owned staging PostgreSQL host required")
    roles = ("admin", "migration", "runtime") if operation == "bootstrap" else (("migration", "runtime") if operation == "migrate" else ("runtime",))
    result: dict[str, Engine] = {}
    for role in roles:
        url = make_url(os.environ.get(f"ENROLLMENT_{role.upper()}_DATABASE_URL", ""))
        if (url.drivername != "postgresql+psycopg" or url.host != host or url.port not in (None, 5432)
                or url.database != DATABASE or url.username != LOGINS[role] or not url.password
                or set(url.query) != {"sslmode", "sslrootcert"} or url.query["sslmode"] != "verify-full"
                or url.query["sslrootcert"] != "/etc/ssl/certs/ca-certificates.crt"):
            raise ValueError("bound PostgreSQL role/TLS URL required")
        result[role] = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 10}, hide_parameters=True)
    return result


def role_flags(connection, role: str) -> tuple | None:
    return connection.execute(text("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolinherit, rolcanlogin FROM pg_roles WHERE rolname=:role"), {"role": role}).first()


def check_role(connection, role: str) -> None:
    if role_flags(connection, role) != (False, False, False, False, False, False, True):
        raise ValueError("database role has unexpected authority")
    if connection.execute(text("SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=:role"), {"role": role}).scalar_one():
        raise ValueError("database role may not inherit or assume another role")


def bootstrap(engines: dict[str, Engine]) -> None:
    admin = engines["admin"]
    with admin.begin() as connection:
        if connection.execute(text("SELECT current_database()")).scalar_one() != DATABASE:
            raise ValueError("wrong database")
        database_names(connection)
        # Refuse all non-enrollment tables before changing any authority.
        if any(not name.startswith("enrollment_") for name in inspect(connection).get_table_names()):
            raise ValueError("database contains unrelated tables")
        driver = connection.connection.driver_connection
        if driver is None:
            raise ValueError("open PostgreSQL driver connection required")
        cursor = driver.cursor()
        try:
            for role in ("migration", "runtime"):
                login = LOGINS[role]
                password = engines[role].url.password
                if role_flags(connection, login) is None:
                    cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD {}").format(sql.Identifier(login), sql.Literal(password)))
                else:
                    check_role(connection, login)
                    cursor.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(login), sql.Literal(password)))
                check_role(connection, login)
            for name in (DATABASE, "postgres", "template1"):
                cursor.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name)))
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(sql.Identifier(DATABASE), sql.Identifier(LOGINS["migration"]), sql.Identifier(LOGINS["runtime"])))
            cursor.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            cursor.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(sql.Identifier(LOGINS["migration"])))
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(LOGINS["runtime"])))
        finally:
            cursor.close()


def migrate(engines: dict[str, Engine]) -> None:
    engine = engines["migration"]
    upgrade(engine)
    with engine.begin() as connection:
        check_role(connection, LOGINS["migration"])
        driver = connection.connection.driver_connection
        if driver is None:
            raise ValueError("open PostgreSQL driver connection required")
        cursor = driver.cursor()
        try:
            # The non-superuser bootstrap cannot assume the migration role.
            # Each owner adjusts only its own defaults and exact object grants.
            cursor.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {}").format(sql.Identifier(LOGINS["runtime"])))
            cursor.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(sql.Identifier(LOGINS["runtime"])))
            tables = set(EnrollmentBase.metadata.tables)
            if BAA not in tables:
                raise ValueError("immutable receipt table mismatch")
            for table in sorted(tables):
                grants = sql.SQL("SELECT, INSERT") if table == BAA else sql.SQL("SELECT, INSERT, UPDATE, DELETE")
                cursor.execute(sql.SQL("GRANT {} ON TABLE {} TO {}").format(grants, sql.Identifier(table), sql.Identifier(LOGINS["runtime"])))
            cursor.execute(sql.SQL("GRANT SELECT ON TABLE enrollment_schema_versions TO {}").format(sql.Identifier(LOGINS["runtime"])))
        finally:
            cursor.close()


def check(engines: dict[str, Engine]) -> dict[str, object]:
    runtime = engines["runtime"]
    if not schema_ready(runtime):
        raise ValueError("schema not ready")
    with runtime.connect() as connection:
        if connection.execute(text("SELECT current_database(),current_user")).first() != (DATABASE, LOGINS["runtime"]):
            raise ValueError("incorrect runtime login")
        check_role(connection, LOGINS["runtime"])
        database_names(connection)
        if set(inspect(connection).get_table_names()) != set(EnrollmentBase.metadata.tables) | {"enrollment_schema_versions"}:
            raise ValueError("unexpected database tables")
        for database in (DATABASE, "postgres", "template1"):
            flags = connection.execute(text("SELECT has_database_privilege(current_user,:database,'CREATE'),has_database_privilege(current_user,:database,'TEMP'),has_database_privilege(current_user,:database,'CONNECT')"), {"database": database}).first()
            if flags != (False, False, database == DATABASE):
                raise ValueError("runtime database privilege exceeds scope")
        # Azure's own managed databases are never modified by bootstrap. They
        # are allowed in the inventory only while their provider access remains
        # closed to the application login.
        for database in connection.execute(text("SELECT datname FROM pg_database WHERE datname IN ('azure_maintenance','azure_sys')")).scalars():
            if connection.execute(text("SELECT has_database_privilege(current_user,:database,'CONNECT') OR has_database_privilege(current_user,:database,'CREATE') OR has_database_privilege(current_user,:database,'TEMP')"), {"database": database}).scalar_one():
                raise ValueError("runtime may not access managed service databases")
        if connection.execute(text("SELECT has_schema_privilege(current_user,'public','CREATE')")).scalar_one():
            raise ValueError("runtime may not create objects")
        for table in sorted(set(EnrollmentBase.metadata.tables) | {"enrollment_schema_versions"}):
            expected = {"SELECT"} if table == "enrollment_schema_versions" else ({"SELECT", "INSERT"} if table == BAA else {"SELECT", "INSERT", "UPDATE", "DELETE"})
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                actual = connection.execute(text("SELECT has_table_privilege(current_user,:table,:privilege)"), {"table": table, "privilege": privilege}).scalar_one()
                if actual != (privilege in expected):
                    raise ValueError("runtime table privilege exceeds exact grant contract")
        trigger = connection.execute(text("SELECT count(*) FROM pg_trigger WHERE tgrelid=CAST(:table AS regclass) AND tgname='enrollment_baa_immutable' AND NOT tgisinternal AND tgenabled='O'"), {"table": BAA}).scalar_one()
        if trigger != 1:
            raise ValueError("immutable agreement trigger missing")
    return {"contract_version": "enrollment-database-check.v1", "schema_version": SCHEMA_VERSION,
            "runtime_role_checked": True, "immutable_receipt_checked": True, "grant_table_count": len(EnrollmentBase.metadata.tables) + 1,
            "azure_connectivity_qualified": False, "restore_qualified": False, "journey_qualified": False}


def main() -> int:
    engines: dict[str, Engine] = {}
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"bootstrap", "migrate", "check"}:
            raise ValueError("explicit database operation required")
        operation = sys.argv[1]
        engines = engines_from_environment(operation)
        if operation == "bootstrap":
            bootstrap(engines)
            result = {"operation": "bootstrap", "roles_created": True, "qualified": False}
        else:
            if operation == "migrate":
                migrate(engines)
            result = check(engines)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        # Never print SQL, driver errors, URLs, credentials or environment.
        print(json.dumps({"error": "enrollment_database_preparation_failed", "class": type(error).__name__}), file=sys.stderr)
        return 1
    finally:
        for engine in engines.values():
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
