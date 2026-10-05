"""Actual full EncounterWorkspace/SettingsHub received practice fax UI against registered signed APIs and real PDF custody.

Vendor/model HTTP, generated PDFs and scripted personas are synthetic. No endpoint, identity verifier, journal, ledger, approval,
execution adapter or PDF parser is replaced by a frontend mock.
"""

import hashlib
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration import test_fax_inbound_source_api as source_fixture

from cosmas_os.application import workspace as ws,model_work as work,provider_team as team,fax_inbound as fax_ledger
from cosmas_os.adapters.gpt41 import _context
from cosmas_os.fax_source_models import FaxInboundSourceReview
from cosmas_os.models import ModelWorkAdmission,EncounterWorkspace
from tests.integration.test_efax_inbound_source_ui_server_lab import invented_pdf
from tests.helpers.task_brief import REQUIREMENTS
from pydantic import SecretStr
import httpx
from cosmas_os.config import settings
from cosmas_os.fax_inbound_models import (
    FaxInboundAttempt,
    FaxInboundOutcome,
)
from cosmas_os.models import Decision, Operation, Ticket

managed_case = source_fixture.managed_case
inbox = source_fixture.inbox
source_http = source_fixture.source_http
NODE = Path("/Users/jw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
REPO = Path(__file__).resolve().parents[2]


def test_six_signed_fax_ui_journeys_with_private_pdf_and_encrypted_restart_recovery(
    source_http, monkeypatch, tmp_path
):
    f = source_http
    monkeypatch.setattr(settings, "workspace_draft_recovery_required", True)
    model_rounds = []
    monkeypatch.setattr(settings,"workspace_agent_tools_enabled",True)
    original_dispatch=work.dispatch_claim
    output = tmp_path / "signed-fax-ui"
    output.mkdir()
    cases = {}
    holder = SimpleNamespace(client=None, active=None, restarts=0)
    request_lock = Lock()

    def start():
        if holder.client is not None:
            holder.client.__exit__(None, None, None)
        monkeypatch.setattr(settings,"workspace_llm_backend","disabled")
        holder.client = f.case.start(f.profile)
        holder.client.__enter__()
        monkeypatch.setattr(settings,"workspace_llm_backend","azure_gpt41")
        monkeypatch.setattr(settings,"workspace_llm_api_key",SecretStr("invented-no-network"))

    def read_workspace():
        with Session(f.case.engine) as session:
            return ws.read(session, f.case.vendor["box"], f.case.vendor["actor"], f.wid)

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
                "case_id": episode.id, "workspace": episode.final_workspace or read_workspace(),
                "review_count":session.scalar(select(func.count()).select_from(FaxInboundSourceReview).where(FaxInboundSourceReview.operation_id==episode.operation_id)),
                "model_rounds":len([r for r in model_rounds if r["workspace_id"]==episode.wid]),
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
            holder.active.final_workspace=prior["workspace"]
            assert prior["case_provider_calls"] == prior["case_credential_calls"] == 2
            assert prior["operation"]["status"] == "succeeded"
        f.documo_id = str(uuid4())
        f.operation_id = None
        f.pdf, passage = invented_pdf(persona, iteration)
        if holder.active is not None:
            with Session(f.case.engine) as session:
                old=session.get(EncounterWorkspace,f.wid)
                from cosmas_os.models import AppointmentObservation
                prior=session.get(AppointmentObservation,old.appointment_id)
                appointment=AppointmentObservation(box_id=f.box,patient_link_id=prior.patient_link_id,external_id=uuid4().hex,source="synthetic",start_at=prior.start_at,patient_label=f"Invented {persona} fax encounter round {iteration}")
                session.add(appointment);session.commit();f.wid=ws.create(session,f.box,f.owner,appointment.id,"fax-ui-next:"+uuid4().hex)["id"]
        with Session(f.case.engine) as session:
            team_snapshot=team.read(session,f.box,f.owner)
            if team_snapshot["revision"]==0:team_snapshot=team.save(session,f.box,f.owner,expected=0,key="fax-ui-team",configuration=team.default_configuration())
        episode = SimpleNamespace(id=str(uuid4()), persona=persona, iteration=iteration,
            operation_id=None, provider_before=len(f.wire), credentials_before=len(f.wire),
            provider_after=None, credentials_after=None,
            before=read_workspace(), fax_id=f.documo_id)
        holder.active = episode
        cases[episode.id] = episode
        episode.document_sha256=hashlib.sha256(f.pdf).hexdigest()
        episode.wid=f.wid
        episode.final_workspace=None
        signed = f.headers()
        assert set(signed) == {"Authorization", "X-Cosmas-Draft-Recovery", "X-Cosmas-Fax-Inbound"}
        return {"case_id": episode.id, "token": signed["Authorization"].removeprefix("Bearer "),
            "workspace": episode.before, "installation_id": str(f.items[1].selection.connection_id),
            "fax_id": f.documo_id, "pdf_sha256": hashlib.sha256(f.pdf).hexdigest(), "pdf_byte_length": len(f.pdf),"passage":passage,"team_revision":team_snapshot["revision"]}

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
                    if self.command=="POST" and parsed.path=="/lab/revoke":
                        size=int(self.headers.get("Content-Length","0"));body=json.loads(self.rfile.read(size));episode=cases[body["case_id"]]
                        with Session(f.case.engine) as session:
                            from cosmas_os.fax_inbound_models import FaxInboundImage
                            image=session.scalar(select(FaxInboundImage).where(FaxInboundImage.operation_id==episode.operation_id))
                            fax_ledger.revoke(session,f.box,f.owner,image.grant_id,key="ui-revoke:"+uuid4().hex)
                        return self.respond(200,inspect(episode))
                    if self.command=="POST" and parsed.path=="/lab/work":
                        size=int(self.headers.get("Content-Length","0"));body=json.loads(self.rfile.read(size));episode=cases[body["case_id"]];return self.respond(200,run_tasks(episode,body.get("handoff_id")))
                    assert parsed.path in {"/provider-team", "/workspaces"} or parsed.path.startswith(("/provider-team/", "/connections/", "/vendor-settings", "/fax-inbound", "/workspaces/"))
                    assert not parsed.query
                    headers = {name: value for name, value in self.headers.items()
                        if name.lower() in {"authorization", "x-cosmas-draft-recovery", "x-cosmas-fax-inbound",
                            "x-cosmas-team-contract", "x-cosmas-model-contract", "x-cosmas-handoff-review", "x-cosmas-connection-contract", "x-cosmas-vendor-setup-contract", "accept", "content-type"}}
                    if self.command == "GET":
                        response = holder.client.get(self.path, headers=headers)
                    else:
                        size = int(self.headers.get("Content-Length", "0"))
                        assert 0 < size <= 65536
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

    def dispatch(claim):
        context=_context(claim.envelope["context"])
        selected=next(p for p in context.sources if p.label=="Received practice fax passage (human reviewed)")
        def provider(request):
            body=json.loads(request.content);assert body["store"] is False
            model_rounds.append({"workspace_id":claim.workspace_id,"role":context.role})
            if not any(m["role"]=="tool" for m in body["messages"]):
                handle=next(p for p in claim.envelope["tool_selection"]["sources"] if p["entry_id"]==selected.entry_id)
                msg={"role":"assistant","content":None,"tool_calls":[{"id":"read_fax","type":"function","function":{"name":"read_selected_source","arguments":json.dumps({k:handle[k] for k in ("entry_id","revision","sha256")})}}]};finish="tool_calls"
            else:
                tool=json.loads(next(m["content"] for m in body["messages"] if m["role"]=="tool"));assert tool["data"]["content"]==selected.content and tool["receipt"]["actor_agent_id"]!=f.owner
                if context.role=="chief":
                    content={"answer":"Preparing a private fax draft.","source_ids":[selected.entry_id],"handoffs":[{"role":"scribe","intended_role":"scribe","brief":"Organize the reviewed fax into a private draft; preserve uncertainty.","requirements":REQUIREMENTS}]}
                    if claim.envelope["baseline"]["flags"]["work_status"]:content["intent"]="conversation"
                else:
                    needs=["Who owns the next step and when should it be reviewed?"]
                    marker="Human-requested revision of the prior private draft\n"
                    if marker in context.question:needs.append(json.loads(context.question.split(marker,1)[1].split("\nTreat the quoted prior draft",1)[0])["feedback"])
                    content={"excerpts":[{"source_id":selected.entry_id,"quote":selected.content}],"needs_from_clinician":needs}
                msg={"role":"assistant","content":json.dumps(content)};finish="stop"
            return httpx.Response(200,json={"model":"gpt-4.1","usage":{"prompt_tokens":100,"completion_tokens":20},"choices":[{"finish_reason":finish,"message":msg}]})
        return original_dispatch(claim,session_factory=lambda:Session(f.case.engine),transport=httpx.MockTransport(provider))
    def run_tasks(episode,hid=None):
        for _ in range(3):
            with Session(f.case.engine) as session:
                rows=list(session.scalars(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id==episode.wid,ModelWorkAdmission.state=="reserved").order_by(ModelWorkAdmission.admitted_at)))
                if not rows:break
                row=rows[0]
                if hid:
                    h=next(h for h in ws.read(session,f.box,f.owner,episode.wid)["handoffs"] if h["id"]==hid)
                    row=next(r for r in rows if r.handoff_attempt_id==h["attempt_id"])
                claim=work.claim(session,f.box,f.owner,row.id)
            assert claim is not None
            result=dispatch(claim)
            with Session(f.case.engine) as session:work.settle(session,claim,result)
            if hid:break
        return read_workspace()
    monkeypatch.setattr(work,"dispatch_claim",dispatch)
    start()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {name: os.environ[name] for name in ("PATH", "TMPDIR") if name in os.environ}
    env.update(COSMAS_FAX_OPERATIONAL_LAB_URL=f"http://127.0.0.1:{server.server_port}",
        COSMAS_FAX_OPERATIONAL_LAB_REPORT=str(output / "ui-server-lab.json"))
    try:
        completed = subprocess.run([str(NODE), "node_modules/vitest/vitest.mjs", "run",
            "src/FaxOperationalServerLab.test.tsx", "--maxWorkers=1"], cwd=REPO / "web", env=env,
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
            assert observed["workspace"]["note"] == episode.before["note"]
            assert observed["review_count"]==1 and observed["model_rounds"]==6
            assert observed["case_provider_calls"] == observed["case_credential_calls"] == 2
            assert observed["image_calls"] == 1
            assert observed["operation"] == {"id": episode.operation_id, "status": "succeeded",
                "attempt_count": 1, "acquisition": True, "invocation": True, "outcome": "acquired",
                "document_sha256": episode.document_sha256, "document_pages": 1,
                "decisions": 1, "patient_link_id": None, "appointment_id": None}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if holder.client is not None:
            holder.client.__exit__(None, None, None)
