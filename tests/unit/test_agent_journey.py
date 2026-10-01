import json
import threading
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from lab.journey import (
    AVAILABLE_OWNERS,
    OWNERS,
    Draft,
    Journey,
    Review,
    deliver_recipients,
    normalize_display_ids,
    readable_draft,
    saved_receipts,
    task_requirements,
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


@pytest.mark.parametrize("bad", ["queued", "missing", "duplicate", "id_at_body_end"])
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
    elif bad == "duplicate":
        review["result_entry_ids"] = ["0", "1", "1"]
    else:
        review["body"] += " Assignment hash: 88df02d2-d522-4fb4-b290-87bf9b91d06a"
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
    "No external actions or requests have been completed.",
    "No requests were completed.",
    "No staff task has been completed.",
    "All uncertainties and planned actions remain uncompleted and require human review before proceeding.",
    "Medication list and cardiology records have not been requested or obtained.",
    "Cardiology records not requested.",
    "Do not mark these requests as completed until explicit permission is documented.",
])
def test_draft_review_regressions_reject_internal_ids_and_unsupported_certainty(text):
    with pytest.raises(LabError):
        readable_draft(text)
    readable_draft("Staff actions remain planned; completion is not documented. Contact preference conflicts.")


@pytest.mark.parametrize("text", [
    "No external actions or requests are confirmed as completed.",
    "No requests are documented as completed.",
    "No tasks are documented to have been completed.",
    "Completion of the planned requests is not documented.",
    "Medication information remains incomplete.",
    "Information needed for the planned work is not complete; completion of actions is not documented.",
    "Information needed for planned work is incomplete; action completion is not documented.",
])
def test_documentation_and_confirmation_gaps_do_not_assert_noncompletion(text):
    readable_draft(text)


@pytest.mark.parametrize("subject,verb", [("Actions", "remain"), ("Tasks", "are"), ("A request", "is"), ("Work", "remains")])
@pytest.mark.parametrize("state", ["uncompleted", "incomplete", "undone"])
def test_undocumented_action_completion_cannot_be_reported_as_known_unfinished_work(subject, verb, state):
    with pytest.raises(LabError, match="completion is not documented"):
        readable_draft(f"{subject} {verb} {state} and require human review.")


def test_shared_worker_cannot_expose_another_episode_claim_to_the_model(tmp_path):
    from cosmas_os.ports.bot_capabilities import ModelCallFailure

    app = SimpleNamespace(box="current-box", owner="current-owner", workspace="current-encounter")
    journey = Journey(app, Store(tmp_path), "current", None, "none")
    claim = SimpleNamespace(box="other-box", owner="other-owner", workspace_id="other-encounter")
    with pytest.raises(ModelCallFailure):
        journey.dispatch(claim)
    assert not journey.acknowledged and not journey.artifacts


def test_independent_durable_admissions_run_together_once_each():
    barrier = threading.Barrier(3)
    seen = []
    lock = threading.Lock()

    def receive(admission):
        with lock:
            seen.append(admission)
        barrier.wait(timeout=2)

    deliver_recipients(SimpleNamespace(recipient=receive), ["a", "b", "c"], 3)
    assert sorted(seen) == ["a", "b", "c"]
    with pytest.raises(LabError):
        deliver_recipients(SimpleNamespace(recipient=receive), ["a", "a", "c"], 3)


