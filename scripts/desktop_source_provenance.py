"""Record the current OS source separately from the pinned Scribe shell source."""
import subprocess
from pathlib import Path


def provenance(root: Path, *, require_clean: bool = False) -> dict:
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
    result = {"version": 1, "commit": git("rev-parse", "HEAD"),
              "tree": git("rev-parse", "HEAD^{tree}"),
              "dirty": bool(git("status", "--porcelain", "--untracked-files=normal"))}
    if require_clean and result["dirty"]:
        raise ValueError("Operational desktop composition requires committed, clean OS source.")
    return result
