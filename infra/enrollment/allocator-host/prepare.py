#!/usr/bin/env python3
"""Prepare only a real commit and its complete current tree for a private host.

No working edits, parent objects, Git configuration, credentials or deployment
actions enter the snapshot. The actual commit identity is preserved unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

CONTRACT = "cosmabot.private-worker-source-snapshot.v1"
OID = re.compile(r"[a-f0-9]{40}")


def git(source: Path, *arguments: str, data: bytes | None = None, executable: str = "git") -> bytes:
    return subprocess.run([executable, "-C", str(source), *arguments], input=data,
        capture_output=True, check=True, timeout=120).stdout


def regular_directory(path: Path) -> None:
    if not path.is_absolute() or path.resolve() != path or not path.is_dir():
        raise ValueError("existing absolute directory without symlink parents required")


def fresh_output(path: Path, source: Path) -> None:
    if (not path.is_absolute() or path.resolve() != path or path.exists()
            or path.is_symlink() or path.is_relative_to(source) or source.is_relative_to(path)):
        raise ValueError("fresh absolute output outside the source required")
    regular_directory(path.parent)


def tree_objects(source: Path, commit: str, *, executable: str = "git") -> tuple[str, list[str], list[dict]]:
    if not OID.fullmatch(commit) or git(source, "rev-parse", "--verify", commit + "^{commit}", executable=executable).decode().strip() != commit:
        raise ValueError("explicit real source commit required")
    tree = git(source, "rev-parse", commit + "^{tree}", executable=executable).decode().strip()
    objects = {commit, tree}
    files = []
    for record in git(source, "ls-tree", "-r", "-t", "-z", commit, executable=executable).split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, kind, object_id = metadata.decode().split()
        path = raw_path.decode("utf-8")
        if (mode not in {"040000", "100644", "100755"} or kind not in {"tree", "blob"}
                or not OID.fullmatch(object_id) or Path(path).is_absolute() or ".." in Path(path).parts):
            raise ValueError("only committed regular source files and trees supported")
        objects.add(object_id)
        if kind == "blob":
            files.append({"path": path, "mode": mode, "object_id": object_id})
    return tree, sorted(objects), files


def prepare(source: Path, commit: str, output: Path) -> dict:
    regular_directory(source)
    fresh_output(output, source)
    tree, objects, files = tree_objects(source, commit)
    output.mkdir(mode=0o700)
    pack = output / "source.pack"
    # No --revs or --thin: enumerate current objects only, never traverse parents.
    with pack.open("xb") as stream:
        subprocess.run(["git", "-C", str(source), "pack-objects", "--stdout"],
            input=("\n".join(objects) + "\n").encode(), stdout=stream,
            stderr=subprocess.PIPE, check=True, timeout=120, umask=0o077)
    pack.chmod(0o600)
    operators = output / "bootstrap"
    operators.mkdir(mode=0o700)
    operator_hashes = {}
    for name in ("prepare.py", "bootstrap.py"):
        content = Path(__file__).with_name(name).read_bytes()
        destination = operators / name
        destination.write_bytes(content)
        destination.chmod(0o600)
        operator_hashes[name] = hashlib.sha256(content).hexdigest()
    manifest = {"contract_version": CONTRACT, "source_commit": commit, "source_tree": tree,
                "source_pack_sha256": hashlib.sha256(pack.read_bytes()).hexdigest(),
                "source_archive_sha256": hashlib.sha256(git(source, "archive", "--format=tar", commit)).hexdigest(),
                "object_ids": objects, "files": files, "bootstrap_operators": operator_hashes,
                "working_tree_observed": git(source, "status", "--porcelain").decode().splitlines(),
                "included_working_tree_edits": False, "included_parent_objects": False,
                "included_repository_configuration": False, "worker_started": False}
    snapshot = output / "source-snapshot.json"
    snapshot.write_text(json.dumps(manifest, indent=2) + "\n")
    snapshot.chmod(0o600)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    os.umask(0o077)
    result = prepare(arguments.source, arguments.source_commit, arguments.output)
    print(json.dumps({key: value for key, value in result.items() if key not in {"files", "object_ids"}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