@pytest.mark.parametrize("mode", ["valid", "stale_input", "transient", "unauthorized", "revoked"])
def test_inline_input_acknowledgment_and_bounded_retry_keep_authority(tmp_path, monkeypatch, mode):
    receipts = [{"status": "completed", "result_entry_id": str(i)} for i in range(3)]
    inputs = {"saved_draft_receipts": receipts}
    calls = []
    revoked = False
    monkeypatch.setattr("lab.journey.time.sleep", lambda _: None)

    def check(role):
        if revoked:
            raise LabError("agent_authority_unavailable")

    class Model:
        def reply(self, messages, tools):
            nonlocal revoked
            calls.append(messages)
            if len(calls) == 1 and mode in {"transient", "unauthorized", "revoked"}:
                revoked = mode == "revoked"
                raise LabError("model_http_401" if mode == "unauthorized" else "model_http_500")
            args = {"body": "Three draft results are saved; human review remains outstanding.",
                    "result_entry_ids": ["0", "1", "2"], "unresolved": ["Review the unresolved source conflict."],
                    "external_action": "not_performed", "input_sha256": "0" * 64 if mode == "stale_input" else digest(inputs)}
            return {"role": "assistant", "tool_calls": [{"id": str(len(calls)), "type": "function",
                    "function": {"name": "submit_draft", "arguments": json.dumps(args)}}]}, {}

    journey = Journey(SimpleNamespace(check_agent=check), Store(tmp_path), "one", Model(), "none", input_mode="inline")
    if mode in {"valid", "transient"}:
        result = journey.request("chief", inputs, Review, lambda v: validate_review(v, receipts), lambda: {})
        assert result.result_entry_ids == ["0", "1", "2"]
        assert len(calls) == (2 if mode == "transient" else 1)
        assert journey.acknowledged == {("chief", "plan")}
    else:
        with pytest.raises(LabError):
            journey.request("chief", inputs, Review, lambda v: validate_review(v, receipts), lambda: {})
        assert not journey.acknowledged
        if mode != "stale_input":
            assert len(calls) == 1


@pytest.mark.parametrize("bad", ["failed", "partial", "source_changed"])
def test_latency_comparison_refuses_incomplete_or_confounded_evidence(bad):
    from lab.compare import compare

    before = {"mode": "azure", "model": "fixed", "fault": "none", "status": "passed",
              "source": {"source_sha256": "same"}, "concurrency": 1, "expected_episode_count": 1,
              "usage": {"tokens": 100, "model_calls": 10},
              "episodes": [{"case": "journey", "passed": True, "duration_ms": 100}]}
    after = deepcopy(before)
    after["episodes"][0]["duration_ms"] = 50
    assert compare(before, after)["observed_reduction_percent"] == 50
    if bad == "failed":
        after["status"] = "failed"
    elif bad == "partial":
        after["expected_episode_count"] = 2
    else:
        after["source"]["source_sha256"] = "different"
    with pytest.raises(ValueError):
        compare(before, after)


def planned_journey(tmp_path, owners=OWNERS, question="Organize saved encounter outputs."):
    from cosmas_os.ports.bot_capabilities import BotContext, SourcePassage

    app = SimpleNamespace(check_agent=lambda role: None, addresses={role: role for role in AVAILABLE_OWNERS})
    journey = Journey(app, Store(tmp_path), "planned", None, "none", input_mode="inline", owners=owners)
    context = BotContext("encounter", 3, "chief", question, "brief", tuple(
        SourcePassage(name, index + 1, "Synthetic " + name, "evidence", "Synthetic source with unconfirmed contact permission.")
        for index, name in enumerate(("intake", "prep", "note"))), ())
    reply = journey.draft(SimpleNamespace(envelope={"context": asdict(context)}, admission_id="chief-admission"))
    return journey, context, reply


def test_plan_selects_three_of_four_and_publishes_readable_bound_briefs(tmp_path):
    from cosmas_os.application import handoff_briefs

    journey, context, reply = planned_journey(tmp_path, AVAILABLE_OWNERS)
    assert journey.available_owners == AVAILABLE_OWNERS
    assert journey.owners == ("visit_prep", "research", "follow_up")
    assert len(reply.handoffs) == 3
    for brief, item in zip(reply.handoffs, journey.plan.tasks, strict=True):
        assert brief.brief == item.next_action and not brief.brief.startswith("{")
        assert brief.requirements == task_requirements(item)
        assert brief.requirements["missing_facts"] == item.prerequisites
        assert brief.requirements["completion_criteria"] == item.completion_criteria
        bound = handoff_briefs.prepare(brief, context, SimpleNamespace(id="origin", revision=4))
        admitted = replace(context, role=item.owner, question=handoff_briefs.question(bound), draft_only=True)
        assert digest(journey.admitted_task(admitted)) == digest(item.model_dump())
    assert journey.replay_owners("Ask Scribe for its draft.") == OWNERS
    assert journey.replay_owners("Use the Scribe transcript; ask Research for questions.") == ("visit_prep", "research", "follow_up")


