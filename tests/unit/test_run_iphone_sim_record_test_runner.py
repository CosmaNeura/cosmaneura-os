"""CI-runnable checks for the Mac iPhone Simulator record-test runner."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run-iphone-sim-record-test.sh"

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


def test_runner_requires_node_24_before_corepack():
    text = RUNNER.read_text(encoding="utf-8")
    assert "resolve_node24" in text
    assert "Node.js 24 is required before corepack enable" in text
    assert text.index("resolve_node24") < text.index("corepack enable")
    assert "COSMAS_NODE_BIN" in text


def test_runner_documents_developer_dir_and_fails_without_xcodebuild():
    text = RUNNER.read_text(encoding="utf-8")
    assert "DEVELOPER_DIR" in text
    assert "Command Line Tools" in text
    assert "xcodebuild -version" in text
    assert "xcodebuild not found on PATH" in text


def test_runner_sets_host_arch_aware_xcodebuild_flags():
    text = RUNNER.read_text(encoding="utf-8")
    assert "ONLY_ACTIVE_ARCH=YES" in text
    assert "ARCHS=arm64" in text
    assert "EXCLUDED_ARCHS=x86_64" in text
    assert '"${ARCH_SETTINGS[@]}"' in text


def test_runner_creates_and_deletes_throwaway_simulator():
    text = RUNNER.read_text(encoding="utf-8")
    assert "simctl create" in text
    assert "CREATED_SIM_UDID" in text
    assert "simctl delete" in text
    assert "newest_iphone_devicetype" in text
    assert "select_ios_runtime_for_device" in text
    assert "simctl list runtimes -j" in text
    assert "COSMAS_SIM_NAME" in text


def _select_runtime(device_type_id: str, path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(RUNNER), "--select-runtime-for-device", device_type_id, str(path)],
        capture_output=True,
        text=True,
    )


def test_select_runtime_skips_iphone19_device_specific_and_picks_ios_27_2(tmp_path: Path):
    path = tmp_path / "runtimes-four.json"
    path.write_text(json.dumps(SIMCTL_RUNTIMES_JSON_FOUR), encoding="utf-8")

    completed = _select_runtime(IPHONE_18_PRO_MAX, path)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "com.apple.CoreSimulator.SimRuntime.iOS-27-2"
    assert "iPhone19-4" not in completed.stdout


def test_select_runtime_fails_clearly_when_device_unsupported(tmp_path: Path):
    path = tmp_path / "runtimes-duo-only.json"
    # Only the Duo-restricted runtime remains.
    payload = {
        "runtimes": [
            rt
            for rt in SIMCTL_RUNTIMES_JSON_FOUR["runtimes"]
            if rt["identifier"].endswith("iPhone19-4")
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    completed = _select_runtime(IPHONE_18_PRO_MAX, path)
    assert completed.returncode != 0
    assert "No available iOS Simulator runtime supports device type" in completed.stderr
    assert IPHONE_18_PRO_MAX in completed.stderr
