#!/usr/bin/env python3
"""Run backend checks against a fresh, owned, synthetic PostgreSQL cluster."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEPLOYMENT_TESTS = (
    "tests/integration/test_database_fingerprint.py",
    "tests/integration/test_database_preparation.py",
    "tests/integration/test_google_calendar_runtime_privileges.py",
    "tests/integration/test_hosted_appointment_runtime_privileges.py",
    "tests/integration/test_scheduling_patient_runtime_privileges.py",
)
COMPACT_TEST = "tests/integration/test_compact_execution.py"


def selections(paths: list[str], profile: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {"workspace": [], "deployment": [], "compact": []}
    for selector in paths or ["tests"]:
        path = (REPO / selector.split("::", 1)[0]).resolve()
        if not path.is_relative_to(REPO / "tests") or not path.exists():
            raise ValueError(f"Test selection must exist below tests/: {selector}")
        relative = path.relative_to(REPO).as_posix()
        normalized = relative + ("::" + selector.split("::", 1)[1] if "::" in selector else "")
        if relative == COMPACT_TEST:
            groups["compact"].append(normalized)
        elif relative in DEPLOYMENT_TESTS:
            groups["deployment"].append(normalized)
        else:
            groups["workspace"].append(normalized)
            if path.is_dir():
                groups["deployment"].extend(
                    name for name in DEPLOYMENT_TESTS if (REPO / name).is_relative_to(path)
                )
                if (REPO / COMPACT_TEST).is_relative_to(path):
                    groups["compact"].append(COMPACT_TEST)
    chosen = {name: list(dict.fromkeys(items)) for name, items in groups.items()
              if items and profile in (name, "all")}
    if not chosen:
        raise ValueError(f"No selected tests belong to the {profile} profile")
    return chosen


def source_state(git: str, env: dict[str, str]) -> dict:
    def read(*args: str) -> str:
        return subprocess.check_output([git, *args], cwd=REPO, env=env, text=True, timeout=10)

    names = read("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    files = {}
    for name in sorted(set(names) - {""}):
        path = REPO / name
        content = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        files[name] = hashlib.sha256(content).hexdigest()
    return {"commit": read("rev-parse", "HEAD").strip(),
            "git_status": read("status", "--porcelain"), "files": files,
            "source_sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}


def stop_child(process: subprocess.Popen) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            continue


class Checks:
    def __init__(self, output: Path, env: dict[str, str], prefix: list[str]):
        self.output, self.env, self.prefix = output, env, prefix
        self.report: dict = {"started_at": datetime.now(UTC).isoformat(), "commands": []}

    def save(self) -> None:
        (self.output / "results.json").write_text(json.dumps(self.report, indent=2) + "\n")

    def run(self, label: str, argv: list[str], timeout: int = 60,
            env: dict[str, str] | None = None) -> int:
        command = self.prefix + argv
        record = {"label": label, "command": command, "cwd": str(REPO),
                  "timeout_seconds": timeout, "log": f"{label}.log"}
        self.report["commands"].append(record)
        self.save()
        print(f"{label}: {record['log']}", flush=True)
        started = time.monotonic()
        with (self.output / record["log"]).open("w") as log:
            process = subprocess.Popen(command, cwd=REPO, env=env or self.env,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record["timed_out"] = True
                stop_child(process)
            except BaseException:
                record["interrupted"] = True
                stop_child(process)
                raise
            finally:
                record.update(exit_code=process.returncode, seconds=round(time.monotonic() - started, 3))
                self.save()
        return 124 if record.get("timed_out") else process.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tests", nargs="*", help="Repository-relative test paths or pytest node IDs")
    parser.add_argument("--profile", choices=("workspace", "deployment", "compact", "all"), default="all")
    parser.add_argument("--postgres-bin", type=Path, help="Directory containing PostgreSQL tools")
    parser.add_argument("--evidence-dir", type=Path, help="New directory; defaults to an owned system-temp directory")
    parser.add_argument("--sandbox-profile", type=Path, help="Optional macOS sandbox-exec profile for child commands")
    parser.add_argument("--pytest-timeout", type=int, default=1800, help="Seconds per pytest process (default: 1800)")
    parser.add_argument("--stack-dump-after", type=int, default=60, help="Pytest faulthandler timeout per test")
    args = parser.parse_args()
    if (REPO / ".env").exists() or (REPO / ".env").is_symlink():
        parser.error("Refusing a checkout containing .env; use a clean checkout")
    if args.pytest_timeout <= 0 or args.stack_dump_after <= 0:
        parser.error("Timeouts must be positive")
    try:
        groups = selections(args.tests, args.profile)
    except ValueError as error:
        parser.error(str(error))
    discovered = shutil.which("pg_ctl")
    pg_bin = args.postgres_bin.resolve() if args.postgres_bin else (
        Path(discovered).resolve().parent if discovered else None
    )
    if pg_bin is None or any(not os.access(pg_bin / name, os.X_OK) for name in ("initdb", "pg_ctl", "createdb", "psql")):
        parser.error("Provide --postgres-bin or put PostgreSQL's pg_ctl and sibling tools on PATH")
    git = shutil.which("git")
    if not git:
        parser.error("git is required to record the checked source")
    prefix = []
    if args.sandbox_profile:
        sandbox = shutil.which("sandbox-exec")
        if sys.platform != "darwin" or not sandbox or not args.sandbox_profile.is_file():
            parser.error("--sandbox-profile requires macOS sandbox-exec and an existing profile")
        prefix = [sandbox, "-f", str(args.sandbox_profile.resolve())]
    if args.evidence_dir:
        output = args.evidence_dir.resolve()
        if output.is_relative_to(REPO):
            parser.error("Keep evidence outside the checked repository")
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
    else:
        output = Path(tempfile.mkdtemp(prefix="cosmas-backend-checks-")).resolve()
    print(f"Evidence: {output}", flush=True)
    data = output / "postgres-data"
    password_file = output / "synthetic-password"
    password_file.write_text(secrets.token_hex(16) + "\n")
    password_file.chmod(0o600)
    password = password_file.read_text().strip()
    owner = "cosmas_local_checks"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]  # pg_ctl must bind this otherwise-free port itself.
    local_tool_dirs = [str(Path(found).parent) for tool in ("openssl", "git", "node", "jq", "swift", "xcodebuild")
                       if (found := shutil.which(tool))]
    scratch = output / "tmp"
    scratch.mkdir()
    env = {"PATH": os.pathsep.join((str(pg_bin), str(Path(sys.executable).parent), *local_tool_dirs, os.defpath)),
           "LANG": "C", "LC_ALL": "C", "PYTHONUTF8": "1", "TMPDIR": str(scratch),
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
           "PYTHONPATH": os.pathsep.join((str(REPO), str(REPO / "src"))), "COSMAS_ENV": "synth_os", "DATA_MODE": "synthetic",
           "AUTH_MODE": "synth_headers", "WORKSPACE_ENABLED": "false", "SYNTH_SEED": "true",
           "BLOB_BACKEND": "local", "CORS_ALLOWED_ORIGINS": "http://127.0.0.1:5173,http://localhost:5173",
           "SYNC_WORKER": "true", "PGPASSWORD": password, "PGCONNECT_TIMEOUT": "5",
           "REDIS_URL": "redis://127.0.0.1:1/0"}
    # Optional laboratory paths only. Never inherit credentials or download tools.
    for key in ("COSMAS_PLAYWRIGHT_MODULE_URL", "COSMAS_CHROMIUM_EXECUTABLE",
                "COSMAS_SCRIBE_SPECIALIST_EVIDENCE_DIR", "COSMAS_COMPLETED_CYCLE_OUTPUT"):
        if key in os.environ:
            env[key] = os.environ[key]
    checks = Checks(output, env, prefix)
    checks.report.update(repository=str(REPO), python=sys.executable, profile=args.profile,
                         selections=groups, postgres={"host": "127.0.0.1", "port": port,
                                                      "owner": owner, "data": str(data)})
    result = 1
    try:
        checks.report["source_before"] = source_state(git, env)
        checks.save()
        if checks.run("initdb", [str(pg_bin / "initdb"), "-D", str(data), "--username", owner,
                                 "--auth-local=trust", "--auth-host=scram-sha-256",
                                 "--pwfile", str(password_file), "--no-locale", "--encoding=UTF8"]):
            raise RuntimeError("initdb failed")
        if checks.run("postgres-start", [str(pg_bin / "pg_ctl"), "-D", str(data), "-l", str(output / "postgres.log"),
                                         "-o", f"-h 127.0.0.1 -p {port} -k '' -c lock_timeout=5s "
                                         "-c statement_timeout=60s -c idle_in_transaction_session_timeout=90s",
                                         "-w", "-t", "15", "start"], 25):
            raise RuntimeError("Owned PostgreSQL did not start")
        result = 0
        for profile, tests in groups.items():
            database = {"workspace": "w1a_local_checks", "deployment": "cosmas_os", "compact": "compact_test"}[profile]
            database_owner = "compact_synth" if profile == "compact" else owner
            if profile == "compact":
                role_file = output / "compact-role.sql"
                role_file.write_text(f"CREATE ROLE compact_synth LOGIN PASSWORD '{password}';\n")
                role_file.chmod(0o600)
                try:
                    if checks.run("compact-role", [str(pg_bin / "psql"), "-X", "-v", "ON_ERROR_STOP=1",
                                                   "-h", "127.0.0.1", "-p", str(port), "-U", owner,
                                                   "-d", "postgres", "-f", str(role_file)]):
                        result = 1
                        continue
                finally:
                    role_file.unlink(missing_ok=True)
            folder = output / profile
            folder.mkdir()
            for name in ("blobs", "model-evidence", "routine-evidence"):
                (folder / name).mkdir()
            basetemp = (folder / "pytest-temp").resolve()
            url = f"postgresql+psycopg://{database_owner}:{password}@127.0.0.1:{port}/{database}"
            test_env = env | {"DATABASE_URL": url, "BLOB_ROOT": str(folder / "blobs"),
                              "COSMAS_TEST_TMP_ROOT": str(basetemp),
                              "MODEL_ACTIVITY_EVIDENCE_ROOT": str(folder / "model-evidence"),
                              "ROUTINE_EVIDENCE_ROOT": str(folder / "routine-evidence"),
                              "ROUTINE_EVIDENCE_LABEL": "local"}
            if profile == "compact":
                test_env["COMPACT_TEST_DATABASE_URL"] = url
                compact_token = secrets.token_hex(16)
                test_env["COMPACT_TEST_DATABASE_TOKEN"] = compact_token
            if checks.run(f"{profile}-createdb", [str(pg_bin / "createdb"), "-h", "127.0.0.1", "-p", str(port),
                                                  "-U", owner, "-O", database_owner, database]):
                result = 1
                continue
            if profile == "compact":
                ownership_file = output / "compact-ownership.sql"
                ownership_file.write_text(
                    "COMMENT ON DATABASE compact_test IS "
                    f"'cosmas-local-compact:{compact_token}';\n"
                )
                if checks.run("compact-ownership", [str(pg_bin / "psql"), "-X", "-v", "ON_ERROR_STOP=1",
                                                     "-h", "127.0.0.1", "-p", str(port), "-U", owner,
                                                     "-d", "postgres", "-f", str(ownership_file)]):
                    result = 1
                    continue
            if checks.run(f"{profile}-migrations", [sys.executable, "-m", "alembic", "upgrade", "head"], 120, test_env):
                result = 1
                continue
            command = [sys.executable, "-m", "pytest", *tests, "-v", "-ra", "--tb=short",
                       "--basetemp", test_env["COSMAS_TEST_TMP_ROOT"],
                       "-o", f"cache_dir={folder / 'pytest-cache'}",
                       "-o", f"faulthandler_timeout={args.stack_dump_after}",
                       f"--junitxml={folder / 'pytest-junit.xml'}"]
            if profile == "workspace":
                command.extend(f"--ignore={name}" for name in (*DEPLOYMENT_TESTS, COMPACT_TEST))
            if checks.run(f"{profile}-pytest", command, args.pytest_timeout, test_env):
                result = 1
    except (Exception, KeyboardInterrupt) as error:
        checks.report["error"] = f"{type(error).__name__}: {error}"
        result = 1
    finally:
        if (data / "postmaster.pid").exists():
            stopped = checks.run("postgres-stop", [str(pg_bin / "pg_ctl"), "-D", str(data),
                                                   "-m", "fast", "-w", "-t", "15", "stop"], 25)
            if stopped and (data / "postmaster.pid").exists():
                checks.run("postgres-stop-immediate", [str(pg_bin / "pg_ctl"), "-D", str(data),
                                                       "-m", "immediate", "-w", "-t", "15", "stop"], 25)
        with socket.socket() as probe:
            probe.settimeout(1)
            port_closed = probe.connect_ex(("127.0.0.1", port)) != 0
        checks.report["cleanup"] = {"owned_port_closed": port_closed,
                                    "postmaster_pid_removed": not (data / "postmaster.pid").exists()}
        password_file.unlink(missing_ok=True)
        try:
            checks.report["source_after"] = source_state(git, env)
            unchanged = checks.report["source_before"]["source_sha256"] == checks.report["source_after"]["source_sha256"]
            checks.report["source_unchanged"] = unchanged
        except Exception as error:
            checks.report["source_check_error"] = str(error)
            unchanged = False
        if not unchanged or not all(checks.report["cleanup"].values()):
            result = 1
        checks.report.update(exit_code=result, finished_at=datetime.now(UTC).isoformat())
        checks.save()
    print(f"{'PASS' if result == 0 else 'FAIL'}: {output / 'results.json'}", flush=True)
    return result


if __name__ == "__main__":
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    raise SystemExit(main())
