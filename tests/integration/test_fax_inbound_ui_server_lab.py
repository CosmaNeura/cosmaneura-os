"""Mounted received practice fax UI against registered signed APIs and real PDF custody.

Only vendor HTTP is synthetic. No endpoint, identity, journal, ledger, approval,
execution adapter or PDF parser is replaced by a frontend mock.
"""

import hashlib
import json
import os
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration import test_fax_inbound_api as signed_fixture

from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.fax_inbound_models import (
    FaxInboundAttempt,
    FaxInboundOutcome,
)
from cosmas_os.models import Decision, Operation, Ticket

managed_case = signed_fixture.managed_case
inbox = signed_fixture.inbox
NODE = Path(shutil.which("node") or "node")
REPO = Path(__file__).resolve().parents[2]


def test_six_signed_fax_ui_journeys_with_private_pdf_and_encrypted_restart_recovery(
    inbox, monkeypatch, tmp_path
):
    f = inbox
    monkeypatch.setattr(settings, "workspace_draft_recovery_required", True)
    output = tmp_path / "signed-fax-ui"
    output.mkdir()
    cases = {}
    holder = SimpleNamespace(client=None, active=None, restarts=0)
    request_lock = Lock()

    def start():
        if holder.client is not None:
            holder.client.__exit__(None, None, None)
        holder.client = f.case.start(f.profile)
        holder.client.__enter__()

    def read_workspace():
        with Session(f.case.engine) as session:
            return ws.read(session, f.case.vendor["box"], f.case.vendor["actor"], f.case.vendor["wid"])

    def inspect(episode):
        with Session(f.case.engine) as session:
            operation = session.get(Operation, episode.operation_id) if episode.operation_id else None
            outcome = session.get(FaxInboundOutcome, episode.operation_id) if episode.operation_id else None
            acquisition = session.get(FaxInboundAttempt, episode.operation_id) if episode.operation_id else None
            invocation = session.get(FaxInboundAttempt, episode.operation_id) if episode.operation_id else None
            ticket = session.get(Ticket, operation.ticket_id) if operation is not None else None
            decisions = session.scalar(select(func.count()).select_from(Decision).where(
                Decision.ticket_id == ticket.id)) if ticket is not None else 0
            return {
                "case_id": episode.id, "workspace": read_workspace(),
                "provider_calls": len(f.wire), "credential_calls": len(f.wire),
                "case_provider_calls": (episode.provider_after if episode.provider_after is not None else len(f.wire)) - episode.provider_before,
                "case_credential_calls": (episode.credentials_after if episode.credentials_after is not None else len(f.wire)) - episode.credentials_before,
                "image_calls": sum(row[2].endswith("/download") for row in f.wire[
                    episode.provider_before:episode.provider_after]),
                "restarts": holder.restarts, "operation": None if operation is None else {
                    "id": operation.id, "status": operation.status, "attempt_count": operation.attempt_count,
                    "acquisition": acquisition is not None, "invocation": invocation is not None,
                    "outcome": outcome.state if outcome is not None else None,
                    "document_sha256": outcome.document_sha256 if outcome is not None else None,
                    "document_pages": outcome.pages if outcome is not None else None,
                    "decisions": decisions, "patient_link_id": ticket.patient_link_id if ticket is not None else None,
                    "appointment_id": ticket.appointment_id if ticket is not None else None,
                },
            }

    def create_case(persona, iteration):
        if holder.active is not None:
            holder.active.provider_after = len(f.wire)
            holder.active.credentials_after = len(f.wire)
            prior = inspect(holder.active)
            assert prior["case_provider_calls"] == prior["case_credential_calls"] == 2
            assert prior["operation"]["status"] == "succeeded"
        f.documo_id = str(uuid4())
        f.operation_id = None
        episode = SimpleNamespace(id=str(uuid4()), persona=persona, iteration=iteration,
            operation_id=None, provider_before=len(f.wire), credentials_before=len(f.wire),
            provider_after=None, credentials_after=None,
            before=read_workspace(), fax_id=f.documo_id)
        holder.active = episode
        cases[episode.id] = episode
        signed = f.headers()
        assert set(signed) == {"Authorization", "X-Cosmas-Draft-Recovery", "X-Cosmas-Fax-Inbound"}
        return {"case_id": episode.id, "token": signed["Authorization"].removeprefix("Bearer "),
            "workspace": episode.before, "installation_id": str(f.items[1].selection.connection_id),
            "fax_id": f.documo_id, "pdf_sha256": hashlib.sha256(f.pdf).hexdigest(), "pdf_byte_length": len(f.pdf)}

    class Bridge(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, data, headers=None):
            raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=True).encode()
            self.send_response(status)
            for name, value in (headers or {}).items():
                if name.lower() not in {"content-length", "content-encoding", "transfer-encoding", "connection"}:
                    self.send_header(name, value)
            if not headers or "content-type" not in headers:
                self.send_header("Content-Type", "application/json")
            if not headers or "cache-control" not in headers:
                self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def dispatch(self):
            with request_lock:
                try:
                    parsed = urlsplit(self.path)
                    if self.command == "GET" and parsed.path == "/lab/case":
                        q = parse_qs(parsed.query)
                        persona, iteration = q["persona"][0], q["round"][0]
                        assert persona in {"physician", "nurse_practitioner", "physician_assistant"}
                        assert iteration in {"1", "2"}
                        return self.respond(200, create_case(persona, iteration))
                    if self.command == "GET" and parsed.path == "/lab/inspect":
                        return self.respond(200, inspect(cases[parse_qs(parsed.query)["case_id"][0]]))
                    if self.command == "POST" and parsed.path == "/lab/restart":
                        size = int(self.headers.get("Content-Length", "0"))
                        assert 0 < size <= 1024
                        body = json.loads(self.rfile.read(size))
                        assert set(body) == {"case_id"} and cases[body["case_id"]] is holder.active
                        start()
                        holder.restarts += 1
                        return self.respond(200, inspect(holder.active))
                    assert holder.active is not None
                    assert parsed.path == "/provider-team/identity" or parsed.path.startswith("/fax-inbound")
                    assert not parsed.query
                    headers = {name: value for name, value in self.headers.items()
                        if name.lower() in {"authorization", "x-cosmas-draft-recovery", "x-cosmas-private-draft", "x-cosmas-fax-inbound",
                            "x-cosmas-team-contract", "accept", "content-type"}}
                    if self.command == "GET":
                        response = holder.client.get(self.path, headers=headers)
                    else:
                        size = int(self.headers.get("Content-Length", "0"))
                        assert 0 < size <= 8192
                        body = self.rfile.read(size)
                        if parsed.path == "/fax-inbound/acquire":
                            request = json.loads(body)
                            with Session(f.case.engine) as session:
                                operation = session.scalar(select(Operation).where(Operation.ticket_id == request["ticket_id"]))
                                assert operation is not None
                                f.operation_id = operation.id
                                holder.active.operation_id = operation.id
                        response = holder.client.post(self.path, headers=headers, content=body)
                    return self.respond(response.status_code, response.content, response.headers)
                except Exception as error:
                    # Synthetic fixture diagnostics only; no raw auth/header/credential values.
                    return self.respond(500, {"error": {"code": "fax_inbound_lab_failure"},
                        "diagnostic": type(error).__name__ + ": " + str(error)[:500]})

        do_GET = dispatch
        do_POST = dispatch

    start()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {name: os.environ[name] for name in ("PATH", "TMPDIR") if name in os.environ}
    env.update(COSMAS_FAX_INBOUND_LAB_URL=f"http://127.0.0.1:{server.server_port}",
        COSMAS_FAX_INBOUND_LAB_REPORT=str(output / "ui-server-lab.json"))
    try:
        completed = subprocess.run([str(NODE), "node_modules/vitest/vitest.mjs", "run",
            "src/FaxInbound.signed-api.test.tsx", "--maxWorkers=1"], cwd=REPO / "web", env=env,
            text=True, capture_output=True, timeout=300)
        (output / "vitest.log").write_text(completed.stdout + completed.stderr)
        observations = [inspect(episode) for episode in cases.values()]
        (output / "backend-evidence.json").write_text(json.dumps({"synthetic_only": True,
            "cases": observations, "provider_wire": f.wire, "credential_calls": len(f.wire),
            "dependency_overrides": 0, "parser": "actual bounded pypdf process",
            "returncode": completed.returncode}, indent=2) + "\n")
        assert completed.returncode == 0, completed.stdout + completed.stderr
        report = json.loads((output / "ui-server-lab.json").read_text())
        assert report["completed"] == report["total"] == len(observations) == 6
        assert len(f.wire) == len(f.wire) == 12 and holder.restarts == 6
        for episode, observed in zip(cases.values(), observations, strict=True):
            assert observed["workspace"] == episode.before
            assert observed["case_provider_calls"] == observed["case_credential_calls"] == 2
            assert observed["image_calls"] == 1
            assert observed["operation"] == {"id": episode.operation_id, "status": "succeeded",
                "attempt_count": 1, "acquisition": True, "invocation": True, "outcome": "acquired",
                "document_sha256": hashlib.sha256(f.pdf).hexdigest(), "document_pages": 1,
                "decisions": 1, "patient_link_id": None, "appointment_id": None}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if holder.client is not None:
            holder.client.__exit__(None, None, None)
