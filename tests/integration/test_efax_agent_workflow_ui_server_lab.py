"""Actual signed Chief/tool/draft/human-review graph with invented fax and Gmail.

The long source was explicitly prepared by the shared source fixture. This
qualifies mounted product composition and human controls, not real clinicians,
live models or outside delivery. The only model boundary is finite mock HTTP.
"""

import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Barrier, Lock, Thread
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration import test_efax_source_full_workflow as full
from tests.integration.test_google_message import read as read_gmail
from tests.integration.test_google_message import select_message

from cosmas_os.adapters.gpt41 import ENDPOINT, _context
from cosmas_os.adapters.gpt41_tools_v6 import validate_prepared
from cosmas_os.application import google_message as gmail
from cosmas_os.application import handoff_briefs
from cosmas_os.application import model_work as work
from cosmas_os.application import note_review as notes
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    AppointmentObservation,
    AuditEvent,
    EncounterWorkspace,
    ModelWorkAdmission,
    Principal,
    WorkspaceHandoffAttempt,
)
from cosmas_os.ports.bot_capabilities import BotReply, ModelCallFailure
from cosmas_os.ports.google_message import GoogleMessageBinding

managed_case = full.managed_case
efax_http = full.efax_http
source_http = full.source_http
long_fax = full.long_fax
NODE = Path("/Users/jw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
REPO = Path(__file__).resolve().parents[2]


def test_six_signed_fax_chief_human_revision_acceptance_graphs(long_fax, monkeypatch, tmp_path):
    f = long_fax
    # The shared managed fixture starts with model work disabled, then enables
    # the real admission/adapter path. No ordinary queue worker may compete
    # with this test's explicitly scoped manual dispatch/barrier.
    assert "handoffs" not in f.client.app.state.workspace_worker_progress
    output = tmp_path / "signed-efax-agent-workflow"
    output.mkdir()
    cases, dispatches, reads = {}, [], []
    lock = Lock()
    holder = SimpleNamespace(active=None, barrier=None)
    original_dispatch = work.dispatch_claim

    def current(episode=None):
        wid = episode.wid if episode is not None else f.wid
        result = full.fax.signed_fixture.result(f.client.get("/workspaces/" + wid,
            headers={**f.headers(), "X-Cosmas-Model-Contract": "1"}))
        result.pop("model_observed_at", None)
        return result

    def dispatch(claim):
        episode = holder.active
        assert episode is not None
        assert claim.workspace_id == episode.wid
        context = _context(claim.envelope["context"])
        validate_prepared(claim.envelope)
        assert claim.envelope["contract"] == "cosmas-gpt41-prepared.v6"
        selected = {p.entry_id: p for p in context.sources}
        assert selected[episode.fax_id].content == full.LONG_PASSAGE
        assert selected[episode.mail_id].content == episode.mail_content
        handles = [next(p for p in claim.envelope["tool_selection"]["sources"] if p["entry_id"] == eid)
            for eid in (episode.fax_id, episode.mail_id)]
        assert handles[0]["sha256"] == full.sha(full.LONG_PASSAGE)
        with Session(f.case.engine) as s:
            row = s.get(ModelWorkAdmission, claim.admission_id)
            assert row is not None and row.source_sha256 == work.source_digest(context)
            if row.kind == "private_handoff":
                assert row.request_body["task_brief"]["version"] == 2
                assert row.request_body["task_brief"]["source_versions"] == handoff_briefs.source_versions(context)
        bodies, receipts = [], []
        tool_sessions = []

        class TrackedToolSession(Session):
            boundary_closed = False

            def close(self):
                try:
                    super().close()
                finally:
                    self.boundary_closed = True

        def tool_session():
            result = TrackedToolSession(f.case.engine)
            with lock:
                tool_sessions.append(result)
            return result

        def provider(request):
            assert str(request.url) == ENDPOINT
            assert request.headers["Authorization"] == "Bearer invented-product-http-key"
            body = json.loads(request.content)
            assert body["model"] == "gpt-4.1" and body["store"] is False
            bodies.append(body)
            assert all(s.boundary_closed and not s.in_transaction() for s in tool_sessions)
            if len(bodies) == 2 and holder.barrier is not None:
                # All three tool transactions have returned before testing
                # the second HTTP round's lock boundary. Otherwise a peer's
                # legitimate concurrent tool read can confuse this probe.
                holder.barrier.wait(timeout=15)
            # Provider I/O occurs outside the owner/admission transaction.
            # Serialize only this diagnostic probe so three model requests
            # do not falsely report a lock held by another probe itself.
            with lock, Session(f.case.engine) as s:
                assert s.scalar(select(Principal).where(Principal.id == f.owner).with_for_update(nowait=True))
            if holder.barrier is not None:
                # A peer must not begin tool I/O or result settlement until
                # all three lock probes have left their HTTP boundary.
                holder.barrier.wait(timeout=15)
            if len(bodies) == 1:
                return httpx.Response(200, json=full.product.response(calls=[{
                    "id": "source_" + str(n), "type": "function", "function": {
                        "name": "read_selected_source", "arguments": json.dumps({k: p[k]
                            for k in ("entry_id", "revision", "sha256")})}} for n, p in enumerate(handles)]))
            assert len(bodies) == 2
            received = [json.loads(m["content"]) for m in body["messages"] if m["role"] == "tool"]
            assert len(received) == 2
            for expected, result in zip(handles, received, strict=True):
                receipt = result["receipt"]
                assert result["tool"] == "read_selected_source"
                assert result["data"]["content"] == selected[expected["entry_id"]].content
                assert hashlib.sha256(result["data"]["content"].encode()).hexdigest() == expected["sha256"]
                assert receipt["initiated_by_human_id"] == f.owner and receipt["actor_agent_id"] != f.owner
                assert receipt["admission_id"] == claim.admission_id
                receipts.append(receipt)
                with lock:
                    reads.append({"case_id": episode.id, "role": context.role,
                        "admission_id": claim.admission_id, "source_id": expected["entry_id"], "receipt": receipt})
            feedback = episode.feedback if "Human-requested revision" in context.question else ""
            if feedback:
                assert feedback in context.question
            summary = full.MID_FACT + "\n" + full.LATE_FACT + "\n" + full.FINAL_FACT
            output = {"answer": summary + ("\n" + feedback if feedback else ""),
                "source_ids": [p.entry_id for p in context.sources]}
            if context.role == "scribe":
                output = {"excerpts": [{"source_id": handles[0]["entry_id"], "quote": full.LATE_FACT},
                    {"source_id": handles[0]["entry_id"], "quote": full.FINAL_FACT}],
                    "needs_from_clinician": ["Confirm missing DOB, medication names and trial eligibility."
                        + (" " + feedback if feedback else "")]}
            flags = claim.envelope["baseline"]["flags"]
            if flags["work_status"]:
                output["intent"] = "conversation"
            if flags["can_handoff"]:
                output["handoffs"] = [{"role": role, "intended_role": role,
                    "brief": "Read full exact original fax and reviewed email; prepare an independent private " + role
                        + " draft retaining uncertainty and a human owner. Do not send or book.",
                    "requirements": full.REQUIREMENTS} for role in ("scribe", "visit_prep", "follow_up")]
            return httpx.Response(200, json=full.product.response(output))

        result = original_dispatch(claim, session_factory=tool_session, transport=httpx.MockTransport(provider))
        assert isinstance(result, BotReply) and result.input_tokens == 200 and result.output_tokens == 40
        assert len(bodies) == 2 and len(receipts) == 2
        with lock:
            dispatches.append({"case_id": episode.id, "admission_id": claim.admission_id,
                "role": context.role, "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                "provider_rounds": len(bodies), "tool_reads": len(receipts),
                "tool_sessions_closed_before_http": all(s.boundary_closed for s in tool_sessions)})
        return result

    monkeypatch.setattr(work, "dispatch_claim", dispatch)

    def inspect(episode):
        with Session(f.case.engine) as s:
            admissions = list(s.scalars(select(ModelWorkAdmission).where(
                ModelWorkAdmission.workspace_id == episode.wid, ModelWorkAdmission.id.in_(episode.admissions))))
            audits = list(s.scalars(select(AuditEvent).where(AuditEvent.box_id == f.box,
                AuditEvent.event_type == "workspace.agent_tool_read")))
            events = [p for p in audits if p.detail.get("admission_id") in episode.admissions]
            def admission_detail(p):
                attempt = s.get(WorkspaceHandoffAttempt, p.handoff_attempt_id) if p.handoff_attempt_id else None
                assert p.handoff_attempt_id is None or attempt is not None
                return {"id": p.id, "state": p.state, "reason": p.reason, "kind": p.kind,
                    "role": p.prepared_envelope["context"]["role"], "source_sha256": p.source_sha256,
                    "envelope_sha256": p.envelope_sha256, "agent_id": p.agent_id, "owner_id": p.owner_id,
                    "handoff_id": attempt.handoff_id if attempt is not None else None}
            return {"case_id": episode.id, "workspace": episode.final_workspace or current(episode),
                "admissions": [admission_detail(p) for p in admissions],
                "tool_receipts": [{"actor_id": p.actor_principal_id, "human_id": p.initiated_by_principal_id,
                    "detail": p.detail} for p in events],
                "dispatches": [p for p in dispatches if p["case_id"] == episode.id],
                "reads": [p for p in reads if p["case_id"] == episode.id],
                "image_calls": sum(p["path"].endswith("/image") for p in f.wire),
                "provider_calls": len(f.wire)}

    with Session(f.case.engine) as google_session:
        g, _mutable_binding = full.select_gmail(f, monkeypatch, google_session)
        frozen_binding = GoogleMessageBinding(account_id=g.account, binding_digest="a" * 64,
            connected_at=g.port.connected, grant_sha256=g.port.grant)
        def binding(_session, identity, _full):
            # DB ownership/ready credential checks remain in the real service.
            # Return only immutable semantic grant facts; concurrent readers
            # never mutate a provider object's shared Session reference.
            assert str(identity.id) == frozen_binding.account_id
            return frozen_binding
        with gmail.install_binding_reader(binding):
            mail_read = read_gmail(g)
            select_message(g, receipt=mail_read)
            google_session.rollback()
            assert not google_session.in_transaction()
            with Session(f.case.engine) as setup:
                original_workspace = setup.get(EncounterWorkspace, f.wid)
                assert original_workspace is not None and original_workspace.patient_link_id is not None
                patient_id = original_workspace.patient_link_id

            def create_case(persona, iteration):
                if holder.active is not None:
                    previous = inspect(holder.active)
                    assert len(previous["admissions"]) == 5 and all(p["state"] == "completed" for p in previous["admissions"])
                    holder.active.final_workspace = previous["workspace"]
                # One real workspace per graph keeps retained history below
                # the product's 12-assignment/50-model-turn limits. No prior
                # handoff, review, admission, source or note is deleted.
                with Session(f.case.engine) as setup:
                    visit = AppointmentObservation(box_id=f.box, patient_link_id=patient_id,
                        external_id=str(uuid4()), source="synthetic", start_at=datetime.now(UTC),
                        patient_label="Invented " + persona + " fax encounter " + iteration)
                    setup.add(visit)
                    setup.commit()
                    workspace = ws.create(setup, f.box, f.owner, visit.id,
                        full.fax.signed_fixture.key(), initial_synthetic_source=False)
                    wid = workspace["id"]
                    setup.rollback()
                    linked_mail = gmail.select_review(setup, f.box, f.owner, wid,
                        expected=workspace["revision"], key=full.fax.signed_fixture.key(),
                        read_id=mail_read["read_id"], source_sha256=mail_read["source_sha256"],
                        patient_link_id=patient_id, reviewed_patient=True, reviewed_exact_message=True,
                        reviewed_untrusted_source=True, external_identity_id=g.account)
                    setup.rollback()
                    workspace = current(SimpleNamespace(wid=wid))
                    linked_fax = full.fax.source.select_review(setup, f.box, f.owner, wid,
                        expected=workspace["revision"], key=full.fax.signed_fixture.key(),
                        operation_id=f.fax_command["operation_id"], document_sha256=f.fax_command["document_sha256"],
                        passage=full.LONG_PASSAGE, page_numbers=(1,), reviewed_patient=True,
                        reviewed_exact_document=True, reviewed_exact_text=True, reviewed_untrusted_source=True)
                    setup.rollback()
                    workspace = current(SimpleNamespace(wid=wid))
                    saved_note = notes.save(setup, f.box, f.owner, wid, expected=workspace["revision"],
                        key=full.fax.signed_fixture.key(), base_note_id=None, source_reply_id=None,
                        content="Invented existing reviewed clinical note. Preserve during private agent work.")
                    setup.rollback()
                    note = saved_note["workspace"]["note"]["latest"]
                    notes.review(setup, f.box, f.owner, wid, note["id"],
                        expected=saved_note["workspace"]["revision"], key=full.fax.signed_fixture.key(),
                        content_hash=note["content_hash"], source_hash=note["source_fingerprint"])
                    setup.rollback()
                    assert not setup.in_transaction()
                before = current(SimpleNamespace(wid=wid))
                mail = next(p for p in before["entries"] if p["id"] == linked_mail["entry_id"])
                assert mail["google_source_state"] == "current"
                episode = SimpleNamespace(id=str(uuid4()), persona=persona, iteration=iteration,
                    wid=wid, admissions=set(), handoffs=set(), final_workspace=None, fax_id=linked_fax["entry_id"],
                    feedback=f"{persona} round {iteration}: retain unknown DOB and confirm the provider owns the draft review.",
                    mail_id=mail["id"], mail_content=mail["content"], before=before)
                holder.active = episode
                cases[episode.id] = episode
                return {"case_id": episode.id, "token": f.headers()["Authorization"].removeprefix("Bearer "),
                    "workspace": episode.before, "fax_entry_id": episode.fax_id,
                    "fax_sha256": full.sha(full.LONG_PASSAGE), "mail_entry_id": mail["id"],
                    "feedback": episode.feedback, "late_fact": full.LATE_FACT, "final_fact": full.FINAL_FACT}

            def scoped_work(episode):
                with Session(f.case.engine) as s:
                    rows = list(s.scalars(select(ModelWorkAdmission).where(
                        ModelWorkAdmission.workspace_id == episode.wid, ModelWorkAdmission.id.in_(episode.admissions),
                        ModelWorkAdmission.kind == "private_handoff", ModelWorkAdmission.state == "reserved")))
                    assert len(rows) in {1, 3}
                    claims = [work.claim(s, f.box, f.owner, p.id) for p in rows]
                    assert all(p is not None for p in claims)
                holder.barrier = Barrier(3) if len(claims) == 3 else None
                def execute(claim):
                    try:
                        result = dispatch(claim)
                    except ModelCallFailure as error:
                        result = error
                    with Session(f.case.engine) as s:
                        work.settle(s, claim, result)
                try:
                    with ThreadPoolExecutor(max_workers=len(claims)) as pool:
                        list(pool.map(execute, claims))
                finally:
                    holder.barrier = None
                observed = inspect(episode)
                assert all(p["state"] == "completed" for p in observed["admissions"])

            class Bridge(BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass

                def respond(self, status, value, headers=None):
                    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
                    self.send_response(status)
                    for name, v in (headers or {}).items():
                        if name.lower() not in {"content-length", "content-encoding", "transfer-encoding", "connection"}:
                            self.send_header(name, v)
                    if not headers or "content-type" not in headers:
                        self.send_header("Content-Type", "application/json")
                    if not headers or "cache-control" not in headers:
                        self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)

                def dispatch_request(self):
                    try:
                        parsed = urlsplit(self.path)
                        if self.command == "GET" and parsed.path == "/lab/case":
                            q = parse_qs(parsed.query)
                            persona, iteration = q["persona"][0], q["round"][0]
                            assert persona in {"physician", "nurse_practitioner", "physician_assistant"} and iteration in {"1", "2"}
                            return self.respond(200, create_case(persona, iteration))
                        if self.command == "GET" and parsed.path == "/lab/inspect":
                            return self.respond(200, inspect(cases[parse_qs(parsed.query)["case_id"][0]]))
                        episode = holder.active
                        assert episode is not None
                        if self.command == "POST" and parsed.path in {"/lab/work", "/lab/revoke"}:
                            size = int(self.headers.get("Content-Length", "0"))
                            assert 0 < size <= 1024
                            value = json.loads(self.rfile.read(size))
                            assert value == {"case_id": episode.id}
                            if parsed.path == "/lab/work":
                                scoped_work(episode)
                            else:
                                assert len(cases) == 6
                                full.revoke(f)
                            return self.respond(200, inspect(episode))
                        assert not parsed.query and (parsed.path.startswith("/provider-team") or parsed.path == "/workspaces"
                            or parsed.path.startswith("/workspaces/" + episode.wid))
                        headers = {name: value for name, value in self.headers.items() if name.lower() in {
                            "authorization", "x-cosmas-draft-recovery", "x-cosmas-team-contract",
                            "x-cosmas-model-contract", "x-cosmas-handoff-review", "accept", "content-type"}}
                        if self.command == "GET":
                            response = f.client.get(self.path, headers=headers)
                        else:
                            size = int(self.headers.get("Content-Length", "0"))
                            assert 0 < size <= 65536
                            body = self.rfile.read(size)
                            response = f.client.post(self.path, headers=headers, content=body)
                            with Session(f.case.engine) as s:
                                episode.admissions.update(s.scalars(select(ModelWorkAdmission.id).where(
                                    ModelWorkAdmission.workspace_id == episode.wid, ModelWorkAdmission.id.not_in(
                                        set().union(*(p.admissions for p in cases.values()))))))
                        return self.respond(response.status_code, response.content, response.headers)
                    except Exception as error:
                        return self.respond(500, {"detail": type(error).__name__ + ": " + str(error)[:500]})

                do_GET = dispatch_request
                do_POST = dispatch_request

            server = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
            server.daemon_threads = True
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            env = {k: os.environ[k] for k in ("PATH", "TMPDIR") if k in os.environ}
            env.update(COSMAS_EFAX_AGENT_LAB_URL=f"http://127.0.0.1:{server.server_port}",
                COSMAS_EFAX_AGENT_LAB_REPORT=str(output / "ui-server-lab.json"))
            try:
                completed = subprocess.run([str(NODE), "node_modules/vitest/vitest.mjs", "run",
                    "src/EFaxAgentWorkflow.signed-api.test.tsx", "--maxWorkers=1"], cwd=REPO / "web", env=env,
                    text=True, capture_output=True, timeout=420)
                (output / "vitest.log").write_text(completed.stdout + completed.stderr)
                observations = [inspect(p) for p in cases.values()]
                (output / "backend-evidence.json").write_text(json.dumps({"synthetic_only": True,
                    "cases": observations, "provider_wire": f.wire, "gmail_calls": g.port.calls,
                    "workspace_ids": [p.wid for p in cases.values()],
                    "worker_boundary": "Managed startup has no handoffs worker; actual claims/dispatch/settlement are manually scoped.",
                    "returncode": completed.returncode}, indent=2) + "\n")
                assert completed.returncode == 0, completed.stdout + completed.stderr
                report = json.loads((output / "ui-server-lab.json").read_text())
                assert report["completed"] == report["total"] == len(cases) == 6
                assert len({p.wid for p in cases.values()}) == 6
                assert len(dispatches) == 30 and len(reads) == 60
                assert g.port.calls == ["list", "read"] and len(f.wire) == 2
                for episode in cases.values():
                    observed = inspect(episode)
                    assert len(observed["admissions"]) == 5 and all(p["state"] == "completed" for p in observed["admissions"])
                    assert len(observed["tool_receipts"]) == 10
                    assert observed["workspace"]["note"] == episode.before["note"]
                    assert len(observed["workspace"]["handoffs"]) == 4
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                # Fence only this fixture's unfinished admissions; never drain
                # or mutate the global authoritative worker queue.
                owned = set().union(*(p.admissions for p in cases.values()))
                with Session(f.case.engine) as s:
                    for row in list(s.scalars(select(ModelWorkAdmission).where(ModelWorkAdmission.id.in_(owned),
                        ModelWorkAdmission.state.in_(("reserved", "running"))))):
                        if row.state == "reserved":
                            claim = work.claim(s, f.box, f.owner, row.id)
                        else:
                            assert row.dispatch_id is not None
                            claim = work.ModelClaim(row.id, f.box, f.owner, row.workspace_id,
                                row.dispatch_id, row.envelope_sha256, row.prepared_envelope)
                        if claim is not None:
                            work.settle(s, claim, ModelCallFailure(dispatch="not_dispatched"))
