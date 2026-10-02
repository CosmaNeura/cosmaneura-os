"""Actual PostgreSQL admission boundaries; only invented provider work."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_model_work_admission import case

from cosmas_os.adapters.gpt41 import _context
from cosmas_os.application import agent_tools as tools
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.models import ModelWorkAdmission, Principal, WorkspaceEntry


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(team.runtime_settings, "workspace_enabled", True)
    monkeypatch.setattr(team.runtime_settings, "workspace_agent_tools_enabled", True)
    monkeypatch.setattr(team.runtime_settings, "workspace_llm_backend", "azure_gpt41")
    monkeypatch.setattr(team.runtime_settings, "workspace_llm_api_key", SecretStr("invented-no-network"))


def admitted(engine):
    box, owner, wid, _ = case(engine)
    with Session(engine) as s:
        admission_id, _ = work.reserve_conversation(s, box, owner, wid, expected=1,
            team_revision=1, key="invented-tools-admission", role="chief", content="Prepare operational next steps.")
        claimed = work.claim(s, box, owner, admission_id)
        assert claimed is not None
        row = s.get(ModelWorkAdmission, admission_id)
        assert row is not None
        version, bot, settings = team.active_bot(s, box, owner, "chief", 1)
        envelope = row.prepared_envelope
        context = _context(envelope["context"])
        selection = tools.prepare_tool_selection(s, box=box, owner=owner,
            workspace_id=wid, agent_id=bot.agent_id, team_revision_id=version.id,
            context_revision=context.context_revision, settings=settings, context=context)
        assert envelope["contract"] == "cosmas-gpt41-prepared.v5" and envelope["tool_selection"] == selection
        return claimed


def test_actual_admitted_reader_returns_exact_source_and_keeps_human_distinct(engine, enabled):
    claimed = admitted(engine)
    with Session(engine) as s:
        reader = tools.AgentToolExecutor(s, claimed)
        result = reader.execute({"tool": "list_selected_sources"})
        source = result["data"]["sources"][0]
        selected = reader.execute({"tool": "read_selected_source", **{
            key: source[key] for key in ("entry_id", "revision", "sha256")
        }})
        assert tools._content_hash(selected["data"]["content"]) == source["sha256"]
        assert selected["receipt"]["actor_agent_id"] != selected["receipt"]["initiated_by_human_id"]
        row = s.get(ModelWorkAdmission, claimed.admission_id)
        assert row is not None and row.state == "running"


@pytest.mark.parametrize("mutation", ["dispatch", "owner", "envelope", "v4", "expired", "disabled-agent", "disabled-human"])
def test_wrong_or_retired_admission_fails_before_selected_content(engine, enabled, mutation, monkeypatch):
    if mutation == 'v4':
        box, owner, wid, _ = case(engine)
        with monkeypatch.context() as legacy:
            legacy.setattr(team.runtime_settings, 'workspace_agent_tools_enabled', False)
            with Session(engine) as s:
                admission, _ = work.reserve_conversation(s, box, owner, wid, expected=1,
                    team_revision=1, key='invented-legacy-admission', role='chief', content='Prepare the invented agenda.')
                claimed = work.claim(s, box, owner, admission)
                assert claimed and claimed.envelope['contract'] == 'cosmas-gpt41-prepared.v4'
        with Session(engine) as s, pytest.raises(tools.ws.WorkspaceError, match='agent_tool_admission_invalid'):
            tools.AgentToolExecutor(s, claimed).execute({'tool':'list_selected_sources'})
        return
    claimed = admitted(engine)
    with Session(engine) as s:
        row = s.get(ModelWorkAdmission, claimed.admission_id)
        assert row is not None
        test_clock: Callable[[], datetime] | None = None
        if mutation == "dispatch":
            claimed = replace(claimed, dispatch_id="invented-other-dispatch")
        elif mutation == "owner":
            claimed = replace(claimed, owner=row.agent_id)
        elif mutation == "envelope":
            value = deepcopy(claimed.envelope)
            value["tool_selection"]["sources"][0]["revision"] += 1
            claimed = replace(claimed, envelope=value)
        elif mutation == "expired":
            assert row.lease_ends_at is not None
            at = row.lease_ends_at + timedelta(seconds=1)
            def expired_clock():
                return at
            test_clock = expired_clock
        elif mutation == "disabled-agent":
            principal = s.get(Principal, row.agent_id)
            assert principal is not None
            principal.state = "disabled"
        else:
            principal = s.get(Principal, row.owner_id)
            assert principal is not None
            principal.state = "disabled"
        s.commit()
        with pytest.raises(tools.ws.WorkspaceError):
            tools.AgentToolExecutor(s, claimed, clock=test_clock).execute({"tool": "list_selected_sources"})


def test_new_unselected_source_and_mutated_selected_source_are_not_silently_read(engine, enabled):
    claimed = admitted(engine)
    source = claimed.envelope["tool_selection"]["sources"][0]
    with Session(engine) as s:
        original = s.get(WorkspaceEntry, source["entry_id"])
        assert original is not None
        snapshot=ws.read(s,claimed.box,claimed.owner,claimed.workspace_id)
        ws.append(s,claimed.box,claimed.owner,claimed.workspace_id,expected=snapshot['revision'],key='invented-new-source',
            kind='evidence',source_label='Invented correction',content='Invented source changed after the model was admitted.')
        with pytest.raises(tools.ws.WorkspaceError, match="source_changed"):
            tools.AgentToolExecutor(s, claimed).execute({"tool": "read_selected_source", **{
                key: source[key] for key in ("entry_id", "revision", "sha256")
            }})


def test_selection_tampering_even_with_new_envelope_hash_fails_closed(engine, enabled):
    claimed = admitted(engine)
    value = deepcopy(claimed.envelope)
    value["tool_selection"]["sources"][0]["sha256"] = "a" * 64
    with Session(engine) as s:
        row = s.get(ModelWorkAdmission, claimed.admission_id)
        assert row is not None
        row.prepared_envelope, row.envelope_sha256 = value, work.digest(value)
        with pytest.raises(DBAPIError, match='invalid model admission transition'):
            s.commit()
        s.rollback()
        altered = replace(claimed, envelope=value, envelope_sha256=work.digest(value))
        with pytest.raises(tools.ws.WorkspaceError, match="agent_tool_admission_invalid"):
            tools.AgentToolExecutor(s, altered).execute({"tool": "list_selected_sources"})


@pytest.mark.parametrize('phase',['before','during'])
def test_runtime_tool_pause_withholds_an_already_admitted_read(engine,enabled,monkeypatch,phase):
    claimed=admitted(engine)
    with Session(engine) as s:
        reader=tools.AgentToolExecutor(s,claimed)
        if phase=='before':
            monkeypatch.setattr(team.runtime_settings,'workspace_agent_tools_enabled',False)
        else:
            original=reader._guard
            def guard_then_pause():
                result=original()
                monkeypatch.setattr(team.runtime_settings,'workspace_agent_tools_enabled',False)
                return result
            monkeypatch.setattr(reader,'_guard',guard_then_pause)
        with pytest.raises(tools.ws.WorkspaceError,match='agent_tools_paused'):
            reader.execute({'tool':'list_selected_sources'})


def test_context_source_does_not_grant_unselected_operation_or_draft(engine, enabled):
    claimed = admitted(engine)
    with Session(engine) as s:
        reader = tools.AgentToolExecutor(s, claimed)
        with pytest.raises(tools.ws.WorkspaceError, match="agent_tool_operation_unavailable"):
            reader.execute({"tool": "read_current_operation_status", "kind": "follow_up",
                "record_id": "unselected-work", "commitment": "a" * 64})
        with pytest.raises(tools.ws.WorkspaceError, match="agent_tool_draft_unavailable"):
            reader.execute({"tool": "read_saved_teammate_draft", "entry_id": "unselected-draft",
                "revision": 1, "sha256": "a" * 64})
