"""Imported calendar controls use the actual signed API, SQL custody and Chief draft."""

import base64
import json
import os
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

from sqlalchemy import func, select, text
from tests.integration.test_calendar_imports import calendar_import_case as _calendar_import_case
from tests.integration.test_calendar_imports import signed_workspace as _signed_workspace

from cosmas_os.models import ModelWorkAdmission

calendar_import_case = _calendar_import_case
signed_workspace = _signed_workspace
REPO = Path(__file__).resolve().parents[2]


def test_signed_calendar_import_ui_recovers_lost_replies_and_preserves_chief_draft(calendar_import_case, tmp_path):
    f = calendar_import_case
    node = shutil.which("node")
    assert node is not None
    initial_models = f.s.scalar(select(func.count()).select_from(ModelWorkAdmission))
    f.s.commit()
    omitted = "https://example.invalid/calendar-file-omitted"
    raw = f.ics(day=f.starts_on, extra=f"URL:{omitted}\r\nDESCRIPTION:{omitted}\r\n")
    encoded = base64.b64encode(raw).decode()

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
                    file_base64=encoded, window=f.window, event_title="Invented calendar visit"))
            if self.path == "/lab/counts":
                models = f.s.scalar(select(func.count()).select_from(ModelWorkAdmission))
                retained = []
                counts = {}
                for name, table in (("imports", "calendar_import_requests"), ("reviews", "calendar_import_source_reviews"),
                                    ("revocations", "calendar_import_revocations")):
                    counts[name] = f.s.scalar(text(f"SELECT count(*) FROM {table} WHERE workspace_id=:wid"), {"wid": f.workspace["id"]})
                for table in ("calendar_import_requests", "calendar_import_snapshots", "calendar_import_source_reviews", "calendar_import_revocations"):
                    retained.extend(f.s.scalars(text(f"SELECT row_to_json(t) FROM {table} t WHERE workspace_id=:wid"), {"wid": f.workspace["id"]}))
                serialized = json.dumps(retained, default=str)
                raw_retained = any(value in serialized for value in (omitted, encoded, "BEGIN:VCALENDAR", "invented-calendar-event", "file_base64", "invented-private-calendar.ics"))
                f.s.commit()
                return self.respond(200, dict(**counts, model_admissions=models, raw_retained=raw_retained))
            response = f.client.get(self.path, headers=dict(self.headers))
            self.respond(response.status_code, response.json())

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            assert 0 <= size <= 1_402_200
            body = self.rfile.read(size)
            response = f.client.post(self.path, headers=dict(self.headers), content=body)
            self.respond(response.status_code, response.json())

    server = HTTPServer(("127.0.0.1", 0), Bridge)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report = tmp_path / "calendar-import-ui.json"
    env = {key: os.environ[key] for key in ("PATH", "TMPDIR") if key in os.environ}
    env.update(COSMAS_CALENDAR_IMPORT_UI_LAB_URL=f"http://127.0.0.1:{server.server_port}",
        COSMAS_CALENDAR_IMPORT_UI_LAB_REPORT=str(report))
    try:
        result = subprocess.run([node, "node_modules/vitest/vitest.mjs", "run",
            "src/CalendarImportServerLab.test.tsx", "--maxWorkers=1"], cwd=REPO / "web",
            env=env, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        evidence = json.loads(report.read_text())
        assert evidence["passed"] and evidence["screenshots"] == 0
        assert evidence["imports"] == 2
        assert evidence["reviews"] == evidence["revocations"] == 1
        assert not evidence["raw_retained"]
        assert evidence["model_admissions"] == initial_models
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
