"""Dedicated additive schema migration. This never imports the clinical Alembic graph."""
from __future__ import annotations

import argparse

from sqlalchemy import create_engine, inspect, text

from .config import EnrollmentSettings
from .models import EnrollmentBase

SCHEMA_VERSION = "enrollment_20261031_v1"


def upgrade(engine) -> None:
    """Apply once to a dedicated enrollment store; retain all receipts on rollback."""
    with engine.begin() as connection:
        present = set(inspect(connection).get_table_names())
        foreign = {n for n in present if not n.startswith("enrollment_")}
        if foreign:
            raise RuntimeError("Enrollment migration requires a database without clinical tables")
        inspector = inspect(connection)
        for table in EnrollmentBase.metadata.sorted_tables:
            if table.name in present and not {column.name for column in table.columns}.issubset(
                    {column["name"] for column in inspector.get_columns(table.name)}):
                raise RuntimeError("Enrollment schema requires an explicit additive migration; existing receipts must be retained")
        EnrollmentBase.metadata.create_all(connection)
        connection.execute(text("CREATE TABLE IF NOT EXISTS enrollment_schema_versions (version VARCHAR(64) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO enrollment_schema_versions (version) VALUES (:version) ON CONFLICT (version) DO NOTHING"), {"version": SCHEMA_VERSION})
        if connection.dialect.name == "postgresql":
            connection.execute(text("""
                CREATE OR REPLACE FUNCTION enrollment_forbid_baa_mutation() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Enrollment BAA receipts are immutable'; END $$
            """))
            connection.execute(text("DROP TRIGGER IF EXISTS enrollment_baa_immutable ON enrollment_baa_acceptances"))
            connection.execute(text("""CREATE TRIGGER enrollment_baa_immutable BEFORE UPDATE OR DELETE
                ON enrollment_baa_acceptances FOR EACH ROW EXECUTE FUNCTION enrollment_forbid_baa_mutation()"""))
        elif connection.dialect.name == "sqlite":
            for verb in ("UPDATE", "DELETE"):
                connection.execute(text(f"""CREATE TRIGGER IF NOT EXISTS enrollment_baa_no_{verb.lower()}
                    BEFORE {verb} ON enrollment_baa_acceptances BEGIN
                    SELECT RAISE(ABORT, 'Enrollment BAA receipts are immutable'); END"""))
        else:
            raise RuntimeError("Enrollment store must be PostgreSQL or synthetic SQLite")


def schema_ready(engine) -> bool:
    try:
        with engine.connect() as connection:
            if connection.execute(text("SELECT version FROM enrollment_schema_versions WHERE version=:version"), {"version": SCHEMA_VERSION}).scalar_one_or_none() != SCHEMA_VERSION:
                return False
            inspector = inspect(connection)
            present = set(inspector.get_table_names())
            for table in EnrollmentBase.metadata.sorted_tables:
                if table.name not in present:
                    return False
                columns = {column["name"] for column in inspector.get_columns(table.name)}
                if not {column.name for column in table.columns}.issubset(columns):
                    return False
            return True
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the dedicated enrollment expand migration")
    parser.add_argument("command", choices=["upgrade", "check"])
    command = parser.parse_args().command
    settings = EnrollmentSettings()
    url = settings.database_url.get_secret_value()
    if not url:
        raise SystemExit("ENROLLMENT_DATABASE_URL is required")
    engine = create_engine(url, pool_pre_ping=True)
    if command == "upgrade":
        upgrade(engine)
    elif not schema_ready(engine):
        raise SystemExit("Enrollment migration is required")
    print(SCHEMA_VERSION)


if __name__ == "__main__":
    main()
