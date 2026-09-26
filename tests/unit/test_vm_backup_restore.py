"""Synthetic in-memory restore contracts; no database, cloud, or process execution."""

from __future__ import annotations

import hashlib
import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

from cosmas_os.application.workspace_fingerprint import _CATALOG_QUERIES

BACKUP_DIRECTORY = Path(__file__).resolve().parents[2] / "infra/beta/vm/backup"


def load_module(name, filename):
    specification = importlib.util.spec_from_file_location(name, BACKUP_DIRECTORY / filename)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


restore = load_module("cosmas_vm_restore_test", "restore.py")
backup = restore.backup
proof = load_module("cosmas_vm_workspace_proof_test", "workspace_proof.py")

SYSTEM_IDENTIFIER = "1234567890123456789"
TARGET_START = "0/5000100"
REPLAY_END = "0/5000170"
CONTROL = f"""pg_control version number:            1300
Database system identifier:           {SYSTEM_IDENTIFIER}
Latest checkpoint location:           0/4000028
wal_level setting:                    replica
max_connections setting:              40
max_worker_processes setting:         8
max_wal_senders setting:              10
max_prepared_xacts setting:           0
max_locks_per_xact setting:           96
"""


@pytest.fixture
def configuration():
    return {
        "version": 1,
        "mode": "restore",
        "generation": "synthetic-restore",
        "system_identifier": SYSTEM_IDENTIFIER,
        "timeline": 1,
        "storage_account": "syntheticrestore",
        "storage_private_ip": "10.10.10.10",
        "tenant_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "client_id": "aaaaaaaa-bbbb-4ccc-8ddd-ffffffffffff",
        "postgres_ca_sha256": "a" * 64,
        "restore_id": "synthetic-target",
        "receipt_sha256": "b" * 64,
        "target_lsn": TARGET_START,
        "restore_certificate_sha256": "c" * 64,
    }


def test_recovery_configuration_preserves_all_source_control_floors(configuration):
    settings = restore.recovery_settings(CONTROL, SYSTEM_IDENTIFIER)
    assert settings == {
        "max_connections": 40,
        "max_worker_processes": 8,
        "max_wal_senders": 10,
        "max_prepared_transactions": 0,
        "max_locks_per_transaction": 96,
    }
    rendered = restore.recovery_configuration(
        backup.validate_config(configuration), Path("/run/credentials/synthetic"), settings
    )
    lines = rendered.splitlines()
    for name, value in settings.items():
        assert lines.count(f"{name} = {value}") == 1
    assert f"recovery_target_lsn = '{TARGET_START}'" in lines
    assert "recovery_target_inclusive = on" in lines
    assert "recovery_target_action = pause" in lines
    assert "hot_standby = on" in lines
    assert "default_transaction_read_only = on" in lines
    assert "primary_conninfo = ''" in lines
    assert "archive_mode = off" in lines


@pytest.mark.parametrize(
    "control",
    [
        pytest.param(
            CONTROL.replace("max_wal_senders setting:              10\n", ""), id="missing"
        ),
        pytest.param(CONTROL + "max_wal_senders setting: 3\n", id="duplicate"),
        pytest.param(
            CONTROL.replace(SYSTEM_IDENTIFIER, "2234567890123456789"), id="foreign-cluster"
        ),
        pytest.param(CONTROL.replace("replica", "minimal"), id="minimal-wal"),
    ],
)
def test_recovery_settings_refuse_unusable_control_data(control):
    with pytest.raises(backup.Refused):
        restore.recovery_settings(control, SYSTEM_IDENTIFIER)


def resign_fingerprint(fingerprint, *, recompute_aggregate=True):
    if recompute_aggregate:
        aggregate = {
            key: fingerprint[key] for key in ("schema_revision", "tables", "catalog")
        }
        fingerprint["aggregate_sha256"] = hashlib.sha256(proof.canonical(aggregate)).hexdigest()
    body = {key: value for key, value in fingerprint.items() if key != "evidence_sha256"}
    fingerprint["evidence_sha256"] = hashlib.sha256(proof.canonical(body)).hexdigest()


