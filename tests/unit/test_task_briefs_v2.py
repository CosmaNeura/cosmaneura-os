"""Full-source v2 is explicit; the saved v1 limits remain unchanged."""
import hashlib
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from tests.helpers.task_brief import REQUIREMENTS
from tests.unit.test_task_briefs import context

from cosmas_os.application import handoff_briefs, model_work
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.ports.bot_capabilities import DraftBrief, SourcePassage


def full_context(lengths=(12000,), character="x"):
    return replace(context(), sources=tuple(SourcePassage(str(i), i + 1,
        "Invented full transcript", "evidence", character * length)
        for i, length in enumerate(lengths)))


def prepare(value):
    return handoff_briefs.prepare(DraftBrief("scribe", "Preserve missing DOB", REQUIREMENTS),
        value, SimpleNamespace(id="origin", revision=2), version=2,
        prepared_contract=handoff_briefs.FULL_SOURCE_CONTRACT)


@pytest.mark.parametrize("lengths", [(12000,), (20000,), (10000, 10000, 10000)])
def test_v2_preserves_full_original_source_hashes_with_no_truncation(lengths):
    value = full_context(lengths)
    task = prepare(value)
    assert task["version"] == 2 and len(task["source_versions"]) == len(lengths)
    assert [s["sha256"] for s in task["source_versions"]] == [
        hashlib.sha256(s.content.encode()).hexdigest() for s in value.sources]
    handoff_briefs.validate(task, value, goal=task["goal"], origin_id="origin",
        prepared_contract=handoff_briefs.FULL_SOURCE_CONTRACT)
    changed = replace(value, sources=(replace(value.sources[0],
        content=value.sources[0].content[:-1] + "z"), *value.sources[1:]))
    with pytest.raises(ValueError, match="source or authority mismatch"):
        handoff_briefs.validate(task, changed, goal=task["goal"], origin_id="origin",
            prepared_contract=handoff_briefs.FULL_SOURCE_CONTRACT)


@pytest.mark.parametrize("contract", [None, "cosmas-gpt41-prepared.v4", "cosmas-gpt41-prepared.v5"])
def test_v2_refuses_downgrade_while_legacy_v1_keeps_exact_semantics(contract):
    value, task = full_context(), prepare(full_context())
    with pytest.raises(ValueError, match="requires the v6"):
        handoff_briefs.validate(task, value, goal=task["goal"], origin_id="origin",
            prepared_contract=contract)
    with pytest.raises(ValueError, match="fit completely"):
        handoff_briefs.prepare(DraftBrief("scribe", "Preserve missing DOB", REQUIREMENTS),
            value, SimpleNamespace(id="origin", revision=2), prepared_contract=contract)


@pytest.mark.parametrize("lengths,character", [((20001,), "x"), ((10000,) * 4, "x"),
    ((1,) * 13, "x"), ((20000,), "界"), ((20000,), "\x01")])
def test_v2_refuses_size_count_and_actual_utf8_or_escaped_read_overflow(lengths, character):
    with pytest.raises(ValueError, match="fit completely|finite tool read bytes"):
        prepare(full_context(lengths, character))


@pytest.mark.parametrize("version", [True, 0, 3, "2"])
def test_unknown_or_noninteger_version_is_not_admitted(version):
    value, task = full_context(), prepare(full_context())
    task["version"] = version
    with pytest.raises(ValueError, match="version"):
        handoff_briefs.validate(task, value, goal=task["goal"], origin_id="origin",
            prepared_contract=handoff_briefs.FULL_SOURCE_CONTRACT)


def test_unsupported_new_chief_preflight_and_v2_downgrade_fail_before_database_or_model(monkeypatch):
    monkeypatch.setattr(model_work.team.runtime_settings, "workspace_agent_tools_enabled", True)
    too_big = full_context((5000,) * 7)
    with pytest.raises(WorkspaceError, match="handoff_source_context_too_large"):
        model_work._new_admission(None, None, None, None, None, {}, "unused", too_big, None, None)
    monkeypatch.setattr(model_work.team.runtime_settings, "workspace_agent_tools_enabled", False)
    with pytest.raises(WorkspaceError, match="handoff_source_contract_unavailable"):
        model_work._new_admission(None, None, None, None, None, {"task_brief": prepare(full_context())},
            "unused", full_context(), None, None)


@pytest.mark.parametrize("tools_enabled", [False, True])
@pytest.mark.parametrize("claimed_table", ["calendar_import_requests", "calendar_import_revocations"])
def test_supported_source_still_checks_import_keys_before_model_preparation(
    monkeypatch, tools_enabled, claimed_table,
):
    monkeypatch.setattr(model_work.team.runtime_settings, "workspace_agent_tools_enabled", tools_enabled)
    checked = []

    def scalar(statement):
        table = statement.get_final_froms()[0].name
        assert statement.compile().params == {
            "workspace_id_1": "invented-workspace", "idempotency_key_1": "claimed-key",
        }
        checked.append(table)
        return "claimed" if table == claimed_table else None

    def prepare_unexpected(*args, **kwargs):
        pytest.fail("an import-owned key must be rejected before model preparation")

    monkeypatch.setattr(model_work.GPT41Connector, "prepare", prepare_unexpected)
    monkeypatch.setattr(model_work.GPT41CompactToolsConnector, "prepare", prepare_unexpected)
    with pytest.raises(WorkspaceError, match="idempotency_conflict"):
        model_work._new_admission(
            SimpleNamespace(scalar=scalar), SimpleNamespace(id="invented-workspace"),
            None, None, None, {"idempotency_key": "claimed-key"}, "unused", context(), None, None,
        )
    assert checked == (["calendar_import_requests"] if claimed_table == "calendar_import_requests"
        else ["calendar_import_requests", "calendar_import_revocations"])


@pytest.mark.parametrize("stored_contract", [handoff_briefs.FULL_SOURCE_CONTRACT, None,
    "cosmas-gpt41-prepared.v5"])
def test_v2_projection_requires_matching_saved_column_and_inner_contract(stored_contract):
    value, task = full_context(), prepare(full_context())
    frozen = replace(value, role="scribe", draft_only=True, question=handoff_briefs.question(task))
    envelope = {"contract": handoff_briefs.FULL_SOURCE_CONTRACT, "context": asdict(frozen)}
    assignment = SimpleNamespace(workspace_id=value.workspace_id, box_id="box", owner_id="owner",
        recipient_agent_id="scribe-agent", recipient_role="scribe", brief=task["goal"], origin_entry_id="origin")
    row = SimpleNamespace(request_body={"task_brief": task}, prepared_envelope=envelope,
        envelope_contract=stored_contract, envelope_sha256=model_work.digest(envelope),
        workspace_id=value.workspace_id, box_id="box", owner_id="owner",
        agent_id="scribe-agent", state="reserved")
    projected = handoff_briefs.projection(None, assignment, row)
    assert projected == ({"task_brief": task} if stored_contract == handoff_briefs.FULL_SOURCE_CONTRACT
        else {"task_brief_unavailable": True})
