"""Actual PostgreSQL model ledger/executor with invented full-source evidence only."""

import json
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration.test_model_work_admission import case

from cosmas_os.adapters.gpt41 import _context
from cosmas_os.adapters.gpt41_tools_v6 import GPT41CompactToolsConnector, validate_prepared
from cosmas_os.application import agent_tools as tools
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.models import ModelWorkAdmission, WorkspaceReply
from cosmas_os.ports.bot_capabilities import BotReply, ModelCallFailure


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(team.runtime_settings, "workspace_enabled", True)
    monkeypatch.setattr(team.runtime_settings, "workspace_agent_tools_enabled", True)
    monkeypatch.setattr(team.runtime_settings, "workspace_llm_backend", "azure_gpt41")
    monkeypatch.setattr(team.runtime_settings, "workspace_llm_api_key", SecretStr("invented-no-network"))


@pytest.fixture
def full_case(engine, enabled) -> Iterator[tuple[str, str, str]]:
    box, owner, wid, _ = case(engine)
    yield box, owner, wid
    # Existing helpers commit. End only this fixture's owned admissions through
    # the normal ledger; never leave paid/reserved work in a global worker queue.
    with Session(engine) as s:
        rows = list(s.scalars(select(ModelWorkAdmission).where(
            ModelWorkAdmission.box_id == box, ModelWorkAdmission.owner_id == owner,
            ModelWorkAdmission.workspace_id == wid, ModelWorkAdmission.state.in_(("reserved", "running")))))
        for row in rows:
            if row.state == "reserved":
                claimed = work.claim(s, box, owner, row.id)
            else:
                assert row.dispatch_id is not None
                claimed = work.ModelClaim(row.id, box, owner, wid, row.dispatch_id,
                    row.envelope_sha256, row.prepared_envelope)
            if claimed is not None:
                work.settle(s, claimed, ModelCallFailure(dispatch="not_dispatched"))
        assert not list(s.scalars(select(ModelWorkAdmission.id).where(
            ModelWorkAdmission.workspace_id == wid, ModelWorkAdmission.state.in_(("reserved", "running")))))


def text(length: int, number: int = 0) -> str:
    prefix, suffix = f"Invented full source {number}. ", f" INVENTED-TAIL-{number}"
    return prefix + "x" * (length - len(prefix) - len(suffix)) + suffix


def append_sources(engine: Any, scope: tuple[str, str, str], lengths: tuple[int, ...],
    *, kind: str = "evidence") -> list[str]:
    box, owner, wid = scope
    ids = []
    with Session(engine) as s:
        for number, length in enumerate(lengths):
            snapshot = ws.read(s, box, owner, wid)
            result = ws.append(s, box, owner, wid, expected=snapshot["revision"],
                key=f"invented-full-{number}", kind=kind, content=text(length, number),
                source_label=f"Invented full evidence {number}" if kind == "evidence" else None)
            ids.append(result["entry_id"])
    return ids


def reserve(engine: Any, scope: tuple[str, str, str], *, role: str = "chief") -> str:
    box, owner, wid = scope
    with Session(engine) as s:
        snapshot = ws.read(s, box, owner, wid)
        aid, _ = work.reserve_conversation(s, box, owner, wid, expected=snapshot["revision"],
            team_revision=1, key="invented-full-admission", role=role,
            content="Review the invented evidence; no external action.")
        assert aid is not None
        return aid


def claim(engine: Any, scope: tuple[str, str, str], admission: str) -> work.ModelClaim:
    box, owner, _ = scope
    with Session(engine) as s:
        claimed = work.claim(s, box, owner, admission)
        assert claimed is not None
        assert claimed.envelope["contract"] == "cosmas-gpt41-prepared.v6"
        # Rehydrate actual JSONB persisted by reservation in another Session.
        validate_prepared(claimed.envelope)
        return claimed


def no_reply(s: Session, wid: str) -> bool:
    return s.scalar(select(WorkspaceReply).where(WorkspaceReply.workspace_id == wid)) is None


