"""Python proof that Release strips DEBUG-only Simulator XCUITest hooks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "clients/apple/ui-tests/prove_release_excludes_demo_fixture.py"


def test_prove_release_excludes_demo_and_uitest_hooks() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    blob = completed.stdout + completed.stderr
    assert "PASS: synthetic demo fixture" in blob
    assert "PASS: bridge/plugin XCUITest mic hooks" in blob