@pytest.mark.parametrize("fault", ["goal", "owner", "prerequisite", "output", "criterion", "source", "saved_plan"])
def test_readable_brief_rejects_changed_admitted_task_or_sources(tmp_path, fault):
    from cosmas_os.application import handoff_briefs

    journey, context, reply = planned_journey(tmp_path)
    brief = reply.handoffs[1]
    bound = handoff_briefs.prepare(brief, context, SimpleNamespace(id="origin", revision=4))
    admitted = replace(context, role="scribe", question=handoff_briefs.question(bound), draft_only=True)
    if fault == "goal":
        bound["goal"] = "Perform a different task instead."
    elif fault == "owner":
        admitted = replace(admitted, role="follow_up")
    elif fault == "prerequisite":
        bound["missing_facts"] = ["Assume permission was confirmed."]
    elif fault == "output":
        bound["expected_output"] = "An externally sent message."
    elif fault == "criterion":
        bound["completion_criteria"] = ["Send the message immediately."]
    elif fault == "source":
        admitted = replace(admitted, sources=(replace(context.sources[0], content="Changed evidence."), *context.sources[1:]))
    else:
        journey.plan.tasks[1].next_action = "A changed task after the plan was saved."
    admitted = replace(admitted, question=handoff_briefs.question(bound))
    with pytest.raises(LabError):
        journey.admitted_task(admitted)


@pytest.mark.parametrize("owners", [("scribe", "research", "follow_up"), ("visit_prep", "research", "follow_up")])
def test_four_available_recipients_still_require_exactly_three_distinct_choices(owners):
    sources = [{"entry_id": name} for name in ("intake", "prep", "note")]
    value = {"tasks": [task(owner) for owner in owners]}
    assert validate_plan(value, sources, AVAILABLE_OWNERS)
    with pytest.raises(LabError):
        validate_plan(value, sources, OWNERS)
    value["tasks"][0]["owner"] = value["tasks"][1]["owner"]
    with pytest.raises(LabError):
        validate_plan(value, sources, AVAILABLE_OWNERS)


def test_reviewer_schema_uses_exact_saved_ids_and_compact_receipts(tmp_path):
    receipts = [{"recipient_role": owner, "status": "completed", "result_entry_id": "saved-" + owner,
                 "draft_text": "A saved draft for human review.", "attempts": [{"id": "large-metadata"}],
                 "task_brief": {"unused": "full canonical metadata retained"}} for owner in OWNERS]
    original = deepcopy(receipts)

    class Model:
        def reply(self, messages, tools):
            assert [tool["function"]["name"] for tool in tools] == ["submit_draft"]
            schema = tools[0]["function"]["parameters"]
            assert schema["properties"]["result_entry_ids"]["items"]["enum"] == [r["result_entry_id"] for r in receipts]
            supplied = json.loads(messages[-1]["content"])
            compact = supplied["admitted_input"]["saved_draft_receipts"]
            assert all(set(item) == {"recipient_role", "status", "result_entry_id", "draft_text"} for item in compact)
            result = {"body": "Three saved drafts require human review before further work.",
                      "result_entry_ids": [r["result_entry_id"] for r in receipts],
                      "unresolved": ["Human owner unassigned: clarify the contact conflict."],
                      "external_action": "not_performed", "input_sha256": supplied["input_sha256"]}
            return {"role": "assistant", "tool_calls": [{"id": "review", "type": "function",
                    "function": {"name": "submit_draft", "arguments": json.dumps(result)}}]}, {}

    journey = Journey(SimpleNamespace(check_agent=lambda _: None), Store(tmp_path), "review", Model(), "none", input_mode="inline")
    journey.phase, journey.receipts = "review", receipts
    journey.review([])
    assert journey.acknowledged == {("chief", "review")}
    assert receipts == original


