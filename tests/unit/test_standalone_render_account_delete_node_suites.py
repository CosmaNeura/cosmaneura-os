"""CI wrappers for standalone render Node suites that synth-ci would otherwise miss.

Runs in a `python-tests-migrate` backend shard (positional). Missing `node`
raises AssertionError (fail, never skip).

Covers the T-REL-7c account-delete staging contract fingerprints and
capture/tools DNS/egress pins in:
  infra/standalone/render-capture-tools.test.mjs
  infra/standalone/render-goldens.test.mjs

Mutation note: dropping either path from NODE_SUITES, or removing the
returncode assertion, lets golden/fingerprint drift leave CI green.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

NODE_SUITES = (
    "infra/standalone/render-capture-tools.test.mjs",
    "infra/standalone/render-goldens.test.mjs",
)


def _require_node() -> str:
    found = shutil.which("node")
    if found is None:
        raise AssertionError(
            "node is required for standalone render account-delete Node suites"
        )
    return found


@pytest.mark.parametrize("relative", NODE_SUITES)
def test_standalone_render_account_delete_node_suite(relative: str) -> None:
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


def test_node_suites_tuple_covers_capture_tools_and_goldens() -> None:
    """Source pin: CI must keep both fingerprint suites in the wrapper list."""
    text = Path(__file__).read_text(encoding="utf-8")
    assert "render-capture-tools.test.mjs" in text
    assert "render-goldens.test.mjs" in text
    assert "MAIN_OWNED_STAGING_FINGERPRINT" in (
        ROOT / "infra/standalone/render-capture-tools.test.mjs"
    ).read_text(encoding="utf-8")
    goldens = (ROOT / "infra/standalone/render-goldens.test.mjs").read_text(
        encoding="utf-8"
    )
    assert "OWNED_STAGING_FINGERPRINT" in goldens
    assert "DEDICATED_SHARED_STAGING_FINGERPRINT" in goldens
