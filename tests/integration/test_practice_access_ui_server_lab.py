"""Signed local product onboarding/member revocation through real DOM controls."""

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.unit import test_practice_access as existing

from cosmas_os.api.practice_access_routes import register
from cosmas_os.models import AuditEvent, ExternalIdentity
from cosmas_os.practice_access_models import (
    PracticeAccessRequest,
    PracticeInvitation,
    PracticeInviteRevocation,
    PracticeInviteUse,
)

case = existing.case
REPO = Path(__file__).resolve().parents[2]
NODE = shutil.which("node") or "node"


def test_signed_onboarding_review_pause_denial_restore_and_reopen(case, tmp_path):
    c = case
    checked, token = existing.verifier(c)
    app = FastAPI()
    register(app, runtime=lambda: c.config, verifier=lambda _origins: checked, session_factory=c.factory)
    client = TestClient(app)
    calls = []
    packet = {"applicant_token": token(c.applicant), "owner_token": token(c.owner)}

    class Bridge(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, status, value):
            encoded = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            if self.path == "/lab/identity":
                return self.respond(200, packet)
            reply = client.get(self.path, headers=dict(self.headers))
            calls.append({"method": "GET", "path": self.path, "status": reply.status_code})
            return self.respond(reply.status_code, reply.json())

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            reply = client.post(self.path, headers=dict(self.headers), content=body)
            calls.append({"method": "POST", "path": self.path, "status": reply.status_code})
            return self.respond(reply.status_code, reply.json())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {k: os.environ[k] for k in ("PATH", "TMPDIR") if k in os.environ}
    env.update(COSMAS_ACCESS_LAB_URL=f"http://127.0.0.1:{server.server_port}",
               COSMAS_ACCESS_LAB_REPORT=str(tmp_path / "ui-server-lab.json"))
    try:
        result = subprocess.run([NODE, "node_modules/vitest/vitest.mjs", "run",
                                 "src/PracticeAccessServerLab.test.tsx", "--maxWorkers=1"],
                                cwd=REPO / "web", env=env, text=True, capture_output=True, timeout=90)
        (tmp_path / "vitest.log").write_text(result.stdout + result.stderr)
        with c.factory() as s:
            identities = s.scalar(select(func.count()).select_from(ExternalIdentity))
            requests = s.scalar(select(func.count()).select_from(PracticeAccessRequest))
            member = s.scalar(select(ExternalIdentity).where(ExternalIdentity.subject == c.applicant.subject))
            events = list(s.scalars(select(AuditEvent.event_type)))
            report = {"synthetic_only": True, "calls": calls, "identity_count": identities,
                      "request_count": requests, "member_active": bool(member and member.active),
                      "audit_event_types": events, "vitest_returncode": result.returncode}
        (tmp_path / "backend-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
        assert result.returncode == 0, result.stdout + result.stderr
        evidence = json.loads((tmp_path / "ui-server-lab.json").read_text())
        assert evidence["completed"] is True
        assert identities == 2 and requests == 1 and report["member_active"]
        with c.factory() as s:
            for model in (PracticeInvitation, PracticeInviteUse, PracticeInviteRevocation):
                assert s.scalar(select(func.count()).select_from(model)) == 1
        assert len([p for p in calls if p["path"] == "/practice-access/invitation/create"]) == 1
        assert len([p for p in calls if p["path"] == "/practice-access/invitation/revoke"]) == 1
        assert len([p for p in calls if p["path"] == "/practice-access/invitation/join"]) == 1
        assert len([p for p in calls if p["path"] == "/practice-access/decide"]) == 1
        assert len([p for p in calls if p["path"] == "/practice-access/member-change"]) == 2
        assert any(p["path"] == "/practice-access/requests" and p["status"] == 403 for p in calls)
    finally:
        server.shutdown()
        server.server_close()
        client.close()
