"""Actual signed local capture/team/plugin/action cycle with authored plan gates.

Simulated ASR is explicit. Public Research is real token-free HTTPS; Spruce and
model endpoints are owned local sockets. Missing actor plans never fall back to
canned semantic outputs. Set COSMAS_COMPLETED_CYCLE_OUTPUT to a fresh directory.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from lab.completed_action_cycle import run_completed_action_cycle, write
from lab.completed_action_evaluator import evaluate_completed_action
from lab.completed_action_sandbox import (
    SYNTHETIC_CREDENTIAL,
    CompletedActionSandbox,
    SandboxVendorTransport,
    digest,
)
from lab.cycle_personas import scenarios
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from tests.integration.test_workspace_capture import admit, capture_case
from tests.unit.test_core_scribe_bridge import reviewed_fixture

from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.api import app as api
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import handoffs, model_work, note_review, scribe_source, vendor_execution
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.models import (
    AuditEvent,
    ModelWorkAdmission,
    Operation,
    WorkspaceEntry,
    WorkspaceReply,
)
from cosmas_os.plugins.runtime import AuthenticatedSession, PluginRuntime
from cosmas_os.ports import vendor_connectors as private
from cosmas_os.ports.creator_review import CreatorReviewView, ProviderEncounter
from cosmas_os.vendor_models import (
    VendorConnectionVersion,
    VendorCorrespondenceVersion,
    VendorProviderObservation,
    VendorSubmitClaim,
    VendorWorkRevision,
)

__all__ = ["capture_case"]


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def wait_plan(folder, name, context, *, timeout=600):
    folder.mkdir(parents=True, exist_ok=True)
    context = {**context, "context_sha256": digest(context)}
    write(folder / ("context.json" if name == "plan.json" else name.replace("plan", "context")), context)
    print("ACTOR_MAILBOX " + str(folder / name), flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (folder / name).exists():
            plan = json.loads((folder / name).read_text())
            assert plan["context_sha256"] == context["context_sha256"], "author_context_binding_changed"
            assert plan["author_agent_id"].startswith("/root"), "actual_actor_author_required"
            return plan
        time.sleep(1)
    raise AssertionError("actor_plan_unavailable_no_admission")


def scenario_review(scenario, session_id, *, clarified):
    value = reviewed_fixture().model_dump(mode="json")
    turns = scenario["turns"] + (scenario["reviewed_contact_resolution"] or [] if clarified else [])
    segments, working = [], []
    speakers = {role: str(uuid4()) for role in ("provider", "patient")}
    for i, item in enumerate(turns):
        origin = {"source_segment_id": str(uuid4()), "source_segment_version": 1,
            "source_locale": "en-US", "speaker_id": speakers[item["speaker"]],
            "speaker_role": "clinician" if item["speaker"] == "provider" else "patient",
            "start_ms": i * 10000, "end_ms": (i + 1) * 10000}
        segments.append({**origin, "content": item["content"], "locale_confidence": None})
        working.append({**origin, "resolution": "english_source", "content": item["content"],
            "translation_id": None, "translation_version": None, "translation_review_id": None})
    value["session_id"] = str(session_id)
    value["source"].update(language_mode="en-US", transcription_adapter_id="simulated_asr_local",
        transcription_model_profile_id="authored_virtual_personas_v1", normalization_profile_id="no_semantic_rewrite_v1",
        duration_ms=len(turns) * 10000, segments=segments)
    value["working"].update(working_transcript_id=str(uuid4()), working_transcript_version=1,
        segments=working, blockers=[], note_ready=True)
    value["review_queue"].update(session_id=str(session_id), working_transcript_id=value["working"]["working_transcript_id"],
        working_transcript_version=1, status="complete", items=[])
    value["capture_continuity"] = {"schema_version": "1.0", "continuity": "continuous", "missing_audio": False}
    # The continuity field is deliberately omitted: no physical audio continuity
    # is established by this simulated-ASR input.
    value.pop("capture_continuity", None)
    return CreatorReviewView.model_validate(value)


class ActorModelSocket:
    """Real owned HTTP with responses composed from the bound actor plan only."""
    def __init__(self, envelope, final, calls, output):
        self.envelope, self.final, self.calls, self.output = envelope, final, calls, output
        self.events = []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                assert self.path == "/chat/completions"
                data = json.loads(self.rfile.read(int(self.headers["content-length"])))
                owner.events.append(data)
                tool_results = [m for m in data["messages"] if m["role"] == "tool"]
                if not tool_results and owner.calls:
                    message = {"role": "assistant", "content": None, "tool_calls": [
                        {"id": "call_" + str(i), "type": "function", "function": {
                            "name": c["tool"], "arguments": json.dumps({k: v for k, v in c.items() if k != "tool"})}}
                        for i, c in enumerate(owner.calls)]}
                    reason = "tool_calls"
                else:
                    message, reason = {"role": "assistant", "content": json.dumps(owner.final)}, "stop"
                value = {"model": "gpt-4.1", "choices": [{"finish_reason": reason, "message": message}],
                         "usage": {"prompt_tokens": 100, "completion_tokens": 100}}
                raw = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = "http://127.0.0.1:" + str(self.server.server_port)
    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        write(self.output, {"envelope_sha256": digest(self.envelope), "rounds": self.events,
                            "listener_closed": True, "thread_stopped": not self.thread.is_alive()})


class ModelSocketTransport(httpx.BaseTransport):
    def __init__(self, origin):
        self.origin, self.inner = httpx.URL(origin), httpx.HTTPTransport(retries=0, trust_env=False)
    def handle_request(self, request):
        assert str(request.url) == "https://cosmascode.services.ai.azure.com/openai/v1/chat/completions"
        request.url = self.origin.copy_with(path="/chat/completions")
        return self.inner.handle_request(request)
    def close(self):
        self.inner.close()


def source_calls(envelope):
    return [{"tool": "read_selected_source", **{k: p[k] for k in ("entry_id", "revision", "sha256")}}
            for p in envelope["tool_selection"]["sources"][:3]]


def final_answer(envelope, answer, tasks=()):
    context = envelope["context"]
    value = {"answer": answer, "source_ids": [p["entry_id"] for p in context["sources"]]}
    schema = envelope["body"]["response_format"]["json_schema"]["schema"]
    if "intent" in schema["required"]:
        value["intent"] = "conversation"
    if "handoffs" in schema["required"]:
        targets = {p["role"]: p["address"] for p in context["handoff_targets"]}
        value["handoffs"] = [{"role": targets[role], "intended_role": role, **task} for role, task in tasks]
    return value


def export_row(row):
    return {column.name: (getattr(row, column.name).isoformat() if isinstance(getattr(row, column.name), datetime)
            else getattr(row, column.name)) for column in row.__table__.columns}


def install_vendor(f, scenario, factory):
    with factory() as s:
        cid, coid = str(uuid4()), str(uuid4())
        chosen = private.ConnectionSelection(vendor="spruce", connection_id=UUID(cid), box_id=UUID(f.box), owner_id=UUID(f.actor),
            environment="production", remote_account_id="virtual_clinic_only", credential_ref=uuid4(), configuration_sha256="a" * 64)
        view = {"id": cid, "revision": 1, "vendor": "spruce", "environment": "production", "label": "Owned virtual Spruce socket",
            "actions": ["spruce_secure_message"], "availability": "enabled"}
        view["public_sha256"] = public.public_digest("cosmas-vendor-public-selection.v1", view)
        connection = VendorConnectionVersion(id=cid, family_id=str(uuid4()), revision=1, box_id=f.box, owner_id=f.actor,
            vendor="spruce", environment="production", private_selection=chosen.model_dump(mode="json"),
            routing={"internal_endpoint_id": "virtual_clinic", "event_route_id": str(uuid4())}, private_sha256=chosen.commitment(),
            public_view=view, public_sha256=view["public_sha256"], reviewed_by=f.actor, reviewed_at=datetime.now(UTC), write_enabled=True, read_enabled=True)
        expiry = datetime.now(UTC) + timedelta(days=2)
        proof = {"destination": {"channel": "secure", "contact_id": scenario["approved_action"]["recipient"]},
            "permission_sha256": "b" * 64, "patient_mapping_sha256": "c" * 64, "practice_mapping_sha256": "d" * 64, "recipient_mapping_sha256": "e" * 64}
        cov = {"id": coid, "revision": 1, "connection_id": cid, "channel": "secure", "recipient_label": scenario["patient"]["name"],
            "destination_display": "Owned virtual private inbox", "permission": "reviewed", "expires_at": public.timestamp(expiry)}
        cov["public_sha256"] = public.public_digest("cosmas-vendor-public-selection.v1", cov)
        correspondence = VendorCorrespondenceVersion(id=coid, family_id=str(uuid4()), revision=1, box_id=f.box, owner_id=f.actor,
            patient_link_id=f.patient_link_id, connection_version_id=cid, private_proof=proof,
            private_sha256=private.digest("cosmas-vendor-correspondence.v1", proof), public_view=cov, public_sha256=cov["public_sha256"],
            reviewed_by=f.actor, reviewed_at=datetime.now(UTC), expires_at=expiry)
        s.add(connection)
        s.flush()
        s.add(correspondence)
        s.commit()
        return {"connection": {k: view[k] for k in ("id", "revision", "public_sha256")},
                "correspondence": {k: cov[k] for k in ("id", "revision", "public_sha256")}, "chosen": chosen}


@pytest.mark.parametrize("scenario", scenarios(), ids=lambda case: case["scenario_id"])
def test_completed_action_cycle(capture_case, monkeypatch, tmp_path, scenario):
    f = capture_case
    root = Path(os.environ.get("COSMAS_COMPLETED_CYCLE_OUTPUT", os.environ.get("COSMAS_SCRIBE_SPECIALIST_EVIDENCE_DIR", str(tmp_path / "cycle-evidence"))))
    folder = root / scenario["scenario_id"]
    folder.mkdir(parents=True, exist_ok=False)
    factory = sessionmaker(f.engine, expire_on_commit=False)
    monkeypatch.setattr(api, "SessionLocal", factory)
    for name, value in {"workspace_agent_tools_enabled": True, "workspace_llm_backend": "azure_gpt41",
            "workspace_llm_api_key": SecretStr("invented-owned-model-socket"), "vendor_work_enabled": True,
            "vendor_io_enabled": True, "workspace_research_enabled": True, "workspace_research_io_enabled": True,
            "research_sources": "pubmed", "research_dataset_mappings": "{}"}.items():
        monkeypatch.setattr(f.configuration, name, value)
        monkeypatch.setattr(settings, name, value)
    for module in (team, handoffs):
        monkeypatch.setattr(module, "runtime_settings", f.configuration)
    def human(method, path, **kwargs):
        url = httpx.URL(path)
        if url.is_absolute_url:
            assert url.host == "cycle-api.example.invalid" and url.scheme == "https"
            path = url.raw_path.decode()
        headers = {**kwargs.pop("headers", {}), "Authorization": "Bearer " + f.token(), "X-Cosmas-Model-Contract": "1"}
        kwargs.pop("timeout", None)
        response = f.client.request(method, path, headers=headers, **kwargs)
        # The trusted host proxy returns exact signed API bytes as a bounded
        # httpx response at its pinned logical HTTPS origin. TestClient is the
        # in-process API transport; credentials remain in this host callback.
        return httpx.Response(response.status_code, headers=dict(response.headers), content=response.content,
            request=httpx.Request(method, "https://cycle-api.example.invalid" + path))
    def snapshot():
        response = human("GET", f"/workspaces/{f.workspace['id']}")
        assert response.status_code == 200, response.text
        return response.json()
    admitted = admit(f)
    assert admitted.status_code == 200, admitted.text
    f.view = scenario_review(scenario, f.port.saved.session_id, clarified=scenario["reviewed_contact_resolution"] is None)
    def existing(binding, credential, key):
        f.port.step("provider_encounter")
        return ProviderEncounter(schema_version="1.0", status="available", review=f.view)
    f.port.provider_encounter = existing
    base = f"/workspaces/{f.workspace['id']}"
    observed = human("POST", base + "/capture/existing", json={"idempotency_key": "cycle-existing-" + uuid4().hex})
    assert observed.status_code == 200, observed.text
    selection = scribe_source.selection(f.view)
    assert selection is not None
    selected = selection.model_dump(mode="json")
    saved = human("POST", base + "/capture/source-packets", json={"expected_revision": 1,
        "idempotency_key": "cycle-source-" + uuid4().hex, "selection": selected, "reviewed": True, "share_with_team": True})
    assert saved.status_code == 200, saved.text
    with factory() as s:
        configuration = team.starter_configuration(f.box, f.actor)
        for bot in configuration["bots"]:
            bot["name"] = scenario["scenario_id"].split("-")[1].title() + " " + bot["role"]
        roster = team.save(s, f.box, f.actor, expected=0, key="cycle-team-" + uuid4().hex, configuration=configuration)
        descriptors = {item["role"]: item for item in roster["members"]}
    initial_cough = None
    if scenario["reviewed_contact_resolution"]:
        # The first actual protected source has ambiguous contact instruction.
        # No VendorWork/delegation exists, so actual FollowUp selection has zero
        # action handles before later human-reviewed clarification is saved.
        initial_cough = {"saved_source": saved.json(), "contact_state": "unresolved", "submission_requests": 0}
        from cosmas_os.application.agent_tools import AgentToolExecutor
        from cosmas_os.ports.bot_capabilities import ModelCallFailure
        with factory() as s:
            aid, _ = model_work.reserve_conversation(s, f.box, f.actor, f.workspace["id"], expected=saved.json()["entry_revision"],
                team_revision=1, key="cycle-unresolved-contact-" + uuid4().hex, role="follow_up",
                content="Contact is ambiguous. Inspect only current selected action authority; do not dispatch.", external_identity_id=f.binding.id)
            claim = model_work.claim(s, f.box, f.actor, aid)
            assert claim is not None
            selection_result = AgentToolExecutor(s, claim, session_factory=factory).execute({"tool": "list_selected_sources"})
            assert selection_result["data"].get("delivery_intents", []) == []
            assert claim.envelope["contract"] == "cosmas-gpt41-prepared.v6"
            initial_cough["actual_admission"] = export_row(s.get(ModelWorkAdmission, aid))
            initial_cough["actual_tool"] = selection_result
            model_work.settle(s, claim, ModelCallFailure(dispatch="not_dispatched"))
        f.view = scenario_review(scenario, f.port.saved.session_id, clarified=True)
        current_selection = scribe_source.selection(f.view)
        assert current_selection is not None
        selected = current_selection.model_dump(mode="json")
        clarified = human("POST", base + "/capture/source-packets", json={"expected_revision": snapshot()["revision"],
            "idempotency_key": "cycle-clarified-source-" + uuid4().hex, "selection": selected, "reviewed": True, "share_with_team": True})
        assert clarified.status_code == 200, clarified.text
        saved = clarified
        observed = human("POST", base + "/capture/existing", json={"idempotency_key": "cycle-read-clarification-" + uuid4().hex})
        assert observed.status_code == 200, observed.text
    packet_ids = [p["entry_id"] for p in saved.json()["entries"]]
    with factory() as s:
        parts = []
        for eid in packet_ids:
            part = s.get(WorkspaceEntry, eid)
            assert part is not None
            parts.append(part)
        text = "".join(p.content.split("\n", 1)[1] for p in parts)
        source = {"content": text, "content_sha256": sha(text), "entry_ids": packet_ids,
            "parts": [{"entry_id": p.id, "revision": p.revision, "content": p.content, "sha256": sha(p.content)} for p in parts],
            "reviewed": True, "input_mode": "simulated_asr", "core_selection": selected,
            "creator_review": observed.json(), "provenance": "Actual signed existing-capture read/source-packet save; authored turns through explicit simulated ASR, no physical recording or real speech inference"}
    installed = install_vendor(f, scenario, factory)
    preflight = PluginRuntime("https://cycle-api.example.invalid", workspace_id=f.workspace["id"],
        session=AuthenticatedSession(human, lambda: "owned-signed-session-" + f.binding.id))
    try:
        catalog = preflight.catalog()
        write(folder / "PLUGIN_PREFLIGHT.json", {"catalog": catalog, "auth": "signed local TestClient through trusted current-session adapter; no JWT file"})
        assert catalog.get("spruce.prepare_delivery"), "plugin_feature_unavailable"
    finally:
        preflight.close()
    f.cycle_vendor = installed
    write(folder / "CAPTURE.json", {"admission": admitted.json(), "existing": observed.json(), "saved": saved.json(), "source": source,
        "initial_ambiguous_contact": initial_cough})
    f.session.rollback()
    plan = wait_plan(folder / "agents", "plan.json", {"scenario": scenario, "workspace_id": f.workspace["id"],
        "source": source, "team": descriptors, "stage": "scribe"})
    assert plan["source_sha256"] == source["content_sha256"]
    # Remaining stages are implemented below; this gate precedes every model
    # admission so actor authors can read the actual current source first.
    run_team_action(f, scenario, source, plan, folder, factory, human, snapshot, descriptors, monkeypatch)


def run_team_action(f, scenario, source, plan, folder, factory, human, snapshot, descriptors, monkeypatch):
    from cosmas_os.application.agent_tools import AgentToolExecutor
    from cosmas_os.ports.bot_capabilities import ModelCallFailure
    from cosmas_os.research_models import ResearchRun
    from cosmas_os.vendor_models import VendorCommandReceipt
    base, wid = f"/workspaces/{f.workspace['id']}", f.workspace["id"]
    calls_index = 0
    task_requirements = {"missing_facts": [], "expected_output": "Private source-bound draft for exact human review.",
        "completion_criteria": ["Preserve reported and unverified facts.", "No clinical decision or external action claim."], "independent": True}
    accepted = {}
    sandbox = CompletedActionSandbox(folder / "receiver")
    receiver_origin = sandbox.start()
    installed = f.cycle_vendor
    def delivery_factory(identity_current):
        async def credential(selection):
            return Credential(selection_sha256=selection.commitment(), credential_ref=str(installed["chosen"].credential_ref),
                              secret=SecretStr(SYNTHETIC_CREDENTIAL))
        return vendor_execution.VendorExecution(factory, credential,
            transport=SandboxVendorTransport(receiver_origin), identity_current=identity_current)
    def dispatch(claimed, final, calls):
        nonlocal calls_index
        calls_index += 1
        socket = ActorModelSocket(claimed.envelope, final, calls, folder / ("model-" + str(calls_index) + ".json"))
        transport = ModelSocketTransport(socket.origin)
        try:
            return model_work.dispatch_claim(claimed, session_factory=factory, transport=transport,
                                            delivery_execution_factory=delivery_factory)
        finally:
            transport.close()
            socket.close()
    def converse(role, question, final_maker, *, tool_maker=source_calls):
        key = "cycle-conversation-" + uuid4().hex
        def worker(claimed):
            return dispatch(claimed, final_maker(claimed.envelope), tool_maker(claimed.envelope))
        monkeypatch.setattr(api, "_model_dispatch", lambda request, identity: worker)
        response = human("POST", base + "/conversation", json={"expected_revision": snapshot()["revision"],
            "team_revision": 1, "idempotency_key": key, "role": role, "content": question})
        assert response.status_code == 200 and response.json()["outcome"] == "saved", response.text
        return response.json()
    def process(final_maker):
        assert model_work.process_next(factory, dispatch=lambda claimed: dispatch(claimed, final_maker(claimed.envelope), source_calls(claimed.envelope)))
    def current_handoff(role, *, revised=False):
        rows = [h for h in snapshot()["handoffs"] if h["recipient_role"] == role]
        return rows[-1]
    def review(role, *, decision="accepted", feedback=""):
        h = current_handoff(role)
        response = human("POST", base + "/handoffs/" + h["id"] + "/review", headers={"X-Cosmas-Handoff-Review": "1"}, json={
            "expected_revision": snapshot()["revision"], "idempotency_key": "cycle-review-" + uuid4().hex,
            "attempt_id": h["attempt_id"], "result_entry_id": h["result_entry_id"], "result_sha256": h["result_sha256"],
            "decision": decision, "feedback": feedback})
        assert response.status_code == 200, response.text
        return current_handoff(role)
    def scribe_final(envelope, version):
        value = plan["scribe"][version]
        for item in value["excerpts"]:
            p = next(p for p in envelope["context"]["sources"] if p["entry_id"] == item["source_id"])
            assert item["quote"] in p["content"], "actor_quote_not_exact_source"
        return value
    try:
        scribe_task = plan["chief"]["scribe_task"]
        if isinstance(scribe_task, str):
            scribe_task = {"brief": scribe_task, "requirements": task_requirements}
        converse("chief", "Ask Scribe to summarize the reviewed original for private human review.",
            lambda e: final_answer(e, plan["chief"]["initial_answer"], [("scribe", scribe_task)]))
        process(lambda e: scribe_final(e, "initial"))
        changed = review("scribe", decision="changes_requested", feedback=plan["feedback"])
        response = human("POST", base + "/handoffs/" + changed["id"] + "/revision", headers={"X-Cosmas-Handoff-Review": "1"},
            json={"expected_revision": snapshot()["revision"], "idempotency_key": "cycle-revise-" + uuid4().hex,
                  "review_id": changed["review"]["id"]})
        assert response.status_code == 200, response.text
        process(lambda e: scribe_final(e, "revised"))
        accepted["scribe"] = review("scribe")
        snap = snapshot()
        scribe_entry = next(p for p in snap["entries"] if p["id"] == accepted["scribe"]["result_entry_id"])
        # Real public read: exact model tool proposal, separate signed human
        # consent, fresh claim execute/read. These command-only admissions do
        # not pretend a semantic model response; authored Research follows.
        def public_claim(key):
            s = factory()
            aid, _ = model_work.reserve_conversation(s, f.box, f.actor, wid, expected=snapshot()["revision"], team_revision=1,
                key=key, role=descriptors["research"]["instance_id"], content="Perform only the separately reviewed public Research lookup.",
                external_identity_id=f.binding.id)
            claim = model_work.claim(s, f.box, f.actor, aid)
            assert claim is not None
            return s, claim
        def public_tool(s, claim, request):
            value = AgentToolExecutor(s, claim, session_factory=factory).execute(request)
            receipt = value["receipt"]
            s.add(AuditEvent(box_id=f.box, aggregate_type="model_admission", aggregate_id=claim.admission_id,
                event_type="workspace.agent_connector_tool", actor_principal_id=receipt["actor_agent_id"], initiated_by_principal_id=f.actor,
                outcome=value["data"].get("state", "observed"), correlation_id=claim.dispatch_id, payload_hash=receipt["sha256"], detail=receipt))
            s.commit()
            return value
        research_query = plan["research"]
        s, claim = public_claim("cycle-research-propose-" + uuid4().hex)
        try:
            proposal = public_tool(s, claim, {"tool": "propose_research_query", **{k: research_query[k] for k in ("topic", "sources", "query")}})
        finally:
            model_work.settle(s, claim, ModelCallFailure(dispatch="not_dispatched"))
            s.close()
        handle = {k: proposal["data"][k] for k in ("ticket_id", "revision_id", "payload_hash")}
        response = human("POST", base + "/agent-research/" + handle["ticket_id"] + "/review", headers={"X-Cosmas-Research-Contract": "1"},
            json={"revision_id": handle["revision_id"], "payload_hash": handle["payload_hash"], "public_query_confirmed": True})
        assert response.status_code == 200 and response.json()["state"] == "approved", response.text
        s, claim = public_claim("cycle-research-execute-" + uuid4().hex)
        try:
            result = public_tool(s, claim, {"tool": "execute_reviewed_research", **handle})
            retained = public_tool(s, claim, {"tool": "read_research_result", **handle})
            assert retained["data"] == result["data"], "public_recovery_drift"
            run = s.get(ResearchRun, result["data"]["run_id"])
            assert run is not None
            research = {"proposal": proposal, "review": response.json(), "execution": result, "readback": retained,
                "native_run": export_row(run)}
            write(folder / "PUBLIC_RESEARCH.json", research)
        finally:
            model_work.settle(s, claim, ModelCallFailure(dispatch="not_dispatched"))
            s.close()
        f.session.rollback()
        stage2 = wait_plan(folder / "agents", "specialists-plan.json", {"scenario": scenario, "workspace_id": wid, "source": source,
            "accepted_scribe": {"entry": scribe_entry, "review": accepted["scribe"]["review"], "sha256": sha(scribe_entry["reply"]["content"])},
            "research": research, "team": descriptors, "stage": "specialists"})
        assert stage2["source_sha256"] == source["content_sha256"]
        tasks = []
        for role in ("visit_prep", "research", "follow_up"):
            task = stage2[role]["task"]
            task = {"brief": task, "requirements": task_requirements} if isinstance(task, str) else task
            # Actual accepted summary is transported inside Chief's immutable
            # assignment; original packet reads remain separate exact tools.
            tasks.append((role, {**task, "brief": task["brief"] + "\n\nExact accepted Scribe draft:\n" + scribe_entry["reply"]["content"]}))
        converse("chief", "Prepare Visit Prep, Research and Follow up drafts from the exact accepted Scribe output and returned public records.",
            lambda e: final_answer(e, stage2["chief"]["specialist_answer"], tasks))
        def specialist_final(e):
            role = e["context"]["role"]
            return final_answer(e, stage2[role]["answer"])
        for _ in range(3):
            process(specialist_final)
        for role in ("visit_prep", "research", "follow_up"):
            accepted[role] = review(role)
        accepted_ids = {role: h["review"]["id"] for role, h in accepted.items()}
        def collect_tools(e):
            handles = e["tool_selection"]["teammate_drafts"]
            desired = {h["result_entry_id"] for h in accepted.values()}
            selected = [p for p in handles if p["entry_id"] in desired]
            assert len(selected) == 4, "accepted_team_read_handles_unavailable"
            return [{"tool": "read_saved_teammate_draft", **{k: p[k] for k in ("entry_id", "revision", "sha256")}} for p in selected]
        chief = converse("chief", "Read all four exact accepted team drafts and summarize administrative next steps without claiming a send.",
            lambda e: final_answer(e, stage2["chief"]["synthesis_answer"]), tool_maker=collect_tools)
        # Human-reviewed source note retains actual packet+accepted-draft lineage
        # without reclassifying a private draft as a signed clinical note.
        with factory() as s:
            snap = ws.read(s, f.box, f.actor, wid)
            saved_note = note_review.save(s, f.box, f.actor, wid, expected=snap["revision"], key="cycle-note-" + uuid4().hex,
                base_note_id=None, source_reply_id=scribe_entry["id"], content=scribe_entry["reply"]["content"])
            n = saved_note["workspace"]["note"]["latest"]
            reviewed_note = note_review.review(s, f.box, f.actor, wid, n["id"], expected=saved_note["entry_revision"], key="cycle-note-review-" + uuid4().hex,
                content_hash=n["content_hash"], source_hash=n["source_fingerprint"])
            current_note = reviewed_note["workspace"]["note"]["latest"]
        source.update(workspace_revision=reviewed_note["entry_revision"], vendor_source={"kind": "reviewed_note", "note_id": n["id"],
            "content_sha256": n["content_hash"], "source_fingerprint": n["source_fingerprint"]},
            native_note=current_note, accepted_scribe_sha256=sha(scribe_entry["reply"]["content"]))
        if scenario["platform"] == "mobile":
            from lab.referral_pdf import build_referral_pdf

            from cosmas_os.adapters.vendor_artifacts import LocalVendorArtifactStore
            with factory() as s:
                prep_reply = s.get(WorkspaceReply, accepted["visit_prep"]["result_entry_id"])
                assert prep_reply is not None
                pdf = build_referral_pdf(accepted_scribe=scribe_entry["reply"]["content"], visit_prep=prep_reply.content,
                    owner_label=scenario["provider"]["name"], source_sha256=source["content_sha256"], synthetic_only=True)
            aid = str(uuid4())
            store = LocalVendorArtifactStore(folder / "private-artifact-store")
            api.app.dependency_overrides[api._vendor_artifact_store] = lambda: store
            try:
                intent = human("POST", base + "/vendor-artifacts", headers={"X-Cosmas-Vendor-Contract": "1"}, json={
                    "artifact_id": aid, "idempotency_key": "cycle-pdf-intent-" + uuid4().hex, "source": source["vendor_source"],
                    "sha256": pdf.pdf_sha256, "byte_length": len(pdf.data), "media_type": "application/pdf"})
                assert intent.status_code == 200, intent.text
                content = human("PUT", base + "/vendor-artifacts/" + aid + "/content", headers={
                    "X-Cosmas-Vendor-Contract": "1", "Content-Type": "application/pdf", "X-Cosmas-Artifact-Write-Key": "cycle-pdf-write-" + uuid4().hex}, content=pdf.data)
                assert content.status_code == 200 and content.json()["artifact"]["state"] == "ready", content.text
                preview = human("GET", base + "/vendor-artifacts/" + aid + "/content", headers={"X-Cosmas-Vendor-Contract": "1"})
                assert preview.status_code == 200 and preview.content == pdf.data
                packet = {"artifact_id": aid, "pdf_base64": base64.b64encode(pdf.data).decode(), "pdf_sha256": pdf.pdf_sha256,
                    "byte_length": len(pdf.data), "pages": pdf.pages, "extracted_text": pdf.extracted_text,
                    "extracted_text_sha256": pdf.extracted_text_sha256, "source_sha256": pdf.source_sha256,
                    "accepted_scribe_sha256": pdf.accepted_scribe_sha256, "visit_prep_sha256": pdf.visit_prep_sha256,
                    "custody": {"intent": intent.json(), "content": content.json(), "preview": {"status": preview.status_code,
                        "sha256": sha_bytes(preview.content), "byte_length": len(preview.content), "headers": dict(preview.headers)}}}
                (folder / "referral-review.pdf").write_bytes(pdf.data)
                f.session.rollback()
                reviewed = wait_plan(folder / "agents", "pdf-review-plan.json", {"scenario": scenario, "source": source,
                    "packet": packet, "owner_id": f.actor, "stage": "human_pdf_preview"})
                assert reviewed["reviewed"] is True and reviewed["artifact_id"] == aid and reviewed["pdf_sha256"] == pdf.pdf_sha256
                review_receipt = {**reviewed, "actor_id": f.actor, "observed_at": datetime.now(UTC).isoformat()}
                review_receipt["sha256"] = digest(review_receipt)
                packet["human_review"] = review_receipt
                source["referral_packet"] = packet
                write(folder / "PDF_REVIEW.json", packet)
                assert sandbox.counters()["submission_requests"] == 0
            finally:
                api.app.dependency_overrides.pop(api._vendor_artifact_store, None)
        plugin = PluginRuntime("https://cycle-api.example.invalid", workspace_id=wid,
            session=AuthenticatedSession(human, lambda: "owned-signed-session-" + f.binding.id))
        worker = {}
        def follow_up(handle, key):
            tool = "read_delivery_status" if "readback" in key else "execute_reviewed_delivery"
            answer = stage2["follow_up"]["execution_answer"] if tool == "execute_reviewed_delivery" else stage2["follow_up"]["readback_answer"]
            value = converse("follow_up", "Execute only the exact approved administrative action." if tool == "execute_reviewed_delivery" else "Read retained status only; never resend.",
                lambda e: final_answer(e, answer), tool_maker=lambda e: [{"tool": tool, **handle}])
            with factory() as s:
                admission = s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == wid,
                    ModelWorkAdmission.request_entry_id == value["saved_entry"]["id"]))
                assert admission is not None
                events = list(s.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == admission.id, AuditEvent.event_type == "workspace.agent_connector_tool")))
                exported = {"response": value, "admission": export_row(admission), "tools": [export_row(p) for p in events]}
            if tool == "execute_reviewed_delivery":
                worker.update(exported)
            return exported
        def reopen(action):
            current = plugin.call("vendor_work_inspect_work", {"workspace_id": wid, "ticket_id": action["ticket_id"]})["result"]
            joined = {"scope": {"workspace_id": wid, "box_id": f.box, "owner_id": f.actor}, "action": action,
                "source_sha256": source["content_sha256"]}
            with factory() as s:
                revision = s.get(VendorWorkRevision, action["revision_id"])
                observation = s.scalar(select(VendorProviderObservation).where(VendorProviderObservation.operation_id == action["operation_id"], VendorProviderObservation.kind == "submission"))
                claimrow = s.get(VendorSubmitClaim, action["operation_id"])
                assert revision is not None and observation is not None and claimrow is not None
                approvalrow = s.get(VendorCommandReceipt, claimrow.approval_receipt_id)
                op = s.get(Operation, action["operation_id"])
                assert approvalrow is not None and op is not None
                count = s.scalar(select(func.count()).select_from(VendorSubmitClaim).where(VendorSubmitClaim.operation_id == op.id))
                raw_revision, raw_observation = export_row(revision), export_row(observation)
                receiver = sandbox.receipt(op.id)
                source_with_native = {**source, "lineage": {"packet_entry_ids": source["entry_ids"], "vendor_source_proof_sha256": revision.source_proof_sha256,
                    "vendor_source_proof": revision.source_proof, "model_context_sha256": worker["admission"]["source_sha256"]}}
                drafts = {}
                for role, h in accepted.items():
                    entry = s.get(WorkspaceReply, h["result_entry_id"])
                    assert entry is not None
                    drafts[role] = {"agent_id": h["recipient_agent_id"], "state": "accepted", "source_sha256": source["content_sha256"],
                        "content": entry.content, "content_sha256": sha(entry.content), "acceptance_receipt_id": h["review"]["id"],
                        "revision_id": h["id"], "raw": {"handoff": h, "entry": export_row(entry)}}
                chief_entry = s.get(WorkspaceReply, chief["saved_entry"]["id"])
                assert chief_entry is not None
                chief_admission = s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.result_entry_id == chief_entry.entry_id))
                assert chief_admission is not None
                drafts["chief"] = {"agent_id": descriptors["chief"]["agent_id"], "state": "saved", "source_sha256": source["content_sha256"],
                    "content": chief_entry.content, "content_sha256": sha(chief_entry.content), "admission_id": chief_admission.id,
                    "result_entry_id": chief_entry.entry_id, "accepted_draft_receipt_ids": accepted_ids, "raw": export_row(chief_admission)}
                tool_event = worker["tools"][0]
                return {"source": source_with_native, "team": {r: p["agent_id"] for r, p in descriptors.items()}, "drafts": drafts,
                    "submit_claim_count": count, "attempt_count": op.attempt_count,
                    "approval": {**joined, "id": approvalrow.id, "actor_id": approvalrow.actor_id, "state": "approved",
                        "observed_at": approvalrow.recorded_at.isoformat(), "administrative_delivery_confirmed": approvalrow.public_request["administrative_delivery_confirmed"],
                        "follow_up_bot_id": approvalrow.public_request["follow_up_bot_id"], "consent_source_sha256": source["content_sha256"], "raw": export_row(approvalrow)},
                    "plugin": {**joined, "id": tool_event["id"], "actor_id": worker["admission"]["agent_id"], "tool": "execute_reviewed_delivery", "state": "saved", "provider": "spruce",
                        "admitted_at": worker["admission"]["admitted_at"], "observed_at": worker["admission"]["finalized_at"], "raw": worker},
                    "publisher": {"operation_id": op.id, "state": observation.public_observation["acceptance"], "request_id": observation.private_reference["value"],
                        "content_sha256": sha(revision.private_command["intent"]["text"]), "recipient": revision.private_command["intent"]["destination"]["contact_id"],
                        "wire_sha256": receiver["wire_sha256"], "wire_sha256_origin": "independent receiver exact HTTP bytes, not provider response hash", "document_attached": False, "raw": {"command_revision": raw_revision, "submit_observation": raw_observation}},
                    "reopen": {**joined, "id": op.id, "request_id": observation.private_reference["value"], "item_id": receiver["item_id"],
                        "receiver_receipt_id": receiver["id"], "dispatch": claimrow.dispatch, "acceptance": current["summary"]["acceptance"],
                        "transport": current["summary"]["transport"], "state": "saved_submission", "conflicting_evidence": current["summary"]["conflicting_evidence"],
                        "raw": {"signed_api": current, "submit_claim": export_row(claimrow), "operation": export_row(op), "receiver_join": receiver["sha256"]}}}
        def acknowledge(receiver, case):
            f.session.rollback()
            ack = wait_plan(folder / "agents", "ack-plan.json", {"scenario": case, "receiver": receiver, "stage": "patient_ack"})
            return {"id": str(uuid4()), "actor": "virtual_patient", "author_agent_id": ack["author_agent_id"], "state": "acknowledged",
                "content": ack["content"], "content_sha256": sha(ack["content"]), "scenario_id": case["scenario_id"],
                "administrative_intent": case["administrative_intent"]["purpose"], "operation_id": receiver["operation_id"],
                "receiver_receipt_id": receiver["id"], "receiver_sha256": receiver["sha256"], "after_receiver": True, "observed_at": datetime.now(UTC).isoformat()}
        try:
            evidence = run_completed_action_cycle(runtime=plugin, human_request=human, scenario=scenario,
                scope={"workspace_id": wid, "box_id": f.box, "owner_id": f.actor, "follow_up_bot_id": descriptors["follow_up"]["agent_id"],
                       **{k: installed[k] for k in ("connection", "correspondence")}},
                accepted_source=source, plan=plan, run_follow_up=follow_up, reopen=reopen, acknowledge=acknowledge,
                sandbox=sandbox, output=folder / "action", lose_reply=True)
            verdict = evaluate_completed_action(evidence, scenario)
            write(folder / "VERDICT.json", verdict)
            assert verdict["passed"], verdict
        finally:
            plugin.close()
    finally:
        sandbox.close()
