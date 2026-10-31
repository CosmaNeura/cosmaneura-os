"""Product admission → HTTP tool rounds → saved drafts, entirely invented data."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.helpers.task_brief import REQUIREMENTS

from cosmas_os.adapters.gpt41 import ENDPOINT, _context
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    AppointmentObservation,
    AuditEvent,
    ModelWorkAdmission,
    PatientLink,
    Principal,
    WorkspaceHandoff,
    WorkspaceHandoffAttempt,
    WorkspaceReply,
)
from cosmas_os.ports.bot_capabilities import ModelCallFailure

TRANSCRIPT = (
    "Invented Scribe transcript. Walk-in adult, date of birth not available. "
    "Provider: What should we address today? Patient: I had heart trouble and want "
    "to ask about research options after a heart attack. Provider: We need to "
    "confirm prior records and details before discussing eligibility. No treatment "
    "was chosen and no referral, appointment or message was sent."
)
SUMMARY = (
    "Invented Scribe summary: questions about post-heart-attack research, including "
    "stem-cell studies. Prior diagnosis, medications and eligibility are unknown. "
    "Prepare questions and an administrative follow-up draft for clinician review."
)


@pytest.fixture
def operational(monkeypatch):
    monkeypatch.setattr(team.runtime_settings, "workspace_enabled", True)
    monkeypatch.setattr(team.runtime_settings, "workspace_agent_tools_enabled", True)
    monkeypatch.setattr(team.runtime_settings, "workspace_llm_backend", "azure_gpt41")
    monkeypatch.setattr(team.runtime_settings, "workspace_llm_api_key", SecretStr("invented-product-http-key"))


def encounter(engine):
    """Committed sessions are essential: every real tool read opens another session."""
    with Session(engine) as s:
        seed = svc.provision_box(svc.Container(s), "Invented product workflow clinic")
        box, owner = seed["box_id"], seed["owner_id"]
        link = PatientLink(box_id=box, source_pair_key="tools:" + str(uuid4()),
            label="Invented walk-in", state="confirmed", confirmed_by_principal_id=owner,
            attested_at=datetime.now(UTC))
        s.add(link)
        s.flush()
        appointment = AppointmentObservation(box_id=box, patient_link_id=link.id,
            external_id=str(uuid4()), source="synthetic", start_at=datetime.now(UTC),
            patient_label="Invented walk-in")
        s.add(appointment)
        s.commit()
        workspace = ws.create(s, box, owner, appointment.id, "invented-create", initial_synthetic_source=False)
        team.save(s, box, owner, expected=0, key="invented-team", configuration=team.default_configuration())
        for number, (label, content) in enumerate((("Invented Scribe transcript", TRANSCRIPT),
            ("Invented Scribe summary", SUMMARY)), start=1):
            workspace = ws.append(s, box, owner, workspace["id"], expected=workspace["revision"],
                key="invented-scribe-" + str(number), kind="evidence", source_label=label,
                content=content)["workspace"]
        return box, owner, workspace["id"]


def reserve(engine, case, content, key):
    box, owner, wid = case
    with Session(engine) as s:
        revision = ws.read(s, box, owner, wid)["revision"]
        admission_id, _ = work.reserve_conversation(s, box, owner, wid, expected=revision,
            team_revision=1, key=key, role="chief", content=content)
        claimed = work.claim(s, box, owner, admission_id)
        assert claimed is not None and claimed.envelope["contract"] == "cosmas-gpt41-prepared.v6"
        return claimed


def response(content=None, calls=None):
    message = {"role": "assistant", "content": json.dumps(content) if content is not None else None}
    if calls:
        message["tool_calls"] = calls
    return {"model": "gpt-4.1", "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        "choices": [{"finish_reason": "tool_calls" if calls else "stop", "message": message}]}


def read_call(handle, name="read_selected_source"):
    return {"id": "call_invented_read", "type": "function", "function": {
        "name": name, "arguments": json.dumps({k: handle[k] for k in ("entry_id", "revision", "sha256")})}}


def tool_http(engine, claimed, *, handoffs=(), teammate=False, mutate_at_round=None):
    """Only the upstream HTTP is fake; parser, authority, tool reader and DB are real."""
    requests, reads = [], []
    context = _context(claimed.envelope["context"])
    selection = claimed.envelope["tool_selection"]
    handle = selection["teammate_drafts"][0] if teammate else selection["sources"][0]
    def handle_http(request):
        assert str(request.url) == ENDPOINT
        assert request.headers["Authorization"] == "Bearer invented-product-http-key"
        body = json.loads(request.content)
        assert body["model"] == "gpt-4.1-dzus" and body["store"] is False
        # The provider HTTP must not hold the admitting owner/workspace lock.
        with Session(engine) as check:
            assert check.scalar(select(Principal).where(Principal.id == claimed.owner).with_for_update(nowait=True))
        requests.append(body)
        if mutate_at_round == len(requests):
            with Session(engine) as other:
                snapshot=ws.read(other,claimed.box,claimed.owner,claimed.workspace_id)
                ws.append(other,claimed.box,claimed.owner,claimed.workspace_id,expected=snapshot['revision'],
                    key='invented-correction-during-run',kind='evidence',source_label='Invented correction',
                    content='Invented correction recorded during the run.')
        if len(requests) == 1:
            return httpx.Response(200, json=response(calls=[read_call(handle,
                "read_saved_teammate_draft" if teammate else "read_selected_source")]))
        assert len(requests) == 2
        tool_result = json.loads(body["messages"][-1]["content"])
        assert body["messages"][-1]["role"] == "tool"
        assert tool_result["receipt"]["admission_id"] == claimed.admission_id
        assert tool_result["receipt"]["initiated_by_human_id"] == claimed.owner
        reads.append(tool_result)
        if teammate:
            assert tool_result["data"]["completion_kind"] == "saved_private_draft"
            assert tool_result["data"]["external_work_established"] is False
        else:
            assert hashlib.sha256(tool_result["data"]["content"].encode()).hexdigest() == handle["sha256"]
        output = {"answer": "Invented private preparation completed; clinician review is still required.",
            "source_ids": [source.entry_id for source in context.sources]}
        if claimed.envelope["baseline"]["flags"]["work_status"]:
            output["intent"] = "conversation"
        if claimed.envelope["baseline"]["flags"]["can_handoff"]:
            output["handoffs"] = [{"role": role, "intended_role": role,
                "brief": "Prepare an invented " + role + " draft preserving missing facts.",
                "requirements": REQUIREMENTS} for role in handoffs]
        return httpx.Response(200, json=response(output))
    return httpx.MockTransport(handle_http), requests, reads


def dispatch_and_settle(engine, claimed, transport):
    try:
        result = work.dispatch_claim(claimed, session_factory=lambda: Session(engine), transport=transport)
    except ModelCallFailure as error:
        result = error
    with Session(engine) as s:
        work.settle(s, claimed, result)
        row = s.get(ModelWorkAdmission, claimed.admission_id)
        assert row is not None
        return row.state, row.result_entry_id, result


@pytest.mark.parametrize("persona", ["nontechnical provider", "nontechnical nurse", "nontechnical physician assistant"])
@pytest.mark.parametrize("run", [1, 2])
def test_clinician_to_chief_to_two_recipients_then_chief_reads_the_saved_work(engine, operational, persona, run):
    case = encounter(engine)
    chief = reserve(engine, case, "I am a " + persona + ". Here is Scribe's transcript and summary. Prepare next steps.",
        "invented-chief-plan-" + str(run))
    transport, requests, reads = tool_http(engine, chief, handoffs=("visit_prep", "follow_up"))
    state, origin_id, result = dispatch_and_settle(engine, chief, transport)
    assert state == "completed" and origin_id and len(requests) == 2 and len(reads) == 1
    assert result.input_tokens == 200 and result.output_tokens == 40
    with Session(engine) as s:
        children = list(s.scalars(select(ModelWorkAdmission).where(
            ModelWorkAdmission.workspace_id == case[2], ModelWorkAdmission.kind == "private_handoff")))
        assert len(children) == 2
        claimed_children = [work.claim(s, case[0], case[1], child.id) for child in children]
    expected_agents = {reads[0]["receipt"]["actor_agent_id"]}
    for child in claimed_children:
        assert child is not None
        assert child.envelope["context"]["draft_only"] is True
        transport, child_requests, child_reads = tool_http(engine, child)
        child_state, draft_id, _ = dispatch_and_settle(engine, child, transport)
        assert child_state == "completed" and draft_id and len(child_requests) == 2 and len(child_reads) == 1
        expected_agents.add(child_reads[0]["receipt"]["actor_agent_id"])
    chief_review = reserve(engine, case, "Read the team's saved draft and tell me what still needs my review.",
        "invented-chief-review-" + str(run))
    assert len(chief_review.envelope["tool_selection"]["teammate_drafts"]) == 2
    transport, review_requests, review_reads = tool_http(engine, chief_review, teammate=True)
    assert dispatch_and_settle(engine, chief_review, transport)[0] == "completed"
    assert len(review_requests) == 2 and len(review_reads) == 1
    with Session(engine) as s:
        events = list(s.scalars(select(AuditEvent).where(AuditEvent.box_id == case[0],
            AuditEvent.event_type == "workspace.agent_tool_read")))
        assert len(events) == 4
        assert {event.actor_principal_id for event in events} == expected_agents and len(expected_agents) == 3
        for event in events:
            assert event.actor_principal_id != event.initiated_by_principal_id == case[1]
            assert event.approved_by_principal_id is None and event.outcome == "read"
            assert "content" not in event.detail and TRANSCRIPT not in json.dumps(event.detail)
        replies = list(s.scalars(select(WorkspaceReply).where(WorkspaceReply.workspace_id == case[2])))
        assert len(replies) == 4
        source_ids = {source["entry_id"] for source in chief.envelope["tool_selection"]["sources"]}
        assert all({citation["entry_id"] for citation in reply.citations} <= source_ids for reply in replies)
        assert all(attempt.status == "completed" for attempt in s.scalars(select(WorkspaceHandoffAttempt).where(
            WorkspaceHandoffAttempt.workspace_id == case[2])))
        assert len(list(s.scalars(select(WorkspaceHandoff).where(WorkspaceHandoff.workspace_id == case[2])))) == 2


@pytest.mark.parametrize("mutate_at_round", [1, 2])
def test_changed_scribe_evidence_withholds_tool_or_final_publication(engine, operational, mutate_at_round):
    case = encounter(engine)
    claimed = reserve(engine, case, "Prepare questions from this invented transcript.", "invented-changed-source")
    transport, requests, _ = tool_http(engine, claimed, mutate_at_round=mutate_at_round)
    state, result_entry, result = dispatch_and_settle(engine, claimed, transport)
    assert state == "failed" and result_entry is None and len(requests) == mutate_at_round
    if mutate_at_round == 1:
        assert isinstance(result, ModelCallFailure) and result.input_tokens == 100
    with Session(engine) as s:
        assert s.scalar(select(WorkspaceReply).where(WorkspaceReply.workspace_id == case[2])) is None
        events = list(s.scalars(select(AuditEvent).where(AuditEvent.box_id == case[0],
            AuditEvent.event_type == "workspace.agent_tool_read")))
        assert len(events) == mutate_at_round - 1


def test_two_workers_can_claim_and_execute_a_reserved_product_task_only_once(engine, operational):
    case = encounter(engine)
    box, owner, wid = case
    with Session(engine) as s:
        admission_id, _ = work.reserve_conversation(s, box, owner, wid, expected=3,
            team_revision=1, key="invented-concurrent", role="chief", content="Prepare the invented agenda.")
    barrier = Barrier(2)
    def claim_once(_):
        barrier.wait(timeout=10)
        with Session(engine) as s:
            return work.claim(s, box, owner, admission_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim_once, range(2)))
    actual = [claimed for claimed in claims if claimed is not None]
    assert len(actual) == 1
    transport, requests, _ = tool_http(engine, actual[0])
    assert dispatch_and_settle(engine, actual[0], transport)[0] == "completed" and len(requests) == 2