@pytest.mark.parametrize("fault", [None, "missing", "review_waived", "bot_owner"])
def test_follow_up_requires_reviewable_human_tasks_with_proposed_roles(fault):
    assignment = task("follow_up")
    draft = {"task_sha256": digest(assignment), "body": "A private follow-up draft awaits human review.",
             "source_ids": assignment["source_ids"], "unresolved": ["DOB, medicines and contact permission are unconfirmed."],
             "status": "draft_ready_for_human_review", "human_tasks": [
                 {"action": "Clarify the missing birth date.", "proposed_human_role": "RN", "review_needed": True}]}
    if fault == "missing":
        del draft["human_tasks"]
    elif fault == "review_waived":
        draft["human_tasks"][0]["review_needed"] = False
    elif fault == "bot_owner":
        draft["human_tasks"][0]["proposed_human_role"] = "follow_up"
    if fault:
        with pytest.raises((LabError, ValidationError)):
            validate_draft(draft, assignment)
    else:
        assert validate_draft(draft, assignment).human_tasks[0].proposed_human_role == "RN"


def test_follow_up_publishes_per_task_suggestions_without_asserting_human_assignment(tmp_path):
    from cosmas_os.application import handoff_briefs

    journey, context, reply = planned_journey(tmp_path)
    bound = handoff_briefs.prepare(reply.handoffs[2], context, SimpleNamespace(id="origin", revision=4))
    admitted = replace(context, role="follow_up", question=handoff_briefs.question(bound), draft_only=True)
    journey.phase = "recipients"
    result = journey.draft(SimpleNamespace(envelope={"context": asdict(admitted)}, admission_id="follow-up-admission"))
    assert result.content.count("Suggested owner: practice staff; individual unassigned; human review required.") == 3
    events = [json.loads(line) for line in journey.store.events.read_text().splitlines()]
    output = next(e["output"] for e in events if e["role"] == "follow_up" and e.get("tool") == "submit_draft")
    assert output["task_sha256"] == digest(journey.plan.tasks[2].model_dump())
    assert len(output["human_tasks"]) == 3


@pytest.mark.parametrize("fault", [None, "duplicate", "wrong_role", "unfinished", "wrong_actor", "foreign_workspace"])
def test_saved_receipts_bind_exact_selected_roles_results_and_scope(fault):
    roles = ("visit_prep", "research", "follow_up")
    app = SimpleNamespace(box="box", owner="owner", workspace="encounter", agent_id=lambda role: "agent-" + role)
    receipts = [{"recipient_role": role, "recipient_agent_id": app.agent_id(role),
                 "result_entry_id": "saved-" + role, "status": "completed", "attempt_count": 1} for role in roles]
    replies = {r["result_entry_id"]: SimpleNamespace(box_id=app.box, owner_id=app.owner, workspace_id=app.workspace,
                agent_id=r["recipient_agent_id"], content="Actual saved draft.") for r in receipts}
    if fault == "duplicate":
        receipts[0]["result_entry_id"] = receipts[1]["result_entry_id"]
    elif fault == "wrong_role":
        receipts[0]["recipient_role"] = "scribe"
    elif fault == "unfinished":
        receipts[0]["status"] = "running"
    elif fault == "wrong_actor":
        replies[receipts[0]["result_entry_id"]].agent_id = "another-agent"
    elif fault == "foreign_workspace":
        replies[receipts[0]["result_entry_id"]].workspace_id = "another-encounter"
    session = SimpleNamespace(get=lambda model, entry: replies.get(entry))
    if fault:
        with pytest.raises(LabError):
            saved_receipts(session, app, {"handoffs": receipts}, roles)
    else:
        result = saved_receipts(session, app, {"handoffs": receipts}, roles)
        assert all(r["draft_text"] == "Actual saved draft." and r["attempt_count"] == 1 for r in result)


