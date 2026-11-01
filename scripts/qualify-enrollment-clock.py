"""PRIVATE source-only clock rehearsal. No vendor calls or credential inputs."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def run(root: Path, receipt: Path) -> int:
    if receipt.exists() or receipt.is_symlink():
        raise ValueError("Use a fresh owned private receipt path")
    if (root / ".env").exists():
        raise ValueError("Use a fresh private source checkout without application environment files")
    from cosmas_os.config import Settings
    runtime_fields = {name.casefold() for name in Settings.model_fields}
    source_env = {key: value for key, value in os.environ.items()
                  if key.casefold() not in runtime_fields and not key.upper().startswith("ENROLLMENT_")}
    source_env["PYTHONPATH"] = os.pathsep.join([str(root), str(root / "src")])
    pg_config = shutil.which("pg_config")
    if not pg_config:
        raise ValueError("Local PostgreSQL tools are required")
    pg = Path(subprocess.check_output([pg_config, "--bindir"], text=True, stderr=subprocess.DEVNULL).strip())
    with tempfile.TemporaryDirectory(prefix="cosmas-enrollment-clock-", dir="/private/tmp" if Path("/private/tmp").is_dir() else None) as folder:
        work = Path(folder)
        work.chmod(0o700)
        password = "synthetic-clock-rehearsal-only"
        (work / "password").write_text(password)
        (work / "password").chmod(0o600)
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        env = {**source_env, "PGPASSWORD": password}
        started = False
        def quiet(args):
            subprocess.run(args, check=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            quiet([str(pg / "initdb"), "-D", str(work / "data"), "-U", "clock_rehearsal",
                "--pwfile", str(work / "password"), "--auth-local=trust", "--auth-host=scram-sha-256"])
            quiet([str(pg / "pg_ctl"), "-D", str(work / "data"), "-l", str(work / "postgres.log"), "-o",
                f"-h 127.0.0.1 -p {port} -k {work}", "-w", "start"])
            started = True
            for name, variable in [("enrollment_synthetic", "ENROLLMENT_TEST_DATABASE_URL"),
                                   ("enrollment_runtime_synthetic", "ENROLLMENT_RUNTIME_TEST_DATABASE_URL")]:
                quiet([str(pg / "createdb"), "-h", "127.0.0.1", "-p", str(port), "-U", "clock_rehearsal", name])
                env[variable] = f"postgresql+psycopg://clock_rehearsal:{password}@127.0.0.1:{port}/{name}"
            # Every application database reference is this owned local runtime;
            # no ambient deployment/Clerk/provider configuration is inherited.
            env["DATABASE_URL"] = env["ENROLLMENT_RUNTIME_TEST_DATABASE_URL"]
            # Capture and discard raw test output. The public receipt carries
            # only test names/results, never provider/customer/card payloads.
            result = None
            timed_out = False
            try:
                result = subprocess.run([sys.executable, "-m", "pytest", "tests/enrollment/test_clock_qualification.py", "-q", "--tb=no",
                    "--junitxml=" + str(work / "tests.xml"), "--basetemp=" + str(work / "pytest")],
                    cwd=root, env=env, capture_output=True, timeout=120)
            except subprocess.TimeoutExpired:
                timed_out = True
            names = []
            failed = skipped = 0
            if (work / "tests.xml").is_file():
                for case in ET.parse(work / "tests.xml").iter("testcase"):
                    outcome = "passed"
                    if case.find("failure") is not None or case.find("error") is not None:
                        outcome, failed = "failed", failed + 1
                    elif case.find("skipped") is not None:
                        outcome, skipped = "skipped", skipped + 1
                    names.append({"test": case.attrib.get("name", "unknown"), "outcome": outcome})
            passed = result is not None and result.returncode == 0 and bool(names) and not failed and not skipped
            payload = {"schema_version": "cosmas-enrollment-m3-source-clock.v1", "source_checks_passed": passed,
                "hosted_stripe_runtime_qualified": False, "vendor_calls": False,
                "bounded_process_timed_out": timed_out,
                "evidence_scope": "invented provider and Clerk; production billing/admission and migrated loopback runtime",
                "tests": names, "remaining_gate": "Protected Stripe TEST Checkout compatibility and private hosted clock/runtime composition are not qualified."}
            descriptor = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(payload, output, indent=2)
                output.write("\n")
            print(json.dumps({"source_checks_passed": passed, "tests": len(names), "hosted_stripe_runtime_qualified": False}))
            return 0 if passed else 1
        finally:
            if started:
                quiet([str(pg / "pg_ctl"), "-D", str(work / "data"), "-w", "stop", "-m", "fast"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Private synthetic enrollment clock source checks; no live mode")
    parser.add_argument("--receipt", type=Path, required=True, help="Fresh private result path; no credentials or provider payloads")
    args = parser.parse_args()
    try:
        return run(Path(__file__).resolve().parents[1], args.receipt.resolve())
    except (OSError, ValueError, subprocess.SubprocessError, ET.ParseError):
        print("Private synthetic qualification could not finish; no hosted timing qualification was granted.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
