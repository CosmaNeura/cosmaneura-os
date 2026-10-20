"""Signed human sharing, real note/source custody and ledger; invented model HTTP only."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from threading import Event
from time import perf_counter
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tests.integration.test_scribe_source_bridge import bridge as original_bridge
from tests.integration.test_scribe_source_bridge import capture_case as original_capture_case
from tests.integration.test_scribe_source_bridge import post

from cosmas_os.api import app as api
from cosmas_os.api.clinical_note_share_schemas import ShareSavedNote
from cosmas_os.application import agent_tools, conversation, handoff_review, handoffs, note_review
from cosmas_os.application import clinical_note_share as share
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import canonical_json
from cosmas_os.models import ModelWorkAdmission, PatientLink, Principal, WorkspaceEntry
from cosmas_os.ports.bot_capabilities import BotReply, ModelCallFailure

SOAP = ("Subjective: Invented person reports a lingering cough.\n"
    "Objective: Examination details unavailable.\n"
    "Assessment: Diagnosis and current medicine list unverified.\n"
    "Plan: Provider to confirm medicines and review treatment questions. No medication change documented. 界🩺\x7f")

bridge = original_bridge
capture_case = original_capture_case


@pytest.fixture
def clinical(bridge, monkeypatch):
    f = bridge
    f.configuration.workspace_llm_backend = "azure_gpt41"
    f.configuration.workspace_llm_api_key = SecretStr("invented-no-network")
    f.configuration.workspace_agent_tools_enabled = True
    for module in (team, conversation, handoffs):
        monkeypatch.setattr(module, "runtime_settings", f.configuration)
    f.research_id = str(uuid4())
    with Session(f.engine) as s:
        config = team.default_configuration()
        config["bots"].append({"role": "research", "name": "Research", "enabled": True,
            "instance_id": f.research_id})
        f.team_revision = team.save(s, f.box, f.actor, expected=0,
            key="invented-clinical-team", configuration=config)["revision"]
    packet = post(f)
    assert packet.status_code == 200, packet.text
    f.packet_ids = {e["entry_id"] for e in packet.json()["entries"]}
    with Session(f.engine) as s:
        saved = note_review.save(s, f.box, f.actor, f.workspace["id"],
            expected=packet.json()["entry_revision"], key="invented-soap-note", base_note_id=None,
            source_reply_id=None, content=SOAP)
    f.saved_workspace = saved["workspace"]
    note = f.saved_workspace["note"]["latest"]
    f.share_body = {"expected_revision": f.saved_workspace["revision"], "idempotency_key": "invented-share-note",
        "note_id": note["id"], "note_version": note["version"], "content_hash": note["content_hash"],
        "source_fingerprint": note["source_fingerprint"], "share_with_team": True}
    f.share_headers = {"Authorization": "Bearer " + f.token(), "X-Cosmas-Clinical-Team": "1"}
    f.share_path = f.base + "/note/team-source"
    yield f
    with Session(f.engine) as s:
        for row in s.scalars(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == f.workspace["id"],
                ModelWorkAdmission.state.in_(("reserved", "running")))):
            if row.state == "reserved":
                claimed = work.claim(s, f.box, f.actor, row.id)
            else:
                assert row.dispatch_id is not None
                claimed = work.ModelClaim(row.id, f.box, f.actor, f.workspace["id"], row.dispatch_id,
                    row.envelope_sha256, row.prepared_envelope)
            if claimed:
                work.settle(s, claimed, ModelCallFailure(dispatch="not_dispatched"))


def shared(f):
    result = f.client.post(f.share_path, headers=f.share_headers, json=f.share_body)
    assert result.status_code == 200, result.text
    return result.json()


def request(receipt):
    note = receipt["workspace"]["note"]["latest"]
    return json.dumps({"contract": share.REQUEST_CONTRACT, "source_entry_id": receipt["source_entry_id"],
        "note_id": note["id"], "note_version": note["version"], "content_hash": note["content_hash"]})


@contextmanager
def sessions(engine):
    with Session(engine) as s:
        yield s


def reserve(f, receipt, *, key="invented-chief-two-drafts", content=None, claim=True):
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.actor, f.workspace["id"])
        aid, _ = work.reserve_conversation(s, f.box, f.actor, f.workspace["id"], expected=current["revision"],
            team_revision=f.team_revision, key=key, role="chief", content=content or request(receipt))
        assert aid is not None
        if not claim:
            return aid
        claimed = work.claim(s, f.box, f.actor, aid)
        assert claimed is not None
        return claimed


def dispatch(f, claim, calls):
    context = claim.envelope["context"]
    handles = claim.envelope["tool_selection"]["sources"]
    note_handle = next(h for h in handles if h["label"] == share.LABEL)
    reads = [h for h in handles if h["entry_id"] in f.packet_ids]
    assert len(reads) <= 4
    if len(reads) < 4:
        reads.append(note_handle)
    def respond(message):
        body = json.loads(message.content)
        calls.append({"role": context["role"], "context": context, "request": body})
        if not any(m["role"] == "tool" for m in body["messages"]):
            return httpx.Response(200, json={"model": "gpt-4.1", "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                "choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                    "tool_calls": [{"id": f"source_{i}", "type": "function", "function": {"name": "read_selected_source",
                        "arguments": json.dumps({k: h[k] for k in ("entry_id", "revision", "sha256")})}}
                        for i, h in enumerate(reads)]}}]})
        ids = [h["entry_id"] for h in handles]
        if context["role"] == "chief":
            answer = {"answer": "Prepare two independent private drafts using the same saved note and transcript.", "source_ids": ids,
                "handoffs": [{"role": role, "intended_role": intended, "brief": brief,
                    "requirements": {"missing_facts": ["Current medicine list and diagnosis unverified."],
                        "expected_output": brief, "completion_criteria": ["Cite the supplied note and transcript; retain uncertainty; private draft only."], "independent": True}}
                    for role, intended, brief in (("follow_up", "follow_up", "Patient email with Subject and Body, plus Provider action items."),
                        (f.research_id, "research", "Provider treatment assessment: findings, drug questions and missing evidence."))]}
        elif context["role"] == "follow_up":
            answer = {"answer": "Subject: Your next review\nBody: Your provider will confirm your medicine list.\n\nProvider action items\nOwner: provider; Next: confirm medicines; Done when: reviewed list recorded.\nPrivate draft; no email sent.", "source_ids": ids}
        else:
            answer = {"answer": "Source-supported findings: current medicine list unverified.\nDrug and treatment questions: what medicines and monitoring apply?\nMissing evidence / next checks: provider to verify current medicines; current drug evidence unavailable. No unsourced treatment recommendation.", "source_ids": ids}
        if "intent" in body["response_format"]["json_schema"]["schema"]["properties"]:
            answer["intent"] = "conversation"
        return httpx.Response(200, json={"model": "gpt-4.1", "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(answer)}}]})
    assert note_handle["entry_id"] in {p["entry_id"] for p in context["sources"]}
    return work.dispatch_claim(claim, session_factory=lambda: sessions(f.engine), transport=httpx.MockTransport(respond))


def test_exact_saved_soap_and_scribe_reach_chief_both_specialists_and_human_review(clinical):
    f = clinical
    receipt = shared(f)
    assert receipt["workspace"]["note"] == f.saved_workspace["note"]
    entry = next(e for e in receipt["workspace"]["entries"] if e["id"] == receipt["source_entry_id"])
    assert json.loads(entry["content"])["note"]["content"] == SOAP
    assert entry["source_label"] == share.LABEL and entry["reply"] is None
    calls = []
    chief = reserve(f, receipt)
    assert "patient email draft with Subject and Body" in chief.envelope["context"]["question"]
    assert "Drug and treatment questions" in chief.envelope["context"]["question"]
    result = dispatch(f, chief, calls)
    assert len(result.handoffs) == 2
    with Session(f.engine) as s:
        work.settle(s, chief, result)
        snapshot = ws.read(s, f.box, f.actor, f.workspace["id"])
        admission = s.get(ModelWorkAdmission, chief.admission_id)
        assert admission is not None
        chief_reply = next(e for e in snapshot["entries"] if e["id"] ==
            admission.request_entry_id)["reply"]["content"]
        assert chief_reply.count("Queued; waiting for a private draft.") == 2
        assert "Patient email with Subject and Body" in chief_reply
        assert "Provider treatment assessment" in chief_reply
        assert "Review each completed result before using it" in chief_reply
    for _ in range(2):
        assert work.process_next(lambda: sessions(f.engine), dispatch=lambda c: dispatch(f, c, calls))
    with Session(f.engine) as s:
        snapshot = ws.read(s, f.box, f.actor, f.workspace["id"])
        assert {h["recipient_role"] for h in snapshot["handoffs"]} == {"follow_up", "research"}
        assert snapshot["note"] == f.saved_workspace["note"]
        for h in snapshot["handoffs"]:
            assert h["status"] == "completed" and h["task_brief"]["version"] == 2
            assert receipt["source_entry_id"] in {p["entry_id"] for p in h["task_brief"]["source_versions"]}
            review = handoff_review.review(s, f.box, f.actor, f.workspace["id"], h["id"], expected=snapshot["revision"],
                key="invented-accept-" + h["recipient_role"], attempt_id=h["attempt_id"], result_entry_id=h["result_entry_id"],
                result_sha256=h["result_sha256"], decision="accepted", feedback="")
            snapshot = review["workspace"]
        assert all(h["review"]["decision"] == "accepted" and h["review_status"] == "current" for h in snapshot["handoffs"])
    assert len(calls) == 6
    for call in calls:
        sources = call["context"]["sources"]
        assert f.packet_ids <= {s["entry_id"] for s in sources}
        assert next(s for s in sources if s["entry_id"] == receipt["source_entry_id"])["content"].endswith(SOAP)
        packets = sorted((s for s in sources if s["entry_id"] in f.packet_ids), key=lambda s: s["revision"])
        assert f.view.working.segments[0].content in "".join(s["content"].split("\n", 1)[1] for s in packets)
        supplied = []
        for message in call["request"]["messages"]:
            if message["role"] == "tool":
                supplied.append(json.loads(message["content"])["data"]["content"])
            elif message["role"] == "user":
                value = json.loads(message["content"])
                supplied.extend(source["text"] for source in value.get("sources", []))
        assert SOAP in "".join(supplied)
    assert all(step in {"exchange", "resolve", "binding", "provider_encounter"} for step in f.port.calls)
    with Session(f.engine) as s:
        edited = note_review.save(s, f.box, f.actor, f.workspace["id"], expected=snapshot["revision"],
            key="invented-note-after-acceptance", base_note_id=f.share_body["note_id"], source_reply_id=None,
            content=SOAP + "\nProvider saved a new version.")
        historical = edited["workspace"]["handoffs"]
        assert all(h["review"]["decision"] == "accepted" and h["review_status"] == "stale" for h in historical)
        h = historical[0]
        with pytest.raises(ws.WorkspaceError, match="handoff_sources_changed"):
            handoff_review.review(s, f.box, f.actor, f.workspace["id"], h["id"], expected=edited["workspace"]["revision"],
                key="invented-block-stale-review", attempt_id=h["attempt_id"], result_entry_id=h["result_entry_id"],
                result_sha256=h["result_sha256"], decision="accepted", feedback="")


@pytest.mark.parametrize("change", ["new_note", "transcript"])
def test_new_note_or_transcript_blocks_old_selection_and_new_chief_work(clinical, change):
    f = clinical
    receipt = shared(f)
    with Session(f.engine) as s:
        current = receipt["workspace"]
        if change == "new_note":
            note_review.save(s, f.box, f.actor, f.workspace["id"], expected=current["revision"], key="invented-note-edit",
                base_note_id=f.share_body["note_id"], source_reply_id=None, content=SOAP + "\nProvider edit.")
        else:
            ws.append(s, f.box, f.actor, f.workspace["id"], expected=current["revision"], key="invented-transcript-change",
                kind="evidence", content="Invented corrected transcript", source_label="Corrected transcript")
    with pytest.raises(ws.WorkspaceError, match="clinical_note_source_changed"):
        reserve(f, receipt)
    fresh = deepcopy(f.share_body)
    with Session(f.engine) as s:
        fresh["expected_revision"] = ws.read(s, f.box, f.actor, f.workspace["id"])["revision"]
    fresh["idempotency_key"] = "invented-stale-share"
    result = f.client.post(f.share_path, headers=f.share_headers, json=fresh)
    assert result.status_code == 409 and result.json()["detail"] == "clinical_note_source_changed"
    recovered = f.client.post(f.share_path + "/resolve", headers=f.share_headers, json=f.share_body)
    assert recovered.status_code == 200 and recovered.json()["outcome"] == "saved"
    with Session(f.engine) as s:
        assert not list(s.scalars(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == f.workspace["id"])))


@pytest.mark.parametrize("change", ["foreign_owner", "principal", "patient", "unchecked", "malformed_id", "spoof"])
def test_human_authority_and_closed_snapshot_contract_fail_before_sharing(clinical, change):
    f = clinical
    body = deepcopy(f.share_body)
    if change == "foreign_owner":
        f.share_headers["Authorization"] = "Bearer " + f.token(sub="invented-foreign-owner")
    elif change in {"principal", "patient"}:
        with Session(f.engine) as s:
            if change == "principal":
                principal = s.get(Principal, f.actor)
                assert principal is not None
                principal.state = "suspended"
            else:
                patient = s.get(PatientLink, f.patient_link_id)
                assert patient is not None
                patient.revoked_at = datetime.now(UTC)
            s.commit()
    elif change == "unchecked":
        body["share_with_team"] = 1
    elif change == "malformed_id":
        body["note_id"] = "not-a-uuid"
    else:
        for kind in ("conversation", "evidence"):
            with Session(f.engine) as s, pytest.raises(ws.WorkspaceError):
                ws.append(s, f.box, f.actor, f.workspace["id"], expected=body["expected_revision"], key="invented-spoof",
                    kind=kind, content=canonical_json({"contract": share.CONTRACT, "request": body,
                        "note": f.saved_workspace["note"]["latest"]}), source_label=share.LABEL)
        return
    result = f.client.post(f.share_path, headers=f.share_headers, json=body)
    assert result.status_code in {401, 403, 404, 422}, result.text
    assert SOAP not in result.text
    with Session(f.engine) as s:
        assert not list(s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == f.workspace["id"], WorkspaceEntry.source_label == share.LABEL)))


def test_resolve_serializes_behind_share_and_revision_fence_rejects_uncommitted_old_intent(clinical):
    f = clinical
    entered, release, resolving = Event(), Event(), Event()
    body = ShareSavedNote.model_validate(f.share_body)
    def delayed_share():
        with Session(f.engine) as s:
            return share.share(s, f.box, f.actor, f.workspace["id"], body,
                fence=lambda: (entered.set(), release.wait(timeout=10)))
    def resolve():
        resolving.set()
        with Session(f.engine) as s:
            return share.resolve(s, f.box, f.actor, f.workspace["id"], body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        submitted = pool.submit(delayed_share)
        assert entered.wait(timeout=5)
        recovered = pool.submit(resolve)
        assert resolving.wait(timeout=5)
        try:
            from concurrent.futures import TimeoutError
            with pytest.raises(TimeoutError):
                recovered.result(timeout=0.15)
        finally:
            release.set()
        saved = submitted.result(timeout=10)
        assert recovered.result(timeout=10)["source_entry_id"] == saved["source_entry_id"]
    absent = body.model_copy(update={"idempotency_key": "invented-absent-old-intent"})
    with Session(f.engine) as s:
        result = share.resolve(s, f.box, f.actor, f.workspace["id"], absent)
        assert result["outcome"] == "not_found" and result["workspace"]["revision"] > absent.expected_revision
    with Session(f.engine) as s, pytest.raises(ws.WorkspaceError, match="workspace_revision_conflict"):
        share.share(s, f.box, f.actor, f.workspace["id"], absent)


@pytest.mark.parametrize("boundary", ["claim", "read", "settle"])
def test_changed_transcript_revokes_pending_source_reads_and_result_publication(clinical, boundary):
    f = clinical
    receipt = shared(f)
    admitted = reserve(f, receipt, claim=boundary != "claim")
    with Session(f.engine) as s:
        snapshot = ws.read(s, f.box, f.actor, f.workspace["id"])
        ws.append(s, f.box, f.actor, f.workspace["id"], expected=snapshot["revision"], key="invented-corrected-after-admit",
            kind="evidence", content="Invented newly corrected transcript", source_label="Corrected transcript")
    with Session(f.engine) as s:
        if boundary == "claim":
            assert work.claim(s, f.box, f.actor, admitted) is None
            aid = admitted
        else:
            aid = admitted.admission_id
            if boundary == "read":
                handle = next(h for h in admitted.envelope["tool_selection"]["sources"] if h["entry_id"] == receipt["source_entry_id"])
                with pytest.raises(ws.WorkspaceError):
                    agent_tools.AgentToolExecutor(s, admitted).execute({"tool": "read_selected_source", **{k: handle[k] for k in ("entry_id", "revision", "sha256")}})
            work.settle(s, admitted, BotReply("Invented withheld draft", (), "azure_gpt41", 10, 5))
        row = s.get(ModelWorkAdmission, aid)
        assert row is not None
        assert row.state == "failed" and row.reason in {"source_changed", "clinical_note_source_changed"}
        assert row.result_entry_id is None


@pytest.mark.parametrize("boundary", ["missing_header", "duplicate_header", "query", "oversize", "duplicate_json", "encoding"])
def test_direct_http_sharing_requires_closed_metadata_and_header_contract(clinical, boundary):
    f = clinical
    headers = dict(f.share_headers)
    path = f.share_path
    content = json.dumps(f.share_body)
    expected = 422
    if boundary == "missing_header":
        del headers["X-Cosmas-Clinical-Team"]
        expected = 426
    elif boundary == "duplicate_header":
        headers = list(headers.items()) + [("X-Cosmas-Clinical-Team", "1")]
        expected = 426
    elif boundary == "query":
        path += "?owner=" + f.actor
    elif boundary == "oversize":
        content += " " * 4096
    elif boundary == "duplicate_json":
        content = content[:-1] + ',"share_with_team":true}'
    else:
        headers["Content-Encoding"] = "gzip"
    if isinstance(headers, dict):
        headers["Content-Type"] = "application/json"
    else:
        headers.append(("Content-Type", "application/json"))
    result = f.client.post(path, headers=headers, content=content)
    assert result.status_code == expected, result.text
    with Session(f.engine) as s:
        assert ws.read(s, f.box, f.actor, f.workspace["id"])["revision"] == f.share_body["expected_revision"]


@pytest.mark.parametrize("content", ["x" * 20000, "界" * 4000], ids=["ascii-limit", "escaped-cjk-limit"])
def test_server_snapshot_bound_rejects_long_or_escaped_notes_without_truncation(clinical, content):
    f = clinical
    with Session(f.engine) as s:
        saved = note_review.save(s, f.box, f.actor, f.workspace["id"], expected=f.saved_workspace["revision"],
            key="invented-oversized-snapshot-note", base_note_id=f.share_body["note_id"], source_reply_id=None, content=content)
    note = saved["workspace"]["note"]["latest"]
    body = {**f.share_body, "expected_revision": saved["entry_revision"], "note_id": note["id"],
        "note_version": note["version"], "content_hash": note["content_hash"], "source_fingerprint": note["source_fingerprint"]}
    result = f.client.post(f.share_path, headers=f.share_headers, json=body)
    assert result.status_code == 422 and result.json()["detail"] == "clinical_note_source_too_large"
    with Session(f.engine) as s:
        snapshot = ws.read(s, f.box, f.actor, f.workspace["id"])
        assert snapshot["revision"] == body["expected_revision"] and snapshot["note"]["latest"]["content"] == content
        assert not any(e["source_label"] == share.LABEL for e in snapshot["entries"])


def test_generic_conversation_json_cannot_forge_shared_source_or_paid_request(clinical):
    f = clinical
    with Session(f.engine) as s:
        w = ws._workspace(s, f.box, f.actor, f.workspace["id"])
        note = note_review._latest(s, w.id)
        content = canonical_json(share._snapshot(note, ShareSavedNote.model_validate(f.share_body)))
        generic = ws.append(s, f.box, f.actor, w.id, expected=f.saved_workspace["revision"], key="invented-generic-snapshot",
            kind="conversation", content=content, source_label=None)
    forged = {"source_entry_id": generic["entry_id"], "workspace": f.saved_workspace}
    with pytest.raises(ws.WorkspaceError, match="clinical_note_source_unavailable"):
        reserve(f, forged)
    with Session(f.engine) as s:
        assert not list(s.scalars(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == f.workspace["id"])))


def test_committed_share_resolution_reuses_exact_receipt_and_rejects_changed_command(clinical):
    f = clinical
    receipt = shared(f)
    for path in (f.share_path, f.share_path + "/resolve"):
        replay = f.client.post(path, headers=f.share_headers, json=f.share_body)
        assert replay.status_code == 200 and replay.json()["source_entry_id"] == receipt["source_entry_id"]
        conflict = f.client.post(path, headers=f.share_headers, json={**f.share_body, "content_hash": "a" * 64})
        assert conflict.status_code == 409 and conflict.json()["detail"] == "idempotency_conflict"


def test_unlinked_private_notebook_cannot_share_a_visit_note(clinical):
    f = clinical
    created = f.client.post("/workspaces/private-drafts", headers={"Authorization": "Bearer " + f.token(), "X-Cosmas-Private-Draft": "1"},
        json={"title": "Invented private preparation", "idempotency_key": "invented-private-notebook"})
    assert created.status_code == 200, created.text
    draft = created.json()
    assert draft["appointment_id"] is None
    result = f.client.post(f"/workspaces/{draft['id']}/note/team-source", headers=f.share_headers,
        json={**f.share_body, "expected_revision": 1})
    assert result.status_code == 409 and result.json()["detail"] == "workspace_appointment_required"
    with Session(f.engine) as s:
        assert not list(s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == draft["id"])))


def test_clinical_team_header_is_allowed_by_actual_cors_preflight(clinical):
    f = clinical
    middleware = next(m for m in api.app.user_middleware if getattr(m.cls, "__name__", None) == "CORSMiddleware")
    options = middleware.kwargs
    assert isinstance(options, dict)
    origins = options["allow_origins"]
    assert isinstance(origins, list) and origins
    origin = origins[0]
    response = f.client.options(f.share_path, headers={"Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,authorization,x-cosmas-clinical-team"})
    assert response.status_code == 200, response.text
    assert "x-cosmas-clinical-team" in response.headers["access-control-allow-headers"].lower()


@pytest.mark.parametrize("forgery", ["request_hash", "changed_note", "unchecked_share", "malformed_note_id", "reserved_evidence"])
def test_database_guard_rejects_forged_snapshot_even_when_app_route_is_bypassed(clinical, forgery):
    f = clinical
    with Session(f.engine) as s:
        w = ws._workspace(s, f.box, f.actor, f.workspace["id"], writing=True)
        note = note_review._latest(s, w.id)
        command = ShareSavedNote.model_validate(f.share_body)
        snapshot = share._snapshot(note, command)
        request_hash = share._hash(command)
        if forgery == "request_hash":
            request_hash = "f" * 64
        elif forgery == "changed_note":
            snapshot["note"]["content"] += "\nForged clinical fact."
        elif forgery == "unchecked_share":
            snapshot["request"]["share_with_team"] = 1
        elif forgery == "malformed_note_id":
            snapshot["request"]["note_id"] = "not-a-uuid"
        w.revision += 1
        s.add(WorkspaceEntry(workspace_id=w.id, box_id=w.box_id, actor_id=w.owner_id, revision=w.revision,
            kind="evidence" if forgery == "reserved_evidence" else "conversation", source_label=share.LABEL,
            content=canonical_json(snapshot), idempotency_key=command.idempotency_key, request_hash=request_hash))
        with pytest.raises(IntegrityError, match="exact current human saved-note sharing required"):
            s.commit()
        s.rollback()
        assert ws.read(s, f.box, f.actor, w.id)["revision"] == f.share_body["expected_revision"]


@pytest.mark.parametrize("tamper", ["stale", "content", "revision", "missing_context", "missing_all_descriptors", "descriptor_digest", "generic_conversation", "reserved_descriptor_label", "ordinary_text", "ordinary_malformed_json"])
def test_database_model_source_guard_preserves_ordinary_text_and_refuses_changed_clinical_context(clinical, tamper):
    f = clinical
    receipt = shared(f)
    aid = reserve(f, receipt, claim=False)
    def verified(s, envelope, command):
        return s.scalar(text("""SELECT public.selected_google_model_sources_current(jsonb_populate_record(
          NULL::public.model_work_admissions,to_jsonb(m)||jsonb_build_object(
          'prepared_envelope',CAST(:envelope AS jsonb),'request_body',CAST(:command AS jsonb))))
          FROM public.model_work_admissions m WHERE id=:aid"""),
            {"aid": aid, "envelope": json.dumps(envelope), "command": json.dumps(command)})
    with Session(f.engine) as s:
        row = s.get(ModelWorkAdmission, aid)
        assert row is not None
        envelope, command = deepcopy(row.prepared_envelope), deepcopy(row.request_body)
        assert verified(s, envelope, command) is True
        if tamper in {"ordinary_text", "ordinary_malformed_json"}:
            command["content"] = "Invented ordinary conversation." if tamper == "ordinary_text" else "{Invented unfinished ordinary message"
            assert verified(s, envelope, command) is True
            return
        note_source = next(p for p in envelope["context"]["sources"] if p["entry_id"] == receipt["source_entry_id"])
        if tamper == "stale":
            current = ws.read(s, f.box, f.actor, f.workspace["id"])
            ws.append(s, f.box, f.actor, f.workspace["id"], expected=current["revision"], key="invented-stale-db-model",
                kind="evidence", content="Invented corrected transcript", source_label="Correction")
        elif tamper == "content":
            note_source["content"] += "\nForged treatment claim."
        elif tamper == "revision":
            note_source["revision"] += 1
        elif tamper in {"missing_context", "missing_all_descriptors"}:
            envelope["context"]["sources"] = [p for p in envelope["context"]["sources"] if p["entry_id"] != receipt["source_entry_id"]]
            if tamper == "missing_all_descriptors":
                envelope["tool_selection"]["sources"] = [p for p in envelope["tool_selection"]["sources"] if p["entry_id"] != receipt["source_entry_id"]]
                envelope["source_delivery"] = [p for p in envelope["source_delivery"] if p["entry_id"] != receipt["source_entry_id"]]
        elif tamper == "descriptor_digest":
            next(p for p in envelope["tool_selection"]["sources"] if p["entry_id"] == receipt["source_entry_id"])["sha256"] = "f" * 64
        elif tamper == "reserved_descriptor_label":
            descriptor = next(p for p in envelope["tool_selection"]["sources"] if p["entry_id"] != receipt["source_entry_id"])
            descriptor["label"] = share.LABEL
        else:
            current = ws.read(s, f.box, f.actor, f.workspace["id"])
            generic = ws.append(s, f.box, f.actor, f.workspace["id"], expected=current["revision"], key="invented-ordinary-db-model",
                kind="conversation", content="Invented generic conversation", source_label=None)
            note_source["entry_id"] = generic["entry_id"]
        assert verified(s, envelope, command) is False


def test_large_mixed_source_fingerprint_matches_python_and_records_bounded_latency(clinical, record_property):
    f = clinical
    with Session(f.engine) as s:
        for label in ("baseline", "mixed_large"):
            if label == "mixed_large":
                for i in range(2):
                    current = ws.read(s, f.box, f.actor, f.workspace["id"])
                    ws.append(s, f.box, f.actor, f.workspace["id"], expected=current["revision"], key=f"invented-mixed-source-{i}",
                        kind="evidence", content="Invented reference " + "x" * 12000 + "界" * 1000 + "🩺\x7f", source_label="Mixed reference")
            current = ws.read(s, f.box, f.actor, f.workspace["id"])
            expected = note_review.source_fingerprint(s, f.workspace["id"], current["revision"])
            started = perf_counter()
            observed = s.scalar(text("SELECT public.clinical_note_fingerprint(:wid,:revision)"), {"wid": f.workspace["id"], "revision": current["revision"]})
            record_property(label + "_fingerprint_ms", round((perf_counter() - started) * 1000, 3))
            assert observed == expected
