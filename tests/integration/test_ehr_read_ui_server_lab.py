"""Mounted Elation controls use the actual signed API, SQL ledger and shared draft."""

import json
import os
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

from sqlalchemy import func, select
from tests.integration.test_ehr_reads import ehr_case as _ehr_case
from tests.integration.test_ehr_reads import revoke
from tests.integration.test_ehr_reads import signed_workspace as _signed_workspace

from cosmas_os.models import ModelWorkAdmission

ehr_case = _ehr_case
signed_workspace = _signed_workspace
REPO = Path(__file__).resolve().parents[2]


def test_signed_elation_ui_recovers_one_read_and_prepares_existing_chief_draft(ehr_case, tmp_path):
    f = ehr_case
    node = shutil.which("node")
    assert node is not None
    initial_models = f.s.scalar(select(func.count()).select_from(ModelWorkAdmission))
    f.s.commit()

    class Bridge(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, value):
            raw = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/lab/state":
                team = f.client.get("/provider-team", headers=f.headers())
                assert team.status_code == 200
                return self.respond(200, dict(workspace=f.workspace, team=team.json(), token=f.token(),
                    starts_at=f.starts_at.isoformat(), ends_at=f.ends_at.isoformat()))
            if self.path == "/lab/counts":
                models = f.s.scalar(select(func.count()).select_from(ModelWorkAdmission))
                f.s.commit()
                return self.respond(200, dict(provider_calls=len(f.provider.calls), model_admissions=models))
            response = f.client.get(self.path, headers=dict(self.headers))
            self.respond(response.status_code, response.json())

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            assert 0 <= size <= 16384
            body = self.rfile.read(size)
            if self.path == "/lab/revoke":
                revoke(f)
                return self.respond(200, {"revoked": True})
            response = f.client.post(self.path, headers=dict(self.headers), content=body)
            self.respond(response.status_code, response.json())

    server = HTTPServer(("127.0.0.1", 0), Bridge)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report = tmp_path / "ehr-read-ui.json"
    env = {key: os.environ[key] for key in ("PATH", "TMPDIR") if key in os.environ}
    env.update(COSMAS_EHR_UI_LAB_URL=f"http://127.0.0.1:{server.server_port}",
        COSMAS_EHR_UI_LAB_REPORT=str(report))
    try:
        result = subprocess.run([node, "node_modules/vitest/vitest.mjs", "run",
            "src/EhrReadServerLab.test.tsx", "--maxWorkers=1"], cwd=REPO / "web",
            env=env, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        evidence = json.loads(report.read_text())
        assert evidence["passed"] and evidence["screenshots"] == 0
        assert evidence["provider_calls"] == 6
        assert evidence["model_admissions"] == initial_models
        assert len(f.provider.calls) == 6
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
