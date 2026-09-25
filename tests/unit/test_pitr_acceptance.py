from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "beta" / "pitr_acceptance.py"
_SPEC = importlib.util.spec_from_file_location("cosmas_pitr_acceptance", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
pitr = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = pitr
_SPEC.loader.exec_module(pitr)

SUBSCRIPTION_ID = "00000000-0000-4000-8000-000000000001"
BOX_ID = "00000000-0000-4000-8000-000000000004"
RESOURCE_GROUP = "rg-cosmas-os-beta-lab01"
SOURCE_NAME = "pg-cosmas-beta-lab01-abc123"
SOURCE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/providers/"
    f"Microsoft.DBforPostgreSQL/flexibleServers/{SOURCE_NAME}"
)
SOURCE_FQDN = f"{SOURCE_NAME}.postgres.database.azure.com"
SUBNET_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/providers/"
    "Microsoft.Network/virtualNetworks/vnet-cosmas-beta-lab01/subnets/snet-postgres"
)
DNS_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/providers/"
    "Microsoft.Network/privateDnsZones/cosmas-beta.postgres.database.azure.com"
)
SOURCE_SHA = "a" * 40
API_DIGEST = "b" * 64
WEB_DIGEST = "c" * 64
IMAGE = f"registry.example.invalid/cosmas-os@sha256:{API_DIGEST}"
NOW = datetime(2026, 9, 3, 17, 0, tzinfo=UTC)


class FakeRunner:
    def __init__(
        self,
        handler: Callable[[list[str]], Any],
        *,
        platform_isolated: bool = True,
    ) -> None:
        self.handler = handler
        self.platform_isolated = platform_isolated
        self.calls: list[list[str]] = []
        self.request_bodies: list[dict[str, Any]] = []
        self.database_envs: list[str] = []

    def run(self, argv: Sequence[str]) -> Any:
        command = list(argv)
        self.calls.append(command)
        if command[0] == "iptables":
            return pitr.CommandResult(0 if self.platform_isolated else 1)
        if command[0] == "docker" and "-c" in command:
            return pitr.CommandResult(
                0 if self.platform_isolated else 1,
                "isolated\n" if self.platform_isolated else "",
            )
        if "--body" in command:
            body_value = command[command.index("--body") + 1]
            assert body_value.startswith("@")
            self.request_bodies.append(json.loads(Path(body_value[1:]).read_text(encoding="utf-8")))
        if "--env-file" in command:
            env_path = Path(command[command.index("--env-file") + 1])
            self.database_envs.append(env_path.read_text(encoding="utf-8"))
        return self.handler(command)


def _environment(tmp_path: Path, operation: str = "manifest") -> dict[str, str]:
    tmp_path.chmod(0o700)
    return {
        "COSMAS_PITR_OPERATION": operation,
        "COSMAS_PITR_SUBSCRIPTION_ID": SUBSCRIPTION_ID,
        "COSMAS_PITR_RESOURCE_GROUP": RESOURCE_GROUP,
        "COSMAS_PITR_LOCATION": "eastus2",
        "COSMAS_PITR_SOURCE_SERVER_ID": SOURCE_ID,
        "COSMAS_PITR_SOURCE_FQDN": SOURCE_FQDN,
        "COSMAS_PITR_POSTGRES_SUBNET_ID": SUBNET_ID,
        "COSMAS_PITR_PRIVATE_DNS_ZONE_ID": DNS_ID,
        "COSMAS_PITR_SOURCE_SHA": SOURCE_SHA,
        "COSMAS_PITR_RELEASE_ID": "release-001",
        "COSMAS_PITR_API_IMAGE_DIGEST": API_DIGEST,
        "COSMAS_PITR_WEB_IMAGE_DIGEST": WEB_DIGEST,
        "COSMAS_PITR_FINGERPRINT_IMAGE": IMAGE,
        "COSMAS_PITR_BOX_ID": BOX_ID,
        "COSMAS_PITR_QUIET_WINDOW_START_UTC": "2026-09-03T15:55:00Z",
        "COSMAS_PITR_QUIET_WINDOW_END_UTC": "2026-09-03T18:30:00Z",
        "COSMAS_PITR_WRITE_FREEZE_EVIDENCE_SHA256": "e" * 64,
        "COSMAS_PITR_MANIFEST_PATH": str(tmp_path / "manifest.json"),
        "COSMAS_PITR_RESTORE_TIME_UTC": "2026-09-03T16:00:00Z",
        "COSMAS_PITR_POLL_ATTEMPTS": "1",
        "COSMAS_PITR_POLL_INTERVAL_SECONDS": "0",
    }


