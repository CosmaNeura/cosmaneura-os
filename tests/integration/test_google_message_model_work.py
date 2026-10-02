"""Reviewed invented Gmail evidence through real product tools and draft review."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.helpers.task_brief import REQUIREMENTS
from tests.integration import test_product_agent_tool_workflow as product
from tests.integration.test_google_message import InventedGoogle

from cosmas_os.adapters.gpt41 import ENDPOINT, _context
from cosmas_os.application import conversation, handoffs
from cosmas_os.application import google_message as messages
from cosmas_os.application import handoff_review as reviews
from cosmas_os.application import handoff_revision as revisions
from cosmas_os.application import model_work as work
from cosmas_os.application import note_review as notes
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.google_connection_models import GoogleConnectionCredential
from cosmas_os.models import (
    AuditEvent,
    EncounterWorkspace,
    ExternalIdentity,
    ModelWorkAdmission,
    Principal,
    WorkspaceEntry,
    WorkspaceHandoff,
    WorkspaceHandoffAttempt,
    WorkspaceHandoffReview,
    WorkspaceNote,
    WorkspaceReply,
)
from cosmas_os.ports.google_message import GoogleMessageBinding


class CommittedInventedGoogle(InventedGoogle):
    """A fake provider port whose DB-only binding works in real worker sessions."""

    def message_binding(self, identity, *, require_full=False, session=None):
        assert session is not None and identity.external_identity_id == self.account
        return GoogleMessageBinding(account_id=self.account, binding_digest="a" * 64,
            connected_at=self.connected, grant_sha256=self.grant)


@pytest.fixture
def google_case(engine, monkeypatch):
    # Every product reader opens its own Session; use committed rows, not a fixture savepoint.
    configuration = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue] -- BaseSettings runtime-only option.
        workspace_enabled=True, workspace_authenticated_enabled=True,
        database_url="postgresql+psycopg://w1a_synth@127.0.0.1:55439/w1a_w1b_test",
        auth_mode="clerk_jwt", synth_seed=False,
        clerk_issuer="https://clerk.example.invalid",
        clerk_jwks_url="https://clerk.example.invalid/.well-known/jwks.json",
        clerk_audience="cosmas-workspace-local", clerk_organization_id="org_invented",
        clerk_authorized_parties="http://localhost:5173", cors_allowed_origins="http://localhost:5173",
        workspace_agent_tools_enabled=True, workspace_google_connection_enabled=True,
        workspace_google_message_enabled=True, workspace_llm_backend="azure_gpt41",
        workspace_llm_api_key=SecretStr("invented-product-http-key"),
    )
    # Provision needs only local product state. Bind the full authenticated profile before work.
    for module in (team, conversation, handoffs):
        monkeypatch.setattr(module, "runtime_settings", configuration)
    with Session(engine) as s:
        from cosmas_os.application import services as svc

        seeded = svc.provision_box(svc.Container(s), "Invented Gmail model clinic")
    configuration.beta_box_id = seeded["box_id"]
    assert configuration.workspace_available and configuration.workspace_google_message_available
    # Reuse the committed product Scribe intake and team fixture, within this fresh Box.
    with Session(engine) as s:
        from tests.integration.test_note_review import prepare

        box, owner, initial, patient = prepare(s, seeded)
        team.save(s, box, owner, expected=0, key="invented-google-team", configuration=team.default_configuration())
        state = ws.append(s, box, owner, initial["id"], expected=initial["revision"],
            key="invented-google-transcript", kind="evidence", source_label="Invented Scribe transcript",
            content=product.TRANSCRIPT)["workspace"]
        state = notes.save(s, box, owner, state["id"], expected=state["revision"],
            key="invented-existing-note", base_note_id=None, source_reply_id=None,
            content="Invented clinical note: record review is pending; no clinical action approved.")["workspace"]
        note = state["note"]["latest"]
        state = notes.review(s, box, owner, state["id"], note["id"], expected=state["revision"],
            key="invented-existing-note-review", content_hash=note["content_hash"],
            source_hash=note["source_fingerprint"])["workspace"]
        note_before = state["note"]["latest"]
        now = datetime.now(UTC)
        account = ExternalIdentity(box_id=box, principal_id=owner,
            issuer="https://clerk-" + str(uuid4()) + ".example.invalid", subject="invented-owner",
            organization_id="org_invented", reviewed_by="Invented owner", evidence_ref="invented:google-model")
        s.add(account)
        s.flush()
        s.add(GoogleConnectionCredential(account_id=account.id, binding_digest="a" * 64,
            status="ready", sealed=b"i" * 40, connected_at=now, expires_at=now + timedelta(hours=1)))
        s.commit()
        port = CommittedInventedGoogle(s, account.id, now)
        f = SimpleNamespace(engine=engine, box=box, owner=owner, wid=state["id"], patient=patient,
            account=account.id, port=port, note_before=note_before, selected=None, replacement=None)
        with messages.install_binding_reader(lambda current, identity, full: port.message_binding(
            messages._scoped_identity(identity), require_full=full, session=current)):
            f.selected = select_current(f, key="initial")
            yield f


def select_current(f, *, key):
    with Session(f.engine) as s:
        f.port.session = s
        observation = messages.list_observed(s, f.box, f.owner, f.account, key="list-" + key, port=f.port)
        receipt = messages.read_selected(s, f.box, f.owner, f.account, key="read-" + key,
            observation_id=observation["read_id"], observation_sha256=observation["source_sha256"],
            message_id="invented-message", port=f.port)
        current = ws.read(s, f.box, f.owner, f.wid)
        return messages.select_review(s, f.box, f.owner, f.wid, expected=current["revision"],
            key="review-" + key, read_id=receipt["read_id"], source_sha256=receipt["source_sha256"],
            patient_link_id=f.patient, reviewed_patient=True, reviewed_exact_message=True,
            reviewed_untrusted_source=True, port=f.port, external_identity_id=f.account)


def change_source(f, fault):
    if fault == "superseded":
        f.port.text = "Subject: Invented replacement\nFrom: sender@example.invalid\n\nInvented revised administrative request."
        f.replacement = select_current(f, key="replacement")
    elif fault == "semantic_grant":
        f.port.grant = "d" * 64
    else:
        with Session(f.engine) as s:
            credential = s.get(GoogleConnectionCredential, f.account)
            assert credential is not None
            credential.status = "disconnected"
            s.commit()


def private_fact_paths(value, needles, path="$", result=None):
    """Diagnostic field locations only; never persist the private value itself."""
    result = [] if result is None else result
    if isinstance(value, dict):
        for key, child in value.items():
            private_fact_paths(child, needles, path + "." + key, result)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            private_fact_paths(child, needles, path + "[" + str(index) + "]", result)
    elif isinstance(value, str) and any(needle in value for needle in needles):
        result.append(path)
    return result


def review_commitment(f, handoff, command):
    return payload_hash({"workspace_id": f.wid, "handoff_id": handoff["id"],
        "expected_revision": command["expected"], "idempotency_key": command["key"],
        "attempt_id": command["attempt_id"], "result_entry_id": command["result_entry_id"],
        "result_sha256": command["result_sha256"], "decision": command["decision"],
        "feedback": command.get("feedback", "")})


def reserve(f, key):
    return product.reserve(f.engine, (f.box, f.owner, f.wid),
        "Use Scribe and the reviewed Google message to prepare an administrative draft for my review.", key)


def model_http(f, claimed, *, offer=False, cite_google=True, change_at_round=None, fault=None):
    """Only provider HTTP is fake: actual admission, parser, tool reader and settle run."""
    calls, receipts = [], []
    context = _context(claimed.envelope["context"])
    source = next(p for p in context.sources if p.entry_id == f.selected["entry_id"])
    handle = next(h for h in claimed.envelope["tool_selection"]["sources"] if h["entry_id"] == source.entry_id)
    assert source.kind == handle["kind"] == "evidence" and source.content == f.port.text
    assert handle["sha256"] == hashlib.sha256(source.content.encode()).hexdigest()
    def respond(request):
        assert str(request.url) == ENDPOINT
        body = json.loads(request.content)
        calls.append(body)
        assert body["store"] is False and body["model"] == "gpt-4.1"
        with Session(f.engine) as check:
            assert check.scalar(select(Principal).where(Principal.id == f.owner).with_for_update(nowait=True))
        if change_at_round == len(calls):
            change_source(f, fault)
        if len(calls) == 1:
            supplied = json.loads(body["messages"][1]["content"])["sources"]
            assert any(p["source_id"] == source.entry_id and p["text"] == source.content for p in supplied)
            return httpx.Response(200, json=product.response(calls=[product.read_call(handle)]))
        assert len(calls) == 2
        result = json.loads(body["messages"][-1]["content"])
        assert result["data"]["content"] == source.content
        assert result["receipt"]["initiated_by_human_id"] == f.owner
        assert result["receipt"]["actor_agent_id"] != f.owner
        receipts.append(result)
        output = {"answer": "Invented administrative draft derived from the reviewed message; clinician review remains required.",
            "source_ids": [p.entry_id for p in context.sources if cite_google or p.entry_id != source.entry_id]}
        if claimed.envelope["baseline"]["flags"]["work_status"]:
            output["intent"] = "conversation"
        if claimed.envelope["baseline"]["flags"]["can_handoff"]:
            output["handoffs"] = [{"role": "follow_up", "intended_role": "follow_up",
                "brief": "Prepare an invented administrative draft; preserve unknown clinical facts.",
                "requirements": REQUIREMENTS}] if offer else []
        return httpx.Response(200, json=product.response(output))
    return httpx.MockTransport(respond), calls, receipts


def complete_handoff(f, *, cite_google=True):
    chief = reserve(f, "invented-google-chief")
    transport, _, _ = model_http(f, chief, offer=True)
    assert product.dispatch_and_settle(f.engine, chief, transport)[0] == "completed"
    with Session(f.engine) as s:
        child = s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == f.wid,
            ModelWorkAdmission.kind == "private_handoff"))
        assert child is not None
        claimed = work.claim(s, f.box, f.owner, child.id)
        assert claimed is not None
    transport, calls, _ = model_http(f, claimed, cite_google=cite_google)
    assert product.dispatch_and_settle(f.engine, claimed, transport)[0] == "completed" and len(calls) == 2
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        handoff = current["handoffs"][0]
        reply = s.get(WorkspaceReply, handoff["result_entry_id"])
        assert reply is not None
        return {"expected": current["revision"], "key": "invented-google-human-review",
            "attempt_id": handoff["attempt_id"], "result_entry_id": handoff["result_entry_id"],
            "result_sha256": hashlib.sha256(reply.content.encode()).hexdigest(), "decision": "accepted"}, handoff


def test_reviewed_google_source_executes_real_product_tool_and_preserves_clinical_note(google_case):
    f = google_case
    claimed = reserve(f, "invented-google-context")
    transport, calls, receipts = model_http(f, claimed)
    state, result_id, result = product.dispatch_and_settle(f.engine, claimed, transport)
    assert state == "completed" and result_id and len(calls) == 2 and len(receipts) == 1
    assert result.input_tokens == 200 and result.output_tokens == 40
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        note = current["note"]["latest"]
        for name in ("id", "content", "content_hash", "source_fingerprint", "review"):
            assert note[name] == f.note_before[name]
        assert note["sources_changed"] is False
        assert notes.source_fingerprint(s, f.wid, current["revision"]) == f.note_before["source_fingerprint"]
        entry = s.get(WorkspaceEntry, f.selected["entry_id"])
        assert entry is not None and entry.kind == "google_message"
        reply = s.get(WorkspaceReply, result_id)
        assert reply is not None and next(c for c in reply.citations if c["entry_id"] == entry.id)["kind"] == "evidence"
        audits = list(s.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == claimed.admission_id,
            AuditEvent.event_type == "workspace.agent_tool_read")))
        assert len(audits) == 1 and f.port.text not in json.dumps(audits[0].detail)
        assert "grant_sha256" not in json.dumps(audits[0].detail)


@pytest.mark.parametrize("fault", ["disconnect", "semantic_grant", "superseded"])
def test_revoked_or_superseded_source_before_tool_call_withholds_content(google_case, fault):
    f = google_case
    claimed = reserve(f, "invented-google-tool-revoked")
    transport, calls, receipts = model_http(f, claimed, change_at_round=1, fault=fault)
    state, result_id, _ = product.dispatch_and_settle(f.engine, claimed, transport)
    assert state == "failed" and result_id is None and len(calls) == 1 and receipts == []
    with Session(f.engine) as s:
        assert s.scalar(select(WorkspaceReply).where(WorkspaceReply.workspace_id == f.wid)) is None
        assert s.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == claimed.admission_id,
            AuditEvent.event_type == "workspace.agent_tool_read")) is None


@pytest.mark.parametrize("fault", ["disconnect", "superseded"])
def test_source_change_before_settle_blocks_even_uncited_derived_draft(google_case, fault):
    f = google_case
    claimed = reserve(f, "invented-google-uncited-settle")
    transport, calls, _ = model_http(f, claimed, cite_google=False)
    result = work.dispatch_claim(claimed, session_factory=lambda: Session(f.engine), transport=transport)
    assert f.selected["entry_id"] not in {citation.entry_id for citation in result.citations}
    assert len(calls) == 2
    change_source(f, fault)
    with Session(f.engine) as s:
        work.settle(s, claimed, result)
        admission = s.get(ModelWorkAdmission, claimed.admission_id)
        assert admission is not None and admission.state == "failed" and admission.result_entry_id is None
        assert s.scalar(select(WorkspaceReply).where(WorkspaceReply.workspace_id == f.wid)) is None


@pytest.mark.parametrize("fault", ["disconnect", "superseded"])
def test_handoff_human_review_binds_all_sources_even_if_child_did_not_cite_google(google_case, fault):
    f = google_case
    command, handoff = complete_handoff(f, cite_google=False)
    change_source(f, fault)
    with Session(f.engine) as s:
        with pytest.raises(ws.WorkspaceError):
            reviews.review(s, f.box, f.owner, f.wid, handoff["id"], **command)
        s.rollback()
        assert s.scalar(select(func.count()).select_from(WorkspaceHandoffReview).where(
            WorkspaceHandoffReview.workspace_id == f.wid)) == 0


@pytest.mark.parametrize("fault", ["disconnect", "superseded"])
def test_lost_handoff_review_reply_recovers_history_without_current_source_authority(google_case, fault):
    f = google_case
    command, handoff = complete_handoff(f)
    command["feedback"] = "Invented accepted café draft; source review remains human-owned."
    commitment = review_commitment(f, handoff, command)
    with Session(f.engine) as s:
        accepted = reviews.review(s, f.box, f.owner, f.wid, handoff["id"], **command)
        assert accepted["request_sha256"] == commitment and accepted["feedback_withheld"] is False
        immediate = reviews.review(s, f.box, f.owner, f.wid, handoff["id"], **command)
        assert immediate["request_sha256"] == commitment and immediate["feedback_withheld"] is False
        assert immediate["entry_revision"] == accepted["entry_revision"]
    change_source(f, fault)
    with Session(f.engine) as s:
        replay = reviews.review(s, f.box, f.owner, f.wid, handoff["id"], **command)
        assert replay["entry_revision"] == accepted["entry_revision"]
        assert replay["request_sha256"] == commitment and replay["feedback_withheld"] is True
        assert "Invented accepted café" not in json.dumps(replay, ensure_ascii=False)
        w = s.get(EncounterWorkspace, f.wid)
        h = s.get(WorkspaceHandoff, handoff["id"])
        attempt = s.get(WorkspaceHandoffAttempt, handoff["attempt_id"])
        stored = reviews.stored_review_for(s, w, h, attempt)
        assert stored is not None and stored["decision"] == "accepted"
        assert reviews.review_for(s, w, h, attempt) is None and reviews.review_status_for(s, w, h, attempt) == "stale"
        assert messages.historical_source(s, w, f.selected["entry_id"]).content.startswith("Subject: Invented message")
        assert s.scalar(select(func.count()).select_from(WorkspaceHandoffReview).where(
            WorkspaceHandoffReview.workspace_id == f.wid)) == 1
        with pytest.raises(ws.WorkspaceError):
            reviews.review(s, f.box, f.owner, f.wid, handoff["id"], **{**command,
                "expected": replay["workspace"]["revision"], "key": "never-authorize-stale-accepted"})
        s.rollback()
        assert s.scalar(select(func.count()).select_from(WorkspaceHandoffReview).where(
            WorkspaceHandoffReview.workspace_id == f.wid)) == 1


def test_google_and_later_ordinary_evidence_have_same_admission_and_handoff_order(google_case):
    f = google_case
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        ws.append(s, f.box, f.owner, f.wid, expected=current["revision"], key="later-ordinary-evidence",
            kind="evidence", source_label="Invented later Scribe summary", content=product.SUMMARY)
    claimed = reserve(f, "invented-google-later-source-order")
    context = _context(claimed.envelope["context"])
    evidence = [source for source in context.sources if source.kind == "evidence"]
    assert [source.revision for source in evidence] == sorted(source.revision for source in evidence)
    assert context.context_revision >= evidence[-1].revision
    transport, calls, _ = model_http(f, claimed, offer=True)
    assert product.dispatch_and_settle(f.engine, claimed, transport)[0] == "completed" and len(calls) == 2
    with Session(f.engine) as s:
        child = s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == f.wid,
            ModelWorkAdmission.kind == "private_handoff"))
        assert child is not None
        child_claim = work.claim(s, f.box, f.owner, child.id)
        assert child_claim is not None
    transport, calls, _ = model_http(f, child_claim)
    assert product.dispatch_and_settle(f.engine, child_claim, transport)[0] == "completed" and len(calls) == 2


@pytest.mark.parametrize("lose_grant", [False, True])
def test_google_derived_scribe_reply_cannot_be_imported_as_a_clinical_note(google_case, lose_grant):
    f = google_case
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        admission_id, _ = work.reserve_conversation(s, f.box, f.owner, f.wid,
            expected=current["revision"], team_revision=1, key="invented-google-scribe-lineage",
            role="scribe", content="Prepare a source-based draft from the reviewed evidence.")
        claimed = work.claim(s, f.box, f.owner, admission_id)
        assert claimed is not None
    context = _context(claimed.envelope["context"])
    source = next(p for p in context.sources if p.entry_id == f.selected["entry_id"])
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        assert str(request.url) == ENDPOINT
        output = {"answer": "Invented Scribe preparation for human review:\n" + source.content,
            "source_ids": [source.entry_id]}
        return httpx.Response(200, json=product.response(output))
    state, result_id, _ = product.dispatch_and_settle(f.engine, claimed, httpx.MockTransport(respond))
    assert state == "completed" and result_id and len(requests) == 1
    if lose_grant:
        change_source(f, "disconnect")
    with Session(f.engine) as s:
        before = s.scalar(select(func.count()).select_from(WorkspaceNote).where(WorkspaceNote.workspace_id == f.wid))
        current = ws.read(s, f.box, f.owner, f.wid)
        reply = s.get(WorkspaceReply, result_id)
        assert reply is not None and reply.role == "scribe" and source.content in reply.content
        with pytest.raises(ws.WorkspaceError, match="google_message_note_import_unavailable"):
            notes.save(s, f.box, f.owner, f.wid, expected=current["revision"],
                key="never-import-google-scribe", base_note_id=current["note"]["latest"]["id"],
                source_reply_id=result_id, content=reply.content)
        s.rollback()
        assert s.scalar(select(func.count()).select_from(WorkspaceNote).where(WorkspaceNote.workspace_id == f.wid)) == before
        assert ws.read(s, f.box, f.owner, f.wid)["note"]["latest"]["id"] == f.note_before["id"]


@pytest.mark.parametrize("fault", ["disconnect", "superseded"])
def test_historical_feedback_and_revision_hide_email_facts_but_keep_receipt_binding(google_case, fault, tmp_path):
    f = google_case
    command, handoff = complete_handoff(f)
    feedback = "Invented email fact: request café follow-up through sender@example.invalid."
    command.update(decision="changes_requested", feedback=feedback)
    commitment = review_commitment(f, handoff, command)
    assert commitment != review_commitment(f, handoff, {**command, "feedback": feedback.replace("café", "cafe")})
    with Session(f.engine) as s:
        saved = reviews.review(s, f.box, f.owner, f.wid, handoff["id"], **command)
        assert saved["request_sha256"] == commitment and saved["feedback_withheld"] is False
        immediate = reviews.review(s, f.box, f.owner, f.wid, handoff["id"], **command)
        assert immediate["request_sha256"] == commitment and immediate["feedback_withheld"] is False
        current = saved["workspace"]
        parent = next(h for h in current["handoffs"] if h["id"] == handoff["id"])
        review = parent["review"]
        assert review is not None and review["feedback"] == feedback
        revised = revisions.reserve(s, f.box, f.owner, f.wid, handoff["id"],
            expected=current["revision"], key="invented-google-feedback-revision", review_id=review["id"])
        child_handoff = next(h for h in revised["workspace"]["handoffs"] if h["id"] == revised["revision_handoff_id"])
        child = s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.handoff_attempt_id == child_handoff["attempt_id"]))
        assert child is not None
        child_claim = work.claim(s, f.box, f.owner, child.id)
        assert child_claim is not None
    transport, calls, _ = model_http(f, child_claim)
    assert product.dispatch_and_settle(f.engine, child_claim, transport)[0] == "completed" and len(calls) == 2
    change_source(f, fault)
    with Session(f.engine) as s:
        recovered = reviews.review(s, f.box, f.owner, f.wid, handoff["id"], **command)
        assert recovered["entry_revision"] == saved["entry_revision"]
        assert recovered["request_sha256"] == commitment and recovered["feedback_withheld"] is True
        current = recovered["workspace"]
        by_id = {h["id"]: h for h in current["handoffs"]}
        public_review = by_id[handoff["id"]]["review"]
        assert public_review is not None
        for key in ("id", "attempt_id", "result_entry_id", "result_sha256", "decision"):
            assert public_review[key] == review[key]
        assert public_review["feedback"] == "Email access must be checked before viewing this feedback."
        revision = by_id[revised["revision_handoff_id"]]["revision_request"]
        assert revision["review_id"] == review["id"] and revision["result_sha256"] == review["result_sha256"]
        assert revision["feedback"] == public_review["feedback"]
        # The separately reviewed replacement source is permitted. The reused sender
        # alone cannot identify a disclosure of the superseded input.
        needles = ["Invented email fact", "Invented administrative request café"]
        if fault == "disconnect":
            needles.append("sender@example.invalid")
        leaked_paths = private_fact_paths(current, needles)
        if leaked_paths:
            diagnostic = {"fault": fault, "paths": leaked_paths, "mode": "invented fixture only; no private content"}
            target: Path = tmp_path / ("google-message-feedback-paths-" + fault + ".json")
            target.write_text(json.dumps(diagnostic, indent=2) + "\n")
        assert leaked_paths == [], {"paths": leaked_paths}
        source_entry = next(e for e in current["entries"] if e["id"] == f.selected["entry_id"])
        assert source_entry["content"] == "" and source_entry["source_label"] == "Unavailable email source"
        if fault == "superseded":
            replacement = next(e for e in current["entries"] if e["id"] == f.replacement["entry_id"])
            assert replacement["google_source_state"] == "current" and replacement["content"] == f.port.text
            old_projection = {**current, "entries": [e for e in current["entries"] if e["id"] != replacement["id"]]}
            assert private_fact_paths(old_projection, ["sender@example.invalid"]) == []
        else:
            assert "sender@example.invalid" not in json.dumps(current)
        assert "Invented message" not in source_entry["source_label"]
        with pytest.raises(ws.WorkspaceError):
            reviews.review(s, f.box, f.owner, f.wid, handoff["id"], **{**command,
                "expected": current["revision"], "key": "never-authorize-stale-feedback"})
        s.rollback()
        with pytest.raises(ws.WorkspaceError, match="handoff_revision_stale"):
            revisions.reserve(s, f.box, f.owner, f.wid, handoff["id"], expected=current["revision"],
                key="never-revise-stale-email-feedback", review_id=review["id"])
        s.rollback()
        assert s.scalar(select(func.count()).select_from(WorkspaceHandoffReview).where(
            WorkspaceHandoffReview.workspace_id == f.wid)) == 1
