"""Closed product tool requests and receipts; invented sources, no model/network."""

from copy import deepcopy
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from cosmas_os.application import agent_tools as tools
from cosmas_os.ports.agent_tools import (
    REQUEST_ADAPTER,
    SourceHandle,
    ToolSelection,
    tool_definitions,
)
from cosmas_os.ports.bot_capabilities import BotContext, SourcePassage

SOURCE = SourcePassage("scribe:invented-encounter", 3, "Invented Scribe transcript", "evidence",
    "Invented patient discussed questions for the visit.")


def context():
    return BotContext("invented-workspace", 4, "chief", "Prepare next steps", "concise", (SOURCE,), ())


def selection():
    return ToolSelection.model_validate(tools._selection([
        SourceHandle(entry_id=SOURCE.entry_id, revision=SOURCE.revision, sha256=tools._content_hash(SOURCE.content),
            label=SOURCE.label, kind=SOURCE.kind).model_dump(),
    ], [], []))


@pytest.mark.parametrize("value", [
    {"tool": "send_email"}, {"tool": "read_selected_source", "url": "https://invented.invalid"},
    {"tool": "list_selected_sources", "owner_id": "invented-human"},
    {"tool": "read_selected_source", "entry_id": SOURCE.entry_id, "revision": True, "sha256": "a" * 64},
    {"tool": "read_selected_source", "entry_id": SOURCE.entry_id, "revision": 3, "sha256": "bad"},
    {"tool": "read_current_operation_status", "kind": "approve", "record_id": "invented-work", "commitment": "a" * 64},
])
def test_no_arbitrary_endpoint_identity_action_or_ambiguous_revision(value):
    with pytest.raises(ValidationError):
        REQUEST_ADAPTER.validate_python(value)


def test_tool_schemas_have_closed_arguments_without_identity_or_endpoints():
    definitions = tool_definitions()
    assert len(definitions) == 4
    for definition in definitions:
        schema = definition["parameters"]
        assert schema["additionalProperties"] is False
        assert "tool" not in schema["properties"]
        assert not {"owner", "owner_id", "agent_id", "url", "endpoint", "approve", "send"} & set(schema["properties"])


@pytest.fixture
def executor(monkeypatch):
    reader = tools.AgentToolExecutor(cast(Session, None), cast(tools.work.ModelClaim, None))
    row = SimpleNamespace(id="invented-admission", dispatch_id="invented-dispatch", workspace_id="invented-workspace",
        agent_id="invented-agent", owner_id="invented-human", envelope_sha256="b" * 64)
    guards = []
    monkeypatch.setattr(reader, "_guard", lambda: (guards.append(1) or row, context(), selection(), {"role": "chief"}))
    return reader, guards


def test_exact_source_read_is_attributed_to_distinct_agent_and_human(executor):
    reader, guards = executor
    request = {"tool": "read_selected_source", "entry_id": SOURCE.entry_id, "revision": SOURCE.revision,
        "sha256": tools._content_hash(SOURCE.content)}
    result = reader.execute(request)
    assert result["data"]["content"] == SOURCE.content and len(guards) == 2
    receipt = result["receipt"]
    assert receipt["actor_agent_id"] == "invented-agent" and receipt["initiated_by_human_id"] == "invented-human"
    assert receipt["request_sha256"] == tools.work.digest(request)
    assert receipt["result_sha256"] == tools.work.digest(result["data"])
    commitment = receipt.pop("sha256")
    assert commitment == tools.work.digest(receipt)


def test_listing_returns_handles_without_source_contents(executor):
    reader, _ = executor
    result = reader.execute({"tool": "list_selected_sources"})
    assert result["data"]["sources"][0]["sha256"] == tools._content_hash(SOURCE.content)
    assert SOURCE.content not in repr(result) and "content" not in result["data"]["sources"][0]


@pytest.mark.parametrize("mutation", [
    {"entry_id": "unselected-source"}, {"revision": 4}, {"sha256": "c" * 64},
])
def test_read_requires_exact_admitted_handle(executor, mutation):
    reader, _ = executor
    request = {"tool": "read_selected_source", "entry_id": SOURCE.entry_id, "revision": 3,
        "sha256": tools._content_hash(SOURCE.content), **mutation}
    with pytest.raises(tools.ws.WorkspaceError, match="agent_tool_source_unavailable"):
        reader.execute(request)


