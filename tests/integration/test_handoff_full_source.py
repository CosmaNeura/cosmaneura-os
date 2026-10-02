"""Installed ledger, exact source tools, edit and human acceptance; fake HTTP only."""
import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy
from inspect import unwrap

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.helpers.task_brief import REQUIREMENTS
from tests.integration.test_agent_tools_full_source import append_sources, text
from tests.integration.test_agent_tools_full_source import enabled as original_enabled
from tests.integration.test_agent_tools_full_source import full_case as original_full_case

from cosmas_os.adapters.gpt41 import _context
from cosmas_os.application import handoff_review, handoff_revision
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.models import ModelWorkAdmission, WorkspaceReply
from cosmas_os.ports.bot_capabilities import ModelCallFailure


@pytest.fixture
def enabled(monkeypatch):
    return unwrap(original_enabled)(monkeypatch)


@pytest.fixture
def full_case(engine, enabled):
    yield from unwrap(original_full_case)(engine, enabled)


@contextmanager
def factory(engine):
    with Session(engine) as s:
        yield s


def dispatch(engine, claimed, calls):
    context = claimed.envelope["context"]
    handle = claimed.envelope["tool_selection"]["sources"][-1]
    source = next(s for s in context["sources"] if s["entry_id"] == handle["entry_id"])
    def respond(request):
        body = json.loads(request.content)
        calls.append({"role": context["role"], "admission_id": claimed.admission_id,
            "request": body})
        if not any(message["role"] == "tool" for message in body["messages"]):
            return httpx.Response(200, json={"model": "gpt-4.1",
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                "choices": [{"finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": None, "tool_calls": [{"id": "exact_source",
                        "type": "function", "function": {"name": "read_selected_source",
                            "arguments": json.dumps({k: handle[k] for k in ("entry_id", "revision", "sha256")})}}]}}]})
        if context["role"] == "chief":
            content = {"answer": "Prepare private drafts; DOB and trial eligibility unknown.",
                "source_ids": [handle["entry_id"]], "handoffs": [{"role": role,
                    "intended_role": role, "brief": "Preserve unknown DOB and trial eligibility.",
                    "requirements": REQUIREMENTS} for role in ("scribe", "visit_prep", "follow_up")]}
        elif context["role"] == "scribe":
            content = {"excerpts": [{"source_id": handle["entry_id"], "quote": source["content"][-40:]}],
                "needs_from_clinician": ["DOB and trial eligibility unknown; confirm with provider."]}
            if "Identify the responsible person" in context["question"]:
                content["needs_from_clinician"].append("Who is the responsible person for confirming these facts?")
        else:
            content = {"answer": "Private draft; DOB and trial eligibility unknown. No appointment booked or message sent.",
                "source_ids": [handle["entry_id"]]}
        if "intent" in body["response_format"]["json_schema"]["schema"]["properties"]:
            content["intent"] = "conversation"
        return httpx.Response(200, json={"model": "gpt-4.1",
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(content)}}]})
    return work.dispatch_claim(claimed, session_factory=lambda: factory(engine),
        transport=httpx.MockTransport(respond))


def reserve_chief(engine, scope, *, key="invented-full-chief"):
    box, owner, wid = scope
    with Session(engine) as s:
        snapshot = ws.read(s, box, owner, wid)
        aid, _ = work.reserve_conversation(s, box, owner, wid,
            expected=snapshot["revision"], team_revision=1, key=key, role="chief",
            content="Ask Scribe, Visit Prep and Follow-up for independent private drafts. Preserve unknown DOB and trial eligibility.")
        assert aid is not None
        claimed = work.claim(s, box, owner, aid)
        assert claimed is not None
        return claimed


