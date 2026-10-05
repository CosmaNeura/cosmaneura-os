"""Long reviewed fax → product tools/three drafts → exact human edit/acceptance.

Registered signed fax acquisition/source routes, real PDF parsing, PostgreSQL
custody, v6 admission/HTTP decoder/tools/settlement and human review services are
real. Only vendor HTTP, Gmail provider/binding and model HTTP are invented. This
does not qualify live model reasoning, an actual clinician UI or outside work.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration import test_efax_inbound_source_api as fax
from tests.integration import test_product_agent_tool_workflow as product
from tests.integration.test_google_message import InventedGoogle, select_message
from tests.integration.test_google_message import read as read_gmail

from cosmas_os.adapters.gpt41 import ENDPOINT, _context
from cosmas_os.adapters.gpt41_tools_v6 import validate_prepared
from cosmas_os.application import agent_tools, handoff_briefs
from cosmas_os.application import google_message as gmail
from cosmas_os.application import handoff_review as reviews
from cosmas_os.application import handoff_revision as revisions
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.google_connection_models import GoogleConnectionCredential
from cosmas_os.models import (
    AuditEvent,
    EncounterWorkspace,
    ExternalIdentity,
    ModelUsageObservation,
    ModelWorkAdmission,
    Principal,
    WorkspaceHandoffAttempt,
    WorkspaceHandoffReview,
    WorkspaceReply,
)
from cosmas_os.ports.bot_capabilities import BotReply

managed_case = fax.managed_case
efax_http = fax.efax_http
source_http = fax.source_http
MID_FACT = "Invented mid-passage fact: the patient reports an unverified prior stent."
LATE_FACT = "Invented late-passage fact: medication names and stem-cell trial eligibility remain unknown."
FINAL_FACT = "Invented final fact: DOB is unavailable; no referral, treatment, booking or message was completed."
FEEDBACK = "Please retain the final unknown DOB and name the provider as the owner of the draft review."
LONG_PASSAGE = (
    "Human-selected invented café fax passage; this is manual text, not OCR. "
    + "x" * (1400 - len("Human-selected invented café fax passage; this is manual text, not OCR. "))
    + MID_FACT
)
LONG_PASSAGE += "y" * (8100 - len(LONG_PASSAGE)) + LATE_FACT
LONG_PASSAGE += "z" * (12000 - len(LONG_PASSAGE) - len(FINAL_FACT)) + FINAL_FACT
REQUIREMENTS = {
    "missing_facts": ["DOB, medication names and clinical-trial eligibility are unconfirmed."],
    "expected_output": "A private draft quoting the supplied facts for clinician review.",
    "completion_criteria": ["Retain uncertainty and confirm a human owner; do not claim outside work."],
    "independent": True,
}


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def long_fax(source_http, monkeypatch):
    f = source_http
    monkeypatch.setattr(settings, "workspace_agent_tools_enabled", True)
    with f.case.start(f.profile) as client:
        # The actual managed lifespan starts with its fixture's disabled model
        # backend. Enable the product model services only after startup: this
        # test deliberately drives exact scoped admissions itself, and must not
        # race three autonomous background lanes for those same reservations.
        # Worker scheduling is qualified separately by product worker tests.
        monkeypatch.setattr(settings, "workspace_llm_backend", "azure_gpt41")
        monkeypatch.setattr(settings, "workspace_llm_api_key", SecretStr("invented-product-http-key"))
        f.client = client
        f.before = fax.read(f, client)
        acquired = fax.acquire(f, client)
        f.fax_command = fax.review_command(f, client, acquired, passage=LONG_PASSAGE)
        f.fax_saved = fax.signed_fixture.result(client.post(f.path, headers=f.headers(), json=f.fax_command))
        fax.validate_commitments(f, f.fax_command, f.fax_saved)
        assert len(LONG_PASSAGE) == 12000 and MID_FACT not in LONG_PASSAGE[:1000]
        assert LATE_FACT not in LONG_PASSAGE[:5000] and LONG_PASSAGE.endswith(FINAL_FACT)
        with Session(f.case.engine) as s:
            config = team.save(s, f.box, f.owner, expected=0, key=fax.signed_fixture.key(),
                configuration=team.default_configuration())
            f.team_revision = config["revision"]
        yield f


def select_gmail(f, monkeypatch, s):
    # Deliberately after actual managed lifespan startup: no OAuth runtime or
    # endpoint is provisioned. This is the explicit provider/binding boundary.
    monkeypatch.setattr(settings, "workspace_google_connection_enabled", True)
    monkeypatch.setattr(settings, "workspace_google_message_enabled", True)
    account = ExternalIdentity(box_id=f.box, principal_id=f.owner,
        issuer="https://invented-fax-mail-" + uuid4().hex + ".invalid", subject="invented-owner",
        reviewed_by="Invented human", evidence_ref="synthetic long fax coexistence", organization_id="org_invented")
    s.add(account)
    s.flush()
    account_id, connected = account.id, datetime.now(UTC)
    s.add(GoogleConnectionCredential(account_id=account_id, binding_digest="a" * 64,
        status="ready", sealed=b"i" * 40, connected_at=connected, expires_at=connected + timedelta(hours=1)))
    s.commit()
    port = InventedGoogle(s, account_id, connected)
    w = s.get(EncounterWorkspace, f.wid)
    assert w is not None
    patient = w.patient_link_id
    s.rollback()
    g = SimpleNamespace(s=s, box=f.box, owner=f.owner, w={"id": f.wid}, patient=patient,
        account=account_id, port=port)

    def current(session, identity, full):
        port.session = session
        return port.message_binding(gmail._scoped_identity(identity), require_full=full, session=session)

    return g, current


def reserve(f, role="chief"):
    with Session(f.case.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        aid, _ = work.reserve_conversation(s, f.box, f.owner, f.wid, expected=current["revision"],
            team_revision=f.team_revision, key=fax.signed_fixture.key(), role=role,
            content="Read the full human-reviewed fax with the email and existing note. Summarize its late facts "
            "and assign independent private drafts to Scribe, Visit Prep and Follow-up. Preserve unknown DOB and trial eligibility.")
        assert aid is not None
        return aid


def claim(f, aid):
    with Session(f.case.engine) as s:
        claimed = work.claim(s, f.box, f.owner, aid)
        assert claimed is not None and claimed.envelope["contract"] == "cosmas-gpt41-prepared.v6"
        validate_prepared(claimed.envelope)
        original = _context(claimed.envelope["context"])
        source = next(p for p in original.sources if p.entry_id == f.fax_saved["entry_id"])
        assert source.kind == "evidence" and source.content == LONG_PASSAGE
        row = s.get(ModelWorkAdmission, aid)
        assert row is not None and row.source_sha256 == work.source_digest(original)
        if row.kind == "private_handoff":
            assert row.request_body["task_brief"]["version"] == 2
            assert row.request_body["task_brief"]["source_versions"] == handoff_briefs.source_versions(original)
        return claimed


def run_model(f, claimed, *, delegate=False, revised=False):
    """Real v6 outbound projection/HTTP rounds/executor; scripted provider output."""
    bodies, reads = [], []
    context = _context(claimed.envelope["context"])
    handle = next(h for h in claimed.envelope["tool_selection"]["sources"] if h["entry_id"] == f.fax_saved["entry_id"])
    assert handle["sha256"] == sha(LONG_PASSAGE)
    displayed = next(p for p in claimed.envelope["source_delivery"] if p["entry_id"] == handle["entry_id"])
    assert displayed["excerpt_chars"] == 1000 and displayed["delivery"] == "excerpt"

    def provider(request):
        assert str(request.url) == ENDPOINT and request.headers["Authorization"] == "Bearer invented-product-http-key"
        body = json.loads(request.content)
        bodies.append(body)
        assert body["store"] is False
        with Session(f.case.engine) as check:
            assert check.scalar(select(Principal).where(Principal.id == f.owner).with_for_update(nowait=True))
        if len(bodies) == 1:
            visible = json.loads(body["messages"][1]["content"])
            fax_excerpt = next(source for source in visible["sources"] if source["source_id"] == handle["entry_id"])
            # Revised tasks deliberately quote the previous private draft in
            # their question; only the selected fax is initially compacted.
            assert fax_excerpt["text"] == LONG_PASSAGE[:1000]
            assert LATE_FACT not in fax_excerpt["text"] and FINAL_FACT not in fax_excerpt["text"]
            return httpx.Response(200, json=product.response(calls=[product.read_call(handle)]))
        assert len(bodies) == 2
        tool = json.loads(body["messages"][-1]["content"])
        reads.append(tool)
        assert tool["tool"] == "read_selected_source" and tool["data"]["content"] == LONG_PASSAGE
        assert tool["data"]["sha256"] == sha(LONG_PASSAGE)
        assert tool["receipt"]["initiated_by_human_id"] == f.owner
        assert tool["receipt"]["actor_agent_id"] != f.owner
        assert tool["receipt"]["admission_id"] == claimed.admission_id
        summary = MID_FACT + "\n" + LATE_FACT + "\n" + FINAL_FACT
        if revised:
            assert FEEDBACK in context.question
            summary += "\n" + FEEDBACK
        output = {"answer": summary, "source_ids": [p.entry_id for p in context.sources]}
        if context.role == "scribe":
            output = {"excerpts": [{"source_id": handle["entry_id"], "quote": LATE_FACT},
                {"source_id": handle["entry_id"], "quote": FINAL_FACT}],
                "needs_from_clinician": ["Can you confirm DOB, medication names and clinical-trial eligibility?"
                    + (" " + FEEDBACK if revised else "")]}
        if claimed.envelope["baseline"]["flags"]["work_status"]:
            output["intent"] = "conversation"
        if claimed.envelope["baseline"]["flags"]["can_handoff"]:
            output["handoffs"] = [{"role": role, "intended_role": role,
                "brief": "Read the exact original sources and prepare a private " + role + " draft retaining unknown facts.",
                "requirements": REQUIREMENTS} for role in ("scribe", "visit_prep", "follow_up")] if delegate else []
        return httpx.Response(200, json=product.response(output))

    state, eid, result = product.dispatch_and_settle(f.case.engine, claimed, httpx.MockTransport(provider))
    assert state == "completed" and eid is not None and len(bodies) == 2 and len(reads) == 1
    assert isinstance(result, BotReply) and result.input_tokens == 200 and result.output_tokens == 40
    assert LATE_FACT in result.content and FINAL_FACT in result.content
    with Session(f.case.engine) as s:
        reply = s.get(WorkspaceReply, eid)
        assert reply is not None
        if context.role == "chief":
            # Chief's deliberately generic saved work status is not its model
            # summary. Verify that summary above, then its exact saved source
            # citations and durable assignments; specialists retain full facts.
            assert f.fax_saved["entry_id"] in {c["entry_id"] for c in reply.citations}
        else:
            assert LATE_FACT in reply.content and FINAL_FACT in reply.content
        if revised:
            assert FEEDBACK in reply.content
    return eid, reads[0]


def human_review(f, hid, decision="accepted", feedback=""):
    with Session(f.case.engine) as s:
        snapshot = ws.read(s, f.box, f.owner, f.wid)
        h = next(h for h in snapshot["handoffs"] if h["id"] == hid)
        reply = s.get(WorkspaceReply, h["result_entry_id"])
        assert reply is not None
        exact_result_sha = sha(reply.content)
        result = reviews.review(s, f.box, f.owner, f.wid, hid, expected=snapshot["revision"],
            key=fax.signed_fixture.key(), attempt_id=h["attempt_id"], result_entry_id=h["result_entry_id"],
            result_sha256=exact_result_sha, decision=decision, feedback=feedback)
        reviewed = next(h for h in result["workspace"]["handoffs"] if h["id"] == hid)
        assert reviewed["review"]["result_sha256"] == exact_result_sha
        assert reviewed["review"]["decision"] == decision and reviewed["review"]["feedback"] == feedback
        return reviewed["review"]["id"], result["workspace"]


def revoke(f):
    fax.signed_fixture.result(f.client.post("/efax-inbound/revoke", headers=f.headers(),
        json={"idempotency_key": fax.signed_fixture.key(), "grant_id": f.grant_id}))


def test_full_manual_fax_email_note_to_three_specialists_and_exact_human_edit_loop(long_fax, monkeypatch):
    f = long_fax
    with Session(f.case.engine) as google_session:
        g, binding = select_gmail(f, monkeypatch, google_session)
        with gmail.install_binding_reader(binding):
            selected_mail = select_message(g)
            google_session.rollback()
            before_work = fax.read(f, f.client)
            original_note = before_work["note"]
            assert original_note == f.before["note"] and original_note is not None
            mail = next(e for e in before_work["entries"] if e["id"] == selected_mail["entry_id"])
            assert mail["google_source_state"] == "current"
            chief = claim(f, reserve(f))
            context = _context(chief.envelope["context"])
            assert {f.fax_saved["entry_id"], mail["id"]} <= {p.entry_id for p in context.sources}
            with pytest.raises(ValueError):
                handoff_briefs.validate_sources(context, version=1)
            handoff_briefs.validate_sources(context, version=2, prepared_contract=chief.envelope["contract"])
            _, chief_read = run_model(f, chief, delegate=True)
            with Session(f.case.engine) as s:
                children = list(s.scalars(select(ModelWorkAdmission).where(
                    ModelWorkAdmission.workspace_id == f.wid, ModelWorkAdmission.kind == "private_handoff")))
                assert {r.request_body["role"] for r in children} == {"scribe", "visit_prep", "follow_up"}
                assert len(children) == 3
                child_ids = []
                for r in children:
                    attempt = s.get(WorkspaceHandoffAttempt, r.handoff_attempt_id)
                    assert attempt is not None
                    child_ids.append((r.id, attempt.handoff_id, r.request_body["role"]))
            actors = {chief_read["receipt"]["actor_agent_id"]}
            scribe_hid = None
            for aid, hid, role in child_ids:
                _, reader = run_model(f, claim(f, aid))
                actors.add(reader["receipt"]["actor_agent_id"])
                if role == "scribe":
                    scribe_hid = hid
                else:
                    human_review(f, hid)
            assert len(actors) == 4 and scribe_hid is not None
            review_id, reviewed = human_review(f, scribe_hid, "changes_requested", FEEDBACK)
            with Session(f.case.engine) as s:
                updated = revisions.reserve(s, f.box, f.owner, f.wid, scribe_hid,
                    expected=reviewed["revision"], key=fax.signed_fixture.key(), review_id=review_id)
                revised_hid = updated["revision_handoff_id"]
                attempt = s.scalar(select(WorkspaceHandoffAttempt).where(WorkspaceHandoffAttempt.handoff_id == revised_hid))
                assert attempt is not None
                row = s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.handoff_attempt_id == attempt.id))
                assert row is not None
                revised_aid = row.id
                assert row.request_body["revision_request"]["feedback"] == FEEDBACK
                assert row.request_body["revision_request"]["review_id"] == review_id
            run_model(f, claim(f, revised_aid), revised=True)
            _, final = human_review(f, revised_hid)
            assert final["note"] == original_note and next(e for e in final["entries"] if e["id"] == mail["id"]) == mail
            assert len(final["handoffs"]) == 4
            assert sum(h.get("review", {}).get("decision") == "accepted" for h in final["handoffs"]) == 3
            with Session(f.case.engine) as s:
                assert s.scalar(select(func.count()).select_from(ModelUsageObservation).where(
                    ModelUsageObservation.workspace_id == f.wid)) == 5
                audits = list(s.scalars(select(AuditEvent).where(AuditEvent.box_id == f.box,
                    AuditEvent.event_type == "workspace.agent_tool_read")))
                assert len(audits) == 5 and all(e.approved_by_principal_id is None for e in audits)
                assert s.scalar(select(func.count()).select_from(WorkspaceHandoffReview).where(
                    WorkspaceHandoffReview.workspace_id == f.wid)) == 4
            revoke(f)
            masked = fax.read(f, f.client)
            assert masked["note"] == original_note
            for earlier in final["handoffs"]:
                retained = next(h for h in masked["handoffs"] if h["id"] == earlier["id"])
                assert retained["result_sha256"] == earlier["result_sha256"]
                assert retained["task_brief_unavailable"] is True
                assert "task_brief" not in retained and "completion_evidence" not in retained
            assert LATE_FACT not in str(masked) and FINAL_FACT not in str(masked) and FEEDBACK not in str(masked)
            assert next(e for e in masked["entries"] if e["id"] == mail["id"]) == mail
            assert fax.resolve(f, f.client, f.fax_command)["source_withheld"] is True
            assert g.port.calls == ["list", "read"]
    assert len(f.wire) == len(f.credentials) == 2


@pytest.mark.parametrize("boundary", ["claim", "read", "settle"])
def test_long_fax_revocation_fences_original_source_at_every_product_boundary(long_fax, boundary):
    f = long_fax
    aid = reserve(f)
    claimed = None if boundary == "claim" else claim(f, aid)
    revoke(f)
    with Session(f.case.engine) as s:
        if boundary == "claim":
            assert work.claim(s, f.box, f.owner, aid) is None
        else:
            assert claimed is not None
            if boundary == "read":
                handle = next(h for h in claimed.envelope["tool_selection"]["sources"] if h["entry_id"] == f.fax_saved["entry_id"])
                with pytest.raises(ws.WorkspaceError):
                    agent_tools.AgentToolExecutor(s, claimed).execute({"tool": "read_selected_source",
                        **{k: handle[k] for k in ("entry_id", "revision", "sha256")}})
            work.settle(s, claimed, BotReply("Never publish the revoked late facts: " + LATE_FACT,
                (), "azure_gpt41", 100, 20))
        row = s.get(ModelWorkAdmission, aid)
        assert row is not None and row.state == "failed" and row.result_entry_id is None
        assert s.scalar(select(WorkspaceReply).where(WorkspaceReply.workspace_id == f.wid)) is None
    masked = fax.read(f, f.client)
    assert masked["note"] == f.before["note"] and LATE_FACT not in str(masked)
    assert fax.resolve(f, f.client, f.fax_command)["source_withheld"] is True
    assert len(f.wire) == 2


def test_long_fax_cannot_silently_downgrade_to_pre_v6_before_model_admission(long_fax, monkeypatch):
    f = long_fax
    monkeypatch.setattr(settings, "workspace_agent_tools_enabled", False)
    with pytest.raises(ws.WorkspaceError, match="efax_inbound_source_context_too_large"):
        reserve(f)
    with Session(f.case.engine) as s:
        assert s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == f.wid)) is None
    assert fax.read(f, f.client)["note"] == f.before["note"] and len(f.wire) == 2


def test_google_message_five_thousand_limit_is_not_broadened_by_long_fax_v6(long_fax, monkeypatch):
    f = long_fax
    with Session(f.case.engine) as s:
        g, binding = select_gmail(f, monkeypatch, s)
        with gmail.install_binding_reader(binding):
            g.port.text = "g" * 5000
            complete = read_gmail(g, key="mail-boundary-5000")
            assert len(complete["message"]["content"]) == 5000
            s.rollback()
            g.port.text += "g"
            with pytest.raises(ws.WorkspaceError, match="google_message_read_unconfirmed"):
                read_gmail(g, key="mail-boundary-5001")
            # The second request reuses the immutable list observation, then
            # performs only its newly keyed selected-message read.
            assert g.port.calls == ["list", "read", "read"]
    assert fax.read(f, f.client)["note"] == f.before["note"] and len(f.wire) == 2
