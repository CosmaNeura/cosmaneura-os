"""The recovery command cannot depend on models imported by pytest or API routes."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

SOURCE = Path(__file__).resolve().parents[2] / "src"
FRESH_PROCESS = """
import os, sys
sys.path.insert(0, sys.argv[1])
from cosmas_os.application.database_fingerprint import DatabaseFingerprintError
from cosmas_os.application.workspace_fingerprint import (
    fingerprint_workspace_database, workspace_fingerprint_failure_json,
)
assert 'cosmas_os.api.app' not in sys.modules
assert 'cosmas_os.application.services' not in sys.modules
assert 'cosmas_os.compact.models' not in sys.modules
try:
    result = fingerprint_workspace_database(
        os.environ['DATABASE_URL'],
        cosmas_env='synth_os' if '/w1a_' in os.environ['DATABASE_URL'] else 'early_adopter_beta',
        data_mode='synthetic',
        require_verify_full=False,
    )
except DatabaseFingerprintError:
    print(workspace_fingerprint_failure_json())
    raise SystemExit(1)
print(result.sanitized_json())
"""


def fresh_snapshot(engine, tmp_path):
    return subprocess.run(
        [sys.executable, "-I", "-c", FRESH_PROCESS, str(SOURCE)],
        cwd=tmp_path,
        env={
            "PATH": os.defpath,
            "DATABASE_URL": engine.url.render_as_string(hide_password=False),
            "COSMAS_ENV": "synth_os",
            "DATA_MODE": "synthetic",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_fresh_process_measures_every_migrated_table(engine, tmp_path):
    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            ).scalars()
        ) - {"alembic_version"}
    first = fresh_snapshot(engine, tmp_path)
    assert first.returncode == 0, first.stderr
    evidence = json.loads(first.stdout)
    assert evidence["status"] == "snapshot_ready"
    assert set(evidence["tables"]) == tables
    assert {
        "vendor_command_retirements",
        "vendor_preparation_retirements",
        "finance_command_receipts",
        "research_runs",
    } <= tables
    assert not any(name.startswith("compact_") for name in tables)
    assert fresh_snapshot(engine, tmp_path).stdout == first.stdout


@pytest.mark.parametrize(
    ("change", "undo"),
    [
        # Moving the table preserves its contents and constraints while leaving only
        # a missing public relation, so the missing and extra checks are independent.
        (
            [
                "CREATE SCHEMA fingerprint_missing",
                "ALTER TABLE vendor_command_retirements SET SCHEMA fingerprint_missing",
            ],
            [
                "ALTER TABLE fingerprint_missing.vendor_command_retirements SET SCHEMA public",
                "DROP SCHEMA fingerprint_missing",
            ],
        ),
        (
            ["CREATE TABLE fingerprint_unexpected (id integer PRIMARY KEY)"],
            ["DROP TABLE fingerprint_unexpected"],
        ),
    ],
)
def test_fresh_process_refuses_missing_or_unexpected_table(engine, tmp_path, change, undo):
    with engine.begin() as connection:
        for statement in change:
            connection.execute(text(statement))
    try:
        result = fresh_snapshot(engine, tmp_path)
        assert result.returncode == 1
        assert json.loads(result.stdout) == {
            "contract": "cosmas-os-workspace-database-fingerprint-v1",
            "status": "failed",
        }
        assert not result.stderr
    finally:
        with engine.begin() as connection:
            for statement in undo:
                connection.execute(text(statement))
    assert fresh_snapshot(engine, tmp_path).returncode == 0
