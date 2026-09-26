from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from tests.unit import test_validate_workload_attestation as attestation_fixture
from tests.unit import test_workload_verification as workload_fixture

workload = workload_fixture.workload
validator = attestation_fixture.validator
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _environment(location: str, maximum: int) -> dict[str, str]:
    return {
        **workload_fixture._environment(),
        "COSMAS_WORKLOAD_LOCATION": location,
        "COSMAS_WORKLOAD_API_MAX_REPLICAS": str(maximum),
    }


def _runner(location: str, maximum: int, *, replicas: int = 1) -> Any:
    runner = workload_fixture.FakeRunner()
    runner.managed_environment["location"] = location
    for app in runner.apps.values():
        app["location"] = location
    runner.apps["api"]["properties"]["template"]["scale"]["maxReplicas"] = maximum
    revision = runner.revisions["api"][0]["properties"]
    revision["template"]["scale"]["maxReplicas"] = maximum
    revision["replicas"] = replicas
    return runner


def _expected(config: Any) -> Any:
    return validator.ExpectedBinding(
        source_sha=config.source_sha,
        release_id=config.release_id,
        state_lineage=config.state_lineage,
        state_serial=config.state_serial,
        state_sha256=config.state_sha256,
        box_id=config.box_id,
        api_digest=config.api_digest,
        web_digest=config.web_digest,
        location=config.location,
        api_max_replicas=config.api_max_replicas,
    )