@pytest.mark.parametrize("fault", [None, "revoked", "changed_receipt", "changed_artifact"])
def test_lab_review_saves_immutable_dependencies_without_creating_a_human_turn(tmp_path, monkeypatch, fault):
    from cosmas_os.application import model_work

    journey, _, _ = planned_journey(tmp_path)
    journey.phase = "review"
    receipts = []
    for owner in journey.owners:
        artifact = journey.store.save(journey.episode, owner, {"body": "Saved draft by " + owner,
            "source_ids": ["intake", "prep", "note"], "dependencies": [], "share_with": ["chief"]})
        journey.artifacts.append(artifact)
        receipts.append({"recipient_role": owner, "status": "completed", "result_entry_id": "saved-" + owner,
                         "draft_text": artifact["body"]})
    if fault == "changed_artifact":
        receipts[0]["draft_text"] += " Changed after saving."
    calls = []

    def snapshot():
        calls.append(True)
        if len(calls) == 2 and fault == "revoked":
            raise LabError("agent_authority_unavailable")
        current = deepcopy(receipts)
        if len(calls) == 2 and fault == "changed_receipt":
            current[0]["result_entry_id"] = "replacement"
        return journey.plan_sources, current

    monkeypatch.setattr(journey, "review_snapshot", snapshot)
    monkeypatch.setattr(model_work, "reserve_conversation", lambda *a, **k: pytest.fail("Lab review created a human turn"))
    if fault:
        with pytest.raises(LabError):
            journey.chief_review_in_lab()
        assert all(artifact["role"] != "chief" for artifact in journey.artifacts)
    else:
        result = journey.chief_review_in_lab()
        assert result["reviewer_channel"] == "lab_artifact"
        assert set(result["structured_review"]["result_entry_ids"]) == {r["result_entry_id"] for r in receipts}
        assert {d["artifact_id"] for d in result["dependencies"]} == set(journey.owners)
        assert journey.store.read(journey.episode, "chief", "chief", result["sha256"]) == result
    assert len(calls) == 2


@pytest.mark.parametrize("fault", [None, "source_changed", "authority_changed"])
def test_lab_review_snapshot_uses_current_scoped_application_sources_and_results(tmp_path, monkeypatch, fault):
    import sqlalchemy.orm

    from cosmas_os.application import model_work, provider_team, workspace

    journey, _, _ = planned_journey(tmp_path)
    journey.app.box, journey.app.owner, journey.app.workspace = "box", "owner", "encounter"
    journey.app.engine, journey.app.team_revision = object(), 1
    journey.app.addresses["chief"] = "chief"
    journey.app.agent_id = lambda role: "agent-" + role
    receipts = [{"recipient_role": role, "recipient_agent_id": journey.app.agent_id(role),
                 "result_entry_id": "saved-" + role, "status": "completed"} for role in journey.owners]
    replies = {r["result_entry_id"]: SimpleNamespace(box_id="box", owner_id="owner", workspace_id="encounter",
                agent_id=r["recipient_agent_id"], content="Actual saved private result.") for r in receipts}
    snapshot = {"id": "encounter", "revision": 4, "handoffs": receipts, "entries": [
        {"id": s["entry_id"], "revision": s["revision"], "source_label": s["label"], "kind": s["kind"], "content": s["content"]}
        for s in journey.plan_sources]}
    if fault == "source_changed":
        snapshot["entries"][0]["content"] += " Changed after planning."

    class Session:
        def __init__(self, engine):
            assert engine is journey.app.engine

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, model, entry):
            return replies.get(entry)

    def current_bot(session, box, owner, role, revision):
        assert (box, owner, role, revision) == ("box", "owner", "chief", 1)
        if fault == "authority_changed":
            raise LabError("agent_authority_unavailable")
        return SimpleNamespace(configuration={"practice_context": ""}), SimpleNamespace(agent_id="agent-chief"), {
            "role": "chief", "include_notebook": True, "include_evidence": True,
            "skills": ["saved_context"], "response_style": "brief"}

    def read(session, box, owner, encounter):
        assert (box, owner, encounter) == ("box", "owner", "encounter")
        return deepcopy(snapshot)

    monkeypatch.setattr(sqlalchemy.orm, "Session", Session)
    monkeypatch.setattr(provider_team, "active_bot", current_bot)
    monkeypatch.setattr(workspace, "read", read)
    monkeypatch.setattr(model_work, "project_workspace", lambda session, snapshot: snapshot)
    monkeypatch.setattr(model_work, "reserve_conversation", lambda *a, **k: pytest.fail("Snapshot created a human turn"))
    if fault:
        with pytest.raises(LabError):
            journey.review_snapshot()
    else:
        sources, actual = journey.review_snapshot()
        assert sources == journey.plan_sources
        assert {r["recipient_role"] for r in actual} == set(journey.owners)
        assert all(r["draft_text"] == "Actual saved private result." for r in actual)