@pytest.mark.parametrize("length", [12000, 20000])
def test_long_original_source_reaches_three_specialists_exact_edit_and_acceptance(engine, full_case, length):
    ids = append_sources(engine, full_case, (length,))
    box, owner, wid = full_case
    with Session(engine) as s:
        note_before = ws.read(s, box, owner, wid)["note"]
    calls = []
    chief = reserve_chief(engine, full_case)
    result = dispatch(engine, chief, calls)
    assert len(result.handoffs) == 3
    with Session(engine) as s:
        work.settle(s, chief, result)
        queued = ws.read(s, box, owner, wid)["handoffs"]
        assert len(queued) == 3 and all(h["task_brief"]["version"] == 2 for h in queued)
    for _ in range(3):
        assert work.process_next(lambda: factory(engine),
            dispatch=lambda claimed: dispatch(engine, claimed, calls))
    with Session(engine) as s:
        snapshot = ws.read(s, box, owner, wid)
        assert snapshot["note"] == note_before
        assert all(h["status"] == "completed" and h["completion_evidence"] for h in snapshot["handoffs"])
        for row in s.scalars(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == wid)):
            assert row.state == "completed"
            frozen = _context(row.prepared_envelope["context"])
            source = next(p for p in frozen.sources if p.entry_id == ids[0])
            assert source.content == text(length) and row.source_sha256 == work.source_digest(frozen)
            if row.kind == "private_handoff":
                assert row.request_body["task_brief"]["version"] == 2
                assert row.request_body["task_brief"]["source_versions"][-1]["sha256"] == hashlib.sha256(text(length).encode()).hexdigest()
        handoff = next(h for h in snapshot["handoffs"] if h["recipient_role"] == "scribe")
        entry = next(e for e in snapshot["entries"] if e["id"] == handoff["result_entry_id"])
        assert "INVENTED-TAIL-0" in entry["reply"]["content"]
        reviewed = handoff_review.review(s, box, owner, wid, handoff["id"], expected=snapshot["revision"],
            key="invented-full-edit-request", attempt_id=handoff["attempt_id"],
            result_entry_id=handoff["result_entry_id"], result_sha256=handoff["result_sha256"],
            decision="changes_requested", feedback="Identify the responsible person for confirming missing facts.")
        saved = next(h for h in reviewed["workspace"]["handoffs"] if h["id"] == handoff["id"])
        revision = handoff_revision.reserve(s, box, owner, wid, handoff["id"],
            expected=reviewed["workspace"]["revision"], key="invented-full-revised-task", review_id=saved["review"]["id"])
        revised_id = revision["revision_handoff_id"]
    assert work.process_next(lambda: factory(engine),
        dispatch=lambda claimed: dispatch(engine, claimed, calls))
    with Session(engine) as s:
        snapshot = ws.read(s, box, owner, wid)
        revised = next(h for h in snapshot["handoffs"] if h["id"] == revised_id)
        assert revised["status"] == "completed" and revised["task_brief"]["version"] == 2
        assert revised["task_brief"]["source_versions"] == handoff["task_brief"]["source_versions"]
        entry = next(e for e in snapshot["entries"] if e["id"] == revised["result_entry_id"])
        assert "responsible person" in entry["reply"]["content"]
        assert revised["result_sha256"] != handoff["result_sha256"]
        accepted = handoff_review.review(s, box, owner, wid, revised_id, expected=snapshot["revision"],
            key="invented-full-exact-accept", attempt_id=revised["attempt_id"],
            result_entry_id=revised["result_entry_id"], result_sha256=revised["result_sha256"],
            decision="accepted", feedback="")
        final = next(h for h in accepted["workspace"]["handoffs"] if h["id"] == revised_id)
        assert final["review"]["decision"] == "accepted" and final["review"]["result_sha256"] == revised["result_sha256"]
        assert accepted["workspace"]["note"] == note_before
    assert len(calls) == 10  # Chief + three specialists + one revised draft, two real adapter rounds each.


@pytest.mark.parametrize("lengths,character", [((5000,) * 7, "x"), ((12000,), "界")])
def test_unsupported_full_delegation_source_refused_before_paid_admission(engine, full_case, lengths, character):
    if character == "x":
        append_sources(engine, full_case, lengths)
    else:
        box, owner, wid = full_case
        with Session(engine) as s:
            snapshot = ws.read(s, box, owner, wid)
            ws.append(s, box, owner, wid, expected=snapshot["revision"], key="invented-full-unicode",
                kind="evidence", content=character * 20000, source_label="Invented complete source")
    with pytest.raises(ws.WorkspaceError, match="handoff_source_context_too_large"):
        reserve_chief(engine, full_case)
    with Session(engine) as s:
        assert s.scalar(select(ModelWorkAdmission.id).where(
            ModelWorkAdmission.workspace_id == full_case[2])) is None


