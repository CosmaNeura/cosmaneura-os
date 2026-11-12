"""CI-runnable checks for the test-only synthetic-iphone-sim-v1 identity module."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "clients/shared"
MODULE = SHARED / "synthetic-iphone-sim-identity.mjs"
TEST = SHARED / "synthetic-iphone-sim-identity.test.mjs"

_HOST_CHECK = (
    "  if (!isSyntheticExampleHost(frontendHost) || !isSyntheticExampleHost(apiHost)) unavailable();\n"
)


def _require_node() -> str:
    found = shutil.which("node")
    if found is None:
        raise AssertionError("node is required for synthetic-iphone-sim-identity checks")
    return found


def test_synthetic_iphone_sim_identity_node_suite() -> None:
    node = _require_node()
    assert MODULE.is_file()
    assert TEST.is_file()
    result = subprocess.run(
        [node, "--test", str(TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    blob = result.stdout + result.stderr
    assert "synthetic-iphone-sim-v1" in blob or "synthetic.example" in blob
    assert "operational-native-identity.mjs stays byte-identical" in blob


def test_synthetic_validator_source_requires_synthetic_example_hosts() -> None:
    text = MODULE.read_text(encoding="utf-8")
    assert _HOST_CHECK in text
    assert "function isSyntheticExampleHost" in text


def test_negative_removing_synthetic_example_host_check_fails_node_suite(tmp_path: Path) -> None:
    """Hole 4: dropping the *.synthetic.example host check must fail CI-run tests."""
    node = _require_node()
    work = tmp_path / "shared"
    work.mkdir()
    for name in (
        "synthetic-iphone-sim-identity.mjs",
        "synthetic-iphone-sim-identity.test.mjs",
        "operational-native-identity.mjs",
        "hosted-workspace-config.mjs",
    ):
        shutil.copyfile(SHARED / name, work / name)

    mutated = (work / "synthetic-iphone-sim-identity.mjs").read_text(encoding="utf-8")
    assert _HOST_CHECK in mutated
    # Comment out the host check (same effect as removal for the validator body).
    leaked = mutated.replace(
        _HOST_CHECK,
        "  // REMOVED for negative proof: isSyntheticExampleHost check\n",
        1,
    )
    assert leaked != mutated
    (work / "synthetic-iphone-sim-identity.mjs").write_text(leaked, encoding="utf-8")

    result = subprocess.run(
        [node, "--test", str(work / "synthetic-iphone-sim-identity.test.mjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode != 0, result.stdout + "\n" + result.stderr
    blob = result.stdout + result.stderr
    assert re.search(r"not ok|fail|AssertionError|Expected", blob, re.I)
