"""Signed ready-user Scribe entry -> generated PCM -> encrypted local save/reopen; PostgreSQL + DOM."""

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import monotonic, sleep
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.unit import test_practice_access as access_fixture
from tests.unit import test_practice_quick_setup as setup_fixture

from cosmas_os.api import app as api
from cosmas_os.application.capture_deadline import new_capture_session
from cosmas_os.model_registry import metadata
from cosmas_os.models import (
    EncounterWorkspace,
    ExternalIdentity,
    Principal,
    ProviderTeamRevision,
    WorkspaceEntry,
)
from cosmas_os.practice_setup_models import PracticeSetupProfile
from cosmas_os.private_recording_models import (
    PrivateRecording,
    PrivateRecordingFinish,
    PrivateRecordingLink,
)

solo = setup_fixture.solo
REPO = Path(__file__).resolve().parents[2]
NODE = "/Users/jw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"


def test_private_scribe_starts_before_slow_notebook_and_reopens_encrypted_audio(solo, monkeypatch, tmp_path):
    case = solo
    with case.factory() as session:
        metadata.create_all(session.get_bind())
    setup_fixture.reserve(case)
    verifier, token = access_fixture.verifier(SimpleNamespace(config=case.runtime))
    monkeypatch.setattr(api, "settings", case.runtime)
    monkeypatch.setattr(api, "SessionLocal", case.factory)
    monkeypatch.setattr(api, "_clerk_verifier", lambda: verifier)

    def get_session():
        with new_capture_session(case.factory) as session:
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
            started = monotonic()
            if self.command == "POST" and self.path == "/workspaces/private-drafts":
                sleep(3)
            response = client.request(self.command, self.path, headers=dict(self.headers), content=body)
            calls.append({"method": self.command, "path": self.path, "status": response.status_code,
                          "seconds": monotonic() - started})
            return self.respond(response.status_code, response.json(), response.headers)

        do_GET = dispatch
        do_POST = dispatch

    server = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    Thread(target=server.serve_forever, daemon=True).start()
    environment = {key: os.environ[key] for key in ("PATH", "TMPDIR") if key in os.environ}
    environment.update(COSMAS_PRIVATE_SCRIBE_LAB_URL=f"http://127.0.0.1:{server.server_port}",
                       COSMAS_PRIVATE_SCRIBE_LAB_REPORT=str(tmp_path / "ui-server-lab.json"),
                       VITE_WORKSPACE_ENABLED="true", VITE_WORKSPACE_AUTHENTICATED_ENABLED="true",
                       VITE_WORKSPACE_CAPTURE_ENABLED="true", VITE_COSMAS_ENV="early_adopter_beta",
                       VITE_WORKSPACE_HOSTED_ENABLED="true", VITE_WORKSPACE_DATA_MODE="synthetic",
                       VITE_WORKSPACE_HOSTED_CLIENT="web", VITE_API_BASE="https://api.example.invalid",
                       VITE_WORKSPACE_HOSTED_API_ORIGIN="https://api.example.invalid",
                       VITE_WORKSPACE_WEB_ORIGIN="https://workspace.example.invalid",
                       VITE_WORKSPACE_DESKTOP_AUTH_ENABLED="false", VITE_WORKSPACE_NATIVE_AUTH_ENABLED="false",
                       VITE_DESKTOP_SYNTHETIC_ENABLED="false", VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED="false")
    try:
        result = subprocess.run([NODE, "node_modules/vitest/vitest.mjs", "run",
            "src/PrivateScribeServerLab.test.tsx", "--maxWorkers=1"], cwd=REPO / "web",
            env=environment, capture_output=True, text=True, timeout=120)
        (tmp_path / "vitest.log").write_text(result.stdout + result.stderr)
        with case.factory() as session:
            counts = {model.__tablename__: session.scalar(select(func.count()).select_from(model))
                      for model in (Principal, ExternalIdentity, PracticeSetupProfile, ProviderTeamRevision, EncounterWorkspace, WorkspaceEntry, PrivateRecording, PrivateRecordingFinish, PrivateRecordingLink)}
            workspaces = list(session.scalars(select(EncounterWorkspace)))
            entries = list(session.scalars(select(WorkspaceEntry)))
            recordings = list(session.scalars(select(PrivateRecording)))
            finishes = list(session.scalars(select(PrivateRecordingFinish)))
            report = {"synthetic_only": True, "calls": calls, "counts": counts,
                "workspace_ids": [row.id for row in workspaces],
                "appointment_ids": [row.appointment_id for row in workspaces],
                "entry_contents": [row.content for row in entries], "vitest_returncode": result.returncode,
                "private_recording_metadata": [{"id": row.id, "workspace_id": row.workspace_id,
                    "local_recording_id": row.local_recording_id, "request_sha256": row.request_sha256} for row in recordings],
                "private_recording_finishes": [{"recording_id": row.recording_id, "capture_state": row.capture_state,
                    "manifest_sha256": row.manifest_sha256, "chunks": row.chunks, "frames": row.frames} for row in finishes]}
        (tmp_path / "backend-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
        assert result.returncode == 0, result.stdout + result.stderr
        ui = json.loads((tmp_path / "ui-server-lab.json").read_text())
        assert ui["completed"] is True
        assert len(workspaces) == 1 and report["appointment_ids"] == [None]
        assert report["entry_contents"] == []
        assert ui["microphone_started_before_create_response"] is True
        assert ui["recording"]["workspace_id"] == workspaces[0].id
        assert ui["recording"]["chunks"] == 1
        assert ui["recording"]["wav_sha256"] == ui["reopened_wav_sha256"]
        assert ui["hardware_simulated"] is True
        assert ui["actual_browser_capture_adapter"] is True
        assert counts[PrivateRecording.__tablename__] == counts[PrivateRecordingFinish.__tablename__] == 2
        assert counts[PrivateRecordingLink.__tablename__] == 0
        assert any(recording.local_recording_id == ui["recording"]["recording_id"] for recording in recordings)
        assert all(recording.workspace_id == ui["recording"]["workspace_id"] for recording in recordings)
        assert all(finish.capture_state == "finished" and finish.chunks == 1 and finish.frames == 1600 for finish in finishes)
        assert not any("/capture/" in call["path"] for call in calls)
        assert all(counts[model.__tablename__] == 1 for model in
                   (ExternalIdentity, PracticeSetupProfile, ProviderTeamRevision, EncounterWorkspace))
        assert len([call for call in calls if call["method"] == "POST" and call["path"] == "/workspaces/private-drafts"]) == 1
        assert next(call["seconds"] for call in calls if call["method"] == "POST" and call["path"] == "/workspaces/private-drafts") >= 3
    finally:
        server.shutdown()
        server.server_close()
        client.close()
        api.app.dependency_overrides.pop(api.get_session, None)
