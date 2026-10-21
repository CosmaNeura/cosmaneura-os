"""Model guards retain exact context without rebuilding unused UI reviews."""

from dataclasses import asdict

import pytest
from sqlalchemy.orm import Session
from tests.integration.test_google_message_model_work import (
    change_source,
    reserve,
)
from tests.integration.test_google_message_model_work import (
    google_case as _google_case,
)
from tests.integration.test_handoff_review import case as _reviewed_case
from tests.integration.test_handoff_review import model as _model
from tests.integration.test_handoff_review import review

from cosmas_os.adapters.gpt41_tools_v6 import GPT41CompactToolsConnector
from cosmas_os.application import agent_tools, handoffs, model_work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.models import EncounterWorkspace

google_case = _google_case
case = _reviewed_case
model = _model


def test_model_context_keeps_exact_reviewed_sources_and_envelope_without_ui_review_reads(
    session, case, monkeypatch
):
    review(session, case)
    box, owner, snapshot = case[:3]
    current = ws.read(session, box, owner, snapshot["id"])
    ws.append(
        session, box, owner, snapshot["id"], expected=current["revision"],
        key="invented-context-parity-source", kind="evidence",
        source_label="Invented source", content="Invented heart history remains unverified.",
    )
    full = ws.read(session, box, owner, snapshot["id"])
    assert full["handoffs"][0]["review"]["decision"] == "accepted"
    workspace = session.get(EncounterWorkspace, snapshot["id"])
    assert workspace is not None
    version, bot, settings = team.active_bot(session, box, owner, "chief", 1)
    roles = handoffs.available_roles(session, box, owner, version, settings)
    command = {"content": "Collect the saved private draft; preserve missing facts."}
    # Independently reconstruct the prior full public-read path, rather than
    # comparing two calls through the optimized projection.
    with monkeypatch.context() as legacy:
        legacy.setattr(ws, "_read_model_context", ws.read)
        expected = model_work._context_for(
            session, workspace, version, settings, bot, command,
            handoff_roles=roles, prepared_contract="cosmas-gpt41-prepared.v6",
        )
    assert expected.sources[-1].content == "Invented heart history remains unverified."
    selection = agent_tools.prepare_tool_selection(
        session, box=box, owner=owner, workspace_id=workspace.id, agent_id=bot.agent_id,
        team_revision_id=version.id, context_revision=expected.context_revision,
        settings=settings, context=expected,
    )
    expected_envelope = GPT41CompactToolsConnector(lambda: "").prepare(expected, selection)

    def unused_display(*args):
        raise AssertionError("Model source guard rebuilt the unused handoff review display")

    with monkeypatch.context() as guarded:
        guarded.setattr(handoffs, "read", unused_display)
        actual = model_work._context_for(
            session, workspace, version, settings, bot, command,
            handoff_roles=roles, prepared_contract="cosmas-gpt41-prepared.v6",
        )
    assert asdict(actual) == asdict(expected)
    assert GPT41CompactToolsConnector(lambda: "").prepare(actual, selection) == expected_envelope
    # The public projection still carries the exact accepted result and review.
    assert ws.read(session, box, owner, snapshot["id"])["handoffs"] == full["handoffs"]


def test_private_source_authority_changed_during_tool_read_is_withheld_by_fresh_post_guard(google_case, monkeypatch):
    f = google_case
    claimed = reserve(f, "invented-context-private-post-guard")
    selected = next(source for source in claimed.envelope["tool_selection"]["sources"]
                    if source["entry_id"] == f.selected["entry_id"])
    with Session(f.engine) as session:
        reader = agent_tools.AgentToolExecutor(session, claimed)
        original = reader._guard
        guards = 0

        def guard_then_revoke():
            nonlocal guards
            guards += 1
            value = original()
            if guards == 1:
                # The fake current provider binding changes without bypassing
                # the real database locks held by the source reader.
                change_source(f, "semantic_grant")
            return value

        monkeypatch.setattr(reader, "_guard", guard_then_revoke)
        with pytest.raises(ws.WorkspaceError):
            reader.execute({"tool": "read_selected_source", **{
                field: selected[field] for field in ("entry_id", "revision", "sha256")
            }})
        assert guards == 2  # The second fresh guard rejects before returning private content.
