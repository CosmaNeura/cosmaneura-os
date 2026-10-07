"""Release source identity comes from Git; dirty source cannot claim a release."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("desktop_provenance", Path(__file__).parents[2] / "scripts/desktop_source_provenance.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_clean_source_commit_and_tree_are_bound_and_dirty_release_is_refused(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()
    git("init", "--quiet")
    git("config", "user.name", "Invented local check")
    git("config", "user.email", "invented@example.invalid")
    (tmp_path / "source.txt").write_text("reviewed source\n")
    git("add", "source.txt")
    git("commit", "--quiet", "-m", "Invented reviewed source")
    result = module.provenance(tmp_path, require_clean=True)
    assert result == {"version": 1, "commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"), "dirty": False}
    (tmp_path / "source.txt").write_text("unreviewed change\n")
    with pytest.raises(ValueError, match="clean OS source"):
        module.provenance(tmp_path, require_clean=True)
    assert module.provenance(tmp_path)["dirty"] is True
