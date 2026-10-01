"""Generate an explicit local replay configuration; never install or activate it."""

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from lab.mcp_doctor import (
    REPO,
    doctor,
    interpreter_path,
    output_parent_path,
    postgres_path,
    repository_path,
)

PACKAGE_FILES = (".codex-plugin/plugin.json", ".mcp.json", "README.md", "scripts/launch.py")


def configuration(*, python: Path, repo: Path, postgres_bin: Path, output_parent: Path,
                  launcher: Path, case: str = "walk_in", role: str = "chief",
                  fault: str = "none", connector_tools: bool = False) -> dict:
    from lab.cases import CASES, ROLES

    if (case not in CASES or role not in ROLES or fault not in {"none", "read_timeout", "lost_save_reply"}
            or type(connector_tools) is not bool):
        raise ValueError("unsupported_synthetic_startup")
    return {"mcpServers": {"cosmabot-lab": {"command": str(python), "args": [
        "-B", str(launcher), "--repo", str(repo), "--postgres-bin", str(postgres_bin),
        "--temp-parent", str(output_parent), "--case", case, "--role", role,
        "--mode", "replay", "--fault", fault, *(["--connector-tools"] if connector_tools else [])]}}}


def destination_path(value: Path) -> Path:
    path = value.expanduser().absolute()
    parent = path.parent.resolve()
    if not parent.is_dir() or path.exists() or path.is_symlink():
        raise ValueError("destination_must_be_new_with_existing_parent")
    path = parent / path.name
    for directory in (Path.home() / ".codex", Path.home() / ".agents"):
        if path.is_relative_to(directory.resolve()):
            raise ValueError("global_configuration_is_not_a_package_destination")
    return path


def write_config(path: Path, value: dict) -> None:
    # Exclusive creation prevents overwriting an existing client configuration.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as target:
        json.dump(value, target, indent=2)
        target.write("\n")


def generate(*, repo: Path, python: Path, postgres_bin: Path, output_parent: Path,
             destination: Path, package: bool, case: str, role: str, fault: str, connector_tools: bool = False) -> dict:
    result = doctor(repo=repo, python=python, postgres_bin=postgres_bin, output_parent=output_parent)
    if not result["ready"]:
        raise ValueError("doctor_not_ready_run_lab_mcp_doctor")
    destination = destination_path(destination)
    template = repo / "plugins/cosmabot-lab"
    if package and destination.name != "cosmabot-lab":
        raise ValueError("package_directory_must_be_named_cosmabot_lab")
    launcher = (destination if package else template) / "scripts/launch.py"
    value = configuration(python=python, repo=repo, postgres_bin=postgres_bin,
                          output_parent=output_parent, launcher=launcher,
                          case=case, role=role, fault=fault, connector_tools=connector_tools)
    if package:
        with tempfile.TemporaryDirectory(prefix=".cosmabot-package-", dir=destination.parent) as staging:
            staged = Path(staging) / "cosmabot-lab"
            for name in PACKAGE_FILES:
                if name == ".mcp.json":
                    continue
                target = staged / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(template / name, target)
            manifest_path = staged / ".codex-plugin/plugin.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["description"] = "Configured project-local synthetic CosmaBot MCP lab."
            manifest["interface"]["shortDescription"] = "Run an isolated synthetic Chief and coworker episode."
            manifest["interface"]["longDescription"] = (
                "Configured local replay package linked to the selected CosmaBot checkout. "
                "Each launch creates a fresh invented-data episode; no provider login or external sends. "
                "Loading this package remains an explicit client action.")
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            readme = staged / "README.md"
            readme.write_text("This generated copy is configured for local synthetic replay. "
                              "It has not been installed or activated. The source scaffold's "
                              "setup and boundary documentation follows.\n\n" + readme.read_text())
            write_config(staged / ".mcp.json", value)
            if destination.exists() or destination.is_symlink():
                raise ValueError("destination_already_exists")
            staged.rename(destination)
    else:
        write_config(destination, value)
    return {"schema": "cosmabot.lab.config.v1", "destination": str(destination),
            "configured": True, "installed": False, "activated": False,
            "mode": "replay", "role": role, "case": case, "connector_tools": connector_tools,
            "episode_output": "fresh_temporary_directory_per_launch", "credentials_stored": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--postgres-bin", type=Path)
    parser.add_argument("--output-parent", type=Path, default=Path(tempfile.gettempdir()))
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--config-output", type=Path)
    target.add_argument("--package-output", type=Path)
    parser.add_argument("--case", default="walk_in")
    parser.add_argument("--role", default="chief")
    parser.add_argument("--fault", choices=("none", "read_timeout", "lost_save_reply"), default="none")
    parser.add_argument("--connector-tools", action="store_true")
    args = parser.parse_args(argv)
    try:
        repo = repository_path(args.repo)
        result = generate(repo=repo, python=interpreter_path(args.python),
                          postgres_bin=postgres_path(args.postgres_bin),
                          output_parent=output_parent_path(args.output_parent, repo),
                          destination=args.package_output or args.config_output,
                          package=args.package_output is not None, case=args.case,
                          role=args.role, fault=args.fault, connector_tools=args.connector_tools)
    except (ValueError, OSError) as error:
        code = str(error) if isinstance(error, ValueError) else "local_configuration_write_failed"
        print(json.dumps({"configured": False, "error": code}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
