"""The local CI runner executes the caller-selected Node, not a tools-directory shadow."""

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path


def test_selected_node_survives_an_openssl_directory_containing_an_older_node(tmp_path, monkeypatch):
    chosen = tmp_path / "node24"
    alternate = tmp_path / "other-tools"
    pg = tmp_path / "postgres"
    python = tmp_path / "python" / "python"
    for folder in (chosen, alternate, pg, python.parent):
        folder.mkdir()
    for file, output in ((chosen / "node", "v24.19.0"), (alternate / "node", "v22.23.2"),
            (alternate / "openssl", "invented-openssl"), (pg / "psql", "invented-postgres")):
        file.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\n")
        file.chmod(0o700)
    monkeypatch.setenv("PATH", os.pathsep.join((str(chosen), str(alternate), os.defpath)))
    script = Path(__file__).resolve().parents[2] / "scripts/check-backend-local.py"
    spec = importlib.util.spec_from_file_location("local_backend_runtime", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = module.child_tool_path(pg, python)
    result = subprocess.run(["node", "--version"], env={"PATH": path}, check=True,
        capture_output=True, text=True, timeout=5)
    assert result.stdout.strip() == "v24.19.0"
    assert shutil.which("openssl", path=path) == str(alternate / "openssl")
    assert shutil.which("psql", path=path) == str(pg / "psql")