def normalization_inputs(owner="scribe"):
    source_ids = [f"00000000-0000-4000-8000-00000000000{number}" for number in range(3)]
    assignment = {**task(owner), "source_ids": source_ids[:2]}
    return {"sources": [{"entry_id": entry, "label": label} for entry, label in zip(source_ids,
        ("Synthetic intake", "Unreviewed Scribe summary", "Synthetic visit notes"), strict=True)],
        "task": assignment, "task_sha256": digest(assignment), "saved_draft_receipts": [
            {"result_entry_id": "10000000-0000-4000-8000-000000000000", "recipient_role": "scribe"}]}


def test_normalization_changes_only_known_identifiers_in_display_fields():
    inputs = normalization_inputs("follow_up")
    source_id = inputs["sources"][0]["entry_id"]
    task_hash = inputs["task_sha256"]
    result_id = inputs["saved_draft_receipts"][0]["result_entry_id"]
    clinical = "Prior heart attack reported; no current chest pain. DOB and medicines missing; consent undocumented."
    original = {"body": clinical + " Source: " + source_id + "; task: " + task_hash + ".",
        "unresolved": ["Contact timing conflicts (morning versus after 15:00). See " + result_id + "."],
        "human_tasks": [{"action": "Clarify DOB using " + source_id + ".", "proposed_human_role": "RN", "review_needed": True}],
        "tasks": [{"next_action": "Review " + source_id, "prerequisites": ["Read " + source_id],
                   "completion_criteria": ["Cite " + source_id], "source_ids": [source_id]}],
        "source_ids": inputs["task"]["source_ids"], "task_sha256": task_hash, "input_sha256": digest(inputs),
        "result_entry_ids": [result_id], "status": "draft_ready_for_human_review"}
    untouched = deepcopy(original)
    normalized, count = normalize_display_ids(original, inputs)
    assert count == 7
    assert original == untouched
    assert normalized["body"] == clinical + " Source: Synthetic intake; task: " + inputs["task"]["next_action"] + "."
    assert normalized["unresolved"] == ["Contact timing conflicts (morning versus after 15:00). See Scribe draft."]
    assert normalized["human_tasks"][0] == {"action": "Clarify DOB using Synthetic intake.",
        "proposed_human_role": "RN", "review_needed": True}
    assert normalized["tasks"][0]["source_ids"] == [source_id]
    for field in ("source_ids", "task_sha256", "input_sha256", "result_entry_ids", "status"):
        assert normalized[field] == original[field]
    assert normalize_display_ids(normalized, inputs) == (normalized, 0)


