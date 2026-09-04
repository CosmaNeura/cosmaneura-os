from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "beta" / "release_recovery_acceptance.py"
_SPEC = importlib.util.spec_from_file_location("cosmas_release_recovery_acceptance", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
recovery = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = recovery
_SPEC.loader.exec_module(recovery)

Config = recovery.Config
CommandResult = recovery.CommandResult
RecoveryError = recovery.RecoveryError
run_recovery = recovery.run_recovery

SUBSCRIPTION = "00000000-0000-4000-8000-000000000101"
RESOURCE_GROUP = "rg-cosmas-os-beta-testbeta"
BETA_ID = "testbeta"
REGISTRY = "cosmastest.azurecr.io"
CURRENT_SOURCE = "a" * 40
PRIOR_SOURCE = "b" * 40
CURRENT_API = "sha256:" + "1" * 64
CURRENT_WEB = "sha256:" + "2" * 64
PRIOR_API = "sha256:" + "3" * 64
PRIOR_WEB = "sha256:" + "4" * 64


def _identity(name: str) -> str:
    return (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}/providers/"
        f"Microsoft.ManagedIdentity/userAssignedIdentities/{name}"
    )


def _resource_id(kind: str) -> str:
    return (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}/providers/"
        f"Microsoft.App/containerApps/ca-{kind}-cosmas-beta-{BETA_ID}"
    )


def _image(kind: str, digest: str) -> str:
    repository = "cosmas-os-web" if kind == "web" else "cosmas-os"
    return f"{REGISTRY}/{repository}@{digest}"


def _app(kind: str, image: str, revision: str) -> dict[str, Any]:
    identity = _identity("id-web") if kind == "web" else _identity("id-runtime")
    configuration: dict[str, Any] = {
        "activeRevisionsMode": "Single",
        "registries": [{"server": REGISTRY, "identity": identity}],
    }
    if kind != "worker":
        configuration["ingress"] = {
            "external": True,
            "allowInsecure": False,
            "targetPort": 8080 if kind == "web" else 8000,
            "fqdn": f"{kind}.example.invalid",
            "traffic": [{"latestRevision": True, "weight": 100}],
        }
    return {
        "id": _resource_id(kind),
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {identity: {}},
        },
        "tags": {
            "track": "B",
            "product": "cosmas-os",
            "env": "early_adopter_beta",
            "deployment_mode": "synthetic_lab",
            "data_classification": "synthetic-only",
        },
        "properties": {
            "provisioningState": "Succeeded",
            "latestRevisionName": revision,
            "latestReadyRevisionName": revision,
            "configuration": configuration,
            "template": {
                "revisionSuffix": revision.rsplit("--", 1)[-1],
                "scale": {"minReplicas": 0 if kind == "web" else 1, "maxReplicas": 1},
                "containers": [{"name": kind, "image": image, "env": []}],
            },
        },
    }


def _revision(kind: str, image: str, name: str, *, active: bool = True) -> dict[str, Any]:
    return {
        "id": f"{_resource_id(kind)}/revisions/{name}",
        "name": name,
        "properties": {
            "active": active,
            "healthState": "Healthy",
            "provisioningState": "Provisioned",
            "replicas": 0 if kind == "web" else 1,
            "template": {"containers": [{"name": kind, "image": image}]},
        },
    }


