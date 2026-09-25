import hashlib
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from tests.integration.test_workspace import encounter
from typer.testing import CliRunner

from cosmas_os.application import provider_team, services, workspace
from cosmas_os.application.database_fingerprint import DatabaseFingerprintError
from cosmas_os.application.workspace_fingerprint import (
    WORKSPACE_FINGERPRINT_CONTRACT,
    fingerprint_workspace_database,
)
from cosmas_os.cli import app
from cosmas_os.models import Base


def snapshot(engine):
    return fingerprint_workspace_database(
        os.environ["DATABASE_URL"], cosmas_env="synth_os" if "/w1a_" in os.environ["DATABASE_URL"] else "early_adopter_beta", data_mode="synthetic",
        database_engine=engine, require_verify_full=False,
    )


def test_complete_stable_snapshot_includes_non_id_primary_keys_and_hides_values(engine):
    first = snapshot(engine)
    assert first == snapshot(engine)
    assert set(first.tables) == set(Base.metadata.tables)
    assert {"appointment_executions", "provider_bots", "workspace_replies",
            "workspace_core_note_sources", "follow_up_sources", "routine_runs",
            "model_work_admissions", "model_usage_observations"} <= set(first.tables)
    encoded = json.loads(first.sanitized_json())
    digest = encoded.pop("evidence_sha256")
    assert digest == hashlib.sha256(json.dumps(encoded, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert first.status == "snapshot_ready"
    assert os.environ["DATABASE_URL"] not in first.sanitized_json()


def test_committed_private_notebook_and_team_changes_are_measured(engine):
    # This test's independently committed invented rows remain in the dedicated
    # rehearsal DB: the fingerprint must observe real committed history.
    with Session(engine) as session:
        seed = services.provision_box(services.Container(session), "Invented restore " + str(uuid4()))
        box, owner = seed["box_id"], seed["owner_id"]
        visit = encounter(session, box, owner)
        note = workspace.create(session, box, owner, visit.id, "restore-create")
        team = provider_team.save(session, box, owner, expected=0, key="restore-team",
                                  configuration=provider_team.default_configuration())
        before = snapshot(engine)
        workspace.append(session, box, owner, note["id"], expected=1, key="restore-notebook",
                         kind="scratchpad", content="Private invented restore sentinel")
        config = team["configuration"]
        config["practice_context"] = "Private invented team sentinel"
        provider_team.save(session, box, owner, expected=1, key="restore-team-change", configuration=config)
    after = snapshot(engine)
    assert after.tables["workspace_entries"] != before.tables["workspace_entries"]
    assert after.tables["provider_team_revisions"] != before.tables["provider_team_revisions"]
    assert after.catalog == before.catalog
    assert "sentinel" not in after.sanitized_json()
    assert owner not in after.sanitized_json() and box not in after.sanitized_json()


@pytest.mark.parametrize(("change", "undo", "section"), [
    ("ALTER TABLE workspace_entries DISABLE TRIGGER workspace_entries_immutable",
     "ALTER TABLE workspace_entries ENABLE TRIGGER workspace_entries_immutable", "triggers"),
    ("GRANT SELECT ON workspace_entries TO PUBLIC", "REVOKE SELECT ON workspace_entries FROM PUBLIC", "table_access"),
    ("ALTER TABLE work_handoffs DROP CONSTRAINT ck_work_handoff_version, ADD CONSTRAINT ck_work_handoff_version CHECK (sequence >= 0 AND sequence <= 201 AND expected_version > 0)",
     "ALTER TABLE work_handoffs DROP CONSTRAINT ck_work_handoff_version, ADD CONSTRAINT ck_work_handoff_version CHECK (sequence >= 1 AND sequence <= 201 AND expected_version > 0)", "constraints"),
])
def test_restore_verification_detects_changed_immutability_and_access(engine, change, undo, section):
    before = snapshot(engine)
    try:
        with engine.begin() as connection:
            connection.execute(text(change))
        after = snapshot(engine)
        assert after.tables == before.tables
        assert after.catalog[section] != before.catalog[section]
        assert after.aggregate_sha256 != before.aggregate_sha256
    finally:
        with engine.begin() as connection:
            connection.execute(text(undo))
    assert snapshot(engine) == before


@pytest.mark.parametrize(("change", "undo"), [
    ("ALTER TABLE routine_runs RENAME TO w18_missing_routine_runs",
     "ALTER TABLE w18_missing_routine_runs RENAME TO routine_runs"),
    ("CREATE VIEW w18_unexpected_view AS SELECT 1 AS invented", "DROP VIEW w18_unexpected_view"),
])
def test_incomplete_or_unexpected_schema_is_not_attested(engine, change, undo):
    try:
        with engine.begin() as connection:
            connection.execute(text(change))
        with pytest.raises(DatabaseFingerprintError, match="database fingerprint failed"):
            snapshot(engine)
    finally:
        with engine.begin() as connection:
            connection.execute(text(undo))


def test_connection_timezone_does_not_change_the_same_snapshot(engine):
    other = create_engine(os.environ["DATABASE_URL"], connect_args={"options": "-c timezone=Pacific/Honolulu"})
    try:
        assert snapshot(other) == snapshot(engine)
    finally:
        other.dispose()


@pytest.mark.parametrize("url", ["", "sqlite:///:memory:",
    "postgresql+psycopg://invented:secret@localhost/cosmas_os",
    "postgresql+psycopg://invented:secret@database.invalid/wrong?sslmode=verify-full&sslrootcert=system",
])
def test_unsafe_source_is_rejected_before_connect(url, monkeypatch):
    from cosmas_os.application import workspace_fingerprint as module
    monkeypatch.setattr(module, "_make_database_engine", lambda _: pytest.fail("must not connect"))
    with pytest.raises(DatabaseFingerprintError):
        fingerprint_workspace_database(url, cosmas_env="early_adopter_beta", data_mode="synthetic")


@pytest.mark.parametrize("arguments", [[], ["--confirm-synthetic-only"], ["--confirm-read-only"]])
def test_cli_requires_explicit_read_only_synthetic_scope(arguments, monkeypatch):
    from cosmas_os.application import workspace_fingerprint as module
    monkeypatch.setattr(module, "fingerprint_workspace_database", lambda *a, **k: pytest.fail("must not connect"))
    result = CliRunner().invoke(app, ["fingerprint-workspace-database", *arguments])
    assert result.exit_code == 1
    assert json.loads(result.output) == {"contract": WORKSPACE_FINGERPRINT_CONTRACT, "status": "failed"}