def test_nonchief_readonly_review_retains_existing_large_context_behavior(engine, full_case):
    append_sources(engine, full_case, (5000,) * 7)
    box, owner, wid = full_case
    with Session(engine) as s:
        snapshot = ws.read(s, box, owner, wid)
        aid, _ = work.reserve_conversation(s, box, owner, wid, expected=snapshot["revision"],
            team_revision=1, key="invented-large-readonly", role="visit_prep", content="Review supplied evidence.")
        assert aid is not None and work.claim(s, box, owner, aid) is not None


def test_v2_child_is_withheld_after_tools_disabled_without_any_model_retry(engine, full_case, monkeypatch):
    append_sources(engine, full_case, (12000,))
    calls, chief = [], reserve_chief(engine, full_case)
    result = dispatch(engine, chief, calls)
    box, owner, wid = full_case
    with Session(engine) as s:
        work.settle(s, chief, result)
        child = s.scalar(select(ModelWorkAdmission).where(
            ModelWorkAdmission.workspace_id == wid, ModelWorkAdmission.kind == "private_handoff"))
        assert child is not None and child.request_body["task_brief"]["version"] == 2
        child_id = child.id
    monkeypatch.setattr(work.team.runtime_settings, "workspace_agent_tools_enabled", False)
    with Session(engine) as s:
        assert work.claim(s, box, owner, child_id) is None
        row = s.get(ModelWorkAdmission, child_id)
        assert row is not None and row.state == "failed" and row.reason == "authority_changed"
    assert len(calls) == 2


def test_recipient_only_oversized_sources_are_refused_before_chief_paid_admission(engine, full_case):
    append_sources(engine, full_case, (5000,) * 7)
    box, owner, wid = full_case
    with Session(engine) as s:
        configuration = team.default_configuration()
        next(bot for bot in configuration["bots"] if bot["role"] == "chief")["include_evidence"] = False
        saved = team.save(s, box, owner, expected=1, key="invented-chief-excludes-evidence",
            configuration=configuration)
        snapshot = ws.read(s, box, owner, wid)
        with pytest.raises(ws.WorkspaceError, match="handoff_source_context_too_large"):
            work.reserve_conversation(s, box, owner, wid, expected=snapshot["revision"],
                team_revision=saved["revision"], key="invented-recipient-too-large", role="chief",
                content="Ask Scribe for a private draft.")
        assert s.scalar(select(ModelWorkAdmission.id).where(ModelWorkAdmission.workspace_id == wid)) is None


def failed_revised_task(engine, scope, failure_dispatch):
    append_sources(engine, scope, (12000,))
    calls, chief = [], reserve_chief(engine, scope)
    result = dispatch(engine, chief, calls)
    box, owner, wid = scope
    with Session(engine) as s:
        work.settle(s, chief, result)
    for _ in range(3):
        assert work.process_next(lambda: factory(engine), dispatch=lambda c: dispatch(engine, c, calls))
    with Session(engine) as s:
        snapshot = ws.read(s, box, owner, wid)
        parent = next(h for h in snapshot["handoffs"] if h["recipient_role"] == "scribe")
        reviewed = handoff_review.review(s, box, owner, wid, parent["id"],
            expected=snapshot["revision"], key="invented-retry-feedback", attempt_id=parent["attempt_id"],
            result_entry_id=parent["result_entry_id"], result_sha256=parent["result_sha256"],
            decision="changes_requested", feedback="Identify the responsible person; DOB remains unknown.")
        receipt = next(h for h in reviewed["workspace"]["handoffs"] if h["id"] == parent["id"])["review"]
        revised = handoff_revision.reserve(s, box, owner, wid, parent["id"],
            expected=reviewed["workspace"]["revision"], key="invented-retry-revision", review_id=receipt["id"])
        revision_id = revised["revision_handoff_id"]
        row = s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == wid,
            ModelWorkAdmission.state == "reserved"))
        assert row is not None
        command, question = deepcopy(row.request_body), row.prepared_envelope["context"]["question"]
        prior_reply = s.get(WorkspaceReply, parent["result_entry_id"])
        assert prior_reply is not None
        prior_content = prior_reply.content
        assert command["revision_request"]["result_sha256"] == parent["result_sha256"]
        marker = "\n\nHuman-requested revision of the prior private draft\n"
        assert marker in question
        quoted, _ = json.JSONDecoder().raw_decode(question.split(marker, 1)[1])
        assert quoted == {"review_id": receipt["id"], "feedback": receipt["feedback"],
            "prior_private_draft": prior_content}
        claimed = work.claim(s, box, owner, row.id)
        assert claimed is not None
        work.settle(s, claimed, ModelCallFailure(dispatch=failure_dispatch))
        saved = next(h for h in ws.read(s, box, owner, wid)["handoffs"] if h["id"] == revision_id)
        assert saved["status"] == ("interrupted" if failure_dispatch == "started_unconfirmed" else "failed")
        return revision_id, saved["attempt_id"], command, question, calls


