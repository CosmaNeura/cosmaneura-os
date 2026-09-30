import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from lab.journey import (
    OWNERS,
    Journey,
    Review,
    readable_draft,
    validate_draft,
    validate_plan,
    validate_review,
)
from lab.store import LabError, Store, digest
from pydantic import ValidationError


def task(owner="scribe"):
    return {"owner": owner, "next_action": "Prepare a source-grounded internal draft.",
            "source_ids": ["intake", "prep", "note"], "prerequisites": ["Read the three exact sources."],
            "completion_criteria": ["Save a draft preserving conflicting contact preferences."],
            "human_review_required": True, "external_action": "not_authorized"}


@pytest.mark.parametrize("bad", ["duplicate_owner", "foreign_source", "omitted_source", "approve", "no_criteria"])
def test_chief_plan_rejects_unaccountable_or_unauthorized_handoffs(bad):
    plan = {"tasks": [task(owner) for owner in OWNERS]}
    sources = [{"entry_id": name} for name in ("intake", "prep", "note")]
    assert validate_plan(plan, sources)
    if bad == "duplicate_owner":
        plan["tasks"][1]["owner"] = "visit_prep"
    elif bad == "foreign_source":
        plan["tasks"][0]["source_ids"] = ["another-patient"]
    elif bad == "omitted_source":
        for item in plan["tasks"]:
            item["source_ids"] = ["intake"]
    elif bad == "approve":
        plan["tasks"][0]["human_review_required"] = False
    else:
        plan["tasks"][0]["completion_criteria"] = []
    with pytest.raises((LabError, ValidationError)):
        validate_plan(plan, sources)


@pytest.mark.parametrize("bad", ["changed_assignment", "wrong_sources", "sent"])
def test_recipient_cannot_substitute_another_task_or_claim_delivery(bad):
    assignment = task()
    draft = {"task_sha256": digest(assignment), "body": "A source-grounded draft awaiting human review.",
             "source_ids": assignment["source_ids"], "unresolved": ["Contact preference remains conflicting."],
             "status": "draft_ready_for_human_review"}
    assert validate_draft(draft, assignment)
    if bad == "changed_assignment":
        altered = deepcopy(assignment)
        altered["next_action"] = "Do different work outside this assignment."
        draft["task_sha256"] = digest(altered)
    elif bad == "wrong_sources":
        draft["source_ids"] = ["another-patient"]
    else:
        draft["status"] = "sent"
    with pytest.raises((LabError, ValidationError)):
        validate_draft(draft, assignment)


@pytest.mark.parametrize("bad", ["queued", "missing", "duplicate"])
def test_chief_cannot_verify_unfinished_missing_or_repeated_results(bad):
    receipts = [{"status": "completed", "result_entry_id": str(i)} for i in range(3)]
    review = {"body": "Three private drafts are saved; human review remains outstanding.",
              "result_entry_ids": ["0", "1", "2"], "unresolved": ["Consent is undocumented."],
              "external_action": "not_performed"}
    assert validate_review(review, receipts)
    if bad == "queued":
        receipts[0]["status"] = "queued"
    elif bad == "missing":
        review["result_entry_ids"] = ["0", "1", "invented-receipt"]
    else:
        review["result_entry_ids"] = ["0", "1", "1"]
    with pytest.raises(LabError):
        validate_review(review, receipts)


@pytest.mark.parametrize("tool", ["submit_draft", "approve", "send_email"])
def test_new_journey_loop_rejects_unread_input_and_unavailable_actions(tmp_path, tool):
    class Model:
        def reply(self, messages, tools):
            return {"role": "assistant", "tool_calls": [{"id": str(len(messages)), "type": "function",
                    "function": {"name": tool, "arguments": json.dumps({})}}]}, {}

    journey = Journey(SimpleNamespace(check_agent=lambda role: None), Store(tmp_path), "one", Model(), "none")
    with pytest.raises(LabError, match="not_submitted"):
        journey.request("chief", {}, Review, lambda v: pytest.fail("Unadmitted output reached validator"), lambda: {})
    assert not journey.acknowledged and not journey.artifacts


@pytest.mark.parametrize("text", [
    "Assignment hash: 6f45732a-94a2-416e-b93b-3356aeb29cf2.",
    "Source hash: " + "a" * 64,
    "Neither action has been completed.",
])
def test_draft_review_regressions_reject_internal_ids_and_unsupported_certainty(text):
    with pytest.raises(LabError):
        readable_draft(text)
    readable_draft("Staff actions remain planned; completion is not documented. Contact preference conflicts.")