@pytest.fixture
def snapshots():
    # Keep the real complete metadata inventory, with invented empty-table digests.
    tables = {
        name: {"count": 0, "sha256": hashlib.sha256(name.encode()).hexdigest()}
        for name in sorted(proof.metadata.tables)
    }
    fingerprint = {
        "contract": proof.WORKSPACE_FINGERPRINT_CONTRACT,
        "status": "snapshot_ready",
        "schema_revision": proof.EXPECTED_SCHEMA_REVISION,
        "tables": tables,
        "catalog": {
            name: {"count": 0, "sha256": hashlib.sha256(name.encode()).hexdigest()}
            for name in sorted(_CATALOG_QUERIES)
        },
    }
    resign_fingerprint(fingerprint)
    source = {
        "contract": proof.CONTRACT,
        "status": "measured",
        "database_state": {
            "username": "cosmas",
            "session_username": "cosmas",
            "rolsuper": False,
            "rolcreatedb": False,
            "rolcreaterole": False,
            "rolreplication": False,
            "rolbypassrls": False,
            "memberships": False,
            "read_only": "on",
            "recovery": False,
            "paused": None,
            "replay_lsn": None,
            "target_lsn": None,
        },
        "fingerprint": fingerprint,
    }
    restored = deepcopy(source)
    restored["database_state"].update(
        recovery=True, paused="paused", replay_lsn=REPLAY_END, target_lsn=TARGET_START
    )
    return source, restored


def test_compare_accepts_complete_snapshot_at_target_record_end(snapshots):
    source, restored = snapshots
    result = proof.compare(source, restored, target_lsn=TARGET_START, replay_lsn=REPLAY_END)
    assert TARGET_START != REPLAY_END
    assert result["status"] == "workspace_restored_at_verified_record"
    assert result["table_count"] == len(proof.metadata.tables)
    assert result["target_lsn"] == TARGET_START
    assert result["replay_lsn"] == REPLAY_END
    assert result["fingerprint_compared"] is True
    assert result["nonadmin_login_verified"] is True
    assert result["read_only_measurements"] is True
    assert result["application_activated"] is False
    assert result["external_state_reconciled"] is False
    assert result["source_sha256"] == hashlib.sha256(proof.canonical(source)).hexdigest()
    assert result["restored_sha256"] == hashlib.sha256(proof.canonical(restored)).hexdigest()


@pytest.mark.parametrize(
    ("side", "field", "value"),
    [
        pytest.param(0, "rolsuper", True, id="privileged-source"),
        pytest.param(1, "memberships", True, id="restored-role-membership"),
        pytest.param(1, "read_only", "off", id="read-write"),
        pytest.param(1, "paused", "pause requested", id="not-yet-paused"),
        pytest.param(1, "target_lsn", "0/5000080", id="wrong-target"),
        pytest.param(1, "replay_lsn", "0/5000180", id="wrong-record-end"),
    ],
)
def test_compare_refuses_unsafe_or_wrong_recovery_state(snapshots, side, field, value):
    snapshots[side]["database_state"][field] = value
    with pytest.raises(ValueError, match="workspace restore proof refused"):
        proof.compare(*snapshots, target_lsn=TARGET_START, replay_lsn=REPLAY_END)


def test_compare_refuses_matching_but_incomplete_inventory(snapshots):
    source, restored = snapshots
    missing_table = next(iter(source["fingerprint"]["tables"]))
    for snapshot in (source, restored):
        del snapshot["fingerprint"]["tables"][missing_table]
        resign_fingerprint(snapshot["fingerprint"])
    assert source["fingerprint"] == restored["fingerprint"]
    with pytest.raises(ValueError, match="workspace restore proof refused"):
        proof.compare(source, restored, target_lsn=TARGET_START, replay_lsn=REPLAY_END)


def test_compare_refuses_matching_snapshots_with_tampered_evidence(snapshots):
    source, restored = snapshots
    for snapshot in (source, restored):
        snapshot["fingerprint"]["evidence_sha256"] = "0" * 64
    assert source["fingerprint"] == restored["fingerprint"]
    with pytest.raises(ValueError, match="workspace restore proof refused"):
        proof.compare(source, restored, target_lsn=TARGET_START, replay_lsn=REPLAY_END)


