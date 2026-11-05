#!/usr/bin/env python3
"""Materialize/validate an offline allocator snapshot, without starting a worker.

This is source and installed-tool preparation only. It never reads credentials,
installs dependencies, logs in, enables a service, or performs provider work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

from prepare import CONTRACT, OID, fresh_output, regular_directory, tree_objects
from hold_flags import load_hold_flags


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(source: Path, *arguments: str, data: bytes | None = None, executable: str = "git") -> bytes:
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                   "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    return subprocess.run([executable, "-C", str(source), *arguments], input=data,
        capture_output=True, check=True, timeout=120, env=environment).stdout


def snapshot_value(path: Path) -> dict:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ValueError("regular absolute reviewed snapshot manifest required")
    value = json.loads(path.read_text())
    expected = {"contract_version", "source_commit", "source_tree", "source_pack_sha256",
                "source_archive_sha256", "object_ids", "files", "bootstrap_operators", "working_tree_observed",
                "included_working_tree_edits", "included_parent_objects",
                "included_repository_configuration", "worker_started"}
    if (not isinstance(value, dict) or set(value) != expected or value["contract_version"] != CONTRACT
            or any(value[name] is not False for name in ("included_working_tree_edits", "included_parent_objects",
                                                        "included_repository_configuration", "worker_started"))
            or not all(isinstance(value[name], str) and OID.fullmatch(value[name]) for name in ("source_commit", "source_tree"))
            or not all(isinstance(value[name], str) and re.fullmatch(r"[a-f0-9]{64}", value[name])
                       for name in ("source_pack_sha256", "source_archive_sha256"))
            or not isinstance(value["object_ids"], list) or not all(isinstance(oid, str) and OID.fullmatch(oid) for oid in value["object_ids"])
            or value["object_ids"] != sorted(set(value["object_ids"]))
            or not isinstance(value["bootstrap_operators"], dict)
            or set(value["bootstrap_operators"]) != {"prepare.py", "bootstrap.py", "hold_flags.py"}
            or not all(isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest)
                       for digest in value["bootstrap_operators"].values())):
        raise ValueError("exact reviewed snapshot contract required")
    return value


def verify_source(source: Path, value: dict, *, executable: str = "git") -> dict:
    regular_directory(source)
    git_directory = source / ".git"
    if git_directory.resolve() != git_directory or not git_directory.is_dir():
        raise ValueError("owned regular Git directory required")
    for path in (git_directory / "config", git_directory / "shallow", git_directory / "index"):
        if path.is_symlink() or not path.is_file():
            raise ValueError("regular snapshot Git metadata required")
    config_keys = set(command(source, "config", "--local", "--name-only", "--list", executable=executable).decode().splitlines())
    if not config_keys <= {"core.repositoryformatversion", "core.filemode", "core.bare", "core.logallrefupdates",
                           "core.ignorecase", "core.precomposeunicode"}:
        raise ValueError("credential or extra repository configuration refused")
    head = command(source, "rev-parse", "HEAD", executable=executable).decode().strip()
    if head != value["source_commit"] or (source / ".git/shallow").read_text() != head + "\n":
        raise ValueError("real selected HEAD must be the exact shallow boundary")
    tree, objects, files = tree_objects(source, head, executable=executable)
    if tree != value["source_tree"] or objects != value["object_ids"] or files != value["files"]:
        raise ValueError("selected complete source tree differs from reviewed manifest")
    if command(source, "status", "--porcelain", "--untracked-files=all", executable=executable).strip():
        raise ValueError("clean exact snapshot checkout required")
    if hashlib.sha256(command(source, "archive", "--format=tar", head, executable=executable)).hexdigest() != value["source_archive_sha256"]:
        raise ValueError("source archive differs from real selected commit")
    indices = list((source / ".git/objects/pack").glob("*.idx"))
    if len(indices) != 1:
        raise ValueError("one exact source pack required")
    actual = set()
    for line in command(source, "verify-pack", "-v", str(indices[0]), executable=executable).decode().splitlines():
        words = line.split()
        if words and OID.fullmatch(words[0]):
            actual.add(words[0])
    if actual != set(value["object_ids"]):
        raise ValueError("extra or missing objects, including historical parents, refused")
    all_objects = set(command(source, "cat-file", "--batch-all-objects", "--batch-check=%(objectname)", executable=executable).decode().splitlines())
    if all_objects != actual:
        raise ValueError("unreviewed loose or alternate historical objects refused")
    if command(source, "remote", executable=executable).strip():
        raise ValueError("no repository credential/remote configuration permitted")
    return {"source_commit": head, "source_tree": tree, "source_objects": len(objects),
            "tracked_files": len(files), "clean_checkout": True, "archive_matches": True,
            "parent_objects_included": False, "worker_started": False}


def materialize(snapshot: Path, pack: Path, output: Path) -> dict:
    value = snapshot_value(snapshot)
    for name, digest in value["bootstrap_operators"].items():
        if sha(Path(__file__).with_name(name)) != digest:
            raise ValueError("bootstrap operator differs from reviewed transfer manifest")
    if not pack.is_absolute() or not pack.is_file() or pack.is_symlink() or sha(pack) != value["source_pack_sha256"]:
        raise ValueError("exact reviewed regular source pack required")
    fresh_output(output, snapshot.parent)
    output.mkdir(mode=0o700)
    command(output, "init", "--quiet", "--template=")
    command(output, "index-pack", "--stdin", data=pack.read_bytes())
    (output / ".git/shallow").write_text(value["source_commit"] + "\n")
    command(output, "update-ref", "--no-deref", "HEAD", value["source_commit"])
    command(output, "read-tree", "--reset", "-u", value["source_commit"] + "^{tree}")
    result = verify_source(output, value)
    return {"contract_version": "cosmabot.private-worker-materialized.v1", **result,
            "snapshot_manifest_sha256": sha(snapshot), "source_pack_sha256": sha(pack)}


def host_environment(paths: dict[str, str], source: Path, evidence: Path) -> dict[str, str]:
    return {"PATH": ":".join(dict.fromkeys(str(Path(path).parent) for path in paths.values())) + ":/usr/bin:/bin",
            "XDG_CONFIG_HOME": str(evidence / "config"), "XDG_CACHE_HOME": str(evidence / "cache"),
            "AZURE_CONFIG_DIR": str(evidence / "azure-version"), "AZURE_CORE_COLLECT_TELEMETRY": "false",
            "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(source / "src")}


def validate_host(
    source: Path,
    snapshot: Path,
    tools_file: Path,
    state_root: Path,
    evidence: Path,
    hold_flags: Path | None = None,
) -> dict:
    value = snapshot_value(snapshot)
    regular_directory(source)
    regular_directory(state_root)
    state = state_root.stat()
    if (state_root == Path("/") or state_root.is_relative_to(source) or source.is_relative_to(state_root)
            or state.st_uid != os.getuid() or stat.S_IMODE(state.st_mode) != 0o700):
        raise ValueError("separate owner-controlled existing persistent 0700 state required")
    fresh_output(evidence, source)
    config = json.loads(tools_file.read_text())
    if not isinstance(config, dict) or set(config) != {"python", "git", "az", "tofu"}:
        raise ValueError("four explicit preinstalled tool records required")
    paths = {}
    for name, record in config.items():
        if (not isinstance(record, dict) or set(record) != {"path", "sha256"}
                or not isinstance(record["path"], str) or not isinstance(record["sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", record["sha256"])):
            raise ValueError("public installed tool path and reviewed executable hash required")
        path = Path(record["path"])
        if not path.is_absolute() or not path.is_file() or sha(path) != record["sha256"]:
            raise ValueError("installed executable differs from reviewed tool")
        paths[name] = str(path)
    result = verify_source(source, value, executable=paths["git"])
    evidence.mkdir(mode=0o700)
    environment = host_environment(paths, source, evidence)

    def local(argv: list[str]) -> str:
        return subprocess.run(argv, env=environment, cwd=source, capture_output=True, text=True,
                              check=True, timeout=30).stdout.strip()

    python = json.loads(local([paths["python"], "-B", "-c", "import json,platform,sys;print(json.dumps({'version':list(sys.version_info[:3]),'system':platform.system(),'machine':platform.machine()}))"]))
    if python["version"] != [3, 13, 15] or python["system"] != "Linux" or python["machine"] not in {"x86_64", "aarch64"}:
        raise ValueError("actual Linux Python3.13.15 host required; Mac tools do not qualify it")
    azure = json.loads(local([paths["az"], "version", "--output", "json"]))
    tofu = json.loads(local([paths["tofu"], "version", "-json"]))
    if azure.get("azure-cli") != "2.89.1" or tofu.get("terraform_version") != "1.12.5":
        raise ValueError("reviewed installed AzureCLI2.89.1/OpenTofu1.12.5 required")
    imports = local([paths["python"], "-B", "-c", "from cosmas_os.enrollment.hosting_worker import main;print('existing-worker-imports-valid')"])
    if imports != "existing-worker-imports-valid":
        raise ValueError("actual app dependencies must already be installed for selected source")
    result.update(contract_version="cosmabot.private-worker-local-host-check.v1", tools=config,
                  python=python, azure_cli=azure["azure-cli"], tofu=tofu["terraform_version"],
                  git=local([paths["git"], "--version"]), state_root=str(state_root),
                  allocation_qualified=False, managed_identity_qualified=False, private_network_qualified=False,
                  worker_started=False, hosting_configuration_enabled=False,
                  p2_extra_box_authorized=False, stripe_live_mode=False)
    if hold_flags is not None:
        holds = load_hold_flags(hold_flags)
        if holds["activation_holds"]["worker_started"] or holds["worker_enable_command_emitted"]:
            raise ValueError("hold-flags receipt cannot claim the worker is started")
        result["hold_flags"] = holds
    (evidence / "local-host-check.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest="operation", required=True)
    restore = operations.add_parser("materialize")
    restore.add_argument("--snapshot", type=Path, required=True)
    restore.add_argument("--pack", type=Path, required=True)
    restore.add_argument("--output", type=Path, required=True)
    check = operations.add_parser("validate")
    check.add_argument("--source", type=Path, required=True)
    check.add_argument("--snapshot", type=Path, required=True)
    check.add_argument("--tools", type=Path, required=True)
    check.add_argument("--state-root", type=Path, required=True)
    check.add_argument("--evidence", type=Path, required=True)
    check.add_argument("--hold-flags", type=Path, default=None,
                       help="Optional cosmabot.private-worker-hold-flags.v1 receipt; activation holds must stay false.")
    arguments = parser.parse_args()
    os.umask(0o077)
    if arguments.operation == "materialize":
        result = materialize(arguments.snapshot, arguments.pack, arguments.output)
    else:
        result = validate_host(
            arguments.source, arguments.snapshot, arguments.tools, arguments.state_root, arguments.evidence,
            hold_flags=arguments.hold_flags,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
