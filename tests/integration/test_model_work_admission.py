"""Real PostgreSQL commits with invented input and an injected model only."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from tests.helpers.task_brief import REQUIREMENTS

from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    AppointmentObservation,
    BoxContext,
    ModelUsageObservation,
    ModelWorkAdmission,
    PatientLink,
    Principal,
    WorkspaceEntry,
    WorkspaceReply,
)
from cosmas_os.ports.bot_capabilities import BotReply


def case(engine):
    with Session(engine) as s:
        box = BoxContext(display_name="Invented W35 ledger clinic")
        s.add(box)
        s.flush()
        owner = Principal(
            box_id=box.id, principal_type="human", display_name="Invented W35 owner", is_owner=True
        )
        s.add(owner)
        s.flush()
        link = PatientLink(
            box_id=box.id,
            source_pair_key="w35:" + str(uuid4()),
            label="Invented W35",
            state="confirmed",
            confirmed_by_principal_id=owner.id,
            attested_at=datetime.now(UTC),
        )
        s.add(link)
        s.flush()
        appointment = AppointmentObservation(
            box_id=box.id,
            patient_link_id=link.id,
            external_id=str(uuid4()),
            source="synthetic",
            start_at=datetime.now(UTC),
            patient_label="Invented W35 visit",
        )
        s.add(appointment)
        s.commit()
        workspace = ws.create(s, box.id, owner.id, appointment.id, "invented-create")
        version = team.save(
            s,
            box.id,
            owner.id,
            expected=0,
            key="invented-team",
            configuration=team.default_configuration(),
        )
        return box.id, owner.id, workspace["id"], version["revision"]


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(team.runtime_settings, "workspace_enabled", True)
    monkeypatch.setattr(team.runtime_settings, "workspace_llm_backend", "azure_gpt41")
    monkeypatch.setattr(
        team.runtime_settings, "workspace_llm_api_key", SecretStr("invented-no-network")
    )


def command(revision=1, key="invented-question"):
    return {
        "expected": revision,
        "team_revision": 1,
        "key": key,
        "role": "visit_prep",
        "content": "Summarize the invented agenda.",
    }


def answer(_):
    return BotReply("Invented answer for human review.", (), "azure_gpt41", 25, 8)


def test_chief_request_payload_names_the_open_invented_visit(engine, enabled):
    box, owner, wid, _ = case(engine)
    with Session(engine) as s:
        admission, _ = work.reserve_conversation(
            s, box, owner, wid, **{**command(), "role": "chief", "content": "What is open on this visit?"}
        )
        row = s.get(ModelWorkAdmission, admission)
        payload = json.loads(row.prepared_envelope["body"]["messages"][1]["content"])
        assert "Invented W35 visit" in payload["question"]
        assert payload["question"].startswith("What is open on this visit?")
        assert any("Invented visit preparation" in source["text"] for source in payload["sources"])
        assert all(source["kind"] != "open_visit" for source in payload["sources"])


def test_reservation_is_durable_and_resolve_is_read_only(engine, enabled):
    box, owner, wid, _ = case(engine)
    with Session(engine) as s:
        admission, _ = work.reserve_conversation(s, box, owner, wid, **command())
    with engine.connect() as c, c.begin():
        c.execute(text("SET TRANSACTION READ ONLY"))
        with Session(bind=c) as s:
            observed = work.resolve_conversation(s, box, owner, wid, **command())
            assert observed["outcome"] == "reserved" and observed["admission"]["id"] == admission
            assert (
                s.scalar(
                    select(func.count())
                    .select_from(WorkspaceReply)
                    .where(WorkspaceReply.workspace_id == wid)
                )
                == 0
            )
            assert (
                s.scalar(
                    select(WorkspaceEntry.revision).where(
                        WorkspaceEntry.id == s.get(ModelWorkAdmission, admission).request_entry_id
                    )
                )
                == 2
            )
    with Session(engine) as s:
        same, replay = work.reserve_conversation(s, box, owner, wid, **command())
        assert same is None and replay["outcome"] == "reserved"


def test_exact_completed_replay_calls_once_and_attaches_reserved_slot(engine, enabled):
    box, owner, wid, _ = case(engine)
    calls = []

    def fake(claim):
        calls.append(claim.envelope_sha256)
        with Session(engine) as other:
            assert other.scalar(
                select(Principal).where(Principal.id == owner).with_for_update(nowait=True)
            )
        return answer(claim)

    with Session(engine) as s:
        first = work.run_conversation(s, box, owner, wid, dispatch=fake, **command())
        second = work.run_conversation(s, box, owner, wid, dispatch=fake, **command())
        assert (
            first["outcome"] == second["outcome"] == "saved"
            and first["saved_entry"] == second["saved_entry"]
        )
        assert first["saved_entry"]["revision"] == 2 and len(calls) == 1
        assert work.usage(s, box, owner)["occupied_units"] == 1
        assert work.workspace_units(s, wid) == 1


def test_unclaimed_expiry_is_pure_and_old_process_cannot_claim(engine, enabled):
    box, owner, wid, _ = case(engine)
    at = datetime.now(UTC)
    with Session(engine) as s:
        admission, _ = work.reserve_conversation(s, box, owner, wid, clock=lambda: at, **command())
        observed = work.resolve_conversation(
            s, box, owner, wid, clock=lambda: at + timedelta(seconds=10), **command()
        )
        assert (
            observed["outcome"] == "abandoned"
            and s.get(ModelWorkAdmission, admission).state == "reserved"
        )
        assert work.usage(s, box, owner, as_of=at + timedelta(hours=25))["occupied_units"] == 0
        assert (
            work.claim(s, box, owner, admission, clock=lambda: at + timedelta(seconds=10)) is None
        )
        assert s.get(ModelWorkAdmission, admission).dispatch_id is None


def test_expired_running_claim_keeps_usage_and_never_publishes_late_answer(engine, enabled):
    box, owner, wid, _ = case(engine)
    at = datetime.now(UTC)
    with Session(engine) as s:
        admission, _ = work.reserve_conversation(s, box, owner, wid, clock=lambda: at, **command())
        claimed = work.claim(s, box, owner, admission, clock=lambda: at + timedelta(seconds=1))
        work.settle(s, claimed, answer(claimed), clock=lambda: at + timedelta(seconds=91))
        observed = work.resolve_conversation(
            s, box, owner, wid, clock=lambda: at + timedelta(seconds=92), **command()
        )
        assert observed["outcome"] == "unknown" and observed["admission"]["usage"] == "verified"
        assert (
            s.scalar(
                select(func.count())
                .select_from(WorkspaceReply)
                .where(WorkspaceReply.workspace_id == wid)
            )
            == 0
        )
        assert (
            s.scalar(
                select(func.count())
                .select_from(ModelUsageObservation)
                .where(ModelUsageObservation.admission_id == admission)
            )
            == 2
        )
        assert work.workspace_units(s, wid) == 1


def test_revocation_after_call_settles_usage_but_withholds_private_output(engine, enabled):
    box, owner, wid, _ = case(engine)

    def revoke(claim):
        with Session(engine) as s:
            s.get(Principal, owner).state = "disabled"
            s.commit()
        return answer(claim)

    with Session(engine) as s:
        with pytest.raises(ws.WorkspaceError) as error:
            work.run_conversation(s, box, owner, wid, dispatch=revoke, **command())
        assert error.value.status == 403
        row = s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == wid))
        assert row.state == "failed" and row.reason == "authority_changed"
        assert (
            s.scalar(
                select(ModelUsageObservation).where(ModelUsageObservation.admission_id == row.id)
            ).usage
            == "verified"
        )
        assert (
            s.scalar(
                select(func.count())
                .select_from(WorkspaceReply)
                .where(WorkspaceReply.workspace_id == wid)
            )
            == 0
        )


def test_replay_before_new_runtime_gate(engine, enabled, monkeypatch):
    box, owner, wid, _ = case(engine)
    with Session(engine) as s:
        first = work.run_conversation(s, box, owner, wid, dispatch=answer, **command())
        monkeypatch.setattr(team.runtime_settings, "workspace_llm_backend", "none")
        _, replay = work.reserve_conversation(s, box, owner, wid, **command())
        assert replay["saved_entry"] == first["saved_entry"]


def chief_answer(claim):
    from cosmas_os.ports.bot_capabilities import DraftBrief

    return BotReply(
        "I queued every draft.",
        (),
        "azure_gpt41",
        30,
        9,
        (DraftBrief("scribe", "Organize the invented saved notes.", REQUIREMENTS),),
    )


@pytest.mark.parametrize("boundary", ["children_expired", "reply_expired", "authority_closed"])
def test_final_publication_fence_rolls_back_staged_children_and_reply(
    engine, enabled, monkeypatch, boundary
):
    from cosmas_os.application import conversation
    from cosmas_os.models import WorkspaceHandoff, WorkspaceHandoffAttempt

    box, owner, wid, _ = case(engine)
    at = datetime.now(UTC)
    current = [at]
    denied = [False]
    original_children, original_reply = work.reserve_children, conversation.record_reply

    def children(*args, **kwargs):
        result = original_children(*args, **kwargs)
        if boundary == "children_expired":
            current[0] = at + timedelta(seconds=92)
        if boundary == "authority_closed":
            denied[0] = True
        return result

    def reply(*args, **kwargs):
        original_reply(*args, **kwargs)
        if boundary == "reply_expired":
            current[0] = at + timedelta(seconds=92)

    def reauthenticate():
        if denied[0]:
            raise ws.WorkspaceError("workspace_access_denied", 403)

    monkeypatch.setattr(work, "reserve_children", children)
    monkeypatch.setattr(conversation, "record_reply", reply)
    request = {**command(), "role": "chief"}
    with Session(engine) as s:
        admission, _ = work.reserve_conversation(
            s, box, owner, wid, clock=lambda: current[0], **request
        )
        current[0] = at + timedelta(seconds=1)
        claimed = work.claim(s, box, owner, admission, clock=lambda: current[0])
        current[0] = at + timedelta(seconds=2)
        work.settle(
            s,
            claimed,
            chief_answer(claimed),
            clock=lambda: current[0],
            reauthenticate=reauthenticate,
        )
        observed = work.resolve_conversation(
            s, box, owner, wid, clock=lambda: current[0], **request
        )
        assert observed["outcome"] == ("failed" if boundary == "authority_closed" else "unknown")
        assert observed["admission"]["usage"] == "verified"
        assert observed["saved_entry"] is None
        snapshot = ws.read(s, box, owner, wid)
        assert snapshot["revision"] == 2 and len(snapshot["entries"]) == 2
        assert [item["kind"] for item in snapshot["entries"]] == ["synthetic_source", "conversation"]
        for model in (WorkspaceHandoff, WorkspaceHandoffAttempt, WorkspaceReply):
            assert (
                s.scalar(select(func.count()).select_from(model).where(model.workspace_id == wid))
                == 0
            )
        assert (
            s.scalar(
                select(func.count())
                .select_from(ModelWorkAdmission)
                .where(ModelWorkAdmission.workspace_id == wid)
            )
            == 1
        )
        assert work.usage(s, box, owner, as_of=current[0])["occupied_units"] == 1
        assert work.usage(s, box, owner, as_of=current[0])["verified_input_tokens"] == 30


def test_chief_and_worker_have_distinct_committed_admissions_and_no_row_lock_during_io(
    engine, enabled
):
    from sqlalchemy.orm import sessionmaker

    from cosmas_os.models import WorkspaceHandoffAttempt

    box, owner, wid, _ = case(engine)
    with Session(engine) as s:
        observation = work.run_conversation(
            s, box, owner, wid, dispatch=chief_answer, **{**command(), "role": "chief"}
        )
        snapshot = work.project_workspace(s, ws.read(s, box, owner, wid))
        assert observation["outcome"] == "saved" and snapshot["revision"] == 3
        assert len([e for e in snapshot["entries"] if e.get("model_request")]) == 2
        handoff = snapshot["handoffs"][0]
        assert handoff["status"] == "queued" and work.workspace_units(s, wid) == 2

    def fake(claim):
        with Session(engine) as other:
            assert other.scalar(
                select(Principal).where(Principal.id == owner).with_for_update(nowait=True)
            )
        return BotReply("Invented source draft.", (), "azure_gpt41_source_draft_v1", 15, 6)

    assert work.process_next(sessionmaker(engine), dispatch=fake)
    with Session(engine) as s:
        final = work.project_workspace(s, ws.read(s, box, owner, wid))
        assert final["revision"] == 3 and final["handoffs"][0]["status"] == "completed"
        assert len([e for e in final["entries"] if e["reply"]]) == 2
        assert work.usage(s, box, owner)["occupied_units"] == 2
        assert s.get(WorkspaceHandoffAttempt, handoff["attempt_id"]).started_at is not None


def test_retry_receipt_stays_bound_to_exact_attempt_after_later_retry(engine, enabled):
    from sqlalchemy.orm import sessionmaker

    from cosmas_os.ports.bot_capabilities import ModelCallFailure

    box, owner, wid, _ = case(engine)
    with Session(engine) as s:
        work.run_conversation(
            s, box, owner, wid, dispatch=chief_answer, **{**command(), "role": "chief"}
        )
        first = ws.read(s, box, owner, wid)["handoffs"][0]

    def fail(_):
        raise ModelCallFailure(dispatch="started_unconfirmed")

    assert work.process_next(sessionmaker(engine), dispatch=fail)
    with Session(engine) as s:
        args = {"expected": 3, "previous_attempt": first["attempt_id"], "key": "invented-retry-one"}
        with s.begin_nested():
            assert (
                work.resolve_retry(s, box, owner, wid, first["id"], **args)["outcome"]
                == "not_found"
            )
        second = work.reserve_retry(s, box, owner, wid, first["id"], **args)
        assert second["outcome"] == "recorded" and second["recorded"]["status"] == "queued"
        assert (
            second["recorded"]["workspace_revision"] == 4
            and second["recorded"]["attempt_number"] == 2
        )
    assert work.process_next(sessionmaker(engine), dispatch=fail)
    with Session(engine) as s:
        third = work.reserve_retry(
            s,
            box,
            owner,
            wid,
            first["id"],
            expected=4,
            previous_attempt=second["recorded"]["attempt_id"],
            key="invented-retry-two",
        )
        assert third["recorded"]["attempt_number"] == 3
        old = work.resolve_retry(s, box, owner, wid, first["id"], **args)
        assert old["recorded"]["attempt_id"] == second["recorded"]["attempt_id"]
        assert (
            old["recorded"]["status"] == "interrupted"
            and old["recorded"]["workspace_revision"] == 4
        )
        assert work.reserve_retry(s, box, owner, wid, first["id"], **args) == old
        claimed = work.claim(s, box, owner, third["recorded"]["admission"]["id"])
        work.settle(s, claimed, ModelCallFailure(dispatch="not_dispatched"))


def test_same_owner_concurrent_reservations_cannot_exceed_one_unit(engine, enabled):
    from concurrent.futures import ThreadPoolExecutor
    from copy import deepcopy
    from threading import Barrier

    from cosmas_os.models import ProviderTeamRevision

    box, owner, wid, _ = case(engine)
    with Session(engine) as s:
        current = team.current(s, box, owner)
        config = deepcopy(current.configuration)
        config["model_work"] = {"version": 1, "max_attempts_per_24h": 1}
        # Persist reviewed configuration through the existing application test
        # seam; review commitment itself is covered by the signed setup suite.
        s.add(
            ProviderTeamRevision(
                box_id=box,
                owner_id=owner,
                revision=2,
                template_version=current.template_version,
                configuration=config,
                idempotency_key="limit-fixture",
                request_hash="d" * 64,
            )
        )
        s.commit()
    barrier = Barrier(2)

    def reserve(key):
        with Session(engine) as s:
            barrier.wait()
            try:
                return work.reserve_conversation(
                    s, box, owner, wid, **{**command(key=key), "team_revision": 2}
                )[0]
            except ws.WorkspaceError as e:
                return e.code

    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(reserve, ["concurrent-one", "concurrent-two"]))
    assert (
        sum(
            item
            not in {"workspace_revision_conflict", "model_attempt_in_progress", "team_work_limit"}
            for item in results
        )
        == 1
    )
    with Session(engine) as s:
        assert work.usage(s, box, owner)["occupied_units"] == 1


def test_source_edit_after_admission_refuses_claim_without_dispatch(engine, enabled):
    box, owner, wid, _ = case(engine)
    with Session(engine) as s:
        admission, _ = work.reserve_conversation(s, box, owner, wid, **command())
        ws.append(
            s,
            box,
            owner,
            wid,
            expected=2,
            key="new-source",
            kind="scratchpad",
            content="New invented fact.",
        )
        assert work.claim(s, box, owner, admission) is None
        row = s.get(ModelWorkAdmission, admission)
        assert row.state == "failed" and row.reason == "source_changed" and row.dispatch_id is None
        assert (
            work.resolve_conversation(s, box, owner, wid, **command())["admission"]["dispatch"]
            == "not_started"
        )


def test_attempt_at_notebook_499_keeps_slot_500_and_publishes_without_revision_upgrade(
    engine, enabled
):
    from cosmas_os.models import EncounterWorkspace

    box, owner, wid, _ = case(engine)
    with Session(engine) as s:
        # Real bounded history insertion; preserve immutable entries and trigger.
        for revision in range(2, 500):
            s.add(
                WorkspaceEntry(
                    workspace_id=wid,
                    box_id=box,
                    actor_id=owner,
                    revision=revision,
                    kind="conversation",
                    content="Invented retained discussion",
                    idempotency_key=f"old-{revision}",
                    request_hash="c" * 64,
                )
            )
        s.get(EncounterWorkspace, wid).revision = 499
        s.commit()
        result = work.run_conversation(s, box, owner, wid, dispatch=answer, **command(revision=499))
        assert result["outcome"] == "saved" and result["saved_entry"]["revision"] == 500
        assert s.get(EncounterWorkspace, wid).revision == 500


def another_workspace(engine, box, owner, wid):
    from cosmas_os.models import EncounterWorkspace

    with Session(engine) as s:
        original = s.get(EncounterWorkspace, wid)
        visit = AppointmentObservation(
            box_id=box,
            patient_link_id=original.patient_link_id,
            external_id=str(uuid4()),
            source="synthetic",
            start_at=datetime.now(UTC),
            patient_label="Invented second workspace",
        )
        s.add(visit)
        s.commit()
        return ws.create(s, box, owner, visit.id, "create-" + uuid4().hex)["id"]


def install_limit_fixture(s, box, owner, amount):
    from copy import deepcopy

    from cosmas_os.models import ProviderTeamRevision

    current = team.current(s, box, owner)
    config = deepcopy(current.configuration)
    config["model_work"] = {"version": 1, "max_attempts_per_24h": amount}
    version = ProviderTeamRevision(
        box_id=box,
        owner_id=owner,
        revision=current.revision + 1,
        template_version=current.template_version,
        configuration=config,
        idempotency_key="fixture-" + uuid4().hex,
        request_hash="e" * 64,
    )
    s.add(version)
    s.commit()
    return version.revision


def test_chief_partial_admission_keeps_paid_answer_and_truthful_unstarted_child(engine, enabled):
    from cosmas_os.models import WorkspaceHandoffAttempt

    box, owner, wid, _ = case(engine)
    other = another_workspace(engine, box, owner, wid)
    with Session(engine) as s:
        revision = install_limit_fixture(s, box, owner, 2)

    def concurrent(claim):
        with Session(engine) as s:
            result = work.run_conversation(
                s, box, owner, other, dispatch=answer, **{**command(), "team_revision": revision}
            )
            assert result["outcome"] == "saved"
        return chief_answer(claim)

    with Session(engine) as s:
        saved = work.run_conversation(
            s,
            box,
            owner,
            wid,
            dispatch=concurrent,
            **{**command(), "role": "chief", "team_revision": revision},
        )
        assert saved["outcome"] == "saved"
        snapshot = ws.read(s, box, owner, wid)
        handoff = snapshot["handoffs"][0]
        assert handoff["status"] == "failed" and handoff["error_code"] == "team_work_limit"
        published = snapshot["entries"][-1]["reply"]["content"]
        assert "Not started: your team's work limit was reached." in published
        assert "Organize the invented saved notes" in published
        assert "I queued every draft" not in published
        attempt = s.get(WorkspaceHandoffAttempt, handoff["attempt_id"])
        assert attempt.started_at is None and attempt.completed_at is not None
        assert (
            s.scalar(
                select(ModelWorkAdmission.id).where(
                    ModelWorkAdmission.handoff_attempt_id == attempt.id
                )
            )
            is None
        )
        assert (
            work.usage(s, box, owner)["occupied_units"] == 2
            and work.usage(s, box, owner)["verified_input_tokens"] == 55
        )


def test_chief_receipt_names_actual_queued_tasks_and_suppresses_action_claims(engine, enabled):
    from cosmas_os.adapters.gpt41 import _context
    from cosmas_os.ports.bot_capabilities import DraftBrief

    box, owner, wid, _ = case(engine)
    briefs = (
        DraftBrief("scribe", "Organize the invented saved notes.", REQUIREMENTS),
        DraftBrief("follow_up", "Prepare a patient email draft and provider action items.", {
            **REQUIREMENTS, "expected_output": "Subject and Body; provider owner and next action."}),
    )
    seen = []

    def dispatch(claim):
        sources = _context(claim.envelope["context"]).sources[:1]
        seen.extend(sources)
        return BotReply("I sent the patient email and completed all tasks.", sources,
            "azure_gpt41", 30, 9, briefs)

    with Session(engine) as s:
        result = work.run_conversation(s, box, owner, wid, dispatch=dispatch,
            **{**command(), "role": "chief"})
        snapshot = ws.read(s, box, owner, wid)
        reply = next(e for e in snapshot["entries"] if e["id"] == result["saved_entry"]["id"])["reply"]
        assert "I sent the patient email" not in reply["content"]
        assert "completed all tasks" not in reply["content"]
        assert reply["content"].count("Queued; waiting for a private draft.") == 2
        assert "Review each completed result before using it" in reply["content"]
        assert reply["citations"] == [{"entry_id": p.entry_id, "revision": p.revision,
            "label": p.label, "kind": p.kind} for p in seen]
        assert len(snapshot["handoffs"]) == 2
        for h in snapshot["handoffs"]:
            assert h["status"] == "queued" and h["error_code"] is None
            assert work._quoted_assignment_text(h["recipient_name"]) in reply["content"]
            assert work._quoted_assignment_text(h["brief"]) in reply["content"]
            assert work._quoted_assignment_text(h["task_brief"]["expected_output"]) in reply["content"]
            assert h["review"] is None and h["result_entry_id"] is None


@pytest.mark.parametrize("reason", ["team_work_limit", "authority_changed"])
def test_chief_receipt_distinguishes_actual_queued_and_unstarted_recipients(engine, enabled, reason):
    from cosmas_os.models import ProviderBot
    from cosmas_os.ports.bot_capabilities import DraftBrief

    box, owner, wid, revision = case(engine)
    other = None
    if reason == "team_work_limit":
        other = another_workspace(engine, box, owner, wid)
        with Session(engine) as s:
            # Chief can initially request two drafts. A separate request uses
            # one slot while Chief is running, leaving exactly one child slot.
            revision = install_limit_fixture(s, box, owner, 3)

    def dispatch(claim):
        if reason == "team_work_limit":
            assert claim.envelope["context"]["handoff_limit"] == 2
            assert other is not None
            with Session(engine) as s:
                competing = work.run_conversation(s, box, owner, other, dispatch=answer,
                    **{**command(), "team_revision": revision})
                assert competing["outcome"] == "saved"
        else:
            with Session(engine) as s:
                recipient = s.scalar(select(ProviderBot).where(ProviderBot.box_id == box,
                    ProviderBot.owner_id == owner, ProviderBot.role == "follow_up"))
                assert recipient is not None
                principal = s.get(Principal, recipient.agent_id)
                assert principal is not None
                principal.state = "disabled"
                s.commit()
        return BotReply("Every teammate finished and I sent the email.", (), "azure_gpt41", 30, 9,
            (DraftBrief("scribe", "Organize the invented saved notes.", REQUIREMENTS),
                DraftBrief("follow_up", "Prepare the private patient email draft.", REQUIREMENTS)))

    with Session(engine) as s:
        result = work.run_conversation(s, box, owner, wid, dispatch=dispatch,
            **{**command(), "role": "chief", "team_revision": revision})
        assert result["outcome"] == "saved", result
        snapshot = ws.read(s, box, owner, wid)
        reply = next(e for e in snapshot["entries"] if e["id"] == result["saved_entry"]["id"])["reply"]["content"]
        assert "Every teammate finished" not in reply and "I sent the email" not in reply
        assert reply.count("Queued; waiting for a private draft.") == 1
        assert reply.count("Not started:") == 1
        assert ("work limit was reached" if reason == "team_work_limit"
            else "access or configuration changed") in reply
        assert {h["recipient_role"]: (h["status"], h["error_code"]) for h in snapshot["handoffs"]} == {
            "scribe": ("queued", None), "follow_up": ("failed", reason)}


@pytest.mark.parametrize("escaped", [False, True])
def test_chief_three_maximum_briefs_fit_reply_bound_without_truncating_saved_tasks(engine, enabled, escaped):
    from cosmas_os.ports.bot_capabilities import DraftBrief

    box, owner, wid, _ = case(engine)
    goal = "*\n" * 2000 if escaped else "X" * 4000
    expected = "!\n" * 300 if escaped else "Y" * 600
    briefs = tuple(DraftBrief(role, goal, {**REQUIREMENTS, "expected_output": expected})
        for role in ("scribe", "visit_prep", "follow_up"))
    with Session(engine) as s:
        result = work.run_conversation(s, box, owner, wid,
            dispatch=lambda _: BotReply("I finished everything.", (), "azure_gpt41", 30, 9, briefs),
            **{**command(), "role": "chief"})
        assert result["outcome"] == "saved"
        snapshot = ws.read(s, box, owner, wid)
        reply = next(e for e in snapshot["entries"] if e["id"] == result["saved_entry"]["id"])["reply"]["content"]
        assert len(reply) <= 20000 and "I finished everything" not in reply
        assert len(snapshot["handoffs"]) == 3
        for h in snapshot["handoffs"]:
            assert h["brief"] == goal
            assert work._quoted_assignment_text(h["task_brief"]["expected_output"]) in reply
        if escaped:
            assert reply.count("full unchanged request") == 3
            assert "Requested work (quoted)" not in reply
        else:
            assert reply.count(goal) == 3


def test_two_claimants_get_only_one_dispatch_token(engine, enabled):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    box, owner, wid, _ = case(engine)
    with Session(engine) as s:
        admission, _ = work.reserve_conversation(s, box, owner, wid, **command())
    barrier = Barrier(2)

    def claim(_):
        with Session(engine) as s:
            barrier.wait(timeout=10)
            return work.claim(s, box, owner, admission)

    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(claim, range(2)))
    assert sum(value is not None for value in claims) == 1
    with Session(engine) as s:
        work.settle(s, next(value for value in claims if value), answer(None))
        assert work.resolve_conversation(s, box, owner, wid, **command())["outcome"] == "saved"


def test_admission_and_usage_are_immutable_and_cannot_move_to_another_owner(engine, enabled):
    from sqlalchemy.exc import DBAPIError

    box, owner, wid, _ = case(engine)
    with Session(engine) as s:
        saved = work.run_conversation(s, box, owner, wid, dispatch=answer, **command())
        aid = saved["admission"]["id"]
        for statement in [
            "DELETE FROM model_work_admissions WHERE id=:id",
            "UPDATE model_work_admissions SET request_body='{}'::jsonb WHERE id=:id",
            "UPDATE model_work_admissions SET state='running',finalized_at=NULL WHERE id=:id",
            "UPDATE model_usage_observations SET input_tokens=0 WHERE admission_id=:id",
            "DELETE FROM model_usage_observations WHERE admission_id=:id",
        ]:
            with pytest.raises(DBAPIError), s.begin_nested():
                s.execute(text(statement), {"id": aid})
        observation = s.scalar(
            select(ModelUsageObservation).where(ModelUsageObservation.admission_id == aid)
        )
        values = {
            column.name: getattr(observation, column.name)
            for column in ModelUsageObservation.__table__.columns
            if column.name != "id"
        }
        values.update(owner_id=str(uuid4()), kind="late_usage")
        with pytest.raises(DBAPIError), s.begin_nested():
            s.add(ModelUsageObservation(**values))
            s.flush()


def test_expired_observation_does_not_mutate_and_explicit_replacement_fences_old_unclaimed(
    engine, enabled
):
    box, owner, wid, _ = case(engine)
    at = datetime.now(UTC)
    with Session(engine) as s:
        old, _ = work.reserve_conversation(s, box, owner, wid, clock=lambda: at, **command())
    with engine.connect() as connection, connection.begin():
        connection.execute(text("SET TRANSACTION READ ONLY"))
        with Session(bind=connection) as s:
            assert (
                work.resolve_conversation(
                    s, box, owner, wid, clock=lambda: at + timedelta(seconds=11), **command()
                )["outcome"]
                == "abandoned"
            )
            assert s.get(ModelWorkAdmission, old).state == "reserved"
    with Session(engine) as s:
        new, _ = work.reserve_conversation(
            s,
            box,
            owner,
            wid,
            clock=lambda: at + timedelta(seconds=11),
            **command(2, "explicit-replacement"),
        )
        assert s.get(ModelWorkAdmission, old).state == "abandoned"
        assert work.claim(s, box, owner, old, clock=lambda: at + timedelta(seconds=12)) is None
        assert work.claim(s, box, owner, new, clock=lambda: at + timedelta(seconds=12)) is not None


@pytest.mark.parametrize("legacy_state", ["queued", "running"])
def test_legacy_unadmitted_handoff_is_visible_but_never_automatically_called(
    engine, enabled, legacy_state
):
    from cosmas_os.domain.hashing import payload_hash
    from cosmas_os.models import EncounterWorkspace, WorkspaceHandoff, WorkspaceHandoffAttempt

    box, owner, wid, _ = case(engine)
    with Session(engine) as s:
        version, chief, _ = team.active_bot(s, box, owner, "chief", 1)
        _, recipient, config = team.active_bot(s, box, owner, "scribe", 1)
        w = s.get(EncounterWorkspace, wid)
        w.revision = 2
        origin = WorkspaceEntry(
            workspace_id=wid,
            box_id=box,
            actor_id=owner,
            revision=2,
            kind="conversation",
            content="Legacy invented draft request.",
            idempotency_key="legacy-chief",
            request_hash="a" * 64,
        )
        s.add(origin)
        s.flush()
        h = WorkspaceHandoff(
            workspace_id=wid,
            box_id=box,
            owner_id=owner,
            origin_entry_id=origin.id,
            issuer_agent_id=chief.agent_id,
            recipient_agent_id=recipient.agent_id,
            recipient_role="scribe",
            recipient_name=config["name"],
            team_revision_id=version.id,
            context_revision=1,
            brief="Legacy invented draft.",
        )
        s.add(h)
        s.flush()
        attempt = WorkspaceHandoffAttempt(
            handoff_id=h.id,
            workspace_id=wid,
            box_id=box,
            owner_id=owner,
            number=1,
            status=legacy_state,
            idempotency_key="initial",
            request_hash=payload_hash({"origin": origin.id, "role": "scribe"}),
            started_at=datetime.now(UTC) if legacy_state == "running" else None,
        )
        s.add(attempt)
        s.commit()
        observed = ws.read(s, box, owner, wid)["handoffs"][0]
        assert observed["status"] == "interrupted"
        assert observed["error_code"] == (
            "legacy_queued_unadmitted" if legacy_state == "queued" else "legacy_running_unconfirmed"
        )
        assert (
            s.scalar(
                select(ModelWorkAdmission.id).where(
                    ModelWorkAdmission.handoff_attempt_id == attempt.id
                )
            )
            is None
        )
        # The new worker's selection requires an admission, so this raw legacy
        # row can only proceed through this explicit, owner-authorized retry.
        recorded = work.reserve_retry(
            s,
            box,
            owner,
            wid,
            h.id,
            expected=2,
            previous_attempt=attempt.id,
            key="explicit-legacy-retry",
        )
        assert (
            recorded["recorded"]["coverage"] == "durable_admission"
            and recorded["recorded"]["status"] == "queued"
        )
        old = s.get(WorkspaceHandoffAttempt, attempt.id)
        assert old.status == "interrupted" and (old.started_at is None) == (
            legacy_state == "queued"
        )
        claim = work.claim(s, box, owner, recorded["recorded"]["admission"]["id"])
        work.settle(
            s,
            claim,
            BotReply("Invented reviewable draft.", (), "azure_gpt41_source_draft_v1", 10, 5),
        )
        assert (
            work.resolve_retry(
                s,
                box,
                owner,
                wid,
                h.id,
                expected=2,
                previous_attempt=attempt.id,
                key="explicit-legacy-retry",
            )["recorded"]["status"]
            == "completed"
        )
