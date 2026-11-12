"""CI checks for the UI-test Xcode project generator (Mac stock Python 3.9)."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "clients/apple/ui-tests/generate-uitest-project.py"


def test_generate_uitest_project_has_no_zip_strict() -> None:
    """Mac /usr/bin/python3 is 3.9.6; zip(..., strict=True) raises TypeError there."""
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "zip":
            for keyword in node.keywords:
                assert keyword.arg != "strict", "zip(..., strict=) is not Python 3.9-safe"
    assert "strict=True" not in source
    assert "_zip_equal" in source


def test_generate_uitest_project_runs_under_current_python(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    project = ROOT / "clients/apple/ui-tests/CosmasSyntheticUITests.xcodeproj/project.pbxproj"
    assert project.is_file()
    blob = project.read_text(encoding="utf-8")
    assert "MicrophonePermissionUITests.swift" in blob
