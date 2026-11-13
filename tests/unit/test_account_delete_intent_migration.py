"""Alembic up/down for account_delete_intents (b57c3d0e9142)."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
PARENT = "a46f2c09d853"
REVISION = "b57c3d0e9142"


@pytest.fixture
def migration_engine():
    raw = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://cosmas:cosmas@localhost:54329/cosmas_os"
    )
    url = make_url(raw)
    assert url.host in {"127.0.0.1", "localhost"}
    name = "cosmas_adi_mig_" + uuid4().hex[:12]
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    target_url = url.set(database=name)
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    engine = create_engine(target_url)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{name}' AND pid <> pg_backend_pid()"
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
        admin.dispose()


def _migrate(engine, revision: str, *, downgrade: bool = False):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        (command.downgrade if downgrade else command.upgrade)(cfg, revision)


def test_account_delete_intents_upgrade_and_downgrade(migration_engine):
    _migrate(migration_engine, PARENT)
    with migration_engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        }
        assert "account_delete_intents" not in tables

    _migrate(migration_engine, REVISION)
    with migration_engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        }
        assert "account_delete_intents" in tables
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            REVISION
        )

    _migrate(migration_engine, PARENT, downgrade=True)
    with migration_engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        }
        assert "account_delete_intents" not in tables
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            PARENT
        )