@pytest.mark.parametrize("failure_dispatch", ["not_dispatched", "started_unconfirmed"])
def test_v2_revised_retry_preserves_exact_feedback_prior_draft_and_source_versions(engine, full_case, failure_dispatch):
    revision_id, previous_attempt, original, question, calls = failed_revised_task(engine, full_case, failure_dispatch)
    box, owner, wid = full_case
    before = len(calls)
    with Session(engine) as s:
        snapshot = ws.read(s, box, owner, wid)
        retry = work.reserve_retry(s, box, owner, wid, revision_id, expected=snapshot["revision"],
            previous_attempt=previous_attempt, key="invented-exact-revised-retry")
        assert retry["outcome"] == "recorded"
        row = s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == wid,
            ModelWorkAdmission.state == "reserved"))
        assert row is not None and row.prepared_envelope["contract"] == "cosmas-gpt41-prepared.v6"
        assert row.request_body["task_brief"] == original["task_brief"]
        assert row.request_body["task_brief"]["version"] == 2
        assert row.request_body["revision_request"] == original["revision_request"]
        assert row.prepared_envelope["context"]["question"] == question
        frozen = _context(row.prepared_envelope["context"])
        assert row.source_sha256 == work.source_digest(frozen)
        retry_id = row.id
    assert len(calls) == before  # Retrying reserves once; no automatic provider/model replay.
    assert work.process_next(lambda: factory(engine), dispatch=lambda c: dispatch(engine, c, calls))
    with Session(engine) as s:
        row = s.get(ModelWorkAdmission, retry_id)
        assert row is not None and row.state == "completed"
        saved = next(h for h in ws.read(s, box, owner, wid)["handoffs"] if h["id"] == revision_id)
        assert saved["status"] == "completed" and saved["attempt_count"] == 2
        reply = s.get(WorkspaceReply, saved["result_entry_id"])
        assert reply is not None and "responsible person" in reply.content


@pytest.mark.parametrize("drift", ["current_source", "forged_prior_review"])
def test_v2_revised_retry_refuses_changed_sources_or_prior_review_before_new_admission(engine, full_case, monkeypatch, drift):
    revision_id, previous_attempt, _, _, calls = failed_revised_task(engine, full_case, "not_dispatched")
    box, owner, wid = full_case
    before = len(calls)
    with Session(engine) as s:
        snapshot = ws.read(s, box, owner, wid)
        if drift == "current_source":
            ws.append(s, box, owner, wid, expected=snapshot["revision"], key="invented-retry-new-source",
                kind="scratchpad", content="Invented new source: DOB remains unknown.")
            snapshot = ws.read(s, box, owner, wid)
        else:
            original_review_for = handoff_review.review_for
            def changed_projection(*args, **kwargs):
                receipt = original_review_for(*args, **kwargs)
                if receipt is None:
                    return None
                return {**receipt, "feedback": "Forged feedback must not enter retry"}
            monkeypatch.setattr(handoff_review, "review_for", changed_projection)
        with pytest.raises(ws.WorkspaceError, match="source_changed|handoff_revision_stale"):
            work.reserve_retry(s, box, owner, wid, revision_id, expected=snapshot["revision"],
                previous_attempt=previous_attempt, key="invented-refused-revised-retry")
        s.rollback()
        assert not list(s.scalars(select(ModelWorkAdmission.id).where(
            ModelWorkAdmission.workspace_id == wid, ModelWorkAdmission.state == "reserved")))
    assert len(calls) == before