@pytest.mark.parametrize("foreign", ["20000000-0000-4000-8000-000000000000", "f" * 64])
def test_normalization_leaves_foreign_ids_for_existing_validation_to_reject(foreign):
    inputs = normalization_inputs()
    value = {"body": "Reported history remains unverified. Unknown reference: " + foreign,
        "unresolved": ["Consent is undocumented."], "source_ids": inputs["task"]["source_ids"],
        "task_sha256": inputs["task_sha256"], "status": "draft_ready_for_human_review"}
    normalized, count = normalize_display_ids(value, inputs)
    assert normalized == value and count == 0
    with pytest.raises(LabError, match="remove_internal_ids"):
        validate_draft(normalized, inputs["task"])


@pytest.mark.parametrize("fault", ["task_hash", "unassigned_source", "duplicate_source"])
def test_display_normalization_does_not_repair_invalid_structured_bindings(fault):
    inputs = normalization_inputs()
    value = {"body": "Review the synthetic saved evidence: " + inputs["sources"][0]["entry_id"],
        "unresolved": ["Consent is undocumented."], "source_ids": inputs["task"]["source_ids"],
        "task_sha256": inputs["task_sha256"], "status": "draft_ready_for_human_review"}
    if fault == "task_hash":
        value["task_sha256"] = "f" * 64
    elif fault == "unassigned_source":
        value["source_ids"] = [inputs["sources"][2]["entry_id"]]
    else:
        value["source_ids"] = [*value["source_ids"], value["source_ids"][0]]
    normalized, count = normalize_display_ids(value, inputs)
    assert count == 1
    assert normalized["source_ids"] == value["source_ids"] and normalized["task_sha256"] == value["task_sha256"]
    with pytest.raises(LabError, match="assignment_or_source_mismatch"):
        validate_draft(normalized, inputs["task"])


@pytest.mark.parametrize("role", ["scribe", "follow_up"])
def test_draft_schema_binds_exact_hashes_and_assigned_sources_with_one_call_normalization(tmp_path, role):
    inputs = normalization_inputs(role)
    calls = []

    class Model:
        def reply(self, messages, tools):
            calls.append(True)
            assert len(tools) == 1
            fields = tools[0]["function"]["parameters"]["properties"]
            assert fields["input_sha256"]["enum"] == [digest(inputs)]
            assert fields["task_sha256"]["enum"] == [inputs["task_sha256"]]
            assert fields["source_ids"]["items"]["enum"] == inputs["task"]["source_ids"]
            assert inputs["sources"][2]["entry_id"] not in fields["source_ids"]["items"]["enum"]
            assert fields["source_ids"]["minItems"] == fields["source_ids"]["maxItems"] == 2
            assert fields["source_ids"]["uniqueItems"] is True
            assert fields["body"]["maxLength"] == (600 if role == "follow_up" else 2500)
            assert "every task.source_ids value exactly once" in messages[0]["content"]
            if role == "follow_up":
                assert "Put actionable items only in human_tasks and gaps only in unresolved" in messages[0]["content"]
            value = {"body": "Reported history remains unverified. Source: " + inputs["sources"][0]["entry_id"],
                "unresolved": ["Consent is undocumented."], "source_ids": inputs["task"]["source_ids"],
                "task_sha256": inputs["task_sha256"], "status": "draft_ready_for_human_review",
                "input_sha256": digest(inputs), "human_tasks": ([{"action": "Clarify the missing DOB.",
                    "proposed_human_role": "RN", "review_needed": True}] if role == "follow_up" else [])}
            return {"role": "assistant", "tool_calls": [{"id": "result", "type": "function",
                    "function": {"name": "submit_draft", "arguments": json.dumps(value)}}]}, {}

    journey = Journey(SimpleNamespace(check_agent=lambda role: None), Store(tmp_path), "bound", Model(), "none", input_mode="inline")
    journey.phase = "recipients"
    result = journey.request(role, inputs, Draft, lambda value: validate_draft(value, inputs["task"]), lambda: {})
    assert len(calls) == 1
    assert result.body == "Reported history remains unverified. Source: Synthetic intake"
    assert result.source_ids == inputs["task"]["source_ids"] and result.task_sha256 == inputs["task_sha256"]
    events = [json.loads(line) for line in journey.store.events.read_text().splitlines()]
    normalized = [event for event in events if event["kind"] == "display_ids_normalized"]
    assert len(normalized) == 1 and normalized[0]["count"] == 1 and normalized[0]["phase"] == "recipients"
    assert "body" not in normalized[0] and "source_ids" not in normalized[0]


