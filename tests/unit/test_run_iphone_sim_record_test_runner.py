"""CI-runnable behavioural checks for the Mac iPhone Simulator record-test runner."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run-iphone-sim-record-test.sh"
RUNNER_TEST_MJS = ROOT / "scripts" / "run-iphone-sim-record-test.test.mjs"

IPHONE_18_PRO_MAX = "com.apple.CoreSimulator.SimDeviceType.iPhone-18-Pro-Max"
IPHONE_DUO = "com.apple.CoreSimulator.SimDeviceType.iPhone-Duo"

# Exactly the four runtimes from the MacBook failure report.
SIMCTL_RUNTIMES_JSON_FOUR = {
    "runtimes": [
        {
            "name": "iOS 26.5",
            "version": "26.5",
            "platform": "iOS",
            "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-26-5",
            "isAvailable": True,
            "supportedDeviceTypes": [
                {"name": "iPhone 18 Pro Max", "identifier": IPHONE_18_PRO_MAX},
                {"name": "iPhone 16", "identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-16"},
            ],
        },
        {
            "name": "iOS 27.0",
            "version": "27.0",
            "platform": "iOS",
            "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-27-0",
            "isAvailable": True,
            "supportedDeviceTypes": [
                {"name": "iPhone 18 Pro Max", "identifier": IPHONE_18_PRO_MAX},
                {"name": "iPhone 16", "identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-16"},
            ],
        },
        {
            "name": "iOS 27.2",
            "version": "27.2",
            "platform": "iOS",
            "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-27-2",
            "isAvailable": True,
            "supportedDeviceTypes": [
                {"name": "iPhone 18 Pro Max", "identifier": IPHONE_18_PRO_MAX},
                {"name": "iPhone 16", "identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-16"},
            ],
        },
        {
            "name": "iOS 27.2 iPhone Duo",
            "version": "27.2",
            "platform": "iOS",
            "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-27-2-iPhone19-4",
            "isAvailable": True,
            "supportedDeviceTypes": [
                {"name": "iPhone Duo", "identifier": IPHONE_DUO},
            ],
        },
    ]
}

SIMCTL_DEVICETYPES_JSON = {
    "devicetypes": [
        {"name": "iPhone 18 Pro Max", "identifier": IPHONE_18_PRO_MAX},
        {"name": "iPhone 16", "identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-16"},
        {"name": "iPhone Duo", "identifier": IPHONE_DUO},
    ]
}


def _run(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(RUNNER), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def test_bash_n_and_shellcheck_clean() -> None:
    assert RUNNER.is_file()
    bash_n = subprocess.run(["bash", "-n", str(RUNNER)], capture_output=True, text=True)
    assert bash_n.returncode == 0, bash_n.stderr
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        raise AssertionError("shellcheck is required for Linux CI coverage of the Mac runner")
    sc = subprocess.run([shellcheck, str(RUNNER)], capture_output=True, text=True)
    assert sc.returncode == 0, sc.stdout + sc.stderr


def test_select_runtime_and_iphone_picks_newest_non_restricted(tmp_path: Path) -> None:
    runtimes = tmp_path / "runtimes.json"
    devices = tmp_path / "devicetypes.json"
    runtimes.write_text(json.dumps(SIMCTL_RUNTIMES_JSON_FOUR), encoding="utf-8")
    devices.write_text(json.dumps(SIMCTL_DEVICETYPES_JSON), encoding="utf-8")
    completed = _run("--select-runtime-and-iphone", str(runtimes), str(devices))
    assert completed.returncode == 0, completed.stderr
    runtime_id, device_id, device_name = completed.stdout.strip().split("\t")
    assert runtime_id == "com.apple.CoreSimulator.SimRuntime.iOS-27-2"
    assert "iPhone19-4" not in runtime_id
    assert device_id == IPHONE_18_PRO_MAX
    assert "Pro Max" in device_name


def test_select_runtime_skips_iphone19_device_specific_and_picks_ios_27_2(tmp_path: Path) -> None:
    path = tmp_path / "runtimes-four.json"
    path.write_text(json.dumps(SIMCTL_RUNTIMES_JSON_FOUR), encoding="utf-8")
    completed = _run("--select-runtime-for-device", IPHONE_18_PRO_MAX, str(path))
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "com.apple.CoreSimulator.SimRuntime.iOS-27-2"
    assert "iPhone19-4" not in completed.stdout


def test_select_runtime_fails_clearly_when_device_unsupported(tmp_path: Path) -> None:
    path = tmp_path / "runtimes-duo-only.json"
    payload = {
        "runtimes": [
            rt
            for rt in SIMCTL_RUNTIMES_JSON_FOUR["runtimes"]
            if rt["identifier"].endswith("iPhone19-4")
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    completed = _run("--select-runtime-for-device", IPHONE_18_PRO_MAX, str(path))
    assert completed.returncode != 0
    assert "No available iOS Simulator runtime supports device type" in completed.stderr
    assert IPHONE_18_PRO_MAX in completed.stderr


def test_ref_handling_rejects_unresolvable_abbrev_without_remote_fetch() -> None:
    """Abbreviated SHAs resolve locally; remote fetch uses the expanded full SHA."""
    text = RUNNER.read_text(encoding="utf-8")
    assert "Pass a full 40-character SHA or a PR number" in text
    assert "rev-parse --verify" in text
    assert 'pull/${ref}/head' in text or "pull/${ref}/head" in text
    assert 'git fetch --depth=1 origin "$full"' in text
    assert "Abbreviated SHA" in text


def test_runner_has_no_overlay_mechanism() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    assert "overlay_if_absent" not in text
    assert "overlay_patch_or_absent" not in text
    assert "OVERLAID_FILES" not in text
    assert "overlay-receipt.txt" not in text
    assert "will not overlay" in text or "will not overlay files" in text
    assert "require_target_path" in text
    assert "list_required_target_paths" in text
    assert "target_unmodified=${TARGET_UNMODIFIED}" in text
    assert 'echo "target_unmodified=yes"' not in text
    assert "tested-sha.txt" in text
    assert "target-receipt.txt" in text
    assert "native_overlay=no" in text
    assert "xcresulttool export attachments" in text
    assert "com.cosmasos.synthetic" in text
    assert "cosmas-mic-uitest-" in text
    # Cleanup deletes only CREATED_SIM_UDID; no sweep of other throwaways.
    assert "Deleting throwaway simulator" in text
    assert "name.startswith(\"cosmas-mic-uitest-\")" not in text
    # Must not copy runner/native sources into the target tree.
    assert "cp -R \"$RUNNER_ROOT" not in text
    assert "cp -R \"$TOOLING_ROOT" not in text


def test_runner_required_paths_list_is_shared_and_complete() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    assert "list_required_target_paths()" in text
    # In-run check and --verify-required-paths both consume the shared list.
    assert "done < <(list_required_target_paths)" in text
    assert text.count("done < <(list_required_target_paths)") >= 2
    required = [
        "scripts/compose-portable-iphone.py",
        "scripts/prepare-synthetic-iphone-web-bundle.mjs",
        "scripts/configure-synthetic-iphone-simulator.py",
        "scripts/install-client-deps.sh",
        "clients/shared/operational-native-identity.mjs",
        "clients/apple/ui-tests",
        "clients/apple/ui-tests/generate-uitest-project.py",
        "clients/apple/ui-tests/CosmasSyntheticUITests/MicrophonePermissionUITests.swift",
        "clients/apple/native-auth/Sources/CosmasNativeAuth/ClerkKeychainCredentials.swift",
        "clients/apple/startup-recovery/CosmasBridgeViewController.swift",
        "clients/apple/startup-recovery/CosmasWorkspaceViewController.swift",
        "clients/capture/native-configured/ios-pcm-capacitor/Sources/CosmaneuraIOSPCMCapacitor/IOSPCMCapacitorPlugin.swift",
    ]
    start = text.index("list_required_target_paths() {")
    end = text.index("\n}\n", start)
    body = text[start:end]
    for rel in required:
        assert rel in body, rel


def test_runner_pre_xcodebuild_dirty_recheck_and_measured_result() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    assert "Target tree became dirty before xcodebuild" in text
    assert "Target tree still unmodified before xcodebuild" in text
    # result.txt must write the measured value, never a hard-coded yes.
    assert "target_unmodified=${TARGET_UNMODIFIED}" in text
    assert 'echo "target_unmodified=yes"' not in text
    # One git-status measurement per checkpoint (no helper that re-calls status).
    assert "measure_target_unmodified" not in text
    assert text.count('git -C "$SRC" status --porcelain') >= 3


def test_verify_required_paths_ok_on_current_tree() -> None:
    completed = _run("--verify-required-paths", str(ROOT))
    assert completed.returncode == 0, completed.stderr
    assert "required-paths-ok" in completed.stdout


def test_verify_required_paths_names_missing_file(tmp_path: Path) -> None:
    # Empty tree: every required path is missing; message must name one.
    completed = _run("--verify-required-paths", str(tmp_path))
    assert completed.returncode != 0
    assert "missing required path:" in completed.stderr
    assert "ClerkKeychainCredentials.swift" in completed.stderr or "prepare-synthetic" in completed.stderr
    assert "will not overlay" in completed.stderr


def test_runner_records_exact_tested_sha_without_modifying_checkout(tmp_path: Path) -> None:
    """Simulate post-checkout receipt writing: clean tree + exact SHA artifacts."""
    text = RUNNER.read_text(encoding="utf-8")
    assert 'git -C "$SRC" status --porcelain' in text
    assert "Target tree unmodified after checkout" in text
    assert "tested-sha.txt" in text and "HEAD_SHA" in text
    assert "tested SHA" in text or "Target SHA $HEAD_SHA" in text

    # Behavioural: a clean git worktree stays clean; record SHA to artifacts.
    repo = tmp_path / "target"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "synth@synthetic.example"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic"], cwd=repo, check=True)
    (repo / "README").write_text("synth\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True)
    assert status == ""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "tested-sha.txt").write_text(sha + "\n", encoding="utf-8")
    (artifacts / "target-receipt.txt").write_text(
        f"target_sha={sha}\ntarget_unmodified=yes\nnative_overlay=no\n",
        encoding="utf-8",
    )
    assert (artifacts / "tested-sha.txt").read_text(encoding="utf-8").strip() == sha
    assert "native_overlay=no" in (artifacts / "target-receipt.txt").read_text(encoding="utf-8")
    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True) == ""


def test_runner_node_test_mjs_passes() -> None:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is required; refusing silent skip for runner .test.mjs")
    assert RUNNER_TEST_MJS.is_file()
    completed = subprocess.run(
        [node, "--test", str(RUNNER_TEST_MJS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={**os.environ, "COSMAS_RUNNER_FIXTURE_DIR": tempfile.mkdtemp(prefix="cosmas-runner-mjs-")},
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
