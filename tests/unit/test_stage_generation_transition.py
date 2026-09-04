from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "infra"
    / "beta"
    / "stage_generation_transition.py"
)
_SPEC = importlib.util.spec_from_file_location("cosmas_stage_generation_transition", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
transition = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = transition
_SPEC.loader.exec_module(transition)

Config = transition.Config
StageTransitionError = transition.StageTransitionError
inspect_stage = transition.inspect_stage
run_transition = transition.run_transition

SOURCE_SHA = "a" * 40
RELEASE_ID = "candidate-one"
NOW = datetime(2026, 9, 3, 16, 0, tzinfo=UTC)


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_private(path: Path, value: bytes) -> None:
    path.write_bytes(value)
    path.chmod(0o600)


def _config(tmp_path: Path, stage: str = "foundation") -> Config:
    release_root = tmp_path / "release"
    stage_root = release_root / "stages" / stage
    stage_root.mkdir(parents=True, mode=0o700)
    release_root.chmod(0o700)
    (release_root / "stages").chmod(0o700)
    _write_private(release_root / "source-sha", f"{SOURCE_SHA}\n".encode())
    payload = tmp_path / "payload.json"
    _write_private(payload, b"{}\n")
    return Config(
        action="transition",
        source_sha=SOURCE_SHA,
        release_id=RELEASE_ID,
        stage=stage,
        release_root=release_root,
        stage_root=stage_root,
        payload_path=payload,
    )


def _approval(
    config: Config,
    *,
    mode: str,
    inventory: dict[str, str | None],
    replacement: bytes,
    approved_at: datetime = NOW,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract": "cosmas-os-d3-stage-generation-approval-v1",
        "confirmation": "AUTHORIZE D3 IMMUTABLE STAGE GENERATION TRANSITION",
        "approved_at": approved_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "reviewer_reference": "owner-ledger:stage-transition-001",
        "reason_reference": "d3-runbook:reviewed-retry",
        "source_sha": config.source_sha,
        "release_id": config.release_id,
        "stage": config.stage,
        "transition_mode": mode,
        "current_artifacts": inventory,
        "replacement_tfvars_sha256": _hash(replacement),
    }


def _set_payload(
    config: Config,
    *,
    mode: str,
    approval: dict[str, Any],
    replacement: bytes,
) -> None:
    payload = {
        "transition_mode": mode,
        "owner_approval": approval,
        "replacement_tfvars_base64": base64.b64encode(replacement).decode(),
    }
    _write_private(config.payload_path, _canonical(payload))


def test_abandoned_generation_is_archived_and_exact_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    original = _canonical({"deploy_workloads": False, "value": "old"})
    replacement = _canonical({"deploy_workloads": False, "value": "corrected"})
    _write_private(config.stage_root / "environment.tfvars.json", original)
    inspection = inspect_stage(config, now=NOW)
    approval = _approval(
        config,
        mode="abandoned_retry",
        inventory=inspection["current_artifacts"],
        replacement=replacement,
    )
    _set_payload(
        config,
        mode="abandoned_retry",
        approval=approval,
        replacement=replacement,
    )

    evidence = run_transition(config, now=NOW)
    assert evidence["history_preserved"] is True
    assert evidence["successful_result_archived"] is False
    assert (config.stage_root / "environment.tfvars.json").read_bytes() == replacement
    archive = config.release_root / "stage-history" / config.stage / evidence["archive_id"]
    assert (archive / "environment.tfvars.json").read_bytes() == original
    evidence_payload = {
        key: value for key, value in evidence.items() if key != "evidence_payload_sha256"
    }
    assert evidence["evidence_payload_sha256"] == _hash(
        json.dumps(evidence_payload, sort_keys=True, separators=(",", ":")).encode()
    )

    repeated = run_transition(config, now=NOW + timedelta(minutes=1))
    assert repeated == evidence
    _write_private(config.payload_path, b"{}\n")
    inspection_after = inspect_stage(config, now=NOW + timedelta(hours=6))
    assert inspection_after["latest_transition"] == evidence


@pytest.mark.parametrize("crash_after_rename", [0, 1])
def test_exact_transition_resumes_after_expiry_from_each_durable_crash_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, crash_after_rename: int
) -> None:
    config = _config(tmp_path)
    original = _canonical({"deploy_workloads": False, "value": "old"})
    replacement = _canonical({"deploy_workloads": False, "value": "new"})
    _write_private(config.stage_root / "environment.tfvars.json", original)
    inventory = inspect_stage(config, now=NOW)["current_artifacts"]
    approval = _approval(
        config,
        mode="abandoned_retry",
        inventory=inventory,
        replacement=replacement,
    )
    _set_payload(
        config,
        mode="abandoned_retry",
        approval=approval,
        replacement=replacement,
    )
    real_rename = transition.os.rename
    rename_count = 0

    def interrupted_rename(source: Path, destination: Path) -> None:
        nonlocal rename_count
        if rename_count == crash_after_rename:
            rename_count += 1
            if crash_after_rename == 1:
                raise KeyboardInterrupt
            raise OSError("simulated interruption")
        rename_count += 1
        real_rename(source, destination)

    monkeypatch.setattr(transition.os, "rename", interrupted_rename)
    expected_error = KeyboardInterrupt if crash_after_rename == 1 else OSError
    with pytest.raises(expected_error):
        run_transition(config, now=NOW)
    monkeypatch.setattr(transition.os, "rename", real_rename)

    evidence = run_transition(config, now=NOW + timedelta(hours=5))
    assert evidence["history_preserved"] is True
    assert (config.stage_root / "environment.tfvars.json").read_bytes() == replacement