class FakeRunner:
    def __init__(self) -> None:
        self.apps: dict[str, dict[str, Any]] = {}
        self.revisions: dict[str, list[dict[str, Any]]] = {}
        self.patch_images: list[str] = []
        for kind, digest in (
            ("api", CURRENT_API),
            ("worker", CURRENT_API),
            ("web", CURRENT_WEB),
        ):
            name = f"ca-{kind}-cosmas-beta-{BETA_ID}--r1"
            self.apps[kind] = _app(kind, _image(kind, digest), name)
            self.revisions[kind] = [_revision(kind, _image(kind, digest), name)]

    def run(self, argv: list[str] | tuple[str, ...]) -> CommandResult:
        if argv[0] == "curl":
            return CommandResult(
                0,
                '{"status":"ready","env":"early_adopter_beta"}\n'
                if argv[-1].endswith("/ready")
                else "ok\n",
            )
        assert argv[:3] == ["az", "rest", "--method"]
        method = argv[3]
        url = argv[argv.index("--url") + 1]
        kind = next(kind for kind in ("api", "worker", "web") if f"ca-{kind}-" in url)
        if method == "get":
            value: dict[str, Any]
            if "/revisions?" in url:
                value = {"value": self.revisions[kind]}
            else:
                value = self.apps[kind]
            return CommandResult(0, json.dumps(value))
        assert method == "patch"
        body_arg = argv[argv.index("--body") + 1]
        assert body_arg.startswith("@")
        body = json.loads(Path(body_arg[1:]).read_text(encoding="utf-8"))
        image = body["properties"]["template"]["containers"][0]["image"]
        assert "@sha256:" in image
        self.patch_images.append(image)
        for revision in self.revisions[kind]:
            revision["properties"]["active"] = False
        number = len(self.revisions[kind]) + 1
        name = f"ca-{kind}-cosmas-beta-{BETA_ID}--r{number}"
        self.apps[kind]["properties"]["template"] = body["properties"]["template"]
        self.apps[kind]["properties"]["latestRevisionName"] = name
        self.apps[kind]["properties"]["latestReadyRevisionName"] = name
        self.revisions[kind].append(_revision(kind, image, name))
        return CommandResult(0, "")


class FailingPatchRunner(FakeRunner):
    def __init__(self) -> None:
        super().__init__()
        self.fail_patches = False

    def run(self, argv: list[str] | tuple[str, ...]) -> CommandResult:
        if self.fail_patches and argv[0] == "az" and argv[3] == "patch":
            return CommandResult(1, "", "simulated failure")
        return super().run(argv)


def _environment(
    tmp_path: Path,
    operation: str,
    *,
    approval_sha256: str = "5" * 64,
    rollback_state_sha256: str | None = None,
) -> dict[str, str]:
    tmp_path.chmod(0o700)
    return {
        "COSMAS_RECOVERY_OPERATION": operation,
        "COSMAS_RECOVERY_SUBSCRIPTION_ID": SUBSCRIPTION,
        "COSMAS_RECOVERY_RESOURCE_GROUP": RESOURCE_GROUP,
        "COSMAS_RECOVERY_BETA_ID": BETA_ID,
        "COSMAS_RECOVERY_REGISTRY": REGISTRY,
        "COSMAS_RECOVERY_RUNTIME_IDENTITY_ID": _identity("id-runtime"),
        "COSMAS_RECOVERY_WEB_IDENTITY_ID": _identity("id-web"),
        "COSMAS_RECOVERY_API_READY_URL": "https://api.example.invalid/ready",
        "COSMAS_RECOVERY_WEB_HEALTH_URL": "https://web.example.invalid/healthz",
        "COSMAS_RECOVERY_CURRENT_SOURCE_SHA": CURRENT_SOURCE,
        "COSMAS_RECOVERY_CURRENT_RELEASE_ID": "current-release",
        "COSMAS_RECOVERY_CURRENT_API_DIGEST": CURRENT_API,
        "COSMAS_RECOVERY_CURRENT_WEB_DIGEST": CURRENT_WEB,
        "COSMAS_RECOVERY_PRIOR_SOURCE_SHA": PRIOR_SOURCE,
        "COSMAS_RECOVERY_PRIOR_RELEASE_ID": "prior-release",
        "COSMAS_RECOVERY_PRIOR_API_DIGEST": PRIOR_API,
        "COSMAS_RECOVERY_PRIOR_WEB_DIGEST": PRIOR_WEB,
        "COSMAS_RECOVERY_APPROVAL_SHA256": approval_sha256,
        "COSMAS_RECOVERY_STATE_PATH": str(tmp_path / "state.private.json"),
        "COSMAS_RECOVERY_POLL_ATTEMPTS": "1",
        "COSMAS_RECOVERY_POLL_INTERVAL_SECONDS": "0",
    } | (
        {"COSMAS_RECOVERY_ROLLBACK_STATE_SHA256": rollback_state_sha256}
        if rollback_state_sha256 is not None
        else {}
    )