@pytest.mark.parametrize("role,length,passes", [("follow_up", 600, True), ("follow_up", 601, False), ("scribe", 601, True)])
def test_follow_up_body_limit_keeps_human_tasks_and_gaps_in_structured_fields(role, length, passes):
    assignment = task(role)
    value = {"body": "Draft context: " + "x" * (length - 15), "task_sha256": digest(assignment),
        "source_ids": assignment["source_ids"], "unresolved": ["DOB, medicines, records and contact permission remain unconfirmed."],
        "status": "draft_ready_for_human_review", "human_tasks": ([{"action": "Clarify missing DOB and medicines.",
            "proposed_human_role": "RN", "review_needed": True}] if role == "follow_up" else [])}
    assert len(value["body"]) == length
    if passes:
        result = validate_draft(value, assignment)
        assert result.unresolved == value["unresolved"]
        assert len(result.human_tasks) == (1 if role == "follow_up" else 0)
    else:
        with pytest.raises(LabError, match="max_600_characters"):
            validate_draft(value, assignment)


@pytest.mark.parametrize("malformed", [[], None], ids=["array", "null"])
@pytest.mark.parametrize("input_mode", ["inline", "tool"])
def test_nonobject_tool_arguments_recover_to_a_valid_submission(tmp_path, malformed, input_mode):
    receipts = [{"status": "completed", "result_entry_id": str(index)} for index in range(3)]
    inputs = {"saved_draft_receipts": receipts}
    calls, validated = [], []

    class Model:
        def reply(self, messages, tools):
            calls.append(True)
            if input_mode == "tool" and len(calls) == 1:
                name, value = "read_assignment", {}
            elif len(calls) == (2 if input_mode == "tool" else 1):
                name, value = "submit_draft", malformed
            else:
                assert json.loads(messages[-1]["content"]) == {"error": "structured_tool_arguments_object_required"}
                name, value = "submit_draft", {
                    "body": "Three saved private drafts await human review before further work.",
                    "result_entry_ids": ["0", "1", "2"], "unresolved": ["Contact permission is undocumented."],
                    "external_action": "not_performed", **({"input_sha256": digest(inputs)} if input_mode == "inline" else {})}
            return {"role": "assistant", "tool_calls": [{"id": str(len(calls)), "type": "function",
                    "function": {"name": name, "arguments": json.dumps(value)}}]}, {}

    def validate(value):
        validated.append(value)
        return validate_review(value, receipts)

    journey = Journey(SimpleNamespace(check_agent=lambda _: None), Store(tmp_path), "recovery", Model(), "none", input_mode=input_mode)
    journey.phase = "review"
    result = journey.request("chief", inputs, Review, validate, lambda: {})
    assert result.result_entry_ids == ["0", "1", "2"]
    assert len(calls) == (3 if input_mode == "tool" else 2) and len(validated) == 1
    assert journey.acknowledged == {("chief", "review")}
    events = [json.loads(line) for line in journey.store.events.read_text().splitlines()]
    failures = [event for event in events if event["kind"] == "tool" and event.get("ok") is False]
    assert len(failures) == 1 and failures[0]["error"] == "structured_tool_arguments_object_required"