def _rehash(evidence: dict[str, Any]) -> None:
    payload = {key: value for key, value in evidence.items() if key != "evidence_payload_sha256"}
    evidence["evidence_payload_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@pytest.mark.parametrize("location", ["centralus", "eastus2"])
@pytest.mark.parametrize(("maximum", "replicas"), [(1, 1), (2, 1), (2, 2)])
def test_exact_reviewed_api_cap_is_verified_and_bound(
    location: str, maximum: int, replicas: int
) -> None:
    config = workload.Config.from_environment(_environment(location, maximum))
    evidence = workload.verify_workload(
        config, _runner(location, maximum, replicas=replicas), now=NOW
    )

    assert evidence["status"] == "verified"
    assert evidence["location"] == location
    assert type(evidence["api_max_replicas"]) is int
    assert evidence["api_max_replicas"] == maximum
    assert evidence["state"]["sha256"] == config.state_sha256
    stored_hash = evidence["evidence_payload_sha256"]
    _rehash(evidence)
    assert evidence["evidence_payload_sha256"] == stored_hash
    validator.validate_attestation(evidence, _expected(config), observed_at=NOW)


@pytest.mark.parametrize(("reviewed", "live"), [(1, 2), (2, 1)])
def test_supported_but_unreviewed_api_cap_is_rejected(reviewed: int, live: int) -> None:
    config = workload.Config.from_environment(_environment("eastus2", reviewed))

    with pytest.raises(workload.WorkloadVerificationError, match="scale"):
        workload.verify_workload(config, _runner("eastus2", live), now=NOW)


@pytest.mark.parametrize("reviewed", [1, 2])
@pytest.mark.parametrize("mismatched_template", ["app", "revision"])
def test_app_and_active_revision_must_both_match_reviewed_cap(
    reviewed: int, mismatched_template: str
) -> None:
    config = workload.Config.from_environment(_environment("eastus2", reviewed))
    runner = _runner("eastus2", reviewed)
    properties = (
        runner.apps["api"]["properties"]
        if mismatched_template == "app"
        else runner.revisions["api"][0]["properties"]
    )
    properties["template"]["scale"]["maxReplicas"] = 3 - reviewed

    with pytest.raises(workload.WorkloadVerificationError, match="scale"):
        workload.verify_workload(config, runner, now=NOW)


@pytest.mark.parametrize("maximum", [1, 2])
def test_actual_replicas_cannot_exceed_reviewed_cap(maximum: int) -> None:
    config = workload.Config.from_environment(_environment("eastus2", maximum))

    with pytest.raises(workload.WorkloadVerificationError, match="active revision"):
        workload.verify_workload(
            config, _runner("eastus2", maximum, replicas=maximum + 1), now=NOW
        )


@pytest.mark.parametrize("location", ["centralus", "eastus2"])
@pytest.mark.parametrize("value", ["", "0", "3", "01", "+1", "1.0", "true", " 1", "1 ", "1\n"])
def test_malformed_reviewed_cap_fails_before_any_remote_request(
    location: str, value: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    environment = _environment(location, 1)
    environment["COSMAS_WORKLOAD_API_MAX_REPLICAS"] = value
    runner = _runner(location, 1)
    monkeypatch.setattr(workload, "os", SimpleNamespace(environ=environment))
    monkeypatch.setattr(workload, "SubprocessRunner", lambda: runner)

    assert workload.main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    assert runner.arm_calls == []
    assert runner.curl_calls == []


@pytest.mark.parametrize("location", ["centralus", "eastus2"])
@pytest.mark.parametrize("missing_key", ["COSMAS_WORKLOAD_LOCATION", "COSMAS_WORKLOAD_API_MAX_REPLICAS"])
def test_reviewed_topology_requires_both_input_values(location: str, missing_key: str) -> None:
    environment = _environment(location, 1)
    del environment[missing_key]

    with pytest.raises(workload.WorkloadVerificationError):
        workload.Config.from_environment(environment)


def test_legacy_centralus_default_is_exactly_two_and_never_one() -> None:
    environment = workload_fixture._environment()
    environment.pop("COSMAS_WORKLOAD_LOCATION", None)
    environment.pop("COSMAS_WORKLOAD_API_MAX_REPLICAS", None)
    config = workload.Config.from_environment(environment)

    assert config.location == "centralus"
    assert config.api_max_replicas == 2
    assert workload.verify_workload(config, _runner("centralus", 2), now=NOW)["status"] == "verified"
    with pytest.raises(workload.WorkloadVerificationError, match="scale"):
        workload.verify_workload(config, _runner("centralus", 1), now=NOW)


@pytest.mark.parametrize(("reviewed", "different"), [(1, 2), (2, 1)])
def test_rehashing_a_different_cap_cannot_change_reviewed_receipt_binding(
    reviewed: int, different: int
) -> None:
    config = workload.Config.from_environment(_environment("eastus2", reviewed))
    evidence = workload.verify_workload(config, _runner("eastus2", reviewed), now=NOW)
    evidence["api_max_replicas"] = different
    _rehash(evidence)

    with pytest.raises(validator.WorkloadAttestationError):
        validator.validate_attestation(evidence, _expected(config), observed_at=NOW)


@pytest.mark.parametrize("missing_key", ["location", "api_max_replicas"])
def test_partial_deployment_binding_cannot_be_downgraded_to_legacy(missing_key: str) -> None:
    config = workload.Config.from_environment(_environment("centralus", 2))
    evidence = workload.verify_workload(config, _runner("centralus", 2), now=NOW)
    del evidence[missing_key]
    _rehash(evidence)

    with pytest.raises(validator.WorkloadAttestationError):
        validator.validate_attestation(evidence, _expected(config), observed_at=NOW)


@pytest.mark.parametrize(("location", "maximum"), [("centralus", 1), ("eastus2", 1), ("eastus2", 2)])
def test_legacy_receipt_cannot_attest_a_different_reviewed_topology(
    location: str, maximum: int
) -> None:
    config = workload.Config.from_environment(_environment(location, maximum))
    evidence = workload.verify_workload(config, _runner(location, maximum), now=NOW)
    del evidence["location"]
    del evidence["api_max_replicas"]
    _rehash(evidence)

    with pytest.raises(validator.WorkloadAttestationError):
        validator.validate_attestation(evidence, _expected(config), observed_at=NOW)


@pytest.mark.parametrize("cap", [True, 1.0, "1", 0, 3])
def test_self_hashed_receipt_requires_a_canonical_integer_cap(cap: object) -> None:
    config = workload.Config.from_environment(_environment("eastus2", 1))
    evidence = workload.verify_workload(config, _runner("eastus2", 1), now=NOW)
    evidence["api_max_replicas"] = cap
    _rehash(evidence)

    with pytest.raises(validator.WorkloadAttestationError):
        validator.validate_attestation(evidence, _expected(config), observed_at=NOW)
