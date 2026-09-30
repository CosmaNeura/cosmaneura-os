from concurrent.futures import ThreadPoolExecutor
from inspect import unwrap
from threading import Barrier

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.helpers.task_brief import REQUIREMENTS
from tests.integration.test_workspace_handoffs import (
    assign,
    prepare,
    worker,
)
from tests.integration.test_workspace_handoffs import (
    model as original_model,
)

from cosmas_os.adapters.gpt41 import _context
from cosmas_os.application import handoffs, model_work
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.models import ModelWorkAdmission, WorkspaceHandoff, WorkspaceReply
from cosmas_os.ports.bot_capabilities import BotReply, DraftBrief


@pytest.fixture
def model(monkeypatch):
    return unwrap(original_model)(monkeypatch)


@pytest.fixture
def case(session, seeded, model):
    return prepare(session, seeded)


def test_saved_task_brief_reaches_actual_child_and_receipt_identifies_exact_result(
    session, case, model
):
    result = assign(session, case)
    task = result["workspace"]["handoffs"][0]
    brief = task["task_brief"]
    assert brief["allowed_actions"] == ["prepare_private_draft"]
    assert brief["depends_on"]["entry_id"] == result["entry_id"]
    assert brief["source_versions"] and brief["independent"] is True
    assert worker(session)
    assert brief["source_versions"][0]["sha256"] in model[-1].question
    assert "Missing or unconfirmed facts" in model[-1].question
    assert "Unknown speakers and continuity warnings remain unresolved" in model[-1].question
    box, owner, workspace, _, _ = case
    saved = ws.read(session, box, owner, workspace["id"])["handoffs"][0]
    receipt = saved["completion_evidence"]
    assert (
        receipt["kind"] == "saved_private_draft" and receipt["entry_id"] == saved["result_entry_id"]
    )
    assert receipt["source_versions"] == brief["source_versions"]
    assert saved["task_brief"] == brief


def test_current_chief_cannot_publish_unstructured_requirements(session, case, monkeypatch):
    monkeypatch.setattr(
        model_work,
        "dispatch_claim",
        lambda _: BotReply(
            "Invalid draft request",
            (),
            "azure_gpt41",
            handoffs=(DraftBrief("scribe", "Missing requirements"),),
        ),
    )
    box, owner, workspace, config, _ = case
    receipt = model_work.run_conversation(
        session,
        box,
        owner,
        workspace["id"],
        expected=1,
        team_revision=config["revision"],
        key="invalid-brief",
        role="chief",
        content="Ask Scribe for a draft",
    )
    assert receipt["outcome"] == "failed"
    assert not session.scalar(
        select(WorkspaceHandoff).where(WorkspaceHandoff.workspace_id == workspace["id"])
    )


def test_new_task_refused_before_admission_stays_visible_but_cannot_retry_without_its_brief(
    session, case, monkeypatch
):
    original = model_work._allowance

    def exhausted_after_chief(s, box, owner, at, configuration):
        if model_work.workspace_units(s, case[2]["id"]):
            raise ws.WorkspaceError("team_work_limit")
        return original(s, box, owner, at, configuration)

    monkeypatch.setattr(model_work, "_allowance", exhausted_after_chief)
    result = assign(session, case)
    task = result["workspace"]["handoffs"][0]
    assert task["status"] == "failed" and task["task_brief_unavailable"] is True
    with pytest.raises(ws.WorkspaceError, match="handoff_context_changed"):
        handoffs.retry(
            session,
            case[0],
            case[1],
            case[2]["id"],
            task["id"],
            expected=result["workspace"]["revision"],
            previous_attempt=task["attempt_id"],
            key="new-v4-no-brief",
        )


def test_changed_source_prevents_dispatch_and_retry_of_exact_task_brief(session, case, model):
    result = assign(session, case)
    task = result["workspace"]["handoffs"][0]
    ws.append(
        session,
        case[0],
        case[1],
        case[2]["id"],
        expected=result["workspace"]["revision"],
        key="changed-source",
        kind="scratchpad",
        content="Different invented source. Cardiac history still unconfirmed.",
    )
    assert worker(session) and len(model) == 1
    observed = ws.read(session, case[0], case[1], case[2]["id"])
    assert observed["handoffs"][0]["error_code"] == "source_changed"
    with pytest.raises(ws.WorkspaceError, match="source_changed"):
        handoffs.retry(
            session,
            case[0],
            case[1],
            case[2]["id"],
            task["id"],
            expected=observed["revision"],
            previous_attempt=task["attempt_id"],
            key="changed-source-retry",
        )


def test_three_independent_admissions_execute_concurrently_and_publish_once(
    engine, model, monkeypatch
):
    def chief(claim):
        context = _context(claim.envelope["context"])
        return BotReply(
            "Prepare three independent drafts",
            context.sources,
            "azure_gpt41",
            handoffs=tuple(
                DraftBrief(role, "Prepare an independent invented draft", REQUIREMENTS)
                for role in ("scribe", "visit_prep", "follow_up")
            ),
        )

    monkeypatch.setattr(model_work, "dispatch_claim", chief)
    with Session(engine) as session:
        data = prepare(
            session, svc.provision_box(svc.Container(session), "Invented parallel task clinic")
        )
        assign(session, data)
        admissions = list(
            session.scalars(
                select(ModelWorkAdmission).where(
                    ModelWorkAdmission.workspace_id == data[2]["id"],
                    ModelWorkAdmission.kind == "private_handoff",
                )
            )
        )
        ids = [row.id for row in admissions]
    assert len(ids) == 3
    barrier = Barrier(3)

    def run(aid):
        with Session(engine) as session:
            claim = model_work.claim(session, data[0], data[1], aid)
        assert claim is not None
        context = _context(claim.envelope["context"])
        barrier.wait(timeout=10)  # All three must reach model I/O before any settles.
        reply = BotReply(
            "Invented private draft",
            context.sources,
            "azure_gpt41_source_draft_v1" if context.role == "scribe" else "azure_gpt41",
        )
        with Session(engine) as session:
            model_work.settle(session, claim, reply)
            assert model_work.claim(session, data[0], data[1], aid) is None
        return aid

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert set(pool.map(run, ids)) == set(ids)
    with Session(engine) as session:
        saved = ws.read(session, data[0], data[1], data[2]["id"])
        assert len(saved["handoffs"]) == 3 and all(
            h["status"] == "completed" for h in saved["handoffs"]
        )
        assert (
            len(
                list(
                    session.scalars(
                        select(WorkspaceReply).where(
                            WorkspaceReply.entry_id.in_(
                                [h["result_entry_id"] for h in saved["handoffs"]]
                            )
                        )
                    )
                )
            )
            == 3
        )
