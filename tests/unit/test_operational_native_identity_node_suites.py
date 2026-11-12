"""CI wrappers for Node identity suites that synth-ci would otherwise miss.

B11 mutation note: dropping any listed suite from NODE_SUITES, or commenting out
the subprocess.run check, lets host-allow-list / drift / transition regressions
leave CI green. Keep the tuple and returncode assertion intact.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Suites proving operational-beta-v1 dual-host set, PENDING_SWIFT_PR drift,
# desktop loader fence, and transition fixture on clerk.staging.cosmas.ai.
NODE_SUITES = (
    "clients/shared/operational-native-identity.test.mjs",
    "clients/shared/native-clerk-host-drift.test.mjs",
    "clients/desktop/native-identity-config.test.mjs",
    "scripts/transition-desktop-identity.test.mjs",
)


def _require_node() -> str:
    found = shutil.which("node")
    if found is None:
        raise AssertionError("node is required for operational native identity Node suites")
    return found


@pytest.mark.parametrize("relative", NODE_SUITES)
def test_operational_native_identity_node_suite(relative: str) -> None:
    node = _require_node()
    path = ROOT / relative
    assert path.is_file(), relative
    result = subprocess.run(
        [node, "--test", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, f"{relative}\n{result.stdout}\n{result.stderr}"


def test_node_suites_tuple_covers_shipped_beta_and_pending_swift() -> None:
    """Source pin: CI must keep drift + transition suites in the wrapper list."""
    text = Path(__file__).read_text(encoding="utf-8")
    assert "native-clerk-host-drift.test.mjs" in text
    assert "transition-desktop-identity.test.mjs" in text
    assert "PENDING_SWIFT_PR" in (
        ROOT / "clients/shared/native-clerk-host-drift.test.mjs"
    ).read_text(encoding="utf-8")
    assert "clerk.staging.cosmas.ai" in (
        ROOT / "scripts/transition-desktop-identity.test.mjs"
    ).read_text(encoding="utf-8")
