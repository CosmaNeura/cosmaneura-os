"""CI wrappers for standalone render Node suites that synth-ci would otherwise miss.

Runs in a `python-tests-migrate` backend shard (positional). Missing `node`
raises AssertionError (fail, never skip).

Covers the account-delete staging contract fingerprints, production-review
key-name allowance, and capture/tools DNS/egress pins in:
  infra/standalone/render-capture-tools.test.mjs
  infra/standalone/render-goldens.test.mjs
  infra/standalone/render-beta.test.mjs
  infra/standalone/render.test.mjs

Mutation note: dropping a path from NODE_SUITES, or removing the
returncode assertion, lets golden/fingerprint or review-name drift leave CI green.
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
    "infra/standalone/render-beta.test.mjs",
    "infra/standalone/render.test.mjs",
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


def test_node_suites_tuple_covers_capture_tools_goldens_and_review() -> None:
    """Source pin: CI must keep fingerprint and review-name suites in the wrapper."""
    text = Path(__file__).read_text(encoding="utf-8")
    assert "render-capture-tools.test.mjs" in text
    assert "render-goldens.test.mjs" in text
    assert "render-beta.test.mjs" in text
    assert "render.test.mjs" in text
    assert "MAIN_OWNED_STAGING_FINGERPRINT" in (
        ROOT / "infra/standalone/render-capture-tools.test.mjs"
    ).read_text(encoding="utf-8")
    goldens = (ROOT / "infra/standalone/render-goldens.test.mjs").read_text(
        encoding="utf-8"
    )
    assert "OWNED_STAGING_FINGERPRINT" in goldens
    assert "DEDICATED_SHARED_STAGING_FINGERPRINT" in goldens
    beta = (ROOT / "infra/standalone/render-beta.test.mjs").read_text(encoding="utf-8")
    assert "optional_exact_names" in beta
    assert "key_vault_secret_names" in beta
    assert "ACCOUNT_DELETE_CLERK_SECRET_KEY" in beta
