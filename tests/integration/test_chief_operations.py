"""Native Chief reads saved operation receipts without setup or side effects."""

from typing import Any

import pytest
from sqlalchemy import func, select
from tests.integration.test_follow_up import case as case
from tests.integration.test_follow_up import complete, count, decide, propose

from cosmas_os.application import conversation, note_review, operations_status, provider_team
from cosmas_os.models import Decision, FollowUpReceipt, Operation, WorkspaceReply


@pytest.mark.parametrize("phase,next_step", [
    ("proposed", "Review the exact proposal before approving"),
    ("sent", "Record the human-verified outcome"),
    ("completed", "Human outcome recorded for the synthetic follow-up"),
    ("source_changed", "Review the changed or unavailable source"),
])
def test_native_chief_has_current_next_steps_and_replay_without_operational_writes(session, case, monkeypatch, phase, next_step):
    monkeypatch.setattr(conversation.runtime_settings, "workspace_llm_backend", "disabled")
    box, owner, _, _ = case
    w = propose(session, case)["workspace"]
    item = w["follow_ups"][0]
    if phase in {"sent", "completed"}:
        w = decide(session, case, item)["workspace"]
    if phase == "completed":
        w = complete(session, case, item)["workspace"]
    if phase == "source_changed":
        w = note_review.save(session, box, owner, w["id"], expected=w["revision"], key="native-changed-note",
            base_note_id=w["note"]["latest"]["id"], source_reply_id=None,
            content="Changed invented plan requires review.")["workspace"]
    team = provider_team.save(session, box, owner, expected=0, key="native-chief-team",
                              configuration=provider_team.default_configuration())
    before = [count(session, model, case) for model in (Decision, Operation, FollowUpReceipt)]
    observed = []
    original = operations_status.linked

    def linked(*args, **kwargs):
        rows = original(*args, **kwargs)
        observed.extend(rows)
        return rows

    monkeypatch.setattr(operations_status, "linked", linked)
    monkeypatch.setattr(conversation, "generate_reply", lambda *args: pytest.fail("Chief renderer ran twice"))
    request: dict[str, Any] = dict(expected=w["revision"], team_revision=team["revision"], key="native-chief-status",
                                   role="chief", content="What is ready and what do I need to do next?")
    first = conversation.ask(session, box, owner, w["id"], **request)
    reply = first["workspace"]["entries"][-1]["reply"]
    assert next_step in reply["content"]
    assert "saved synthetic delivery and human outcome receipts" in reply["content"]
    assert reply["backend"] == "local_source_review_v1"
    assert reply["context_revision"] == request["expected"]
    assert len(observed) == 1 and observed[0]["record_id"] == item["ticket_id"]
    assert observed[0]["scope"] == {"box_id": box, "owner_id": owner, "workspace_id": w["id"]}
    assert item["body"] not in repr(observed) and "Private invented agenda" not in reply["content"]
    session.expire_all()
    replay = conversation.ask(session, box, owner, w["id"], **request)
    assert replay["entry_id"] == first["entry_id"] and len(observed) == 1
    assert replay["workspace"]["entries"][-1]["reply"] == reply
    assert [count(session, model, case) for model in (Decision, Operation, FollowUpReceipt)] == before
    assert session.scalar(select(func.count()).select_from(WorkspaceReply).where(WorkspaceReply.workspace_id == w["id"])) == 1


def test_other_native_role_keeps_existing_context_without_automatic_operations_read(session, case, monkeypatch):
    monkeypatch.setattr(conversation.runtime_settings, "workspace_llm_backend", "disabled")
    box, owner, w, _ = case
    team = provider_team.save(session, box, owner, expected=0, key="native-other-role",
                              configuration=provider_team.default_configuration())
    monkeypatch.setattr(operations_status, "linked", lambda *args, **kwargs: pytest.fail("other role acquired automatic work read"))
    result = conversation.ask(session, box, owner, w["id"], expected=w["revision"], team_revision=team["revision"],
        key="native-prep-status", role="visit_prep", content="Review the saved preparation")
    assert result["workspace"]["entries"][-1]["reply"]["role"] == "visit_prep"