def test_exact_digest_rollback_then_forward_is_resumable(tmp_path: Path) -> None:
    runner = FakeRunner()
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    rollback = run_recovery(
        Config.from_environment(_environment(tmp_path, "rollback")), runner, now=now
    )

    assert rollback["status"] == "rolled_back_healthy"
    assert rollback["mutable_tags_used"] is False
    assert set(rollback["result_revision_ids"]) == {"api", "worker", "web"}
    assert all("@sha256:" in image for image in runner.patch_images)

    forward_environment = _environment(
        tmp_path,
        "forward",
        approval_sha256="6" * 64,
        rollback_state_sha256=rollback["state_sha256"],
    )
    forward = run_recovery(Config.from_environment(forward_environment), runner, now=now)
    assert forward["status"] == "forward_restored_healthy"
    assert forward["configuration_unchanged_except_exact_digest"] is True
    assert len(runner.patch_images) == 6

    repeated = run_recovery(Config.from_environment(forward_environment), runner, now=now)
    assert repeated["status"] == "forward_restored_healthy"
    assert len(runner.patch_images) == 6


def test_recovery_rejects_mutable_or_same_release_inputs(tmp_path: Path) -> None:
    environment = _environment(tmp_path, "rollback")
    environment["COSMAS_RECOVERY_PRIOR_API_DIGEST"] = "latest"
    with pytest.raises(RecoveryError, match="configuration invalid"):
        Config.from_environment(environment)

    environment = _environment(tmp_path, "rollback")
    environment["COSMAS_RECOVERY_PRIOR_WEB_DIGEST"] = CURRENT_API
    with pytest.raises(RecoveryError, match="configuration invalid"):
        Config.from_environment(environment)

    environment = _environment(tmp_path, "rollback")
    environment["COSMAS_RECOVERY_PRIOR_SOURCE_SHA"] = CURRENT_SOURCE
    with pytest.raises(RecoveryError, match="configuration invalid"):
        Config.from_environment(environment)


def test_forward_rejects_configuration_drift(tmp_path: Path) -> None:
    runner = FakeRunner()
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    run_recovery(Config.from_environment(_environment(tmp_path, "rollback")), runner, now=now)
    state = json.loads((tmp_path / "state.private.json").read_text(encoding="utf-8"))
    runner.apps["api"]["properties"]["configuration"]["ingress"]["targetPort"] = 9999

    with pytest.raises(RecoveryError):
        run_recovery(
            Config.from_environment(
                _environment(
                    tmp_path,
                    "forward",
                    approval_sha256="6" * 64,
                    rollback_state_sha256=state["state_sha256"],
                )
            ),
            runner,
            now=now,
        )


def test_forward_rejects_tampered_private_state(tmp_path: Path) -> None:
    runner = FakeRunner()
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    config = Config.from_environment(_environment(tmp_path, "rollback"))
    run_recovery(config, runner, now=now)
    state = json.loads(config.state_path.read_text(encoding="utf-8"))
    state["binding"]["prior"]["api_digest"] = "sha256:" + "9" * 64
    config.state_path.write_text(json.dumps(state), encoding="utf-8")
    config.state_path.chmod(0o600)

    with pytest.raises(RecoveryError, match="state invalid"):
        run_recovery(
            Config.from_environment(
                _environment(
                    tmp_path,
                    "forward",
                    approval_sha256="6" * 64,
                    rollback_state_sha256=state["state_sha256"],
                )
            ),
            runner,
            now=now,
        )


