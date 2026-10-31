"""Mounted product review UI against actual synthetic API, DB and tool dispatcher.

Only the upstream model is a fake. This is DOM qualification, not physical-device
or clinical validation. The bridge lives solely in this test process.
"""

import json
import os
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.helpers.task_brief import REQUIREMENTS
from tests.integration.test_workspace_handoffs import prepare

from cosmas_os.adapters.gpt41 import _context
from cosmas_os.api import app as api
from cosmas_os.application import model_work as work
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.models import ModelWorkAdmission

NODE = Path(shutil.which("node") or "node")
REPO = Path(__file__).resolve().parents[2]


def test_actual_product_ui_runs_six_human_revision_acceptance_loops(engine, monkeypatch, tmp_path):
    assert NODE.is_file(), "Pinned existing Node runtime is required for mounted UI qualification"
    runtime = work.team.runtime_settings
    monkeypatch.setattr(runtime, "workspace_enabled", True)
    monkeypatch.setattr(runtime, "workspace_llm_backend", "azure_gpt41")
    monkeypatch.setattr(runtime, "workspace_llm_api_key", SecretStr("invented-model-no-network"))
    monkeypatch.setattr(runtime, "workspace_agent_tools_enabled", True)
    original_dispatch = work.dispatch_claim
    rounds = []
    cases = {}

    def dispatch(claim):
        context = _context(claim.envelope["context"])

        def provider(request):
            body = json.loads(request.content)
            assert str(request.url).endswith("/openai/v1/chat/completions")
            assert body["model"] == "gpt-4.1-dzus" and body["store"] is False
            rounds.append(
                {
                    "admission_id": claim.admission_id,
                    "agent_role": context.role,
                    "message_count": len(body["messages"]),
                }
            )
            if not any(m["role"] == "tool" for m in body["messages"]):
                handle = next(p for p in claim.envelope['tool_selection']['sources'] if p['kind']=='scratchpad')
                value = {
                    "model": "gpt-4.1",
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "read_1",
                                        "type": "function",
                                        "function": {
                                            "name": "read_selected_source",
                                            "arguments": json.dumps(
                                                {
                                                    k: handle[k]
                                                    for k in ("entry_id", "revision", "sha256")
                                                }
                                            ),
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                }
            else:
                tool_result = json.loads(
                    next(m["content"] for m in body["messages"] if m["role"] == "tool")
                )
                assert (
                    tool_result["receipt"]["actor_agent_id"]
                    != tool_result["receipt"]["initiated_by_human_id"]
                )
                if context.role == "chief":
                    content = {
                        "answer": "Preparing a private documentation draft.",
                        "source_ids": [],
                        "handoffs": [
                            {
                                "role": "scribe",
                                "intended_role": "scribe",
                                "brief": "Organize the invented encounter and preserve missing heart history.",
                                "requirements": REQUIREMENTS,
                            }
                        ],
                    }
                else:
                    source = next(p for p in context.sources if p.kind=='scratchpad')
                    assert 'SYNTHETIC Shawn visit' in source.content and 'DOB unavailable' in source.content
                    content = {
                        "excerpts": [{"source_id": source.entry_id, "quote": source.content}],
                        "needs_from_clinician": [
                            "What heart history and medications need confirmation?"
                        ]
                        + (
                            [
                                "Can you "
                                + json.loads(
                                    context.question.split(
                                        "Human-requested revision of the prior private draft\n", 1
                                    )[1].split("\nTreat the quoted prior draft", 1)[0]
                                )["feedback"]
                                + "?"
                            ]
                            if "Human-requested revision of the prior private draft\n"
                            in context.question
                            else []
                        ),
                    }
                value = {
                    "model": "gpt-4.1",
                    "usage": {"prompt_tokens": 150, "completion_tokens": 30},
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": json.dumps(content)},
                        }
                    ],
                }
            return httpx.Response(200, json=value)

        return original_dispatch(
            claim, session_factory=lambda: Session(engine), transport=httpx.MockTransport(provider)
        )

    monkeypatch.setattr(work, "dispatch_claim", dispatch)

    def sessions():
        with Session(engine) as session:
            yield session

    api.app.dependency_overrides[api.get_session] = sessions
    client = TestClient(api.app)  # no background lifespan; the test directs exact queued tasks

    def current(case):
        with Session(engine) as session:
            return work.project_workspace(
                session, ws.read(session, case["box"], case["owner"], case["wid"])
            )

    def run_task(case, hid):
        with Session(engine) as session:
            row = session.scalar(
                select(ModelWorkAdmission).where(
                    ModelWorkAdmission.workspace_id == case["wid"],
                    ModelWorkAdmission.state == "reserved",
                    ModelWorkAdmission.handoff_attempt_id.is_not(None),
                )
            )
            assert row is not None
            snapshot = ws.read(session, case["box"], case["owner"], case["wid"])
            task = next(h for h in snapshot["handoffs"] if h["id"] == hid)
            assert row.handoff_attempt_id == task["attempt_id"]
            claim = work.claim(session, case["box"], case["owner"], row.id)
        assert claim is not None
        result = dispatch(claim)
        with Session(engine) as session:
            work.settle(session, claim, result)
        return current(case)

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
            parsed = urlsplit(self.path)
            if parsed.path == "/lab/case":
                params = parse_qs(parsed.query)
                persona, iteration = params.get("persona", [""])[0], params.get("round", [""])[0]
                if persona not in {
                    "physician",
                    "nurse_practitioner",
                    "physician_assistant",
                } or iteration not in {"1", "2"}:
                    return self.respond(422, {"detail": "invalid synthetic case"})
                with Session(engine) as session:
                    box, owner, initial, team, _ = prepare(
                        session, svc.provision_box(svc.Container(session), "Invented UI practice")
                    )
                    appended = ws.append(
                        session,
                        box,
                        owner,
                        initial["id"],
                        expected=1,
                        key="synthetic-intake",
                        kind="scratchpad",
                        content="SYNTHETIC Shawn visit. Reports heart issues; diagnosis and dates unknown. DOB unavailable. Medication list missing. Plan to review heart-attack clinical trials. No treatment or referral occurred.",
                    )
                    receipt = work.run_conversation(
                        session,
                        box,
                        owner,
                        initial["id"],
                        expected=appended["workspace"]["revision"],
                        team_revision=team["revision"],
                        key="synthetic-chief-plan",
                        role="chief",
                        content="Ask Scribe to organize this invented visit for review.",
                    )
                    assert receipt["outcome"] == "saved", receipt
                    case = {"box": box, "owner": owner, "wid": initial["id"]}
                    cases[initial["id"]] = case
                    task = ws.read(session, box, owner, initial["id"])["handoffs"][0]
                snapshot = run_task(case, task["id"])
                return self.respond(
                    200, {"identity": {"boxId": box, "actorId": owner}, "workspace": snapshot}
                )
            response = client.get(self.path, headers=dict(self.headers))
            return self.respond(response.status_code, response.json())

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            assert 0 <= size <= 12288
            body = self.rfile.read(size)
            if self.path == "/lab/work":
                value = json.loads(body)
                assert set(value) == {"workspace_id", "handoff_id"}
                case = cases[value["workspace_id"]]
                return self.respond(200, {"workspace": run_task(case, value["handoff_id"])})
            response = client.post(self.path, headers=dict(self.headers), content=body)
            return self.respond(response.status_code, response.json())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report_root = Path(os.environ.get("COSMAS_OPERATIONAL_EVIDENCE_DIR", str(tmp_path)))
    report_root.mkdir(parents=True, exist_ok=True)
    report = report_root / "ui-server-lab.json"
    env = {key: os.environ[key] for key in ("PATH", "TMPDIR") if key in os.environ}
    env.update(
        COSMAS_HANDOFF_LAB_URL=f"http://127.0.0.1:{server.server_port}",
        COSMAS_HANDOFF_LAB_REPORT=str(report),
    )
    try:
        completed = subprocess.run(
            [
                str(NODE),
                "node_modules/vitest/vitest.mjs",
                "run",
                "src/HandoffReviewServerLab.test.tsx",
                "--maxWorkers=1",
            ],
            cwd=REPO / "web",
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        evidence = json.loads(report.read_text())
        assert len(evidence["episodes"]) == 6 and all(e["passed"] for e in evidence["episodes"])
        assert (
            len(cases) == 6 and len(rounds) == 36
        )  # Chief, first draft, revised draft; two actual provider rounds each.
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        client.close()
        api.app.dependency_overrides.clear()
