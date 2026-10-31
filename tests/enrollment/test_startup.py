"""The image's module command must own a serving process, even while closed."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx


def test_enrollment_module_serves_health_with_default_admission_closed(tmp_path):
    source = Path(__file__).resolve().parents[2] / "src"
    log = tmp_path / "startup.log"
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(source),
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    with log.open("w") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "cosmas_os.enrollment.api", "--host", "127.0.0.1", "--port", "0"],
            cwd=tmp_path,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 15
            address = None
            while time.monotonic() < deadline:
                assert process.poll() is None, "Enrollment module exited before serving."
                match = re.search(r"Uvicorn running on http://127[.]0[.]0[.]1:(\d+)", log.read_text())
                if match:
                    address = "http://127.0.0.1:" + match.group(1)
                    break
                time.sleep(0.05)
            assert address is not None, "Enrollment module did not bind its owned loopback socket."
            with httpx.Client(base_url=address, timeout=2, trust_env=False) as client:
                assert client.get("/health").status_code == 200
                operational = client.get("/operational-ready")
                assert operational.status_code == 503
                assert operational.json() == {"component": "enrollment", "operational_ready": False}
                config = client.get("/enrollment/v1/config").json()
                assert config["enabled"] is False
                assert config["billing_configured"] is False
                assert config["activation_available"] is False
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