def test_compare_refuses_matching_missing_catalog_with_valid_hashes(snapshots):
    source, restored = snapshots
    for snapshot in (source, restored):
        del snapshot["fingerprint"]["catalog"]["table_access"]
        resign_fingerprint(snapshot["fingerprint"])
    assert source["fingerprint"] == restored["fingerprint"]
    with pytest.raises(ValueError, match="workspace restore proof refused"):
        proof.compare(source, restored, target_lsn=TARGET_START, replay_lsn=REPLAY_END)


def test_compare_refuses_matching_invalid_aggregate_with_valid_outer_hashes(snapshots):
    source, restored = snapshots
    for snapshot in (source, restored):
        snapshot["fingerprint"]["aggregate_sha256"] = "0" * 64
        resign_fingerprint(snapshot["fingerprint"], recompute_aggregate=False)
    assert source["fingerprint"] == restored["fingerprint"]
    with pytest.raises(ValueError, match="workspace restore proof refused"):
        proof.compare(source, restored, target_lsn=TARGET_START, replay_lsn=REPLAY_END)


def test_compare_refuses_matching_unknown_fingerprint_fields(snapshots):
    source, restored = snapshots
    for snapshot in (source, restored):
        snapshot["fingerprint"]["unreviewed_field"] = "synthetic"
        resign_fingerprint(snapshot["fingerprint"])
    assert source["fingerprint"] == restored["fingerprint"]
    with pytest.raises(ValueError, match="workspace restore proof refused"):
        proof.compare(source, restored, target_lsn=TARGET_START, replay_lsn=REPLAY_END)


def test_compare_refuses_different_data_even_with_valid_evidence_hash(snapshots):
    source, restored = snapshots
    table = next(iter(restored["fingerprint"]["tables"].values()))
    table["count"] = 1
    resign_fingerprint(restored["fingerprint"])
    with pytest.raises(ValueError, match="workspace restore proof refused"):
        proof.compare(source, restored, target_lsn=TARGET_START, replay_lsn=REPLAY_END)


@pytest.mark.parametrize(
    "override",
    [
        pytest.param({"storage_prefix": "file:///tmp/synthetic-backups"}, id="file-prefix"),
        pytest.param({"storage_account": "file:///tmp/synthetic-backups"}, id="file-account"),
        pytest.param({"mode": "local"}, id="local-mode"),
    ],
)
def test_runtime_configuration_cannot_select_local_storage(configuration, override):
    configuration.update(override)
    with pytest.raises(backup.Refused):
        backup.validate_config(configuration)


@pytest.mark.parametrize("mode", ["backup", "restore"])
def test_clean_runtime_environment_pins_azure_storage(configuration, monkeypatch, mode):
    configuration["mode"] = mode
    if mode == "backup":
        for name in backup.RESTORE_KEYS:
            del configuration[name]
    monkeypatch.setattr(backup.os, "environ", {"UNRELATED_SETTING": "ignored"})
    environment = backup.clean_environment(
        backup.validate_config(configuration), Path("/run/credentials/synthetic")
    )
    assert environment["WALG_AZ_PREFIX"] == (
        "azure://postgres-backups/cosmabot/synthetic-restore/" + SYSTEM_IDENTIFIER
    )
    assert environment["AZURE_STORAGE_ACCOUNT"] == "syntheticrestore"
    assert environment["AZURE_TOKEN_CREDENTIALS"] == "EnvironmentCredential"
    assert "WALG_FILE_PREFIX" not in environment
    assert "UNRELATED_SETTING" not in environment


@pytest.mark.parametrize(
    "ambient",
    [
        pytest.param({"WALG_FILE_PREFIX": "/tmp/synthetic-backups"}, id="file-environment"),
        pytest.param({"WALG_AZ_PREFIX": "file:///tmp/synthetic-backups"}, id="prefix-override"),
        pytest.param({"WALG_CONFIG_FILE": "/tmp/synthetic-walg.json"}, id="config-override"),
    ],
)
def test_clean_runtime_environment_refuses_storage_overrides(configuration, monkeypatch, ambient):
    monkeypatch.setattr(backup.os, "environ", ambient)
    with pytest.raises(backup.Refused, match="ambient credential/config override"):
        backup.clean_environment(configuration, Path("/run/credentials/synthetic"))