@pytest.mark.parametrize("crash_boundary", ["mkdir", "tfvars", "marker", "evidence"])
def test_exact_transition_resumes_after_partial_publication_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_boundary: str,
) -> None:
    config = _config(tmp_path)
    original = _canonical({"deploy_workloads": False, "value": "old"})
    replacement = _canonical({"deploy_workloads": False, "value": "new"})
    _write_private(config.stage_root / "environment.tfvars.json", original)
    inventory = inspect_stage(config, now=NOW)["current_artifacts"]
    approval = _approval(
        config,
        mode="abandoned_retry",
        inventory=inventory,
        replacement=replacement,
    )
    _set_payload(
        config,
        mode="abandoned_retry",
        approval=approval,
        replacement=replacement,
    )
    real_write = transition._write_exclusive
    completed_publications = 0

    def interrupted_write(
        path: Path,
        data: bytes,
        *,
        temporary_root: Path,
        mode: int = 0o600,
    ) -> None:
        nonlocal completed_publications
        if crash_boundary == "mkdir" and completed_publications == 0:
            raise KeyboardInterrupt
        real_write(path, data, temporary_root=temporary_root, mode=mode)
        completed_publications += 1
        expected_count = {"tfvars": 1, "marker": 2, "evidence": 3}.get(
            crash_boundary
        )
        if completed_publications == expected_count:
            raise KeyboardInterrupt

    monkeypatch.setattr(transition, "_write_exclusive", interrupted_write)
    with pytest.raises(KeyboardInterrupt):
        run_transition(config, now=NOW)
    monkeypatch.setattr(transition, "_write_exclusive", real_write)

    evidence = run_transition(config, now=NOW + timedelta(hours=5))
    assert evidence["history_preserved"] is True
    assert (config.stage_root / "environment.tfvars.json").read_bytes() == replacement
    assert not (config.stage_root / ".stage-transition-attestation.json").exists()


@pytest.mark.parametrize("unexpected_kind", ["file", "symlink"])
def test_transition_rejects_unexpected_pending_generation_entries(
    tmp_path: Path,
    unexpected_kind: str,
) -> None:
    config = _config(tmp_path)
    original = _canonical({"deploy_workloads": False, "value": "old"})
    replacement = _canonical({"deploy_workloads": False, "value": "new"})
    _write_private(config.stage_root / "environment.tfvars.json", original)
    inventory = inspect_stage(config, now=NOW)["current_artifacts"]
    approval = _approval(
        config,
        mode="abandoned_retry",
        inventory=inventory,
        replacement=replacement,
    )
    _set_payload(
        config,
        mode="abandoned_retry",
        approval=approval,
        replacement=replacement,
    )
    transition_id = _hash(
        json.dumps(approval, sort_keys=True, separators=(",", ":")).encode()
    )
    pending_root = (
        config.release_root / "stages" / f".{config.stage}.next-{transition_id}"
    )
    pending_root.mkdir(mode=0o700)
    unexpected = pending_root / "plan.tfplan"
    if unexpected_kind == "file":
        _write_private(unexpected, b"unexpected")
    else:
        unexpected.symlink_to(config.stage_root / "environment.tfvars.json")

    with pytest.raises(StageTransitionError, match="unexpected artifacts"):
        run_transition(config, now=NOW + timedelta(hours=5))
    assert (config.stage_root / "environment.tfvars.json").read_bytes() == original


def test_durable_rename_fsyncs_both_parent_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_parent = tmp_path / "source-parent"
    destination_parent = tmp_path / "destination-parent"
    source_parent.mkdir(mode=0o700)
    destination_parent.mkdir(mode=0o700)
    source = source_parent / "generation"
    destination = destination_parent / "generation"
    source.mkdir(mode=0o700)
    fsynced: list[Path] = []

    monkeypatch.setattr(transition, "_fsync_directory", fsynced.append)
    transition._durable_rename(source, destination)

    assert destination.is_dir()
    assert fsynced == [destination_parent, source_parent]


