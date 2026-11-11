"""CI-runnable checks for the Mac iPhone Simulator record-test runner."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run-iphone-sim-record-test.sh"


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
    assert "COSMAS_SIM_NAME" in text
