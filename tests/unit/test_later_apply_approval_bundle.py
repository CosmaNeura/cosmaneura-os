from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "beta" / "later_apply_approval_bundle.py"
_SPEC = importlib.util.spec_from_file_location("cosmas_later_apply_approval_bundle", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
tool = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = tool
_SPEC.loader.exec_module(tool)

SOURCE_SHA = "1" * 40
PLAN_SHA = "2" * 64
PROVIDER_SHA = "3" * 64
STATE_SHA = "4" * 64
LINEAGE = "00000000-0000-4000-8000-000000000101"
BOX_ID = "00000000-0000-4000-8000-000000000102"
NOW = "2026-09-04T12:10:00Z"


def _private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def _write_private(path: Path, value: object, *, raw: bool = False) -> Path:
    if raw:
        assert isinstance(value, str)
        path.write_text(value, encoding="utf-8")
    elif isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _review(variable_sha: str, stage: str) -> dict[str, Any]:
    managed_action = {
        "address": "azurerm_container_app.api",
        "type": "azurerm_container_app",
        "mode": "managed",
        "actions": ["update"],
    }
    return {
        "schema_version": 1,
        "phase": "subsequent",
        "generated_at": "2026-09-04T12:00:00Z",
        "plan_sha256": PLAN_SHA,
        "source_sha": SOURCE_SHA,
        "terraform_version": "1.10.6",
        "provider_lock_sha256": PROVIDER_SHA,
        "variable_file_sha256": variable_sha,
        "prior_state": {"lineage": LINEAGE, "serial": 42, "sha256": STATE_SHA},
        "boundary": {
            "subscription_id": "00000000-0000-4000-8000-000000000103",
            "tenant_id": "00000000-0000-4000-8000-000000000104",
            "deploy_identity_client_id": "00000000-0000-4000-8000-000000000105",
            "beta_id": "lab01",
            "box_id": BOX_ID,
            "state_resource_group": "rg-cosmas-os-beta-state-lab01",
            "workload_resource_group": "rg-cosmas-os-beta-lab01",
            "state_vnet_id": (
                "/subscriptions/00000000-0000-4000-8000-000000000103/"
                "resourceGroups/rg-cosmas-os-beta-state-lab01/"
                "providers/Microsoft.Network/virtualNetworks/vnet-state"
            ),
            "state_blob_private_dns_zone_id": (
                "/subscriptions/00000000-0000-4000-8000-000000000103/"
                "resourceGroups/rg-cosmas-os-beta-state-lab01/"
                "providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
            ),
            "deployment_mode": "synthetic_lab",
            "data_classification": "synthetic-only",
        },
        "managed_action_counts": {
            "create": 0,
            "update": 1,
            "delete": 0,
            "replace": 0,
            "no_op": 0,
        },
        "managed_actions": [managed_action],
        "critical_planned_values": {
            "environment": "early_adopter_beta",
            "location": "centralus",
            "box_id": BOX_ID,
            "deployment_mode": "synthetic_lab",
            "data_classification": "synthetic-only",
            "registry_network_posture": "private",
            "workloads_enabled": stage == "workloads",
            "database_preparation_job_enabled": True,
            "runtime_acceptance_job_enabled": stage == "workloads",
            "image_reference": "registry.invalid/api@sha256:" + "5" * 64,
            "web_image_reference": "registry.invalid/web@sha256:" + "6" * 64,
            "api_origin": "https://api.example.test",
            "web_origin": "https://beta.example.test",
            "web_default_fqdn": "web.example.azurecontainerapps.io",
            "web_custom_domain": "beta.example.test",
            "web_custom_domain_binding_enabled": True,
            "acr_login_server": "registry.invalid",
        },
        "security_posture": [
            {
                "address": managed_action["address"],
                "type": managed_action["type"],
                "actions": managed_action["actions"],
                "before": {"external_enabled": False},
                "after": {"external_enabled": False},
            }
        ],
    }


def _inputs(tmp_path: Path, *, stage: str = "database") -> dict[str, Path | str]:
    tmp_path.chmod(0o700)
    artifacts = _private_dir(tmp_path / "artifacts")
    bundles = _private_dir(tmp_path / "bundles")
    variable_raw = b'deployment_mode = "synthetic_lab"\n'
    variable_file = _write_private(artifacts / "environment.tfvars", variable_raw)
    review_file = _write_private(
        artifacts / "review.json",
        _review(hashlib.sha256(variable_raw).hexdigest(), stage),
    )
    return {
        "artifacts": artifacts,
        "bundles": bundles,
        "variable_file": variable_file,
        "review_file": review_file,
        "request": artifacts / "approval-request.json",
        "stage": stage,
    }


def _request_args(inputs: dict[str, Path | str]) -> list[str]:
    return [
        "request",
        "--review",
        str(inputs["review_file"]),
        "--var-file",
        str(inputs["variable_file"]),
        "--source-sha",
        SOURCE_SHA,
        "--release-id",
        "release-b",
        "--stage",
        str(inputs["stage"]),
        "--request-out",
        str(inputs["request"]),
        "--now",
        NOW,
    ]


def _owner(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "contract": "cosmas-os-d3-protected-owner-authorization-v2",
        "authorization_status": "APPROVED",
        "source_sha": request["source_sha"],
        "release_id": request["release_id"],
        "stage": request["stage"],
        "plan_sha256": request["plan_sha256"],
        "review_sha256": request["review_sha256"],
        "variable_file_sha256": request["variable_file_sha256"],
        "state": request["state"],
        "owner_assertion": request["exact_owner_assertion"],
        "reviewer": "Owner Reviewer",
        "approved_at": "2026-09-04T12:05:00Z",
        "expires_at": "2026-09-04T12:20:00Z",
    }


def _prepare_owner(inputs: dict[str, Path | str]) -> Path:
    request = json.loads(Path(inputs["request"]).read_text(encoding="utf-8"))
    return _write_private(Path(inputs["artifacts"]) / "owner-authorization.json", _owner(request))


def _materialize_args(inputs: dict[str, Path | str], owner: Path) -> list[str]:
    return [
        "materialize",
        "--review",
        str(inputs["review_file"]),
        "--var-file",
        str(inputs["variable_file"]),
        "--request",
        str(inputs["request"]),
        "--owner-authorization",
        str(owner),
        "--bundle-root",
        str(inputs["bundles"]),
        "--source-sha",
        SOURCE_SHA,
        "--release-id",
        "release-b",
        "--stage",
        str(inputs["stage"]),
        "--now",
        NOW,
    ]


@pytest.mark.parametrize("stage", ["database", "workloads"])
def test_creates_strict_content_addressed_bundle(tmp_path: Path, stage: str) -> None:
    inputs = _inputs(tmp_path, stage=stage)
    assert tool.main(_request_args(inputs)) == 0
    request_path = Path(inputs["request"])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["status"] == "PENDING_OWNER_AUTHORIZATION"
    assert request["does_not_authorize"] is True
    assert request["exact_owner_assertion"] == (
        f"AUTHORIZE D3 {stage.upper()} APPLY {PLAN_SHA} {request['review_sha256']}"
    )
    assert stat.S_IMODE(request_path.stat().st_mode) == 0o600

    owner = _prepare_owner(inputs)
    assert tool.main(_materialize_args(inputs, owner)) == 0

    bundle = Path(inputs["bundles"]) / PLAN_SHA
    assert stat.S_IMODE(bundle.stat().st_mode) == 0o700
    assert {item.name for item in bundle.iterdir()} == {
        "approval-request.json",
        "owner-authorization.json",
        "claim.json",
        "source-approval.json",
        "manifest.json",
    }
    assert all(stat.S_IMODE(item.stat().st_mode) == 0o600 for item in bundle.iterdir())
    assert (bundle / "approval-request.json").read_bytes() == request_path.read_bytes()
    assert (bundle / "owner-authorization.json").read_bytes() == owner.read_bytes()
    assert not any(".partial" in item.name for item in Path(inputs["bundles"]).iterdir())


def test_request_refuses_existing_output(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    _write_private(Path(inputs["request"]), b"do-not-replace")
    with pytest.raises(ValueError, match="already exists"):
        tool.main(_request_args(inputs))
    assert Path(inputs["request"]).read_bytes() == b"do-not-replace"


def test_secure_file_rejects_non_private_parent(tmp_path: Path) -> None:
    target = _write_private(tmp_path / "owner.json", b"{}\n")
    tmp_path.chmod(0o755)

    with pytest.raises(ValueError, match="0700"):
        tool._secure_file(target, "owner authorization")


def test_secure_file_reads_from_the_validated_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    target = _write_private(tmp_path / "owner.json", b"trusted\n")
    replacement = _write_private(tmp_path / "replacement.json", b"replaced\n")
    moved = tmp_path / "original.json"
    real_fstat = tool.os.fstat
    swapped = False

    def swap_after_file_validation(descriptor: int) -> os.stat_result:
        nonlocal swapped
        details = real_fstat(descriptor)
        if not swapped and stat.S_ISREG(details.st_mode):
            target.rename(moved)
            replacement.rename(target)
            swapped = True
        return details

    monkeypatch.setattr(tool.os, "fstat", swap_after_file_validation)
    assert tool._secure_file(target, "owner authorization") == b"trusted\n"
    assert swapped is True
    assert target.read_bytes() == b"replaced\n"


def test_request_rejects_duplicate_review_key(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    review = Path(inputs["review_file"])
    raw = review.read_text(encoding="utf-8").replace(
        '"schema_version": 1,', '"schema_version": 1, "schema_version": 1,', 1
    )
    _write_private(review, raw, raw=True)
    with pytest.raises(ValueError, match="duplicate JSON key"):
        tool.main(_request_args(inputs))


def test_request_rejects_tampered_tfvars_binding(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    Path(inputs["variable_file"]).write_text('deployment_mode = "wrong"\n', encoding="utf-8")
    Path(inputs["variable_file"]).chmod(0o600)
    with pytest.raises(ValueError, match="variable-file binding"):
        tool.main(_request_args(inputs))


def test_materialize_rejects_duplicate_owner_key(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    tool.main(_request_args(inputs))
    owner = _prepare_owner(inputs)
    raw = owner.read_text(encoding="utf-8").replace(
        '"schema_version": 2,', '"schema_version": 2, "schema_version": 2,', 1
    )
    _write_private(owner, raw, raw=True)
    with pytest.raises(ValueError, match="duplicate JSON key"):
        tool.main(_materialize_args(inputs, owner))
    assert list(Path(inputs["bundles"]).iterdir()) == []


def test_materialize_rejects_expired_owner_authorization(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    tool.main(_request_args(inputs))
    request = json.loads(Path(inputs["request"]).read_text(encoding="utf-8"))
    owner_value = _owner(request)
    owner_value["expires_at"] = NOW
    owner = _write_private(Path(inputs["artifacts"]) / "owner.json", owner_value)
    with pytest.raises(ValueError, match="not currently effective"):
        tool.main(_materialize_args(inputs, owner))


@pytest.mark.parametrize("field", ["source_sha", "owner_assertion", "state"])
def test_materialize_rejects_tampered_owner_binding(tmp_path: Path, field: str) -> None:
    inputs = _inputs(tmp_path)
    tool.main(_request_args(inputs))
    request = json.loads(Path(inputs["request"]).read_text(encoding="utf-8"))
    owner_value = _owner(request)
    if field == "source_sha":
        owner_value[field] = "f" * 40
    elif field == "owner_assertion":
        owner_value[field] += " TAMPERED"
    else:
        owner_value[field] = {**owner_value[field], "serial": 41}
    owner = _write_private(Path(inputs["artifacts"]) / "owner.json", owner_value)
    with pytest.raises(ValueError, match="contract/binding"):
        tool.main(_materialize_args(inputs, owner))


def test_materialize_rejects_tampered_request_self_hash(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    tool.main(_request_args(inputs))
    request_path = Path(inputs["request"])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["evidence_payload_sha256"] = "f" * 64
    _write_private(request_path, request)
    owner = _write_private(Path(inputs["artifacts"]) / "owner.json", _owner(request))
    with pytest.raises(ValueError, match="evidence hash"):
        tool.main(_materialize_args(inputs, owner))


def test_materialize_refuses_replay_without_changing_bundle(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    tool.main(_request_args(inputs))
    owner = _prepare_owner(inputs)
    args = _materialize_args(inputs, owner)
    tool.main(args)
    bundle = Path(inputs["bundles"]) / PLAN_SHA
    original = {
        item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in bundle.iterdir()
    }

    with pytest.raises(ValueError, match="replay or overwrite"):
        tool.main(args)
    assert {
        item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in bundle.iterdir()
    } == original


def test_materialize_refuses_preexisting_empty_bundle_claim(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    tool.main(_request_args(inputs))
    owner = _prepare_owner(inputs)
    bundle = Path(inputs["bundles"]) / PLAN_SHA
    bundle.mkdir(mode=0o700)

    with pytest.raises(ValueError, match="replay or overwrite"):
        tool.main(_materialize_args(inputs, owner))
    assert list(bundle.iterdir()) == []


def test_materialize_reserves_final_directory_and_writes_manifest_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path)
    tool.main(_request_args(inputs))
    owner = _prepare_owner(inputs)
    bundle = Path(inputs["bundles"]) / PLAN_SHA
    writes: list[str] = []
    original = tool._write_new_file

    def record_write(path: Path, raw: bytes) -> None:
        assert path.parent == bundle
        assert bundle.is_dir()
        writes.append(path.name)
        original(path, raw)

    monkeypatch.setattr(tool, "_write_new_file", record_write)
    tool.main(_materialize_args(inputs, owner))

    assert writes == [
        "approval-request.json",
        "owner-authorization.json",
        "claim.json",
        "source-approval.json",
        "manifest.json",
    ]


def test_materialize_leaves_an_incomplete_claim_and_refuses_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path)
    tool.main(_request_args(inputs))
    owner = _prepare_owner(inputs)
    bundle = Path(inputs["bundles"]) / PLAN_SHA
    original = tool._write_new_file
    writes = 0

    def interrupt_write(path: Path, raw: bytes) -> None:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("simulated interruption")
        original(path, raw)

    monkeypatch.setattr(tool, "_write_new_file", interrupt_write)
    with pytest.raises(OSError, match="simulated interruption"):
        tool.main(_materialize_args(inputs, owner))

    assert bundle.is_dir()
    assert {item.name for item in bundle.iterdir()} == {"approval-request.json"}
    monkeypatch.setattr(tool, "_write_new_file", original)
    with pytest.raises(ValueError, match="replay or overwrite"):
        tool.main(_materialize_args(inputs, owner))


@pytest.mark.parametrize("unsafe", ["owner-mode", "owner-symlink", "bundle-root-mode"])
def test_materialize_rejects_unsafe_paths_and_modes(tmp_path: Path, unsafe: str) -> None:
    inputs = _inputs(tmp_path)
    tool.main(_request_args(inputs))
    owner = _prepare_owner(inputs)
    if unsafe == "owner-mode":
        owner.chmod(0o644)
    elif unsafe == "owner-symlink":
        target = owner
        owner = Path(inputs["artifacts"]) / "owner-link.json"
        owner.symlink_to(target)
    else:
        Path(inputs["bundles"]).chmod(0o755)
    with pytest.raises(ValueError, match="symlink|0600|0700"):
        tool.main(_materialize_args(inputs, owner))


def test_request_rejects_destructive_review(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    review_path = Path(inputs["review_file"])
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["managed_action_counts"]["update"] = 0
    review["managed_action_counts"]["delete"] = 1
    review["managed_actions"][0]["actions"] = ["delete"]
    review["security_posture"][0]["actions"] = ["delete"]
    _write_private(review_path, review)
    with pytest.raises(ValueError, match="destructive"):
        tool.main(_request_args(inputs))


def test_request_rejects_future_review_timestamp(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    review_path = Path(inputs["review_file"])
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["generated_at"] = "2026-09-04T12:11:00Z"
    _write_private(review_path, review)
    with pytest.raises(ValueError, match="in the future"):
        tool.main(_request_args(inputs))


def test_request_rejects_review_for_other_stage(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, stage="database")
    review_path = Path(inputs["review_file"])
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["critical_planned_values"]["workloads_enabled"] = True
    _write_private(review_path, review)
    with pytest.raises(ValueError, match="exact database stage"):
        tool.main(_request_args(inputs))


@pytest.mark.parametrize(
    ("stage", "runtime_acceptance_enabled"),
    [("database", True), ("workloads", False)],
)
def test_request_rejects_wrong_runtime_acceptance_switch(
    tmp_path: Path, stage: str, runtime_acceptance_enabled: bool
) -> None:
    inputs = _inputs(tmp_path, stage=stage)
    review_path = Path(inputs["review_file"])
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["critical_planned_values"]["runtime_acceptance_job_enabled"] = runtime_acceptance_enabled
    _write_private(review_path, review)

    with pytest.raises(ValueError, match=f"exact {stage} stage"):
        tool.main(_request_args(inputs))


def test_materialize_requires_separate_owner_authorization() -> None:
    parser = tool._parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "materialize",
                "--review",
                "/private/tmp/review.json",
                "--var-file",
                "/private/tmp/vars.tfvars",
                "--request",
                "/private/tmp/request.json",
                "--bundle-root",
                "/private/tmp/bundles",
                "--source-sha",
                SOURCE_SHA,
                "--release-id",
                "release-b",
                "--stage",
                "database",
            ]
        )


def test_no_ambient_environment_can_change_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OWNER_ASSERTION", "AUTHORIZE EVERYTHING")
    monkeypatch.setenv("REVIEWER", "Attacker")
    parser = tool._parser()
    parsed = parser.parse_args(
        [
            "request",
            "--review",
            "/private/tmp/review.json",
            "--var-file",
            "/private/tmp/vars.tfvars",
            "--source-sha",
            SOURCE_SHA,
            "--release-id",
            "release-b",
            "--stage",
            "database",
            "--request-out",
            "/private/tmp/request.json",
        ]
    )
    assert not hasattr(parsed, "reviewer")
    assert not hasattr(parsed, "owner_assertion")