def _source() -> dict[str, Any]:
    return {
        "id": SOURCE_ID,
        "name": SOURCE_NAME,
        "location": "eastus2",
        "tags": {
            "track": "B",
            "product": "cosmas-os",
            "env": "early_adopter_beta",
            "deployment_mode": "synthetic_lab",
            "data_classification": "synthetic-only",
            "box_scope": "dedicated",
            "box_id": BOX_ID,
            "managed": "terraform",
        },
        "properties": {
            "fullyQualifiedDomainName": SOURCE_FQDN,
            "state": "Ready",
            "version": "16",
            "network": {
                "publicNetworkAccess": "Disabled",
                "delegatedSubnetResourceId": SUBNET_ID,
                "privateDnsZoneArmResourceId": DNS_ID,
            },
            "backup": {"earliestRestoreDate": "2026-08-28T00:00:00.123456Z"},
        },
    }


def _not_found() -> Any:
    return pitr.CommandResult(
        3,
        stderr=(
            'ERROR: Not Found({"error":{"code":"ResourceNotFound",'
            '"message":"invented target absent"}})'
        ),
    )


def _fingerprint(seed: str = "d") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract": pitr.FINGERPRINT_CONTRACT,
        "status": "ready",
        "schema_revision": "0002_external_identities",
        "schema_at_expected_head": True,
        "structures": {"box_contexts": {"count": 1, "sha256": seed * 64}},
        "aggregate_sha256": seed * 64,
    }
    payload["evidence_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload


def _assert_evidence_self_hash(evidence: dict[str, Any]) -> None:
    payload = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    assert (
        evidence["evidence_sha256"]
        == hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def _manifest_runner() -> FakeRunner:
    def handle(command: list[str]) -> Any:
        url = command[command.index("--url") + 1]
        if SOURCE_ID in url:
            return pitr.CommandResult(0, json.dumps(_source()))
        return _not_found()

    return FakeRunner(handle)


def _create_manifest(tmp_path: Path) -> tuple[dict[str, str], Any, dict[str, Any]]:
    environment = _environment(tmp_path)
    config = pitr.Config.from_environment(environment)
    pitr.create_manifest(config, _manifest_runner(), now=NOW, nonce="123456789abc")
    manifest = json.loads(config.manifest_path.read_text(encoding="utf-8"))
    return environment, config, manifest


def _approved_environment(
    tmp_path: Path,
    operation: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    environment, _, manifest = _create_manifest(tmp_path)
    database_url_file = tmp_path / "database-url"
    database_url_file.write_text(
        f"postgresql+psycopg://runtime:invented-password@{SOURCE_FQDN}:5432/"
        "cosmas_os?sslmode=verify-full&sslrootcert=system\n",
        encoding="utf-8",
    )
    database_url_file.chmod(0o600)
    environment.update(
        {
            "COSMAS_PITR_OPERATION": operation,
            "COSMAS_PITR_STATE_PATH": str(tmp_path / "state.json"),
            "COSMAS_PITR_DATABASE_URL_FILE": str(database_url_file),
            "COSMAS_PITR_APPROVED_MANIFEST_SHA256": manifest["manifest_sha256"],
        }
    )
    return environment, manifest


def _target(manifest: dict[str, Any], *, state: str = "Ready") -> dict[str, Any]:
    target_name = manifest["restore"]["target_name"]
    return {
        "id": manifest["restore"]["target_resource_id"],
        "name": target_name,
        "location": "eastus2",
        "tags": {
            "track": "B",
            "product": "cosmas-os",
            "env": "early_adopter_beta",
            "deployment_mode": "synthetic_lab",
            "data_classification": "synthetic-only",
            "box_scope": "dedicated",
            "box_id": BOX_ID,
            "managed": "pitr-acceptance",
            "pitr_manifest_sha256": manifest["manifest_sha256"],
            "pitr_source_id_sha256": hashlib.sha256(SOURCE_ID.lower().encode()).hexdigest(),
        },
        "properties": {
            "fullyQualifiedDomainName": f"{target_name}.postgres.database.azure.com",
            "state": state,
            "version": "16",
            "network": {
                "publicNetworkAccess": "Disabled",
                "delegatedSubnetResourceId": SUBNET_ID,
                "privateDnsZoneArmResourceId": DNS_ID,
            },
        },
    }


def test_manifest_binds_exact_live_source_and_emits_only_sanitized_evidence(tmp_path) -> None:
    config = pitr.Config.from_environment(_environment(tmp_path))
    runner = _manifest_runner()

    evidence = pitr.create_manifest(config, runner, now=NOW, nonce="123456789abc")
    manifest = json.loads(config.manifest_path.read_text(encoding="utf-8"))
    serialized_evidence = json.dumps(evidence, sort_keys=True)

    assert stat.S_IMODE(config.manifest_path.stat().st_mode) == 0o400
    assert manifest["binding"]["source_server_id"] == SOURCE_ID
    assert manifest["binding"]["source_fqdn"] == SOURCE_FQDN
    assert manifest["binding"]["postgres_subnet_id"] == SUBNET_ID
    assert manifest["binding"]["private_dns_zone_id"] == DNS_ID
    assert manifest["binding"]["quiet_window_start_utc"] == "2026-09-03T15:55:00Z"
    assert manifest["binding"]["quiet_window_end_utc"] == "2026-09-03T18:30:00Z"
    assert manifest["binding"]["write_freeze_evidence_sha256"] == "e" * 64
    assert manifest["restore"]["point_in_time_utc"] == "2026-09-03T16:00:00Z"
    assert manifest["restore"]["delete_target_after_verification"] is True
    manifest_hash = manifest.pop("manifest_sha256")
    assert manifest_hash == pitr._sha256_json(manifest)
    assert evidence["manifest_sha256"] == manifest_hash
    assert evidence["source_binding_verified"] is True
    assert evidence["source_quiet_window_bound"] is True
    assert evidence["target_absence_verified"] is True
    _assert_evidence_self_hash(evidence)
    for forbidden in (SOURCE_ID, SOURCE_FQDN, SUBNET_ID, DNS_ID, BOX_ID):
        assert forbidden not in serialized_evidence
    assert [call[3] for call in runner.calls] == ["get", "get"]


@pytest.mark.parametrize(
    "restore_time",
    [
        "2026-08-20T00:00:00Z",
        "2026-09-03T15:50:00Z",
        "2026-09-03T16:59:00Z",
        "not-a-time",
    ],
)
def test_manifest_rejects_restore_time_outside_explicit_safe_window(
    tmp_path,
    restore_time: str,
) -> None:
    environment = _environment(tmp_path)
    environment["COSMAS_PITR_RESTORE_TIME_UTC"] = restore_time
    if restore_time == "not-a-time":
        with pytest.raises(pitr.PitrError):
            pitr.Config.from_environment(environment)
        return
    config = pitr.Config.from_environment(environment)
    with pytest.raises(pitr.PitrError):
        pitr.create_manifest(config, _manifest_runner(), now=NOW, nonce="123456789abc")
    assert not config.manifest_path.exists()


def test_start_requires_exact_approved_hash_before_fingerprint_or_create(tmp_path) -> None:
    environment, _ = _approved_environment(tmp_path, "start")
    environment["COSMAS_PITR_APPROVED_MANIFEST_SHA256"] = "f" * 64
    config = pitr.Config.from_environment(environment)
    runner = FakeRunner(lambda _command: pytest.fail("Azure/Docker must not run"))

    with pytest.raises(pitr.PitrError, match="approved manifest hash mismatch"):
        pitr.start_restore(config, runner, now=NOW + timedelta(minutes=1))

    assert runner.calls == []


def test_start_builds_atomic_private_restore_request_and_hides_database_url(tmp_path) -> None:
    environment, manifest = _approved_environment(tmp_path, "start")
    config = pitr.Config.from_environment(environment)
    target_id = manifest["restore"]["target_resource_id"]

    def handle(command: list[str]) -> Any:
        if command[0] == "docker":
            return pitr.CommandResult(0, json.dumps(_fingerprint()) + "\n")
        method = command[command.index("--method") + 1]
        url = command[command.index("--url") + 1]
        if method == "get" and SOURCE_ID in url:
            return pitr.CommandResult(0, json.dumps(_source()))
        if method == "get" and target_id in url:
            return _not_found()
        if method == "put" and target_id in url:
            return pitr.CommandResult(0)
        return pitr.CommandResult(2, stderr="unexpected")

    runner = FakeRunner(handle)
    evidence = pitr.start_restore(config, runner, now=NOW + timedelta(minutes=1))

    assert evidence["status"] == "restore_started"
    _assert_evidence_self_hash(evidence)
    assert stat.S_IMODE(Path(environment["COSMAS_PITR_STATE_PATH"]).stat().st_mode) == 0o600
    assert len(runner.request_bodies) == 1
    request = runner.request_bodies[0]
    assert request["location"] == "eastus2"
    assert request["tags"] == pitr._restore_tags(config, manifest["manifest_sha256"])
    assert request["properties"] == {
        "createMode": "PointInTimeRestore",
        "sourceServerResourceId": SOURCE_ID,
        "pointInTimeUTC": "2026-09-03T16:00:00Z",
        "network": {
            "delegatedSubnetResourceId": SUBNET_ID,
            "privateDnsZoneArmResourceId": DNS_ID,
            "publicNetworkAccess": "Disabled",
        },
    }
    flattened_commands = json.dumps(runner.calls)
    assert "invented-password" not in flattened_commands
    assert all("--pull" in call and "never" in call for call in runner.calls if call[0] == "docker")
    isolation_rules = [call for call in runner.calls if call[0] == "iptables"]
    assert isolation_rules == [
        ["iptables", "-C", "DOCKER-USER", "-d", "169.254.169.254/32", "-j", "REJECT"],
        ["iptables", "-C", "DOCKER-USER", "-d", "168.63.129.16/32", "-j", "REJECT"],
    ]
    isolation_probes = [call for call in runner.calls if call[0] == "docker" and "-c" in call]
    assert len(isolation_probes) == 1
    assert "169.254.169.254" in isolation_probes[0][-1]
    assert "168.63.129.16" in isolation_probes[0][-1]
    fingerprint_calls = [
        call for call in runner.calls if call[0] == "docker" and "fingerprint-beta-database" in call
    ]
    assert len(fingerprint_calls) == 1
    assert fingerprint_calls[0][fingerprint_calls[0].index("--user") + 1] == "10001:10001"
    assert runner.database_envs == [
        "COSMAS_ENV=early_adopter_beta\n"
        "DATA_MODE=synthetic\n"
        f"DATABASE_URL=postgresql+psycopg://runtime:invented-password@{SOURCE_FQDN}:5432/"
        "cosmas_os?sslmode=verify-full&sslrootcert=system\n"
    ]
    assert list(tmp_path.glob(".pitr-request.*")) == []
    assert list(tmp_path.glob(".pitr-db-env.*")) == []
    for forbidden in (SOURCE_ID, SOURCE_FQDN, SUBNET_ID, DNS_ID, BOX_ID, "invented-password"):
        assert forbidden not in json.dumps(evidence)


def test_start_refuses_missing_docker_platform_deny_before_restore_create(tmp_path) -> None:
    environment, manifest = _approved_environment(tmp_path, "start")
    config = pitr.Config.from_environment(environment)
    target_id = manifest["restore"]["target_resource_id"]

    def handle(command: list[str]) -> Any:
        method = command[command.index("--method") + 1]
        url = command[command.index("--url") + 1]
        if method == "get" and SOURCE_ID in url:
            return pitr.CommandResult(0, json.dumps(_source()))
        if method == "get" and target_id in url:
            return _not_found()
        return pytest.fail("restore must not be created without platform isolation")

    runner = FakeRunner(handle, platform_isolated=False)
    with pytest.raises(pitr.PitrError, match="platform isolation is not active"):
        pitr.start_restore(config, runner, now=NOW + timedelta(minutes=1))
    assert not any(
        call[0] == "az" and call[call.index("--method") + 1] == "put" for call in runner.calls
    )
    assert runner.database_envs == []


def test_start_requires_active_owner_approved_source_quiet_window(tmp_path) -> None:
    environment, _ = _approved_environment(tmp_path, "start")
    config = pitr.Config.from_environment(environment)
    runner = FakeRunner(lambda _command: pytest.fail("quiet-window failure must precede commands"))

    with pytest.raises(pitr.PitrError, match="quiet window is too close to expiry"):
        pitr.start_restore(config, runner, now=datetime(2026, 9, 3, 18, 20, tzinfo=UTC))
    assert runner.calls == []


def test_quiet_window_end_is_exclusive(tmp_path) -> None:
    config = pitr.Config.from_environment(_environment(tmp_path))
    with pytest.raises(pitr.PitrError, match="quiet window is not active"):
        pitr._assert_quiet_window(
            config,
            datetime(2026, 9, 3, 18, 30, tzinfo=UTC),
            require_remaining=False,
        )


def test_approved_manifest_expiry_is_exclusive(tmp_path) -> None:
    environment, manifest = _approved_environment(tmp_path, "start")
    config = pitr.Config.from_environment(environment)
    expires_at = datetime.fromisoformat(str(manifest["expires_at"]).replace("Z", "+00:00"))
    with pytest.raises(pitr.PitrError, match="approved manifest expired"):
        pitr._read_approved_manifest(config, expires_at, require_unexpired=True)


def _started_restore(
    tmp_path: Path,
) -> tuple[dict[str, str], dict[str, Any]]:
    environment, manifest = _approved_environment(tmp_path, "start")
    target_id = manifest["restore"]["target_resource_id"]

    def handle(command: list[str]) -> Any:
        if command[0] == "docker":
            return pitr.CommandResult(0, json.dumps(_fingerprint()) + "\n")
        method = command[command.index("--method") + 1]
        url = command[command.index("--url") + 1]
        if method == "get" and SOURCE_ID in url:
            return pitr.CommandResult(0, json.dumps(_source()))
        if method == "get" and target_id in url:
            return _not_found()
        if method == "put":
            return pitr.CommandResult(0)
        raise AssertionError(command)

    pitr.start_restore(
        pitr.Config.from_environment(environment),
        FakeRunner(handle),
        now=NOW + timedelta(minutes=1),
    )
    environment["COSMAS_PITR_OPERATION"] = "complete"
    return environment, manifest


@pytest.mark.parametrize(
    ("phase", "target_exists"),
    [("restore_started", True), ("restore_started", False), ("f1_captured", True)],
)
def test_start_rejects_missing_historical_timestamp_without_mutation(
    tmp_path, phase: str, target_exists: bool,
) -> None:
    environment, manifest = _started_restore(tmp_path)
    environment["COSMAS_PITR_OPERATION"] = "start"
    config = pitr.Config.from_environment(environment)
    state_path = Path(environment["COSMAS_PITR_STATE_PATH"])
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["phase"] = phase
    state.pop("restore_started_at_utc")
    state.pop("restore_ready_at_utc")
    pitr._save_state(config, state)
    original_state = state_path.read_bytes()
    target_id = manifest["restore"]["target_resource_id"]

    def handle(command: list[str]) -> Any:
        if command[0:4] == ["az", "rest", "--method", "get"]:
            url = command[command.index("--url") + 1]
            if SOURCE_ID in url:
                return pitr.CommandResult(0, json.dumps(_source()))
            if target_id in url:
                return (
                    pitr.CommandResult(0, json.dumps(_target(manifest)))
                    if target_exists else _not_found()
                )
        return pytest.fail("historical timestamp failure must not create, delete, or fingerprint")

    runner = FakeRunner(handle)
    with pytest.raises(pitr.PitrError, match="restore start timestamp missing"):
        pitr.start_restore(config, runner, now=NOW + timedelta(minutes=2))

    assert state_path.read_bytes() == original_state
    assert all(call[0:4] == ["az", "rest", "--method", "get"] for call in runner.calls)


def test_start_retry_preserves_original_timestamp(tmp_path) -> None:
    environment, manifest = _started_restore(tmp_path)
    environment["COSMAS_PITR_OPERATION"] = "start"
    config = pitr.Config.from_environment(environment)
    state_path = Path(environment["COSMAS_PITR_STATE_PATH"])
    original_state = state_path.read_bytes()
    target_id = manifest["restore"]["target_resource_id"]

    def handle(command: list[str]) -> Any:
        if command[0:4] == ["az", "rest", "--method", "get"]:
            url = command[command.index("--url") + 1]
            if SOURCE_ID in url:
                return pitr.CommandResult(0, json.dumps(_source()))
            if target_id in url:
                return pitr.CommandResult(0, json.dumps(_target(manifest, state="Creating")))
        return pytest.fail("an existing restore must not be recreated, deleted, or fingerprinted")

    runner = FakeRunner(handle)
    evidence = pitr.start_restore(config, runner, now=NOW + timedelta(minutes=2))

    assert evidence["status"] == "restore_started"
    assert state_path.read_bytes() == original_state
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["restore_started_at_utc"] == "2026-09-03T17:01:00Z"
    assert all(call[0:4] == ["az", "rest", "--method", "get"] for call in runner.calls)


def test_complete_proves_f1_f2_f3_deletes_exact_target_then_proves_f4(tmp_path) -> None:
    environment, manifest = _started_restore(tmp_path)
    config = pitr.Config.from_environment(environment)
    target_id = manifest["restore"]["target_resource_id"]
    target_exists = True

    def handle(command: list[str]) -> Any:
        nonlocal target_exists
        if command[0] == "docker":
            return pitr.CommandResult(0, json.dumps(_fingerprint()) + "\n")
        method = command[command.index("--method") + 1]
        url = command[command.index("--url") + 1]
        if method == "get" and SOURCE_ID in url:
            return pitr.CommandResult(0, json.dumps(_source()))
        if method == "get" and target_id in url:
            return (
                pitr.CommandResult(0, json.dumps(_target(manifest)))
                if target_exists
                else _not_found()
            )
        if method == "delete" and target_id in url:
            target_exists = False
            return pitr.CommandResult(0)
        raise AssertionError(command)

    runner = FakeRunner(handle)
    evidence, exit_code = pitr.complete_restore(
        config,
        runner,
        now=NOW + timedelta(minutes=2),
        sleeper=lambda _seconds: None,
        clock=lambda: NOW + timedelta(minutes=2),
    )

    assert exit_code == 0
    assert evidence["status"] == "verified"
    assert evidence["f1_f2_f3_equal"] is True
    assert evidence["exact_target_deleted"] is True
    assert evidence["target_absence_404_verified"] is True
    assert evidence["f4_equals_f1"] is True
    assert evidence["measurement"] == {
        "restore_started_at_utc": "2026-09-03T17:01:00Z",
        "restore_ready_at_utc": "2026-09-03T17:02:00Z",
        "write_freeze_at_utc": "2026-09-03T15:55:00Z",
        "restore_point_utc": "2026-09-03T16:00:00Z",
        "measured_rto_seconds": 60,
        "measured_rpo_seconds": 0,
    }
    _assert_evidence_self_hash(evidence)
    delete_calls = [
        call for call in runner.calls if call[0:4] == ["az", "rest", "--method", "delete"]
    ]
    assert len(delete_calls) == 1
    assert delete_calls[0][delete_calls[0].index("--url") + 1] == pitr._arm_url(target_id)
    state = json.loads(Path(environment["COSMAS_PITR_STATE_PATH"]).read_text(encoding="utf-8"))
    assert state["phase"] == "complete"
    assert state["f1"] == state["f2"] == state["f3"] == state["f4"]
    for forbidden in (SOURCE_ID, SOURCE_FQDN, target_id, BOX_ID, "invented-password"):
        assert forbidden not in json.dumps(evidence)


def test_complete_requires_quiet_window_but_cleanup_does_not(tmp_path) -> None:
    environment, _ = _started_restore(tmp_path)
    config = pitr.Config.from_environment(environment)
    runner = FakeRunner(lambda _command: pytest.fail("expired quiet window must precede commands"))

    with pytest.raises(pitr.PitrError, match="quiet window is not active"):
        pitr.complete_restore(
            config,
            runner,
            now=datetime(2026, 9, 3, 18, 31, tzinfo=UTC),
            sleeper=lambda _seconds: None,
        )
    assert runner.calls == []


def test_complete_cleans_exact_target_but_fails_attestation_on_fingerprint_mismatch(
    tmp_path,
) -> None:
    environment, manifest = _started_restore(tmp_path)
    config = pitr.Config.from_environment(environment)
    target_id = manifest["restore"]["target_resource_id"]
    target_exists = True
    fingerprint_calls = 0

    def handle(command: list[str]) -> Any:
        nonlocal target_exists, fingerprint_calls
        if command[0] == "docker":
            fingerprint_calls += 1
            value = _fingerprint("e") if fingerprint_calls == 1 else _fingerprint()
            return pitr.CommandResult(0, json.dumps(value) + "\n")
        method = command[command.index("--method") + 1]
        url = command[command.index("--url") + 1]
        if method == "get" and SOURCE_ID in url:
            return pitr.CommandResult(0, json.dumps(_source()))
        if method == "get" and target_id in url:
            return (
                pitr.CommandResult(0, json.dumps(_target(manifest)))
                if target_exists
                else _not_found()
            )
        if method == "delete" and target_id in url:
            target_exists = False
            return pitr.CommandResult(0)
        raise AssertionError(command)

    runner = FakeRunner(handle)
    evidence, exit_code = pitr.complete_restore(
        config,
        runner,
        now=NOW + timedelta(minutes=2),
        sleeper=lambda _seconds: None,
        clock=lambda: NOW + timedelta(minutes=2),
    )

    assert exit_code == 1
    assert evidence["status"] == "failed"
    assert evidence["f1_f2_f3_equal"] is False
    assert evidence["exact_target_deleted"] is True
    assert target_exists is False


def test_complete_rto_includes_time_spent_polling_until_ready(tmp_path) -> None:
    environment, manifest = _started_restore(tmp_path)
    environment["COSMAS_PITR_POLL_ATTEMPTS"] = "3"
    environment["COSMAS_PITR_POLL_INTERVAL_SECONDS"] = "5"
    config = pitr.Config.from_environment(environment)
    target_id = manifest["restore"]["target_resource_id"]
    target_exists = True
    readiness_reads = 0
    observed_time = NOW + timedelta(minutes=2)

    def handle(command: list[str]) -> Any:
        nonlocal target_exists, readiness_reads
        if command[0] == "docker":
            return pitr.CommandResult(0, json.dumps(_fingerprint()) + "\n")
        method = command[command.index("--method") + 1]
        url = command[command.index("--url") + 1]
        if method == "get" and SOURCE_ID in url:
            return pitr.CommandResult(0, json.dumps(_source()))
        if method == "get" and target_id in url:
            if not target_exists:
                return _not_found()
            readiness_reads += 1
            state = "Creating" if readiness_reads < 3 else "Ready"
            return pitr.CommandResult(0, json.dumps(_target(manifest, state=state)))
        if method == "delete" and target_id in url:
            target_exists = False
            return pitr.CommandResult(0)
        raise AssertionError(command)

    def sleep_and_advance(seconds: float) -> None:
        nonlocal observed_time
        observed_time += timedelta(seconds=seconds)

    evidence, exit_code = pitr.complete_restore(
        config,
        FakeRunner(handle),
        now=NOW + timedelta(minutes=2),
        sleeper=sleep_and_advance,
        clock=lambda: observed_time,
    )

    assert exit_code == 0
    assert readiness_reads >= 3
    assert evidence["measurement"]["restore_started_at_utc"] == "2026-09-03T17:01:00Z"
    assert evidence["measurement"]["restore_ready_at_utc"] == "2026-09-03T17:02:10Z"
    assert evidence["measurement"]["measured_rto_seconds"] == 70


def test_complete_does_not_record_ready_time_until_a_ready_poll(tmp_path) -> None:
    environment, manifest = _started_restore(tmp_path)
    environment["COSMAS_PITR_POLL_ATTEMPTS"] = "2"
    environment["COSMAS_PITR_POLL_INTERVAL_SECONDS"] = "3"
    config = pitr.Config.from_environment(environment)
    target_id = manifest["restore"]["target_resource_id"]
    sleeps: list[float] = []

    def handle(command: list[str]) -> Any:
        method = command[command.index("--method") + 1]
        url = command[command.index("--url") + 1]
        if method == "get" and SOURCE_ID in url:
            return pitr.CommandResult(0, json.dumps(_source()))
        if method == "get" and target_id in url:
            return pitr.CommandResult(0, json.dumps(_target(manifest, state="Creating")))
        raise AssertionError(command)

    evidence, exit_code = pitr.complete_restore(
        config,
        FakeRunner(handle),
        now=NOW + timedelta(minutes=2),
        sleeper=sleeps.append,
        clock=lambda: pytest.fail("clock must only be sampled after Ready is observed"),
    )

    assert exit_code == 2
    assert evidence["status"] == "restore_pending"
    assert sleeps == [3]
    state = json.loads(Path(environment["COSMAS_PITR_STATE_PATH"]).read_text(encoding="utf-8"))
    assert state["phase"] == "restore_started"
    assert state["restore_ready_at_utc"] is None


def test_complete_persists_first_ready_observation_before_fingerprinting(tmp_path) -> None:
    environment, manifest = _started_restore(tmp_path)
    config = pitr.Config.from_environment(environment)
    target_id = manifest["restore"]["target_resource_id"]

    def handle(command: list[str]) -> Any:
        if command[0] == "docker":
            return pitr.CommandResult(1, stderr="invented fingerprint failure")
        method = command[command.index("--method") + 1]
        url = command[command.index("--url") + 1]
        if method == "get" and SOURCE_ID in url:
            return pitr.CommandResult(0, json.dumps(_source()))
        if method == "get" and target_id in url:
            return pitr.CommandResult(0, json.dumps(_target(manifest)))
        raise AssertionError(command)

    with pytest.raises(pitr.PitrError):
        pitr.complete_restore(
            config,
            FakeRunner(handle),
            now=NOW + timedelta(minutes=2),
            sleeper=lambda _seconds: None,
            clock=lambda: NOW + timedelta(minutes=2),
        )

    state = json.loads(Path(environment["COSMAS_PITR_STATE_PATH"]).read_text(encoding="utf-8"))
    assert state["phase"] == "restore_started"
    assert state["restore_ready_at_utc"] == "2026-09-03T17:02:00Z"


def test_complete_rejects_ready_clock_before_polling_started(tmp_path) -> None:
    environment, manifest = _started_restore(tmp_path)
    config = pitr.Config.from_environment(environment)
    target_id = manifest["restore"]["target_resource_id"]

    def handle(command: list[str]) -> Any:
        if command[0] == "docker":
            return pytest.fail("fingerprint must not run after invalid ready timestamp")
        method = command[command.index("--method") + 1]
        url = command[command.index("--url") + 1]
        if method == "get" and SOURCE_ID in url:
            return pitr.CommandResult(0, json.dumps(_source()))
        if method == "get" and target_id in url:
            return pitr.CommandResult(0, json.dumps(_target(manifest)))
        raise AssertionError(command)

    with pytest.raises(pitr.PitrError, match="restore ready timestamp invalid"):
        pitr.complete_restore(
            config,
            FakeRunner(handle),
            now=NOW + timedelta(minutes=2),
            sleeper=lambda _seconds: None,
            clock=lambda: NOW,
        )


def test_cleanup_refuses_drifted_target_without_deleting(tmp_path) -> None:
    environment, manifest = _approved_environment(tmp_path, "cleanup")
    config = pitr.Config.from_environment(environment)
    target = _target(manifest)
    target["tags"]["box_id"] = "99999999-9999-4999-8999-999999999999"

    def handle(command: list[str]) -> Any:
        method = command[command.index("--method") + 1]
        if method == "get":
            return pitr.CommandResult(0, json.dumps(target))
        return pytest.fail("drifted target must not be deleted")

    runner = FakeRunner(handle)
    with pytest.raises(pitr.PitrError, match="restore target binding invalid"):
        pitr.cleanup_restore(config, runner, now=NOW + timedelta(minutes=2))
    assert all("delete" not in call for call in runner.calls)


def test_cleanup_remains_available_without_database_secret_or_state(tmp_path) -> None:
    environment, manifest = _approved_environment(tmp_path, "cleanup")
    environment.pop("COSMAS_PITR_DATABASE_URL_FILE")
    environment.pop("COSMAS_PITR_STATE_PATH")
    config = pitr.Config.from_environment(environment)

    evidence = pitr.cleanup_restore(
        config,
        FakeRunner(lambda _command: _not_found()),
        now=datetime(2026, 9, 4, 17, 0, tzinfo=UTC),
        sleeper=lambda _seconds: None,
    )

    assert evidence["status"] == "cleaned"
    _assert_evidence_self_hash(evidence)
    assert evidence["manifest_sha256"] == manifest["manifest_sha256"]
    assert "target_resource_id" not in json.dumps(evidence)


def test_unrecognized_azure_failure_is_not_accepted_as_target_absence(tmp_path) -> None:
    config = pitr.Config.from_environment(_environment(tmp_path))

    def handle(command: list[str]) -> Any:
        url = command[command.index("--url") + 1]
        if SOURCE_ID in url:
            return pitr.CommandResult(0, json.dumps(_source()))
        return pitr.CommandResult(1, stderr="ERROR: connection timed out")

    with pytest.raises(pitr.PitrError, match="Azure resource read failed"):
        pitr.create_manifest(config, FakeRunner(handle), now=NOW, nonce="123456789abc")
    assert not config.manifest_path.exists()


@pytest.mark.parametrize(
    "stderr",
    [
        "ERROR: Not Found",
        'ERROR: Not Found({"error":{"code":"AuthorizationFailed"}})',
        'ERROR: Not Found({"error":{"code":"ResourceNotFound"}}) trailing',
        'prefix ERROR: Not Found({"error":{"code":"ResourceNotFound"}})',
        'ERROR: Not Found({"error":{"code":"ResourceNotFound"}',
    ],
)
def test_azure_not_found_lookalikes_fail_closed(stderr: str) -> None:
    assert pitr._not_found(pitr.CommandResult(1, stderr=stderr)) is False


def test_exact_azure_cli_289_json_not_found_shape_is_accepted() -> None:
    result = pitr.CommandResult(
        1,
        stderr=(
            'ERROR: Not Found({"error":{"code":"ResourceNotFound",'
            '"message":"The Resource was not found."}})'
        ),
    )

    assert pitr._not_found(result) is True
