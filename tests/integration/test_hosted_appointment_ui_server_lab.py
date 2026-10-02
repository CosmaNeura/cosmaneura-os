"""Actual mounted hosted appointment controls against signed product APIs.

Seven synthetic episodes use PostgreSQL and bounded scheduling GET adapters.
The UI never mocks appointmentApi or calls the execution route.
"""

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration.test_hosted_appointment_proposals import (
    ORIGIN,
    assert_unchanged_and_unsubmitted,
)
from tests.integration.test_hosted_appointment_proposals import (
    capture_case as _capture_case,
)
from tests.integration.test_hosted_appointment_proposals import (
    proposal_case as _proposal_case,
)

from cosmas_os.application import workspace as ws
from cosmas_os.models import AppointmentReceipt, AppointmentWork, Operation

capture_case = _capture_case
proposal_case = _proposal_case
NODE = Path("/Users/jw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
REPO = Path(__file__).resolve().parents[2]


def test_actual_signed_hosted_appointment_ui_six_persona_loops_and_exact_lost_save_recovery(
    proposal_case, tmp_path
):
    f = proposal_case
    assert f.configuration.workspace_hosted_enabled
    assert f.configuration.workspace_scheduling_available and f.configuration.workspace_appointments_enabled
    # The mounted modern hosted client requires the real current protocol gate;
    # the reused lower-level fixture leaves this optional for legacy API cases.
    f.configuration.workspace_draft_recovery_required = True
    wire, episodes = [], []
    request_lock = Lock()

    def snapshot():
        with Session(f.engine) as session:
            current = ws.read(session, f.box, f.owner, f.wid)
            assert current["note"] == f.note_before
            assert current["entries"] == f.entries_before
            assert current["revision"] == f.revision_before
            return current

    class Bridge(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, value, headers=None):
            raw = json.dumps(value).encode()
            self.send_response(status)
            selected = {"Content-Type": "application/json", "Cache-Control": "no-store"}
            if headers:
                for name in ("Content-Type", "Cache-Control", "X-Cosmas-Workspace-Protocol"):
                    if name in headers:
                        selected[name] = headers[name]
            for name, value in {**selected, "Content-Length": str(len(raw))}.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/lab/case":
                params = parse_qs(parsed.query)
                if set(params) != {"persona", "round"} or any(len(v) != 1 for v in params.values()):
                    return self.respond(422, {"detail": "invalid invented case"})
                persona, iteration = params["persona"][0], params["round"][0]
                if persona not in {"physician", "nurse_practitioner", "physician_assistant"} or iteration not in {"1", "2", "lost_save"}:
                    return self.respond(422, {"detail": "invalid invented case"})
                if iteration == "lost_save" and persona != "physician":
                    return self.respond(422, {"detail": "invalid invented case"})
                now = datetime.now(UTC)
                packet = {
                    "workspace": snapshot(), "bot": f.bot,
                    "token": f.token(azp=ORIGIN, sid="invented-ui-" + persona + "-" + iteration),
                    "scope": f.configuration.beta_box_id + ":" + f.owner,
                    "slot": {"starts_at": (now + timedelta(days=2)).isoformat(),
                             "ends_at": (now + timedelta(days=2, minutes=30)).isoformat()},
                    "dob": None, "receiver_calls": len(f.receiver.calls),
                }
                episodes.append({"persona": persona, "round": iteration})
                return self.respond(200, packet)
            if parsed.path == "/lab/inspect" and not parsed.query:
                with Session(f.engine) as session:
                    rows = list(session.scalars(select(AppointmentWork).where(AppointmentWork.workspace_id == f.wid)))
                    states = []
                    for row in rows:
                        operation = session.scalar(select(Operation).where(Operation.ticket_id == row.ticket_id))
                        states.append({"ticket_id": row.ticket_id,
                            "dispatch_started": operation is not None and operation.started_at is not None,
                            "attempt_count": operation.attempt_count if operation else 0})
                    receipt_count = session.scalar(select(func.count()).select_from(AppointmentReceipt).where(
                        AppointmentReceipt.box_id == f.box))
                return self.respond(200, {"workspace": snapshot(), "receiver_calls": len(f.receiver.calls),
                    "receiver_writes": 0, "appointment_receipts": receipt_count, "operations": states})
            with request_lock:
                response = f.client.get(self.path, headers=dict(self.headers))
            wire.append({"method": "GET", "path": self.path, "status": response.status_code})
            return self.respond(response.status_code, response.json(), response.headers)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 2048 or not self.path.startswith(f.path) or self.path.endswith("/execute"):
                return self.respond(422, {"detail": "outside invented proposal controls"})
            body = self.rfile.read(length)
            with request_lock:
                response = f.client.post(self.path, headers=dict(self.headers), content=body)
            value = json.loads(body)
            wire.append({"method": "POST", "path": self.path, "status": response.status_code,
                "key": value.get("idempotency_key"), "choice": value.get("choice")})
            return self.respond(response.status_code, response.json(), response.headers)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report_root = Path(os.environ.get("COSMAS_OPERATIONAL_EVIDENCE_DIR", str(tmp_path)))
    report_root.mkdir(parents=True, exist_ok=True)
    report = report_root / "hosted-appointment-ui-server-lab.json"
    env = {k: os.environ[k] for k in ("PATH", "TMPDIR") if k in os.environ}
    env.update(COSMAS_HOSTED_APPOINTMENT_LAB_URL=f"http://127.0.0.1:{server.server_port}",
               COSMAS_HOSTED_APPOINTMENT_LAB_REPORT=str(report))
    try:
        result = subprocess.run([str(NODE), "node_modules/vitest/vitest.mjs", "run",
            "src/AppointmentPanel.hosted-actual.test.tsx", "--maxWorkers=1"], cwd=REPO / "web",
            env=env, capture_output=True, text=True, timeout=300)
        (report_root / "hosted-appointment-ui-vitest.txt").write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        evidence = json.loads(report.read_text())
        assert len(evidence["episodes"]) == 6 and all(e["passed"] for e in evidence["episodes"])
        assert len(evidence["recoveries"]) == 1 and evidence["recoveries"][0]["passed"]
        assert len(episodes) == 7 and len(f.receiver.calls) == 7
        assert all(call.endswith("/availability/verified") for call in f.receiver.calls)
        assert len(f.receiver.credentials) == 7
        assert len([w for w in wire if w["method"] == "POST"]) == 22
        assert all(w["status"] == 200 for w in wire)
        assert not any(w["path"].endswith("/execute") for w in wire)
        with Session(f.engine) as session:
            rows = list(session.scalars(select(AppointmentWork).where(AppointmentWork.workspace_id == f.wid)))
            assert len(rows) == 7
        for row in rows:
            response = f.client.get(f.path + "/" + row.ticket_id, headers={**f.headers,
                "X-Cosmas-Draft-Recovery": "2", "X-Cosmas-Workspace-Protocol": "1"})
            assert response.status_code == 200
            item = response.json()
            assert item["state"] == "rejected" and item["dispatch_started"] is False
            assert_unchanged_and_unsubmitted(f, item)
        snapshot()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
