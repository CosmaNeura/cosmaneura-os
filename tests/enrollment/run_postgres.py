"""Rehearse only enrollment tests on an ephemeral loopback PostgreSQL server."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    pg = Path(subprocess.check_output(["pg_config", "--bindir"], text=True).strip())
    with tempfile.TemporaryDirectory(prefix="cosmas-enrollment-pg-", dir="/private/tmp") as folder:
        work = Path(folder)
        password = "synthetic-enrollment-rehearsal-only"
        (work / "password").write_text(password)
        (work / "password").chmod(0o600)
        data = work / "data"
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        env = {**os.environ, "PGPASSWORD": password}
        started = False
        try:
            subprocess.run([str(pg / "initdb"), "-D", str(data), "-U", "enrollment_rehearsal",
                            "--pwfile", str(work / "password"), "--auth-local=trust", "--auth-host=scram-sha-256"],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            subprocess.run([str(pg / "pg_ctl"), "-D", str(data), "-l", str(work / "postgres.log"), "-o",
                            f"-h 127.0.0.1 -p {port} -k {work}", "-w", "start"], check=True, stdout=subprocess.DEVNULL)
            started = True
            subprocess.run([str(pg / "createdb"), "-h", "127.0.0.1", "-p", str(port), "-U", "enrollment_rehearsal", "enrollment_synthetic"],
                           check=True, env=env)
            env["ENROLLMENT_TEST_DATABASE_URL"] = f"postgresql+psycopg://enrollment_rehearsal:{password}@127.0.0.1:{port}/enrollment_synthetic"
            result = subprocess.run([sys.executable, "-m", "pytest", "tests/enrollment/test_postgres.py", "-q"], cwd=root, env=env)
            if result.returncode:
                raise SystemExit(result.returncode)
        finally:
            if started:
                subprocess.run([str(pg / "pg_ctl"), "-D", str(data), "-w", "stop", "-m", "fast"], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