def test_revalidation_failure_withholds_content(executor, monkeypatch):
    reader, _ = executor
    guard = reader._guard
    count = 0
    def revoke():
        nonlocal count
        count += 1
        if count == 2:
            raise tools.ws.WorkspaceError("authority_changed", 403)
        return guard()
    monkeypatch.setattr(reader, "_guard", revoke)
    with pytest.raises(tools.ws.WorkspaceError, match="authority_changed"):
        reader.execute({"tool": "read_selected_source", "entry_id": SOURCE.entry_id, "revision": 3,
            "sha256": tools._content_hash(SOURCE.content)})


def test_unselected_draft_and_operation_are_rejected_before_any_read(executor, monkeypatch):
    reader, _ = executor
    monkeypatch.setattr(tools, "_draft_rows", lambda *a, **k: pytest.fail("unselected draft read"))
    monkeypatch.setattr(tools.operations, "read", lambda *a, **k: pytest.fail("unselected operation read"))
    with pytest.raises(tools.ws.WorkspaceError, match="agent_tool_draft_unavailable"):
        reader.execute({"tool": "read_saved_teammate_draft", "entry_id": "unselected-draft", "revision": 1, "sha256": "c" * 64})
    with pytest.raises(tools.ws.WorkspaceError, match="agent_tool_operation_unavailable"):
        reader.execute({"tool": "read_current_operation_status", "kind": "follow_up", "record_id": "unselected-work", "commitment": "c" * 64})


def test_mutation_request_is_rejected_before_admission_queries(executor):
    reader, guards = executor
    with pytest.raises(tools.ws.WorkspaceError, match="agent_tool_request_invalid"):
        reader.execute({"tool": "send_email", "body": "Invented draft"})
    assert guards == []


def test_selection_hash_covers_exact_metadata():
    value = selection().model_dump()
    commitment = value.pop("sha256")
    assert commitment == tools.work.digest(value)
    changed = deepcopy(value)
    changed["sources"][0]["revision"] += 1
    assert tools.work.digest(changed) != commitment


def test_selected_draft_remains_attributed_and_never_establishes_external_work(executor, monkeypatch):
    reader, _ = executor
    row, ctx, _, settings = reader._guard()
    row.box_id, row.context_revision, row.team_revision_id = "invented-box", 4, "invented-team"
    draft = {"entry_id": "invented-draft", "revision": 2, "sha256": tools._content_hash("Invented teammate draft"),
        "agent_id": "invented-teammate", "role": "follow_up", "label": "Follow-up"}
    selected = ToolSelection.model_validate(tools._selection([], [draft], []))
    monkeypatch.setattr(reader, "_guard", lambda: (row, ctx, selected, settings))
    monkeypatch.setattr(tools, "_draft_rows", lambda *a, **k: [(SimpleNamespace(id=draft["entry_id"], revision=2),
        SimpleNamespace(content="Invented teammate draft", agent_id=draft["agent_id"], role=draft["role"]))])
    result = reader.execute({"tool": "read_saved_teammate_draft", **{
        key: draft[key] for key in ("entry_id", "revision", "sha256")
    }})
    assert result["data"]["agent_id"] == "invented-teammate"
    assert result["data"]["completion_kind"] == "saved_private_draft"
    assert result["data"]["external_work_established"] is False


def test_changed_operation_commitment_is_withheld(executor, monkeypatch):
    reader, _ = executor
    row, ctx, _, settings = reader._guard()
    row.box_id = "invented-box"
    handle = {"kind": "follow_up", "record_id": "invented-work", "commitment": "d" * 64}
    selected = ToolSelection.model_validate(tools._selection([], [], [handle]))
    monkeypatch.setattr(reader, "_guard", lambda: (row, ctx, selected, settings))
    monkeypatch.setattr(tools.work, "now", lambda *a, **k: None)
    monkeypatch.setattr(tools.operations, "read", lambda *a, **k: {"evidence": {"commitment": "e" * 64}})
    with pytest.raises(tools.ws.WorkspaceError, match="agent_tool_source_changed"):
        reader.execute({"tool": "read_current_operation_status", **handle})
