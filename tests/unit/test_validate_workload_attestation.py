from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "infra" / "beta" / "validate_workload_attestation.py"
)
_SPEC = importlib.util.spec_from_file_location("cosmas_validate_workload_attestation", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
validator = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = validator
_SPEC.loader.exec_module(validator)

SOURCE_SHA = "1" * 40
RELEASE_ID = "release-b"
LINEAGE = "00000000-0000-4000-8000-000000000103"
BOX_ID = "00000000-0000-4000-8000-000000000102"
STATE_SHA256 = "2" * 64
API_DIGEST = "sha256:" + "3" * 64
WEB_DIGEST = "sha256:" + "4" * 64
OBSERVED_AT = datetime(2026, 9, 4, 12, 15, tzinfo=UTC)


def _expected() -> Any:
    return validator.ExpectedBinding(
        source_sha=SOURCE_SHA,
        release_id=RELEASE_ID,
        state_lineage=LINEAGE,
        state_serial=42,
        state_sha256=STATE_SHA256,
        box_id=BOX_ID,
        api_digest=API_DIGEST,
        web_digest=WEB_DIGEST,
    )


def _attestation() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "cosmas-os-d3-workload-verification-v1",
        "status": "verified",
        "completed_at": "2026-09-04T12:00:00Z",
        "source_sha": SOURCE_SHA,
        "release_id": RELEASE_ID,
        "box_id": BOX_ID,
        "state": {
            "exists": True,
            "lineage": LINEAGE,
            "serial": 42,
            "sha256": STATE_SHA256,
        },
        "images": {"api": API_DIGEST, "worker": API_DIGEST, "web": WEB_DIGEST},
        "revision_id_sha256": {"api": "5" * 64, "worker": "6" * 64, "web": "7" * 64},
        "exact_revisions_and_images_verified": True,
        "single_revision_traffic_verified": True,
        "api_ready_verified": True,
        "web_health_verified": True,
        "worker_probe_configuration_verified": True,
        "exact_runtime_configuration_verified": True,
        "managed_environment_verified": True,
        "worker_private_and_ready": True,
        "synthetic_box_id_returned": True,
        "person_or_patient_identifiers_returned": False,
        "secrets_returned": False,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {**payload, "evidence_payload_sha256": hashlib.sha256(encoded).hexdigest()}


def _write(path: Path, evidence: dict[str, Any]) -> None:
    path.write_text(json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8")


def test_current_attestation_is_accepted(tmp_path: Path) -> None:
    artifact = tmp_path / "attestation.json"
    _write(artifact, _attestation())

    validator.load_and_validate_attestation(
        artifact,
        _expected(),
        require_protected_metadata=False,
        observed_at=OBSERVED_AT,
    )


def test_absent_attestation_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(validator.WorkloadAttestationError, match="unavailable"):
        validator.load_and_validate_attestation(
            tmp_path / "missing.json",
            _expected(),
            require_protected_metadata=False,
            observed_at=OBSERVED_AT,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda evidence: evidence["state"].update({"serial": 41}),
        lambda evidence: evidence["state"].update(
            {"lineage": "00000000-0000-4000-8000-000000000108"}
        ),
        lambda evidence: evidence["state"].update({"sha256": "8" * 64}),
        lambda evidence: evidence["state"].update({"exists": False}),
        lambda evidence: evidence.update({"box_id": "00000000-0000-4000-8000-000000000109"}),
        lambda evidence: evidence["images"].update({"api": "sha256:" + "9" * 64}),
        lambda evidence: evidence.update({"source_sha": "a" * 40}),
        lambda evidence: evidence.update({"release_id": "release-c"}),
    ],
)
def test_stale_binding_is_rejected(mutation) -> None:
    evidence = _attestation()
    mutation(evidence)
    payload = {key: value for key, value in evidence.items() if key != "evidence_payload_sha256"}
    evidence["evidence_payload_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    with pytest.raises(validator.WorkloadAttestationError):
        validator.validate_attestation(evidence, _expected(), observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda evidence: evidence.update({"api_ready_verified": False}),
        lambda evidence: evidence.update({"secrets_returned": True}),
        lambda evidence: evidence["revision_id_sha256"].update({"api": "not-a-hash"}),
        lambda evidence: evidence.update({"unexpected": True}),
        lambda evidence: evidence.update({"evidence_payload_sha256": "f" * 64}),
    ],
)
def test_tampered_or_unsuccessful_attestation_is_rejected(mutation) -> None:
    evidence = _attestation()
    mutation(evidence)

    with pytest.raises(validator.WorkloadAttestationError):
        validator.validate_attestation(evidence, _expected(), observed_at=OBSERVED_AT)


@pytest.mark.parametrize("completed_at", ["2026-09-04T11:14:59Z", "2026-09-04T12:20:01Z"])
def test_stale_or_future_attestation_is_rejected(completed_at: str) -> None:
    evidence = _attestation()
    evidence["completed_at"] = completed_at
    payload = {key: value for key, value in evidence.items() if key != "evidence_payload_sha256"}
    evidence["evidence_payload_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    with pytest.raises(
        validator.WorkloadAttestationError,
        match="completion time",
    ):
        validator.validate_attestation(evidence, _expected(), observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    ("field", "value"),
    [("exists", 1), ("serial", 42.0), ("serial", True)],
)
def test_state_type_confusion_is_rejected(field: str, value: object) -> None:
    evidence = _attestation()
    evidence["state"][field] = value
    payload = {key: item for key, item in evidence.items() if key != "evidence_payload_sha256"}
    evidence["evidence_payload_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    with pytest.raises(
        validator.WorkloadAttestationError,
        match="state binding",
    ):
        validator.validate_attestation(evidence, _expected(), observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "expected_location,actual_location", [("eastus2", "centralus"), ("centralus", "eastus2")]
)
def test_rehashed_cross_region_attestation_is_rejected(
    expected_location: str, actual_location: str
) -> None:
    evidence = _attestation() | {"location": actual_location, "api_max_replicas": 2}
    payload = {key: value for key, value in evidence.items() if key != "evidence_payload_sha256"}
    evidence["evidence_payload_sha256"] = validator._canonical_sha256(payload)
    with pytest.raises(validator.WorkloadAttestationError, match="profile binding"):
        validator.validate_attestation(
            evidence, replace(_expected(), location=expected_location), observed_at=OBSERVED_AT
        )


@pytest.mark.parametrize("profile", [[], ["eastus2", "1"], ["centralus", "2"]])
def test_cli_passes_exact_expected_profile(monkeypatch, profile: list[str]) -> None:
    observed = []
    monkeypatch.setattr(
        validator, "load_and_validate_attestation", lambda path, expected: observed.append(expected)
    )
    arguments = [
        "evidence.json",
        SOURCE_SHA,
        RELEASE_ID,
        LINEAGE,
        "42",
        STATE_SHA256,
        BOX_ID,
        API_DIGEST,
        WEB_DIGEST,
    ]
    assert validator.main(arguments + profile) == 0
    assert len(observed) == 1
    assert observed[0].location == (profile[0] if profile else "centralus")
    assert observed[0].api_max_replicas == (int(profile[1]) if profile else 2)


@pytest.mark.parametrize(
    "profile",
    [["eastus2"], ["eastus2", "01"], ["eastus2", "1.0"], ["eastus2", "true"], ["eastus2", " 1"]],
)
def test_cli_rejects_partial_or_noncanonical_profile(monkeypatch, profile: list[str]) -> None:
    def unexpected_read(*args, **kwargs):
        pytest.fail("invalid profile must fail before reading evidence")

    monkeypatch.setattr(validator, "load_and_validate_attestation", unexpected_read)
    arguments = [
        "evidence.json",
        SOURCE_SHA,
        RELEASE_ID,
        LINEAGE,
        "42",
        STATE_SHA256,
        BOX_ID,
        API_DIGEST,
        WEB_DIGEST,
    ]
    assert validator.main(arguments + profile) == 1