def test_new_transition_directory_is_fsynced_with_its_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    created = parent / "created"
    fsynced: list[Path] = []

    monkeypatch.setattr(transition, "_fsync_directory", fsynced.append)
    transition._ensure_parent(created)

    assert created.is_dir()
    assert fsynced == [created, parent]


def test_completed_transition_retry_allows_normal_active_stage_artifacts(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    original = _canonical({"deploy_workloads": False, "value": "old"})
    replacement = _canonical({"deploy_workloads": False, "value": "new"})
    _write_private(config.stage_root / "environment.tfvars.json", original)
    inventory = inspect_stage(config, now=NOW)["current_artifacts"]
    approval = _approval(
        config,
        mode="abandoned_retry",
        inventory=inventory,
        replacement=replacement,
    )
    _set_payload(
        config,
        mode="abandoned_retry",
        approval=approval,
        replacement=replacement,
    )
    evidence = run_transition(config, now=NOW)
    plan = b"binary-plan"
    _write_private(config.stage_root / "plan.tfplan", plan)
    _write_private(
        config.stage_root / "review.json",
        _canonical({"schema_version": 1, "plan_sha256": _hash(plan)}),
    )
    _write_private(config.stage_root / "approval.json", _canonical({"approved": True}))
    _write_private(
        config.stage_root / "result.json",
        _canonical({"schema_version": 1, "plan_sha256": _hash(plan)}),
    )
    _write_private(config.stage_root / "plan.private.log", b"private plan output")
    _write_private(config.stage_root / "apply.private.log", b"private apply output")

    assert run_transition(config, now=NOW + timedelta(hours=5)) == evidence


def test_idempotent_retry_rejects_modified_archive(tmp_path: Path) -> None:
    config = _config(tmp_path)
    original = _canonical({"deploy_workloads": False, "value": "old"})
    replacement = _canonical({"deploy_workloads": False, "value": "new"})
    _write_private(config.stage_root / "environment.tfvars.json", original)
    inventory = inspect_stage(config, now=NOW)["current_artifacts"]
    approval = _approval(
        config,
        mode="abandoned_retry",
        inventory=inventory,
        replacement=replacement,
    )
    _set_payload(
        config,
        mode="abandoned_retry",
        approval=approval,
        replacement=replacement,
    )
    evidence = run_transition(config, now=NOW)
    archive_vars = (
        config.release_root
        / "stage-history"
        / config.stage
        / evidence["archive_id"]
        / "environment.tfvars.json"
    )
    _write_private(archive_vars, original + b" ")

    with pytest.raises(StageTransitionError, match="archived stage artifacts"):
        run_transition(config, now=NOW + timedelta(minutes=1))


def test_abandoned_generation_rejects_a_successful_result(tmp_path: Path) -> None:
    config = _config(tmp_path)
    original = _canonical({"deploy_workloads": False})
    replacement = _canonical({"deploy_workloads": False, "retry": True})
    _write_private(config.stage_root / "environment.tfvars.json", original)
    plan = b"binary-plan"
    _write_private(config.stage_root / "plan.tfplan", plan)
    review = {"schema_version": 1, "plan_sha256": _hash(plan)}
    _write_private(config.stage_root / "review.json", _canonical(review))
    _write_private(config.stage_root / "approval.json", _canonical({"schema_version": 1}))
    _write_private(
        config.stage_root / "result.json",
        _canonical({"schema_version": 1, "plan_sha256": _hash(plan)}),
    )
    inventory = inspect_stage(config, now=NOW)["current_artifacts"]
    approval = _approval(
        config,
        mode="abandoned_retry",
        inventory=inventory,
        replacement=replacement,
    )
    _set_payload(
        config,
        mode="abandoned_retry",
        approval=approval,
        replacement=replacement,
    )

    with pytest.raises(StageTransitionError, match="cannot be abandoned"):
        run_transition(config, now=NOW)


def test_abandoned_generation_archives_partial_zero_byte_apply_artifact(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    original = _canonical({"deploy_workloads": False})
    replacement = _canonical({"deploy_workloads": False, "retry": True})
    _write_private(config.stage_root / "environment.tfvars.json", original)
    _write_private(config.stage_root / "result.json", b"")
    inventory = inspect_stage(config, now=NOW)["current_artifacts"]
    assert inventory["result_sha256"] == hashlib.sha256(b"").hexdigest()
    assert inspect_stage(config, now=NOW)["successful_result_present"] is False
    approval = _approval(
        config,
        mode="abandoned_retry",
        inventory=inventory,
        replacement=replacement,
    )
    _set_payload(
        config,
        mode="abandoned_retry",
        approval=approval,
        replacement=replacement,
    )

    evidence = run_transition(config, now=NOW)
    assert evidence["successful_result_archived"] is False


def test_planned_workloads_progression_allows_only_dns_ready_and_fresh_probe(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "workloads")
    old_values = {
        "deploy_workloads": True,
        "web_custom_domain": "beta.cosmaneura.com",
        "web_custom_domain_dns_ready": False,
        "web_origin": "https://beta.cosmaneura.com",
        "runner_live_network_evidence_reference": "runner-network:sha256:" + "1" * 64,
        "image_digest": "2" * 64,
    }
    new_values = {
        **old_values,
        "web_custom_domain_dns_ready": True,
        "runner_live_network_evidence_reference": "runner-network:sha256:" + "3" * 64,
    }
    original = _canonical(old_values)
    replacement = _canonical(new_values)
    _write_private(config.stage_root / "environment.tfvars.json", original)
    plan = b"workload-plan"
    _write_private(config.stage_root / "plan.tfplan", plan)
    review = {"schema_version": 1, "plan_sha256": _hash(plan)}
    _write_private(config.stage_root / "review.json", _canonical(review))
    _write_private(config.stage_root / "approval.json", _canonical({"schema_version": 1}))
    _write_private(
        config.stage_root / "result.json",
        _canonical({"schema_version": 1, "plan_sha256": _hash(plan)}),
    )
    inventory = inspect_stage(config, now=NOW)["current_artifacts"]
    approval = _approval(
        config,
        mode="planned_workloads_progression",
        inventory=inventory,
        replacement=replacement,
    )
    _set_payload(
        config,
        mode="planned_workloads_progression",
        approval=approval,
        replacement=replacement,
    )

    evidence = run_transition(config, now=NOW)
    assert evidence["transition_mode"] == "planned_workloads_progression"
    assert evidence["successful_result_archived"] is True


def test_planned_workloads_progression_rejects_unrelated_change(tmp_path: Path) -> None:
    config = _config(tmp_path, "workloads")
    old_values = {
        "deploy_workloads": True,
        "web_custom_domain": "beta.cosmaneura.com",
        "web_custom_domain_dns_ready": False,
        "web_origin": "https://beta.cosmaneura.com",
        "runner_live_network_evidence_reference": "old-probe",
        "api_min_replicas": 1,
    }
    new_values = {
        **old_values,
        "web_custom_domain_dns_ready": True,
        "runner_live_network_evidence_reference": "new-probe",
        "api_min_replicas": 2,
    }
    _write_private(config.stage_root / "environment.tfvars.json", _canonical(old_values))
    plan = b"workload-plan"
    _write_private(config.stage_root / "plan.tfplan", plan)
    _write_private(
        config.stage_root / "review.json",
        _canonical({"schema_version": 1, "plan_sha256": _hash(plan)}),
    )
    _write_private(config.stage_root / "approval.json", _canonical({"schema_version": 1}))
    _write_private(
        config.stage_root / "result.json",
        _canonical({"schema_version": 1, "plan_sha256": _hash(plan)}),
    )
    replacement = _canonical(new_values)
    inventory = inspect_stage(config, now=NOW)["current_artifacts"]
    approval = _approval(
        config,
        mode="planned_workloads_progression",
        inventory=inventory,
        replacement=replacement,
    )
    _set_payload(
        config,
        mode="planned_workloads_progression",
        approval=approval,
        replacement=replacement,
    )

    with pytest.raises(StageTransitionError, match="unrelated tfvars"):
        run_transition(config, now=NOW)


def test_transition_rejects_stale_or_tampered_authorization(tmp_path: Path) -> None:
    config = _config(tmp_path)
    original = _canonical({"deploy_workloads": False})
    replacement = _canonical({"deploy_workloads": False, "retry": True})
    _write_private(config.stage_root / "environment.tfvars.json", original)
    inventory = inspect_stage(config, now=NOW)["current_artifacts"]
    inventory["environment_tfvars_sha256"] = "f" * 64
    approval = _approval(
        config,
        mode="abandoned_retry",
        inventory=inventory,
        replacement=replacement,
        approved_at=NOW - timedelta(hours=5),
    )
    _set_payload(
        config,
        mode="abandoned_retry",
        approval=approval,
        replacement=replacement,
    )

    with pytest.raises(StageTransitionError, match="four-hour"):
        run_transition(config, now=NOW)

    approval["approved_at"] = NOW.isoformat(timespec="seconds").replace("+00:00", "Z")
    _set_payload(
        config,
        mode="abandoned_retry",
        approval=approval,
        replacement=replacement,
    )
    with pytest.raises(StageTransitionError, match="differ"):
        run_transition(config, now=NOW)