@pytest.mark.parametrize("lengths", [(6000,), (20000,)])
def test_actual_reservation_read_and_settlement_keep_full_sources_independent_of_delivery(engine, full_case, lengths):
    ids = append_sources(engine, full_case, lengths)
    aid = reserve(engine, full_case)
    claimed = claim(engine, full_case, aid)
    original = _context(claimed.envelope["context"])
    assert sum(len(source.content) for source in original.sources) >= sum(lengths)
    records = {item["entry_id"]: item for item in claimed.envelope["source_delivery"]}
    for entry_id, length in zip(ids, lengths, strict=True):
        selected = next(source for source in original.sources if source.entry_id == entry_id)
        assert len(selected.content) == length
        assert records[entry_id]["sha256"] == tools._content_hash(selected.content)
        assert records[entry_id]["excerpt_chars"] <= 1000
    with Session(engine) as s:
        row = s.get(ModelWorkAdmission, aid)
        assert row is not None and row.source_sha256 == work.source_digest(original)
        reader = tools.AgentToolExecutor(s, claimed)
        listing = reader.execute({"tool": "list_selected_sources"})
        assert {item["entry_id"] for item in listing["data"]["sources"]} == {source.entry_id for source in original.sources}
        for entry_id in ids:
            handle = next(item for item in listing["data"]["sources"] if item["entry_id"] == entry_id)
            observed = reader.execute({"tool": "read_selected_source", **{
                key: handle[key] for key in ("entry_id", "revision", "sha256")}})
            source = next(source for source in original.sources if source.entry_id == entry_id)
            assert observed["data"]["content"] == source.content
            assert observed["receipt"]["envelope_sha256"] == claimed.envelope_sha256
            assert observed["receipt"]["actor_agent_id"] != observed["receipt"]["initiated_by_human_id"]
        work.settle(s, claimed, BotReply("Invented reviewable result; no external work.", (), "azure_gpt41", 10, 5))
        row = s.get(ModelWorkAdmission, aid)
        assert row is not None and row.state == "completed"
        assert not no_reply(s, claimed.workspace_id)


def test_chief_delegation_context_above_thirty_thousand_is_refused_before_any_admission(engine, full_case):
    append_sources(engine, full_case, (5000,) * 7)
    with pytest.raises(ws.WorkspaceError, match="handoff_source_context_too_large"):
        reserve(engine, full_case)
    with Session(engine) as s:
        assert s.scalar(select(ModelWorkAdmission.id).where(
            ModelWorkAdmission.workspace_id == full_case[2])) is None
        assert no_reply(s, full_case[2])


@pytest.mark.parametrize("boundary", ["claim", "read", "settle"])
def test_same_first_five_thousand_chars_new_tail_supersedes_actual_full_admission(engine, full_case, boundary):
    ids = append_sources(engine, full_case, (6000,), kind="scratchpad")
    aid = reserve(engine, full_case)
    claimed = None if boundary == "claim" else claim(engine, full_case, aid)
    box, owner, wid = full_case
    with Session(engine) as s:
        row = s.get(ModelWorkAdmission, aid)
        assert row is not None
        original = next(source for source in _context(row.prepared_envelope["context"]).sources if source.entry_id == ids[0])
        changed = original.content[:-1] + "z"
        assert changed[:5000] == original.content[:5000] and tools._content_hash(changed) != tools._content_hash(original.content)
        snapshot = ws.read(s, box, owner, wid)
        ws.append(s, box, owner, wid, expected=snapshot["revision"], key="invented-new-tail",
            kind="scratchpad", content=changed)
        if boundary == "claim":
            assert work.claim(s, box, owner, aid) is None
        elif boundary == "read":
            assert claimed is not None
            with pytest.raises(ws.WorkspaceError, match="source_changed"):
                tools.AgentToolExecutor(s, claimed).execute({"tool": "read_selected_source",
                    "entry_id": original.entry_id, "revision": original.revision,
                    "sha256": tools._content_hash(original.content)})
            work.settle(s, claimed, BotReply("Invented withheld result.", (), "azure_gpt41", 10, 5))
        else:
            assert claimed is not None
            work.settle(s, claimed, BotReply("Invented withheld result.", (), "azure_gpt41", 10, 5))
        row = s.get(ModelWorkAdmission, aid)
        assert row is not None and row.state == "failed" and row.reason == "source_changed"
        assert no_reply(s, wid)


