"""Exercise the real offline Git snapshot and its tamper/path boundaries."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "infra/enrollment/allocator-host"
spec = importlib.util.spec_from_file_location("allocator_source_prepare", HOST / "prepare.py")
assert spec and spec.loader
prepare_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_module)


@pytest.fixture
def bootstrap_module(monkeypatch):
    hold_spec = importlib.util.spec_from_file_location("hold_flags", HOST / "hold_flags.py")
    assert hold_spec and hold_spec.loader
    hold_module = importlib.util.module_from_spec(hold_spec)
    hold_spec.loader.exec_module(hold_module)
    monkeypatch.setitem(sys.modules, "prepare", prepare_module)
    monkeypatch.setitem(sys.modules, "hold_flags", hold_module)
    bootstrap_spec = importlib.util.spec_from_file_location("allocator_source_bootstrap", HOST / "bootstrap.py")
    assert bootstrap_spec and bootstrap_spec.loader
    module = importlib.util.module_from_spec(bootstrap_spec)
    bootstrap_spec.loader.exec_module(module)
    return module


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True,
                          check=True, text=True).stdout.strip()


@pytest.fixture
def snapshot(tmp_path):
    source = tmp_path / "original"
    source.mkdir()
    git(source, "init", "--quiet")
    git(source, "config", "user.name", "Synthetic Builder")
    git(source, "config", "user.email", "builder@example.invalid")
    git(source, "config", "credential.helper", "not-to-be-copied")
    (source / "old.txt").write_text("historical object excluded")
    git(source, "add", ".")
    git(source, "commit", "--quiet", "-m", "synthetic parent")
    parent = git(source, "rev-parse", "HEAD")
    (source / "old.txt").unlink()
    (source / "src").mkdir()
    (source / "src/worker.py").write_text("print('committed synthetic worker')\n")
    executable = source / "run.sh"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    git(source, "add", "-A")
    git(source, "commit", "--quiet", "-m", "synthetic selected source")
    commit = git(source, "rev-parse", "HEAD")
    # Working edits and an untracked private-looking filename are not exported.
    (source / "src/worker.py").write_text("uncommitted synthetic edit\n")
    (source / "private-local.env").write_text("synthetic untracked fixture\n")
    output = tmp_path / "snapshot"
    manifest = prepare_module.prepare(source, commit, output)
    return source, parent, commit, output, manifest


def materialize(snapshot, target: Path):
    folder = snapshot[3]
    return subprocess.run([os.sys.executable, str(folder / "bootstrap/bootstrap.py"), "materialize",
                           "--snapshot", str(folder / "source-snapshot.json"),
                           "--pack", str(folder / "source.pack"), "--output", str(target)],
                          capture_output=True, text=True)


def test_snapshot_preserves_real_commit_without_history_or_config(snapshot, tmp_path):
    source, parent, commit, _, manifest = snapshot
    target = tmp_path / "materialized"
    result = materialize(snapshot, target)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["source_commit"] == commit
    assert receipt["clean_checkout"] and receipt["archive_matches"]
    assert git(target, "rev-parse", "HEAD") == commit
    assert git(target, "rev-parse", "HEAD^{tree}") == git(source, "rev-parse", commit + "^{tree}")
    assert (target / ".git/shallow").read_text() == commit + "\n"
    assert git(target, "status", "--porcelain", "--untracked-files=all") == ""
    assert (target / "src/worker.py").read_text() == "print('committed synthetic worker')\n"
    assert (target / "run.sh").stat().st_mode & 0o111
    assert not (target / "private-local.env").exists()
    assert parent not in manifest["object_ids"]
    assert subprocess.run(["git", "-C", str(target), "cat-file", "-e", parent], capture_output=True).returncode != 0
    assert git(target, "config", "--local", "--get-regexp", "^core[.]")
    assert subprocess.run(["git", "-C", str(target), "config", "--local", "--get", "credential.helper"], capture_output=True).returncode != 0
    assert git(target, "remote") == ""
    assert set(snapshot[4]["bootstrap_operators"]) == {"prepare.py", "bootstrap.py", "hold_flags.py"}
    assert (snapshot[3] / "bootstrap/hold_flags.py").is_file()


@pytest.mark.parametrize("tamper", ["pack", "commit", "tree", "objects"])
def test_snapshot_rejects_tampering(snapshot, tmp_path, tamper):
    folder, manifest = snapshot[3:]
    if tamper == "pack":
        pack = folder / "source.pack"
        pack.write_bytes(pack.read_bytes() + b"changed")
    else:
        if tamper == "commit":
            manifest["source_commit"] = snapshot[1]
        elif tamper == "tree":
            manifest["source_tree"] = "1" * 40
        else:
            manifest["object_ids"].append("1" * 40)
            manifest["object_ids"].sort()
        (folder / "source-snapshot.json").write_text(json.dumps(manifest))
    result = materialize(snapshot, tmp_path / "materialized")
    assert result.returncode != 0
    assert "Traceback" in result.stderr


def test_snapshot_refuses_existing_or_symlink_output(snapshot, tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    assert materialize(snapshot, target).returncode != 0
    link = tmp_path / "linked"
    link.symlink_to(target, target_is_directory=True)
    assert materialize(snapshot, link).returncode != 0
    assert list(target.iterdir()) == []


def test_snapshot_validation_refuses_added_git_credential_config(snapshot, tmp_path, bootstrap_module):
    target = tmp_path / "materialized"
    assert materialize(snapshot, target).returncode == 0
    git(target, "config", "credential.helper", "synthetic-extra-config")
    with pytest.raises(ValueError, match="extra repository configuration"):
        bootstrap_module.verify_source(target, snapshot[4])


def test_snapshot_validation_refuses_injected_loose_parent(snapshot, tmp_path, bootstrap_module):
    target = tmp_path / "materialized"
    assert materialize(snapshot, target).returncode == 0
    original, parent = snapshot[:2]
    raw_parent = subprocess.run(["git", "-C", str(original), "cat-file", "-p", parent],
                               capture_output=True, check=True).stdout
    restored = subprocess.run(["git", "-C", str(target), "hash-object", "-t", "commit", "-w", "--stdin"],
                              input=raw_parent, capture_output=True, check=True).stdout.decode().strip()
    assert restored == parent
    with pytest.raises(ValueError, match="historical objects"):
        bootstrap_module.verify_source(target, snapshot[4])


def test_host_validation_refuses_state_inside_source_before_tools(snapshot, tmp_path):
    target = tmp_path / "materialized"
    assert materialize(snapshot, target).returncode == 0
    state = target / "private-state"
    state.mkdir(mode=0o700)
    result = subprocess.run([os.sys.executable, str(HOST / "bootstrap.py"), "validate",
        "--source", str(target), "--snapshot", str(snapshot[3] / "source-snapshot.json"),
        "--tools", str(tmp_path / "missing-tools.json"), "--state-root", str(state),
        "--evidence", str(tmp_path / "evidence")], capture_output=True, text=True)
    assert result.returncode != 0
    assert not (tmp_path / "evidence").exists()


def test_host_child_environment_isolates_config_without_repurposing_home(tmp_path, bootstrap_module):
    source, evidence = tmp_path / "source", tmp_path / "evidence"
    environment = bootstrap_module.host_environment({"python": sys.executable}, source, evidence)
    assert not {"HOME", "home", "CODEX_HOME"} & set(environment)
    assert environment["XDG_CONFIG_HOME"] == str(evidence / "config")
    assert environment["XDG_CACHE_HOME"] == str(evidence / "cache")
    assert environment["AZURE_CONFIG_DIR"] == str(evidence / "azure-version")
    assert environment["AZURE_CORE_COLLECT_TELEMETRY"] == "false"
    assert environment["AZURE_EXTENSION_USE_DYNAMIC_INSTALL"] == "no"
