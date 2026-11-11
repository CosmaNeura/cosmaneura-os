"""CI-runnable checks for the synthetic iPhone web-bundle generator."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/prepare-synthetic-iphone-web-bundle.mjs"
TEST = ROOT / "scripts/prepare-synthetic-iphone-web-bundle.test.mjs"


def _require_node() -> str:
    found = shutil.which("node")
    if found is None:
        raise AssertionError("node is required for synthetic iPhone web-bundle checks")
    return found


def test_synthetic_web_bundle_generator_unit_suite() -> None:
    node = _require_node()
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
    assert "staging accepts *.synthetic.example" in blob or "synthetic.example" in blob


def test_synthetic_inputs_are_pk_test_and_synthetic_example_only() -> None:
    node = _require_node()
    result = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            "import {syntheticIphoneRendererInputs} from "
            f"'file://{SCRIPT.as_posix()}';"
            "console.log(JSON.stringify(syntheticIphoneRendererInputs()));",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={k: v for k, v in os.environ.items() if not k.startswith("VITE_")},
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    files = json.loads(result.stdout)
    identity = files["apple-identity.json"]
    env = files["apple-build-env.json"]
    blob = json.dumps(files)
    assert identity["publishableKey"].startswith("pk_test_")
    assert identity["apiOrigin"].endswith(".synthetic.example")
    assert identity["frontendOrigin"].endswith(".synthetic.example")
    assert env["VITE_WORKSPACE_HOSTED_API_ORIGIN"].endswith(".synthetic.example")
    assert env["VITE_WORKSPACE_DATA_MODE"] == "synthetic"
    for forbidden in ("pk_live_", "sk_live_", "sk_test_", "cosmas.ai", "cosmaneura.com"):
        assert forbidden not in blob


def test_documented_prepare_command_exists() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "prepare-synthetic-iphone-web-bundle.mjs" in text
    assert "--output" in text
    assert "*.synthetic.example" in text or ".synthetic.example" in text
    assert "pk_test_" in text
