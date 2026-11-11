"""CI-runnable checks for the Mac iPhone Simulator record-test runner."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run-iphone-sim-record-test.sh"

# Old simctl format: SimRuntime id lives inside the parentheses after ` - `.
SIMCTL_RUNTIMES_OLD_PARENS_ID = """\
== Runtimes ==
iOS 17.5 (17.5 - com.apple.CoreSimulator.SimRuntime.iOS-17-5) (available)
iOS 18.4 (18.4 - com.apple.CoreSimulator.SimRuntime.iOS-18-4) (available)
tvOS 18.2 (18.2 - com.apple.CoreSimulator.SimRuntime.tvOS-18-2) (available)
"""

# macOS 27 / Xcode 27 format: build lives in parens; id follows `) - `.
# The previous `()`-split parser kept a leading ` - ` on the id.
SIMCTL_RUNTIMES_MACOS27 = """\
== Runtimes ==
iOS 26.1 (26.1 - 23B77) - com.apple.CoreSimulator.SimRuntime.iOS-26-1
iOS 27.0 (27.0 - 25A362) - com.apple.CoreSimulator.SimRuntime.iOS-27-0
watchOS 27.0 (27.0 - 25R362) - com.apple.CoreSimulator.SimRuntime.watchOS-27-0
"""

SIMCTL_RUNTIMES_MIXED = """\
== Runtimes ==
iOS 18.4 (18.4 - com.apple.CoreSimulator.SimRuntime.iOS-18-4) (available)
iOS 27.0 (27.0 - 25A362) - com.apple.CoreSimulator.SimRuntime.iOS-27-0
iOS 26.0 (26.0 - 23A339) - com.apple.CoreSimulator.SimRuntime.iOS-26-0
"""


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
    assert "newest_ios_runtime" in text
    assert "parse_newest_ios_runtime" in text
    assert r"com\.apple\.CoreSimulator\.SimRuntime\.[A-Za-z0-9-]+" in text
    assert "COSMAS_SIM_NAME" in text


def _parse_runtimes_file(path: Path) -> str:
    completed = subprocess.run(
        ["bash", str(RUNNER), "--parse-runtimes-file", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_newest_ios_runtime_parses_old_parens_id_and_macos27_formats(tmp_path: Path):
    old = tmp_path / "runtimes-old.txt"
    old.write_text(SIMCTL_RUNTIMES_OLD_PARENS_ID, encoding="utf-8")
    assert _parse_runtimes_file(old) == "com.apple.CoreSimulator.SimRuntime.iOS-18-4"

    macos27 = tmp_path / "runtimes-macos27.txt"
    macos27.write_text(SIMCTL_RUNTIMES_MACOS27, encoding="utf-8")
    parsed = _parse_runtimes_file(macos27)
    assert parsed == "com.apple.CoreSimulator.SimRuntime.iOS-27-0"
    assert not parsed.startswith(" - ")
    assert " " not in parsed

    mixed = tmp_path / "runtimes-mixed.txt"
    mixed.write_text(SIMCTL_RUNTIMES_MIXED, encoding="utf-8")
    assert _parse_runtimes_file(mixed) == "com.apple.CoreSimulator.SimRuntime.iOS-27-0"
