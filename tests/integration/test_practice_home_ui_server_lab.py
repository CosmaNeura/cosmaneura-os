"""Actual signed solo setup -> default team -> private note, PostgreSQL + rendered DOM."""

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.unit import test_practice_access as access_fixture
from tests.unit import test_practice_quick_setup as setup_fixture

from cosmas_os.api import app as api
from cosmas_os.model_registry import metadata
from cosmas_os.models import (
    EncounterWorkspace,
    ExternalIdentity,
    Principal,
    ProviderTeamRevision,
    WorkspaceEntry,
)
from cosmas_os.practice_setup_models import PracticeSetupProfile

solo = setup_fixture.solo
REPO = Path(__file__).resolve().parents[2]
NODE = "/Users/jw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"


def test_real_solo_setup_team_private_note_save_reopen(solo, monkeypatch, tmp_path):
    case = solo
    with case.factory() as session:
        metadata.create_all(session.get_bind())
    setup_fixture.reserve(case)
    verifier, token = access_fixture.verifier(SimpleNamespace(config=case.runtime))
    monkeypatch.setattr(api, "settings", case.runtime)
    monkeypatch.setattr(api, "SessionLocal", case.factory)
    monkeypatch.setattr(api, "_clerk_verifier", lambda: verifier)

    def get_session():
        with case.factory() as session:
            yield session

    api.app.dependency_overrides[api.get_session] = get_session
    client = TestClient(api.app)
    calls = []

    class Bridge(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, status, value, headers=None):
            encoded = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            for key, value in (headers or {}).items():
                if key.lower().startswith("x-cosmas"):
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(encoded)

        def dispatch(self):
            if self.path == "/lab/identity":
                return self.respond(200, {"token": token(case.member)})
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            response = client.request(self.command, self.path, headers=dict(self.headers), content=body)
            calls.append({"method": self.command, "path": self.path, "status": response.status_code})
            return self.respond(response.status_code, response.json(), response.headers)

        do_GET = dispatch
        do_POST = dispatch

    server = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    Thread(target=server.serve_forever, daemon=True).start()
    environment = {key: os.environ[key] for key in ("PATH", "TMPDIR") if key in os.environ}
    environment.update(COSMAS_HOME_LAB_URL=f"http://127.0.0.1:{server.server_port}",
                       COSMAS_HOME_LAB_REPORT=str(tmp_path / "ui-server-lab.json"))
    try:
        result = subprocess.run([NODE, "node_modules/vitest/vitest.mjs", "run",
            "src/PracticeHomeServerLab.test.tsx", "--maxWorkers=1"], cwd=REPO / "web",
            env=environment, capture_output=True, text=True, timeout=120)
        (tmp_path / "vitest.log").write_text(result.stdout + result.stderr)
        with case.factory() as session:
            counts = {model.__tablename__: session.scalar(select(func.count()).select_from(model))
                      for model in (Principal, ExternalIdentity, PracticeSetupProfile, ProviderTeamRevision, EncounterWorkspace, WorkspaceEntry)}
            workspaces = list(session.scalars(select(EncounterWorkspace)))
            entries = list(session.scalars(select(WorkspaceEntry)))
            report = {"synthetic_only": True, "calls": calls, "counts": counts,
                "workspace_ids": [row.id for row in workspaces],
                "appointment_ids": [row.appointment_id for row in workspaces],
                "entry_contents": [row.content for row in entries], "vitest_returncode": result.returncode}
        (tmp_path / "backend-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
        assert result.returncode == 0, result.stdout + result.stderr
        ui = json.loads((tmp_path / "ui-server-lab.json").read_text())
        assert ui["completed"] is True
        assert len(workspaces) == 1 and report["appointment_ids"] == [None]
        assert ui["content"] in report["entry_contents"]
        assert all(counts[model.__tablename__] == 1 for model in
                   (ExternalIdentity, PracticeSetupProfile, ProviderTeamRevision, EncounterWorkspace))
        assert len([call for call in calls if call["method"] == "POST" and call["path"] == "/workspaces/private-drafts"]) == 1
    finally:
        server.shutdown()
        server.server_close()
        client.close()
        api.app.dependency_overrides.pop(api.get_session, None)
