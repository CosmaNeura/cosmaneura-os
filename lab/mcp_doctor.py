"""Bounded, credential-free prerequisite checks; never starts a lab or logs in."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SDK_VERSION = "2.2.0"
PG_PROGRAMS = ("initdb", "pg_ctl", "createdb", "postgres")
REPO = Path(__file__).resolve().parents[1]

PROBE = r'''
import contextlib, importlib, importlib.metadata, io, json, socket, sys
class NoNetwork(socket.socket):
    def connect(self, *args, **kwargs):
        raise OSError("doctor_network_disabled")
    def connect_ex(self, *args, **kwargs):
        raise OSError("doctor_network_disabled")
socket.socket = NoNetwork
result = {"python": list(sys.version_info[:3]), "imports": {}, "mcp_version": None}
for name in ("lab.engine", "lab.application", "cosmas_os.model_registry"):
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            importlib.import_module(name)
        result["imports"][name] = True
    except Exception:
        result["imports"][name] = False
try:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        importlib.import_module("mcp.server")
    result["mcp_version"] = importlib.metadata.version("mcp")
except Exception:
    pass
print(json.dumps(result))
'''


def local_environment(repo: Path, output_parent: Path | None = None) -> dict[str, str]:
    """Do not inherit provider credentials or an ambient product configuration."""
    env = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C",
           "PYTHONPATH": os.pathsep.join((str(repo), str(repo / "src"))),
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "PYTHONNOUSERSITE": "1"}
    if output_parent is not None:
        env["TMPDIR"] = str(output_parent)
    return env


def interpreter_path(value: str | Path | None = None) -> Path:
    # A venv executable is commonly a symlink. Preserve it to retain sys.prefix.
    raw = str(value or sys.executable)
    found = shutil.which(raw) if not Path(raw).is_absolute() else raw
    if not found:
        raise ValueError("python_executable_unavailable")
    path = Path(found).expanduser().absolute()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("python_executable_unavailable")
    return path


def repository_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if not all((path / name).is_file() for name in
               ("pyproject.toml", "lab/engine.py", "src/cosmas_os/__init__.py")):
        raise ValueError("cosmabot_repository_unavailable")
    return path


def postgres_path(value: str | Path | None = None) -> Path:
    if value is not None:
        path = Path(value).expanduser().resolve()
    else:
        pg_config = shutil.which("pg_config")
        if not pg_config:
            raise ValueError("postgres_binaries_unavailable")
        try:
            response = subprocess.run([pg_config, "--bindir"], env={"PATH": os.defpath},
                                      capture_output=True, text=True, timeout=5, check=True)
            path = Path(response.stdout.strip()).resolve()
        except (OSError, subprocess.SubprocessError):
            raise ValueError("postgres_binaries_unavailable") from None
    if not path.is_dir() or not all((path / name).is_file() and os.access(path / name, os.X_OK)
                                    for name in PG_PROGRAMS):
        raise ValueError("postgres_binaries_unavailable")
    return path


def output_parent_path(value: str | Path, repo: Path) -> Path:
    path = Path(value).expanduser().resolve()
    if path.is_relative_to(repo) or not path.is_dir():
        raise ValueError("output_parent_must_exist_outside_repository")
    return path


def doctor(*, repo: Path, python: Path, postgres_bin: Path, output_parent: Path) -> dict:
    checks = []

    def check(name: str, ok: bool, detail: str):
        checks.append({"name": name, "ok": ok, "detail": detail})

    def report() -> dict:
        return {"schema": "cosmabot.lab.doctor.v1", "ready": all(row["ok"] for row in checks),
                "checks": checks, "paths": {"python": str(python), "repository": str(repo),
                                            "postgres_bin": str(postgres_bin),
                                            "output_parent": str(output_parent)},
                "provider_login": False, "network_install": False, "database_started": False,
                "environment_values_reported": False}

    # Match runtime admission before importing project settings. Never read this file.
    env_path = repo / ".env"
    no_env = not (env_path.exists() or env_path.is_symlink())
    check("checkout_env_absent", no_env,
          "The source checkout must contain no .env file or .env symlink.")
    if not no_env:
        return {**report(), "error": "checkout_env_refused"}

    try:
        run = subprocess.run([str(python), "-B", "-c", PROBE], cwd=repo,
                             env=local_environment(repo), capture_output=True, text=True,
                             timeout=12, check=True)
        if len(run.stdout) > 8192:
            raise ValueError("probe_output_limit")
        probe = json.loads(run.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        probe = {}
    version = probe.get("python", [])
    check("python_3_13", version[:2] == [3, 13],
          "Python 3.13 required; selected executable must retain its project dependencies.")
    imports = probe.get("imports", {})
    check("project_imports", all(imports.get(name) is True for name in
                                ("lab.engine", "lab.application", "cosmas_os.model_registry")),
          "Import local lab and product models without starting a service or opening a database.")
    check("optional_mcp_sdk", probe.get("mcp_version") == SDK_VERSION,
          f"Optional mcp extra must provide SDK {SDK_VERSION} before an MCP launch.")
    versions = []
    for name in PG_PROGRAMS:
        try:
            result = subprocess.run([str(postgres_bin / name), "--version"],
                                    env={"PATH": os.defpath}, capture_output=True, text=True,
                                    timeout=5, check=True)
            match = re.search(r"\(PostgreSQL\) (\d+)(?:\.\d+)*", result.stdout)
            versions.append(match.group(1) if match else None)
        except (OSError, subprocess.SubprocessError):
            versions.append(None)
    check("postgres_binaries", all(versions) and len(set(versions)) == 1,
          "initdb, pg_ctl, createdb and postgres must be executable and from one major version.")
    writable = False
    try:
        output_parent = output_parent_path(output_parent, repo)
        with tempfile.TemporaryFile(dir=output_parent) as probe_file:
            probe_file.write(b"CosmaBot lab prerequisite probe\n")
            probe_file.flush()
            os.fsync(probe_file.fileno())
        writable = True
    except (OSError, ValueError):
        pass
    check("output_parent", writable,
          "Fresh temporary episodes require a writable existing directory outside the repository.")
    return report()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--postgres-bin", type=Path)
    parser.add_argument("--output-parent", type=Path, default=Path(tempfile.gettempdir()))
    args = parser.parse_args(argv)
    try:
        repo = repository_path(args.repo)
        result = doctor(repo=repo, python=interpreter_path(args.python),
                        postgres_bin=postgres_path(args.postgres_bin),
                        output_parent=output_parent_path(args.output_parent, repo))
    except ValueError as error:
        print(json.dumps({"schema": "cosmabot.lab.doctor.v1", "ready": False,
                          "error": str(error)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
