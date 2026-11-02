"""Alembic up/down for the T-REL-6 real-patient recording gate migration."""

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
PREVIOUS = "z35e1b98a742"
HEAD = "aa46f2c09b853"


@pytest.fixture
def migration_engine():
    raw = os.environ.get("DATABASE_URL", "postgresql+psycopg://cosmas:cosmas@localhost:54329/cosmas_os")
    url = make_url(raw)
    assert url.host in {"127.0.0.1", "localhost"}
    name = "cosmas_rpr_mig_" + uuid4().hex[:12]
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


def test_real_patient_recording_migration_up_and_down(migration_engine):
    _migrate(migration_engine, PREVIOUS)
    with migration_engine.connect() as connection:
        assert "real_patient_recording_enabled" not in {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'box_contexts'"
                )
            )
        }

    _migrate(migration_engine, HEAD)
    with migration_engine.begin() as connection:
        box_id = str(uuid4())
        connection.execute(
            text(
                "INSERT INTO box_contexts (id, display_name) VALUES (:id, :name)"
            ),
            {"id": box_id, "name": "Invented migration clinic"},
        )
        row = connection.execute(
            text(
                "SELECT real_patient_recording_enabled, real_patient_recording_kill_engaged "
                "FROM box_contexts WHERE id = :id"
            ),
            {"id": box_id},
        ).one()
        assert row == (False, True)
        patient_default = connection.execute(
            text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'patient_links' AND column_name = 'recording_class'"
            )
        ).scalar_one()
        appointment_default = connection.execute(
            text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'appointment_observations' "
                "AND column_name = 'recording_class'"
            )
        ).scalar_one()
        assert "synthetic" in patient_default
        assert "synthetic" in appointment_default
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == HEAD

    _migrate(migration_engine, PREVIOUS, downgrade=True)
    with migration_engine.connect() as connection:
        columns = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name IN ('box_contexts', 'patient_links', "
                    "'appointment_observations')"
                )
            )
        }
        assert "real_patient_recording_enabled" not in columns
        assert "real_patient_recording_kill_engaged" not in columns
        assert "recording_class" not in columns
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == PREVIOUS

    _migrate(migration_engine, HEAD)
    with migration_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == HEAD