def test_forward_requires_distinct_authorization_bound_to_exact_rollback_state(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    rollback = run_recovery(
        Config.from_environment(_environment(tmp_path, "rollback")), runner, now=now
    )

    with pytest.raises(RecoveryError, match="configuration invalid"):
        Config.from_environment(_environment(tmp_path, "forward"))

    wrong_state = _environment(
        tmp_path,
        "forward",
        approval_sha256="6" * 64,
        rollback_state_sha256="7" * 64,
    )
    with pytest.raises(RecoveryError, match="different rollback state"):
        run_recovery(Config.from_environment(wrong_state), runner, now=now)

    correct = _environment(
        tmp_path,
        "forward",
        approval_sha256="6" * 64,
        rollback_state_sha256=rollback["state_sha256"],
    )
    evidence = run_recovery(Config.from_environment(correct), runner, now=now)
    assert evidence["approval_sha256"] == "6" * 64
    assert evidence["rollback_state_sha256"] == rollback["state_sha256"]


def test_partial_forward_accepts_fresh_authorization_for_same_rollback_checkpoint(
    tmp_path: Path,
) -> None:
    runner = FailingPatchRunner()
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    rollback = run_recovery(
        Config.from_environment(_environment(tmp_path, "rollback")), runner, now=now
    )
    first = _environment(
        tmp_path,
        "forward",
        approval_sha256="6" * 64,
        rollback_state_sha256=rollback["state_sha256"],
    )
    runner.fail_patches = True
    with pytest.raises(RecoveryError, match="update failed"):
        run_recovery(Config.from_environment(first), runner, now=now)

    state_path = tmp_path / "state.private.json"
    interrupted = json.loads(state_path.read_text(encoding="utf-8"))
    assert interrupted["phase"] == "forward_requested"
    assert [item["approval_sha256"] for item in interrupted["forward_authorizations"]] == ["6" * 64]

    runner.fail_patches = False
    fresh = _environment(
        tmp_path,
        "forward",
        approval_sha256="7" * 64,
        rollback_state_sha256=rollback["state_sha256"],
    )
    evidence = run_recovery(Config.from_environment(fresh), runner, now=now)
    assert evidence["status"] == "forward_restored_healthy"
    completed = json.loads(state_path.read_text(encoding="utf-8"))
    assert [item["approval_sha256"] for item in completed["forward_authorizations"]] == [
        "6" * 64,
        "7" * 64,
    ]


def test_completed_forward_accepts_fresh_authorization_if_wrapper_evidence_was_lost(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    rollback = run_recovery(
        Config.from_environment(_environment(tmp_path, "rollback")), runner, now=now
    )
    first = _environment(
        tmp_path,
        "forward",
        approval_sha256="6" * 64,
        rollback_state_sha256=rollback["state_sha256"],
    )
    run_recovery(Config.from_environment(first), runner, now=now)
    patch_count = len(runner.patch_images)

    fresh = _environment(
        tmp_path,
        "forward",
        approval_sha256="7" * 64,
        rollback_state_sha256=rollback["state_sha256"],
    )
    evidence = run_recovery(Config.from_environment(fresh), runner, now=now)
    assert evidence["approval_sha256"] == "7" * 64
    assert len(runner.patch_images) == patch_count


def test_partial_and_completed_rollback_accept_fresh_authorization(
    tmp_path: Path,
) -> None:
    runner = FailingPatchRunner()
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    runner.fail_patches = True
    with pytest.raises(RecoveryError, match="update failed"):
        run_recovery(Config.from_environment(_environment(tmp_path, "rollback")), runner, now=now)
    interrupted = json.loads((tmp_path / "state.private.json").read_text(encoding="utf-8"))
    assert interrupted["phase"] == "rollback_requested"

    runner.fail_patches = False
    second = _environment(tmp_path, "rollback", approval_sha256="6" * 64)
    evidence = run_recovery(Config.from_environment(second), runner, now=now)
    assert evidence["approval_sha256"] == "6" * 64

    patch_count = len(runner.patch_images)
    third = _environment(tmp_path, "rollback", approval_sha256="7" * 64)
    repeated = run_recovery(Config.from_environment(third), runner, now=now)
    assert repeated["approval_sha256"] == "7" * 64
    assert len(runner.patch_images) == patch_count
    completed = json.loads((tmp_path / "state.private.json").read_text(encoding="utf-8"))
    assert [item["approval_sha256"] for item in completed["rollback_authorizations"]] == [
        "5" * 64,
        "6" * 64,
        "7" * 64,
    ]