@pytest.mark.parametrize("source_region", ["tail", "omitted-source"])
def test_full_digest_refuses_projection_change_even_with_identical_decoder_source_windows(engine, full_case, monkeypatch, source_region):
    # The only injected seam is the current authorized source projection. The
    # row, saved JSON, claim, executor and settlement are real product services.
    append_sources(engine, full_case, (6000,) if source_region == "tail" else (5000,) * 7)
    aid = reserve(engine, full_case, role="visit_prep" if source_region == "omitted-source" else "chief")
    claimed = claim(engine, full_case, aid)
    frozen = _context(claimed.envelope["context"])
    eligible = {source["source_id"] for source in claimed.envelope["baseline"]["sources"]}
    target = next(source for source in frozen.sources
        if len(source.content) == 6000) if source_region == "tail" else next(
            source for source in frozen.sources if source.entry_id not in eligible and len(source.content) == 5000)
    current = work._context_for
    def changed_projection(*args, **kwargs):
        context = current(*args, **kwargs)
        return replace(context, sources=tuple(replace(source, content=source.content[:-1] + "z")
            if source.entry_id == target.entry_id else source for source in context.sources))
    monkeypatch.setattr(work, "_context_for", changed_projection)
    projected = replace(frozen, sources=tuple(replace(source, content=source.content[:-1] + "z")
        if source.entry_id == target.entry_id else source for source in frozen.sources))
    assert work.source_digest(projected) != work.source_digest(frozen)
    assert target.entry_id not in eligible or target.content[:5000] == next(
        source for source in projected.sources if source.entry_id == target.entry_id).content[:5000]
    with Session(engine) as s:
        with pytest.raises(ws.WorkspaceError, match="source_changed"):
            tools.AgentToolExecutor(s, claimed).execute({"tool": "list_selected_sources"})
        work.settle(s, claimed, BotReply("Invented tail-derived output must stay private.", (), "azure_gpt41", 10, 5))
        row = s.get(ModelWorkAdmission, aid)
        assert row is not None and row.state == "failed" and row.reason == "source_changed"
        assert no_reply(s, claimed.workspace_id)


def test_actual_http_compact_read_uses_persisted_executor_receipt_then_settles_once(engine, full_case):
    ids = append_sources(engine, full_case, (6000,))
    aid = reserve(engine, full_case)
    claimed = claim(engine, full_case, aid)
    handle = next(item for item in claimed.envelope["tool_selection"]["sources"] if item["entry_id"] == ids[0])
    request = {key: handle[key] for key in ("entry_id", "revision", "sha256")}
    responses = iter([
        {"model": "gpt-4.1", "usage": {"prompt_tokens": 100, "completion_tokens": 20}, "choices": [
            {"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "invented_read", "type": "function", "function": {
                    "name": "read_selected_source", "arguments": json.dumps(request)}}]}}]},
        {"model": "gpt-4.1", "usage": {"prompt_tokens": 100, "completion_tokens": 20}, "choices": [
            {"finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps({
                "answer": "Invented full-source review for human acceptance.", "source_ids": [ids[0]], "handoffs": []})}}]},
    ])
    bodies = []
    def fake_http(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=next(responses))
    with Session(engine) as s:
        result = GPT41CompactToolsConnector(lambda: "invented-key", transport=httpx.MockTransport(fake_http)).review_prepared(
            claimed.envelope, execute=tools.AgentToolExecutor(s, claimed).execute)
        assert len(bodies) == 2 and result.input_tokens == 200
        after = json.loads(bodies[1]["messages"][1]["content"])
        assert ids[0] not in {source["source_id"] for source in after["sources"]}
        returned = json.loads(bodies[1]["messages"][-1]["content"])
        assert returned["receipt"]["admission_id"] == aid
        assert len(returned["data"]["content"]) == 6000
        work.settle(s, claimed, result)
        work.settle(s, claimed, result)
        assert len(list(s.scalars(select(WorkspaceReply).where(WorkspaceReply.workspace_id == claimed.workspace_id)))) == 1
        row = s.get(ModelWorkAdmission, aid)
        assert row is not None and row.state == "completed"
