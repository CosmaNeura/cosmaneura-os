"""Exact private human-result review, failure recovery and database authority fences."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration import test_workspace_handoffs as shared
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace

from cosmas_os.api import app as api_module
from cosmas_os.api.handoff_review_schemas import HandoffReview, HandoffRevision
from cosmas_os.application import conversation, handoffs, team_setup
from cosmas_os.application import handoff_review as reviews
from cosmas_os.application import handoff_revision as revisions
from cosmas_os.application import provider_team as team
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    Decision,
    EncounterWorkspace,
    ExternalIdentity,
    ModelWorkAdmission,
    Operation,
    PatientLink,
    Principal,
    Ticket,
    WorkspaceEntry,
    WorkspaceHandoff,
    WorkspaceHandoffAttempt,
    WorkspaceHandoffReview,
    WorkspaceHandoffRevision,
    WorkspaceReply,
)

model = shared.model
signed_workspace = _signed_workspace


def request_sessions(session):
    """Fresh HTTP ownership, retaining the fixture's outer rollback boundary."""
    from cosmas_os.application.capture_deadline import own_capture_session

    connection = session.get_bind()

    def get_session():
        with Session(bind=connection, join_transaction_mode="create_savepoint", autoflush=False) as owned:
            yield own_capture_session(owned)

    return get_session


def isolate_http_request(client, session):
    """Release caller savepoints before an owned request shares the test connection."""
    from cosmas_os.application.capture_deadline import current_budget

    original = client.request

    def request(*args, **kwargs):
        assert current_budget() is None
        # Service commits remain inside the fixture's outer transaction, but not
        # inside a caller read savepoint that a later worker rollback can erase.
        session.commit()
        try:
            return original(*args, **kwargs)
        finally:
            session.expire_all()
            assert current_budget() is None
            assert "os_capture_owner" not in session.info

    return request


@pytest.fixture
def case(session, seeded, model):
    prepared = shared.prepare(session, seeded)
    shared.assign(session, prepared)
    assert shared.worker(session)
    box, owner, workspace, config, patient = prepared
    current = ws.read(session, box, owner, workspace["id"])
    handoff = current["handoffs"][0]
    reply = session.get(WorkspaceReply, handoff["result_entry_id"])
    return (
        box,
        owner,
        current,
        config,
        patient,
        handoff,
        hashlib.sha256(reply.content.encode()).hexdigest(),
    )


def review(s, case, **changes):
    box, owner, workspace, _, _, handoff, result_hash = case
    return reviews.review(
        s,
        box,
        owner,
        workspace["id"],
        handoff["id"],
        **{
            "expected": workspace["revision"],
            "key": "human-review-001",
            "attempt_id": handoff["attempt_id"],
            "result_entry_id": handoff["result_entry_id"],
            "result_sha256": result_hash,
            "decision": "accepted",
            "feedback": "",
            **changes,
        },
    )


def projected(s, case):
    w = s.get(EncounterWorkspace, case[2]["id"], populate_existing=True)
    h = s.get(WorkspaceHandoff, case[5]["id"], populate_existing=True)
    a = s.get(WorkspaceHandoffAttempt, case[5]["attempt_id"], populate_existing=True)
    return w, h, a, reviews.review_for(s, w, h, a)


def test_accepted_review_is_exact_durable_and_no_model_or_external_action(session, case, model):
    counts = {
        t: session.scalar(select(func.count()).select_from(t))
        for t in (Ticket, Decision, Operation)
    }
    calls = len(model)
    result = review(session, case)
    w, h, a, receipt = projected(session, case)
    assert receipt["decision"] == "accepted" and receipt["result_sha256"] == case[6]
    assert receipt["attempt_id"] == a.id and receipt["result_entry_id"] == a.result_entry_id
    row = session.get(WorkspaceHandoffReview, receipt["id"])
    admission = session.scalar(
        select(ModelWorkAdmission).where(ModelWorkAdmission.handoff_attempt_id == a.id)
    )
    assert row.source_versions == admission.request_body["task_brief"]["source_versions"]
    assert row.source_sha256 == admission.source_sha256 and row.owner_id != row.agent_id
    assert result["entry_revision"] == case[2]["revision"] + 1
    assert result["workspace"]["revision"] >= result["entry_revision"]
    assert reviews.review_status_for(session, w, h, a) == "current"
    assert counts == {t: session.scalar(select(func.count()).select_from(t)) for t in counts}
    assert len(model) == calls


def test_lost_response_exact_retry_survives_reopen_and_unrelated_turn(session, case):
    first = review(session, case)
    ws.append(
        session,
        case[0],
        case[1],
        case[2]["id"],
        expected=first["entry_revision"],
        key="unrelated-human-turn",
        kind="conversation",
        content="Invented status question.",
    )
    session.expire_all()
    again = review(session, case)
    assert again["entry_revision"] == first["entry_revision"]
    assert again["workspace"]["revision"] == first["entry_revision"] + 1
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffReview)
            .where(WorkspaceHandoffReview.workspace_id == case[2]["id"])
        )
        == 1
    )
    with Session(bind=session.connection(), join_transaction_mode="create_savepoint") as reopened:
        assert projected(reopened, case)[3]["id"] == projected(session, case)[3]["id"]


@pytest.mark.parametrize(
    "changes",
    [
        {"decision": "changes_requested", "feedback": "Keep unknown facts explicit."},
        {"feedback": "Different intent"},
        {"expected": 99},
        {"result_sha256": "0" * 64},
        {"attempt_id": str(uuid4())},
        {"result_entry_id": str(uuid4())},
    ],
)
def test_same_key_changed_intent_conflicts_without_another_review(session, case, changes):
    review(session, case)
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        review(session, case, **changes)
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffReview)
            .where(WorkspaceHandoffReview.workspace_id == case[2]["id"])
        )
        == 1
    )


def test_changes_requested_persists_feedback_without_implicit_reassignment(session, case, model):
    calls = len(model)
    before = session.scalar(select(func.count()).select_from(WorkspaceHandoffAttempt))
    review(
        session,
        case,
        decision="changes_requested",
        feedback="Retain the missing appointment detail and revise the next step.",
    )
    receipt = projected(session, case)[3]
    assert receipt["decision"] == "changes_requested" and receipt["feedback"].startswith("Retain")
    assert session.scalar(select(func.count()).select_from(WorkspaceHandoffAttempt)) == before
    assert len(model) == calls


@pytest.mark.parametrize(
    "changes",
    [
        {"decision": "changes_requested"},
        {"feedback": "x" * 2001},
        {"feedback": "\0"},
        {"result_sha256": "wrong"},
        {"expected": True},
    ],
)
def test_invalid_review_never_saves(session, case, changes):
    with pytest.raises(ws.WorkspaceError, match="invalid_handoff_review"):
        review(session, case, **changes)
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffReview)
            .where(WorkspaceHandoffReview.workspace_id == case[2]["id"])
        )
        == 0
    )


@pytest.mark.parametrize("target", ["foreign_human", "agent", "owner_disabled", "patient_revoked"])
def test_only_current_workspace_human_can_review(session, case, target):
    actor = case[1]
    if target == "foreign_human":
        person = Principal(
            box_id=case[0], principal_type="human", display_name="Invented colleague"
        )
        session.add(person)
        session.commit()
        actor = person.id
    elif target == "agent":
        actor = case[5]["recipient_agent_id"]
    elif target == "owner_disabled":
        session.get(Principal, actor).state = "disabled"
        session.commit()
    else:
        session.get(PatientLink, case[4]).revoked_at = datetime.now(UTC)
        session.commit()
    with pytest.raises(ws.WorkspaceError):
        reviews.review(
            session,
            case[0],
            actor,
            case[2]["id"],
            case[5]["id"],
            expected=case[2]["revision"],
            key="human-review-001",
            attempt_id=case[5]["attempt_id"],
            result_entry_id=case[5]["result_entry_id"],
            result_sha256=case[6],
            decision="accepted",
        )
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffReview)
            .where(WorkspaceHandoffReview.workspace_id == case[2]["id"])
        )
        == 0
    )


@pytest.mark.parametrize("kind", ["scratchpad", "evidence"])
@pytest.mark.parametrize("already_reviewed", [False, True])
def test_changed_source_blocks_review_and_invalidates_prior_acceptance(
    session, case, kind, already_reviewed
):
    current = review(session, case)["entry_revision"] if already_reviewed else case[2]["revision"]
    ws.append(
        session,
        case[0],
        case[1],
        case[2]["id"],
        expected=current,
        key="changed-current-source",
        kind=kind,
        content="Invented changed source version.",
        source_label="Invented evidence" if kind == "evidence" else None,
    )
    w, h, a, receipt = projected(session, case)
    assert receipt is None
    assert reviews.review_status_for(session, w, h, a) == (
        "stale" if already_reviewed else "not_reviewed"
    )
    with pytest.raises(ws.WorkspaceError, match="handoff_sources_changed"):
        review(session, case, expected=w.revision, key="new-stale-review")
    assert session.scalar(
        select(func.count())
        .select_from(WorkspaceHandoffReview)
        .where(WorkspaceHandoffReview.workspace_id == case[2]["id"])
    ) == int(already_reviewed)


@pytest.mark.parametrize("fault", ["wrong_result", "wrong_hash", "foreign_attempt", "incomplete"])
def test_exact_completed_result_required(session, case, fault):
    changes = {}
    if fault == "wrong_result":
        changes["result_entry_id"] = str(uuid4())
    elif fault == "wrong_hash":
        changes["result_sha256"] = "0" * 64
    elif fault == "foreign_attempt":
        changes["attempt_id"] = str(uuid4())
    else:
        # No result has been delivered on this separate admitted assignment.
        other = shared.prepare(
            session, svc.provision_box(svc.Container(session), "Invented unfinished draft")
        )
        queued = shared.assign(session, other)["workspace"]
        h = queued["handoffs"][0]
        with pytest.raises(ws.WorkspaceError, match="handoff_result_unavailable"):
            reviews.review(
                session,
                other[0],
                other[1],
                other[2]["id"],
                h["id"],
                expected=queued["revision"],
                key="unfinished-human-review",
                attempt_id=h["attempt_id"],
                result_entry_id=str(uuid4()),
                result_sha256="a" * 64,
                decision="accepted",
            )
        return
    with pytest.raises(ws.WorkspaceError):
        review(session, case, **changes)
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffReview)
            .where(WorkspaceHandoffReview.workspace_id == case[2]["id"])
        )
        == 0
    )


def test_unverifiable_changed_reply_never_projects_accepted(session, case):
    review(session, case)
    w, h, a, _ = projected(session, case)
    with session.no_autoflush:
        session.get(WorkspaceReply, a.result_entry_id).content = "Invented changed result"
        assert reviews.review_for(session, w, h, a) is None
        assert reviews.review_status_for(session, w, h, a) == "stale"
    session.expire_all()
    assert projected(session, case)[3]["decision"] == "accepted"


def test_database_review_history_is_immutable(session, case):
    review(session, case)
    row = session.scalar(select(WorkspaceHandoffReview))
    for statement in (
        "UPDATE workspace_handoff_reviews SET decision='changes_requested',feedback='changed' WHERE id=:id",
        "DELETE FROM workspace_handoff_reviews WHERE id=:id",
    ):
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(text(statement), {"id": row.id})


@pytest.mark.parametrize("fault", ["hash", "agent", "attempt", "source", "space", "tab", "newline"])
def test_database_refuses_unbound_review_inserts(session, case, fault):
    w, h, a, _ = projected(session, case)
    admission, reply, versions = reviews._binding(session, w, h, a)
    values = dict(
        workspace_id=w.id,
        box_id=w.box_id,
        owner_id=w.owner_id,
        handoff_id=h.id,
        attempt_id=a.id,
        result_entry_id=a.result_entry_id,
        agent_id=reply.agent_id,
        result_sha256=case[6],
        source_sha256=admission.source_sha256,
        source_versions=deepcopy(versions),
        expected_revision=w.revision,
        workspace_revision=w.revision + 1,
        decision="accepted",
        feedback="",
        request_hash="a" * 64,
        idempotency_key="forged-db-review",
    )
    if fault == "hash":
        values["result_sha256"] = "0" * 64
    if fault == "agent":
        values["agent_id"] = case[1]
    if fault == "attempt":
        values["attempt_id"] = str(uuid4())
    if fault in {"space", "tab", "newline"}:
        values["decision"] = "changes_requested"
        values["feedback"] = {"space": "   ", "tab": "\t", "newline": "\n"}[fault]
    if fault == "source":
        values["source_versions"] = [
            {
                "entry_id": str(uuid4()),
                "revision": 1,
                "label": "Invented forged source",
                "kind": "evidence",
                "sha256": "b" * 64,
            }
        ]
    with pytest.raises(DBAPIError), session.begin_nested():
        session.get(EncounterWorkspace, case[2]["id"]).revision += 1
        session.flush()
        session.add(WorkspaceHandoffReview(**values))
        session.flush()


def test_two_concurrent_reviewers_commit_one_exact_review(engine, model):
    with Session(engine) as s:
        seed = svc.provision_box(svc.Container(s), "Invented review concurrency")
        prepared = shared.prepare(s, seed)
        shared.assign(s, prepared)
        assert shared.worker(s)
        box, owner, w, config, patient = prepared
        current = ws.read(s, box, owner, w["id"])
        h = current["handoffs"][0]
        reply = s.get(WorkspaceReply, h["result_entry_id"])
        case = (
            box,
            owner,
            current,
            config,
            patient,
            h,
            hashlib.sha256(reply.content.encode()).hexdigest(),
        )
    barrier = Barrier(2)

    def run(_):
        with Session(engine) as s:
            barrier.wait()
            return review(s, case)["entry_revision"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(run, range(2)))) == 1
    with Session(engine) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(WorkspaceHandoffReview)
                .where(WorkspaceHandoffReview.workspace_id == w["id"])
            )
            == 1
        )
        assert projected(s, case)[3]["decision"] == "accepted"


def test_closed_schema_requires_human_feedback_and_rejects_actor_override(case):
    body = dict(
        expected_revision=case[2]["revision"],
        idempotency_key="api-review-001",
        attempt_id=case[5]["attempt_id"],
        result_entry_id=case[5]["result_entry_id"],
        result_sha256=case[6],
        decision="accepted",
    )
    assert HandoffReview.model_validate(body).feedback == ""
    for changes in (
        {"actor_id": case[1]},
        {"decision": "changes_requested"},
        {"expected_revision": True},
        {"feedback": "x" * 2001},
    ):
        with pytest.raises(ValidationError):
            HandoffReview.model_validate({**body, **changes})


def test_api_contract_review_is_explicit_and_idempotent(session, case, monkeypatch):
    async def paused_worker(factory, stop, *, progress=None):
        await stop.wait()

    monkeypatch.setattr(handoffs, "run_worker", paused_worker)
    api_module.app.dependency_overrides[api_module.get_session] = request_sessions(session)
    try:
        with TestClient(api_module.app) as client:
            monkeypatch.setattr(client, "request", isolate_http_request(client, session))
            route = f"/workspaces/{case[2]['id']}/handoffs/{case[5]['id']}/review"
            headers = {
                "X-Box-Id": case[0],
                "X-Actor-Principal-Id": case[1],
                "X-Cosmas-Model-Contract": "1",
                "X-Cosmas-Handoff-Review": "1",
            }
            body = dict(
                expected_revision=case[2]["revision"],
                idempotency_key="api-review-001",
                attempt_id=case[5]["attempt_id"],
                result_entry_id=case[5]["result_entry_id"],
                result_sha256=case[6],
                decision="accepted",
            )
            missing = {k: v for k, v in headers.items() if k != "X-Cosmas-Handoff-Review"}
            assert client.post(route, headers=missing, json=body).status_code == 426
            assert (
                client.post(
                    route, headers=headers, json={**body, "actor_id": "PRIVATE INVALID"}
                ).status_code
                == 422
            )
            response = client.post(route, headers=headers, json=body)
            assert response.status_code == 200, response.text
            replay = client.post(route, headers=headers, json=body)
            assert replay.status_code == 200, replay.text
            assert replay.json()["entry_revision"] == response.json()["entry_revision"]
            session.expire_all()
            assert "os_capture_owner" not in session.info
            assert projected(session, case)[3]["decision"] == "accepted"
    finally:
        api_module.app.dependency_overrides.clear()


def changes_requested(s, case):
    result = review(
        s,
        case,
        decision="changes_requested",
        feedback="Retain the missing detail and make the next action explicit.",
    )
    return result, projected(s, case)[3]


def revise(s, case, response, receipt, **changes):
    return revisions.reserve(
        s,
        case[0],
        case[1],
        case[2]["id"],
        case[5]["id"],
        **{
            "expected": response["workspace"]["revision"],
            "key": "human-revision-001",
            "review_id": receipt["id"],
            **changes,
        },
    )


def test_explicit_revision_queues_fresh_same_recipient_with_full_quoted_result(
    session, case, model
):
    response, receipt = changes_requested(session, case)
    before = len(model)
    result = revise(session, case, response, receipt)
    assert len(model) == before
    assert result["entry_revision"] == response["workspace"]["revision"] + 1
    assert result["workspace"]["revision"] == result["entry_revision"] + 1
    fresh = session.get(WorkspaceHandoff, result["revision_handoff_id"])
    assert fresh.recipient_agent_id == case[5]["recipient_agent_id"] and fresh.id != case[5]["id"]
    origin = session.get(WorkspaceEntry, fresh.origin_entry_id)
    assert origin.kind == "conversation" and session.get(WorkspaceReply, origin.id) is None
    attempt = session.scalar(
        select(WorkspaceHandoffAttempt).where(WorkspaceHandoffAttempt.handoff_id == fresh.id)
    )
    row = session.scalar(
        select(ModelWorkAdmission).where(ModelWorkAdmission.handoff_attempt_id == attempt.id)
    )
    assert attempt.status == "queued" and attempt.number == 1 and row.state == "reserved"
    assert row.request_body["task_brief"]["depends_on"] == {
        "entry_id": origin.id,
        "revision": origin.revision,
    }
    old = session.scalar(
        select(ModelWorkAdmission).where(
            ModelWorkAdmission.handoff_attempt_id == case[5]["attempt_id"]
        )
    )
    assert (
        row.request_body["task_brief"]["source_versions"]
        == old.request_body["task_brief"]["source_versions"]
    )
    assert row.request_body["revision_request"]["feedback"] == receipt["feedback"]
    assert (
        session.get(WorkspaceReply, receipt["result_entry_id"]).content
        in row.prepared_envelope["context"]["question"]
    )
    assert len(row.prepared_envelope["context"]["question"]) <= 12000
    assert projected(session, case)[3]["revision_handoff_id"] == fresh.id
    assert (
        revisions.revision_for(session, session.get(EncounterWorkspace, fresh.workspace_id), fresh)[
            "revision_request"
        ]
        == row.request_body["revision_request"]
    )


def test_revision_lost_response_replay_never_creates_second_assignment(session, case):
    response, receipt = changes_requested(session, case)
    first = revise(session, case, response, receipt)
    session.expire_all()
    second = revise(session, case, response, receipt)
    assert second["revision_handoff_id"] == first["revision_handoff_id"]
    assert second["entry_revision"] == first["entry_revision"]
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffRevision)
            .where(WorkspaceHandoffRevision.workspace_id == case[2]["id"])
        )
        == 1
    )
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        revise(session, case, response, receipt, expected=first["workspace"]["revision"])
    with pytest.raises(ws.WorkspaceError, match="handoff_revision_already_requested"):
        revise(
            session,
            case,
            response,
            receipt,
            expected=first["workspace"]["revision"],
            key="another-revision-key",
        )


def test_revised_draft_can_receive_new_exact_review_and_another_explicit_revision(
    session, case, model
):
    response, receipt = changes_requested(session, case)
    first = revise(session, case, response, receipt)
    assert shared.worker(session)
    current = ws.read(session, case[0], case[1], case[2]["id"])
    fresh = next(h for h in current["handoffs"] if h["id"] == first["revision_handoff_id"])
    assert fresh["status"] == "completed"
    assert "task_brief" in fresh and not fresh.get("task_brief_unavailable")
    result_hash = hashlib.sha256(
        session.get(WorkspaceReply, fresh["result_entry_id"]).content.encode()
    ).hexdigest()
    new_case = case[0], case[1], current, case[3], case[4], fresh, result_hash
    reviewed = review(
        session,
        new_case,
        key="second-human-review",
        decision="changes_requested",
        feedback="One more invented correction.",
    )
    new_receipt = projected(session, new_case)[3]
    assert new_receipt["decision"] == "changes_requested" and new_receipt["id"] != receipt["id"]
    revised_again = revise(session, new_case, reviewed, new_receipt, key="second-human-revision")
    assert revised_again["revision_handoff_id"] not in {first["revision_handoff_id"], case[5]["id"]}
    assert len(model) == 3


@pytest.mark.parametrize(
    "fault", ["accepted", "source_changed", "wrong_review", "agent", "foreign_human"]
)
def test_revision_requires_current_same_owner_changes_requested_receipt(session, case, fault):
    response, receipt = (
        changes_requested(session, case)
        if fault != "accepted"
        else (review(session, case), projected(session, case)[3])
    )
    if fault == "source_changed":
        ws.append(
            session,
            case[0],
            case[1],
            case[2]["id"],
            expected=response["workspace"]["revision"],
            key="source-before-revise",
            kind="scratchpad",
            content="Invented current correction.",
        )
    if fault in {"agent", "foreign_human"}:
        actor = case[5]["recipient_agent_id"]
        if fault == "foreign_human":
            person = Principal(
                box_id=case[0], principal_type="human", display_name="Other invented owner"
            )
            session.add(person)
            session.commit()
            actor = person.id
        with pytest.raises(ws.WorkspaceError):
            revisions.reserve(
                session,
                case[0],
                actor,
                case[2]["id"],
                case[5]["id"],
                expected=response["workspace"]["revision"],
                key="human-revision-001",
                review_id=receipt["id"],
            )
    else:
        with pytest.raises(ws.WorkspaceError):
            revise(
                session,
                case,
                response,
                receipt,
                **({"review_id": str(uuid4())} if fault == "wrong_review" else {}),
            )
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffRevision)
            .where(WorkspaceHandoffRevision.workspace_id == case[2]["id"])
        )
        == 0
    )


def test_revision_never_truncates_overlarge_previous_result(session, case, monkeypatch):
    response, receipt = changes_requested(session, case)
    monkeypatch.setattr(revisions, "revision_question", lambda *args: "x" * 12000)
    with pytest.raises(ws.WorkspaceError, match="handoff_revision_too_large"):
        revise(session, case, response, receipt)
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffRevision)
            .where(WorkspaceHandoffRevision.workspace_id == case[2]["id"])
        )
        == 0
    )
    assert (
        session.get(EncounterWorkspace, case[2]["id"], populate_existing=True).revision
        == response["workspace"]["revision"]
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoff)
            .where(WorkspaceHandoff.workspace_id == case[2]["id"])
        )
        == 1
    )


def test_revision_link_is_immutable_database_history(session, case):
    response, receipt = changes_requested(session, case)
    revise(session, case, response, receipt)
    link = session.scalar(select(WorkspaceHandoffRevision))
    for statement in (
        "UPDATE workspace_handoff_revisions SET review_id=:other WHERE id=:id",
        "DELETE FROM workspace_handoff_revisions WHERE id=:id",
    ):
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(text(statement), {"id": link.id, "other": str(uuid4())})


def test_two_concurrent_revision_requests_reserve_once(engine, model):
    with Session(engine) as s:
        seed = svc.provision_box(svc.Container(s), "Invented revision concurrency")
        prepared = shared.prepare(s, seed)
        shared.assign(s, prepared)
        assert shared.worker(s)
        box, owner, workspace, config, patient = prepared
        current = ws.read(s, box, owner, workspace["id"])
        h = current["handoffs"][0]
        result_hash = hashlib.sha256(
            s.get(WorkspaceReply, h["result_entry_id"]).content.encode()
        ).hexdigest()
        case = box, owner, current, config, patient, h, result_hash
        response, receipt = changes_requested(s, case)
    barrier = Barrier(2)

    def run(_):
        with Session(engine) as s:
            barrier.wait()
            return revise(s, case, response, receipt)["revision_handoff_id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(run, range(2)))) == 1
    with Session(engine) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(WorkspaceHandoffRevision)
                .where(WorkspaceHandoffRevision.workspace_id == workspace["id"])
            )
            == 1
        )
        # These rows are committed independently of the usual per-test outer transaction.
        # Consume the reserved child so the next test's global worker cannot select it.
        assert shared.worker(s)
        link = s.scalar(
            select(WorkspaceHandoffRevision).where(
                WorkspaceHandoffRevision.workspace_id == workspace["id"]
            )
        )
        child = ws.read(s, box, owner, workspace["id"])["handoffs"]
        assert (
            next(h for h in child if h["id"] == link.revision_handoff_id)["status"] == "completed"
        )


def test_revision_schema_accepts_only_explicit_human_receipt_selection():
    body = dict(expected_revision=1, idempotency_key="revision-schema", review_id=str(uuid4()))
    assert HandoffRevision.model_validate(body).expected_revision == 1
    with pytest.raises(ValidationError):
        HandoffRevision.model_validate({**body, "feedback": "Override review"})


@pytest.mark.parametrize(
    "fault", ["agent_disabled", "chief_disabled", "team_changed", "restricted"]
)
@pytest.mark.parametrize("previous_review", [False, True])
def test_current_team_and_agent_authority_required_for_current_review(
    session, case, fault, previous_review, monkeypatch
):
    if previous_review:
        review(session, case)
    if fault in {"agent_disabled", "chief_disabled"}:
        actor = (
            case[5]["recipient_agent_id"]
            if fault == "agent_disabled"
            else session.get(WorkspaceHandoff, case[5]["id"]).issuer_agent_id
        )
        session.get(Principal, actor).state = "disabled"
        session.commit()
    else:
        config = deepcopy(case[3]["configuration"])
        if fault == "restricted":
            config["bots"][0]["blocked_capabilities"] = ["private_draft_handoff"]
        else:
            config["practice_context"] = "Invented changed practice context"
        setup = None
        if fault == "restricted":
            monkeypatch.setattr(team.runtime_settings, "workspace_team_setup_enabled", True)
            setup = team_setup.rehearsal(
                session, case[0], case[1], None, expected=1, configuration=config, contract=1
            )["setup_review"]
        team.save(
            session,
            case[0],
            case[1],
            expected=1,
            key="changed-authority-team",
            configuration=config,
            setup_review=setup,
            team_contract=1,
        )
    w, h, a, receipt = projected(session, case)
    assert receipt is None
    assert reviews.review_status_for(session, w, h, a) == (
        "stale" if previous_review else "not_reviewed"
    )
    with pytest.raises(ws.WorkspaceError):
        review(session, case, expected=w.revision, key="current-authority-review")
    assert session.scalar(
        select(func.count())
        .select_from(WorkspaceHandoffReview)
        .where(WorkspaceHandoffReview.workspace_id == case[2]["id"])
    ) == int(previous_review)


def test_three_revisions_limit_is_explicit_and_existing_receipts_still_readable(session, case):
    current_case = case
    for depth in range(3):
        response = review(
            session,
            current_case,
            key=f"depth-review-{depth}",
            decision="changes_requested",
            feedback="Invented correction.",
        )
        receipt = projected(session, current_case)[3]
        revised = revise(session, current_case, response, receipt, key=f"depth-revise-{depth}")
        assert shared.worker(session)
        current = ws.read(session, case[0], case[1], case[2]["id"])
        h = next(h for h in current["handoffs"] if h["id"] == revised["revision_handoff_id"])
        assert h["status"] == "completed" and not h.get("task_brief_unavailable")
        current_case = (
            case[0],
            case[1],
            current,
            case[3],
            case[4],
            h,
            hashlib.sha256(
                session.get(WorkspaceReply, h["result_entry_id"]).content.encode()
            ).hexdigest(),
        )
    response = review(
        session,
        current_case,
        key="depth-final-review",
        decision="changes_requested",
        feedback="Needs a fresh assignment context.",
    )
    receipt = projected(session, current_case)[3]
    assert receipt["decision"] == "changes_requested"
    with pytest.raises(ws.WorkspaceError, match="handoff_revision_limit"):
        revise(session, current_case, response, receipt, key="depth-fourth-request")
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffRevision)
            .where(WorkspaceHandoffRevision.workspace_id == case[2]["id"])
        )
        == 3
    )
    assert projected(session, case)[3]["decision"] == "changes_requested"


@pytest.fixture
def signed_case(signed_workspace, session, model, monkeypatch):
    f = signed_workspace
    monkeypatch.setitem(
        api_module.app.dependency_overrides, api_module.get_session, request_sessions(session)
    )
    monkeypatch.setattr(f.client, "request", isolate_http_request(f.client, session))
    f.configuration.workspace_team_setup_enabled = True
    f.configuration.workspace_prep_enabled = True
    f.configuration.workspace_llm_backend = "azure_gpt41"
    f.configuration.workspace_llm_api_key = conversation.runtime_settings.workspace_llm_api_key
    for module in (team, conversation, handoffs):
        monkeypatch.setattr(module, "runtime_settings", f.configuration)
    config = team.save(
        session,
        f.box,
        f.actor,
        expected=0,
        key="signed-review-team",
        configuration=team.default_configuration(),
    )
    prepared = f.box, f.actor, f.workspace, config, f.appointment.patient_link_id
    shared.assign(session, prepared)
    assert shared.worker(session)
    current = ws.read(session, f.box, f.actor, f.workspace["id"])
    h = current["handoffs"][0]
    f.base = f"/workspaces/{f.workspace['id']}/handoffs/{h['id']}"
    f.headers = {
        "Authorization": "Bearer " + f.token(),
        "X-Cosmas-Model-Contract": "1",
        "X-Cosmas-Handoff-Review": "1",
    }
    f.review_body = dict(
        expected_revision=current["revision"],
        idempotency_key="signed-human-review",
        attempt_id=h["attempt_id"],
        result_entry_id=h["result_entry_id"],
        result_sha256=hashlib.sha256(
            session.get(WorkspaceReply, h["result_entry_id"]).content.encode()
        ).hexdigest(),
        decision="changes_requested",
        feedback="Make the invented next action explicit.",
    )
    f.case = (
        f.box,
        f.actor,
        current,
        config,
        f.appointment.patient_link_id,
        h,
        f.review_body["result_sha256"],
    )
    return f


def signed_revision_body(f):
    saved = f.client.post(f.base + "/review", headers=f.headers, json=f.review_body)
    assert saved.status_code == 200, saved.text
    h = next(h for h in saved.json()["workspace"]["handoffs"] if h["id"] == f.case[5]["id"])
    return dict(
        expected_revision=saved.json()["workspace"]["revision"],
        idempotency_key="signed-human-revision",
        review_id=h["review"]["id"],
    )


@pytest.mark.parametrize("persona", ["provider", "nurse", "pa"])
def test_signed_human_two_run_review_revision_loop_exact_retry_and_reopen(
    signed_case, session, persona
):
    f = signed_case
    before = {
        t: session.scalar(select(func.count()).select_from(t))
        for t in (Ticket, Decision, Operation)
    }
    f.review_body["feedback"] = f"Invented {persona} review: preserve what remains unknown."
    body = signed_revision_body(f)
    first = f.client.post(f.base + "/revision", headers=f.headers, json=body)
    assert first.status_code == 200, first.text
    session.expire_all()
    replay_headers = {**f.headers, "Authorization": "Bearer " + f.token(sid="session_reopened")}
    replay = f.client.post(f.base + "/revision", headers=replay_headers, json=body)
    assert (
        replay.status_code == 200
        and replay.json()["revision_handoff_id"] == first.json()["revision_handoff_id"]
    )
    assert replay.json()["entry_revision"] == first.json()["entry_revision"]
    assert shared.worker(session)
    current = f.client.get(f"/workspaces/{f.workspace['id']}", headers=replay_headers)
    assert current.status_code == 200, current.text
    h = next(
        h for h in current.json()["handoffs"] if h["id"] == first.json()["revision_handoff_id"]
    )
    assert (
        h["status"] == "completed"
        and h["revision_request"]["feedback"] == f.review_body["feedback"]
    )
    second_body = dict(
        expected_revision=current.json()["revision"],
        idempotency_key="signed-final-acceptance",
        attempt_id=h["attempt_id"],
        result_entry_id=h["result_entry_id"],
        result_sha256=h["result_sha256"],
        decision="accepted",
    )
    accepted = f.client.post(
        f"/workspaces/{f.workspace['id']}/handoffs/{h['id']}/review",
        headers=replay_headers,
        json=second_body,
    )
    assert accepted.status_code == 200, accepted.text
    final = next(x for x in accepted.json()["workspace"]["handoffs"] if x["id"] == h["id"])
    assert final["review"]["decision"] == "accepted" and final["review_status"] == "current"
    assert before == {t: session.scalar(select(func.count()).select_from(t)) for t in before}
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffRevision)
            .where(WorkspaceHandoffRevision.workspace_id == f.workspace["id"])
        )
        == 1
    )


@pytest.mark.parametrize("path", ["review", "revision"])
@pytest.mark.parametrize(
    "fault",
    [
        "missing_review",
        "duplicate_review",
        "missing_model",
        "query",
        "duplicate_json",
        "extra",
        "wrong_scope",
    ],
)
def test_signed_routes_reject_unnegotiated_unbounded_or_foreign_requests(
    signed_case, session, path, fault
):
    f = signed_case
    body = f.review_body if path == "review" else signed_revision_body(f)
    headers = dict(f.headers)
    route = f.base + "/" + path
    payload = json.dumps(body)
    if fault == "missing_review":
        headers.pop("X-Cosmas-Handoff-Review")
    elif fault == "duplicate_review":
        headers["X-Cosmas-Handoff-Review"] = "1, 1"
    elif fault == "missing_model":
        headers.pop("X-Cosmas-Model-Contract")
    elif fault == "query":
        route += "?actor=other"
    elif fault == "duplicate_json":
        payload = payload[:-1] + ',"expected_revision":1}'
    elif fault == "extra":
        payload = payload[:-1] + ',"actor_id":"not-authorized"}'
    else:
        route = route.replace(f.workspace["id"], str(uuid4()))
    response = f.client.post(
        route, headers={**headers, "Content-Type": "application/json"}, content=payload
    )
    expected = (
        426
        if fault in {"missing_review", "duplicate_review", "missing_model"}
        else 404
        if fault == "wrong_scope"
        else 422
    )
    assert response.status_code == expected, response.text
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffRevision)
            .where(WorkspaceHandoffRevision.workspace_id == f.workspace["id"])
        )
        == 0
    )
    assert session.scalar(
        select(func.count())
        .select_from(WorkspaceHandoffReview)
        .where(WorkspaceHandoffReview.workspace_id == f.workspace["id"])
    ) == int(path == "revision")


@pytest.mark.parametrize("path", ["review", "revision"])
def test_signed_revoked_identity_denies_result_review_and_revision(signed_case, session, path):
    f = signed_case
    body = f.review_body if path == "review" else signed_revision_body(f)
    f.binding.active = False
    session.commit()
    response = f.client.post(f.base + "/" + path, headers=f.headers, json=body)
    assert response.status_code == 403, response.text
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffRevision)
            .where(WorkspaceHandoffRevision.workspace_id == f.workspace["id"])
        )
        == 0
    )


def test_review_reauthenticates_after_owner_lock_and_before_commit(session, case):
    phases = []
    result = review(session, case, reauthenticate=lambda: phases.append("checked"))
    assert result["entry_revision"] == case[2]["revision"] + 1 and phases == ["checked", "checked"]


def test_precommit_revoked_identity_rolls_back_review_receipt_and_revision(session, case):
    identity = ExternalIdentity(
        box_id=case[0],
        principal_id=case[1],
        provider="clerk",
        issuer="https://review.example.invalid",
        subject="invented-review",
        organization_id="org_invented",
        reviewed_by="Invented reviewer",
        evidence_ref="test:review-reauthentication",
    )
    session.add(identity)
    session.commit()
    checks = []

    def revoke():
        checks.append("checked")
        if len(checks) == 2:
            identity.active = False
            session.flush()

    with pytest.raises(ws.WorkspaceError, match="workspace_access_denied"):
        review(session, case, external_identity_id=identity.id, reauthenticate=revoke)
    assert checks == ["checked", "checked"]
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffReview)
            .where(WorkspaceHandoffReview.workspace_id == case[2]["id"])
        )
        == 0
    )
    assert (
        session.get(EncounterWorkspace, case[2]["id"], populate_existing=True).revision
        == case[2]["revision"]
    )


@pytest.mark.parametrize("decision", ["accepted", "changes_requested"])
def test_lost_review_reply_recovers_original_receipt_after_source_change_without_authorizing_revision(
    session, case, decision
):
    feedback = "Retain unknown facts." if decision == "changes_requested" else ""
    saved = review(session, case, decision=decision, feedback=feedback)
    w, h, a, current = projected(session, case)
    saved_id = current["id"]
    changed = ws.append(
        session,
        case[0],
        case[1],
        case[2]["id"],
        expected=saved["workspace"]["revision"],
        key="later-source-after-lost-review",
        kind="scratchpad",
        content="Invented changed source after the response was lost.",
    )
    latest_revision = changed["workspace"]["revision"]
    session.expire_all()
    replay = review(session, case, decision=decision, feedback=feedback)
    assert replay["entry_revision"] == saved["entry_revision"]
    assert replay["workspace"]["revision"] == latest_revision
    w, h, a, current = projected(session, case)
    assert current is None and reviews.review_status_for(session, w, h, a) == "stale"
    assert reviews.stored_review_for(session, w, h, a)["id"] == saved_id
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffReview)
            .where(WorkspaceHandoffReview.workspace_id == w.id)
        )
        == 1
    )
    with pytest.raises(ws.WorkspaceError, match="handoff_revision_stale"):
        revisions.reserve(
            session,
            case[0],
            case[1],
            w.id,
            h.id,
            expected=latest_revision,
            key="never-revise-stale-review",
            review_id=saved_id,
        )
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffRevision)
            .where(WorkspaceHandoffRevision.workspace_id == w.id)
        )
        == 0
    )


def test_stored_revised_result_review_retains_exact_recursive_provenance_after_source_change(
    session, case
):
    response, receipt = changes_requested(session, case)
    reserved = revise(session, case, response, receipt)
    assert shared.worker(session)
    current = ws.read(session, case[0], case[1], case[2]["id"])
    fresh = next(h for h in current["handoffs"] if h["id"] == reserved["revision_handoff_id"])
    new_case = (
        case[0],
        case[1],
        current,
        case[3],
        case[4],
        fresh,
        hashlib.sha256(
            session.get(WorkspaceReply, fresh["result_entry_id"]).content.encode()
        ).hexdigest(),
    )
    accepted = review(session, new_case, key="revised-exact-acceptance")
    w, h, a, receipt = projected(session, new_case)
    ws.append(
        session,
        case[0],
        case[1],
        w.id,
        expected=accepted["workspace"]["revision"],
        key="changed-after-revised-review",
        kind="scratchpad",
        content="Invented later correction.",
    )
    session.expire_all()
    again = review(session, new_case, key="revised-exact-acceptance")
    assert again["entry_revision"] == accepted["entry_revision"]
    w, h, a, _ = projected(session, new_case)
    assert reviews.stored_review_for(session, w, h, a)["id"] == receipt["id"]
    assert reviews.review_for(session, w, h, a) is None
    assert reviews.result_recovery_digest(session, w, h, a) == new_case[6]


@pytest.mark.parametrize("projection", [{}, {"task_brief_unavailable": True}])
def test_unverified_completion_projection_never_invents_result_digest(session, case, monkeypatch, projection):
    from cosmas_os.application import handoff_briefs

    assert case[5]["result_sha256"] == case[6]
    monkeypatch.setattr(handoff_briefs, "projection", lambda *args, **kwargs: deepcopy(projection))
    current = ws.read(session, case[0], case[1], case[2]["id"])
    selected = next(h for h in current["handoffs"] if h["id"] == case[5]["id"])
    assert selected["result_sha256"] is None
    assert "completion_evidence" not in selected


@pytest.mark.parametrize("fault", ["foreign_workspace", "foreign_owner", "wrong_handoff", "old_attempt", "not_completed", "missing_result", "wrong_agent", "corrupt_envelope"])
def test_historical_result_digest_rejects_missing_or_corrupt_binding(session, case, fault):
    from copy import copy

    w, h, a, _ = projected(session, case)
    assert reviews.result_recovery_digest(session, w, h, a) == case[6]
    selected_w, selected_h, selected_a = copy(w), copy(h), copy(a)
    if fault == "foreign_workspace":
        selected_w.id = str(uuid4())
    if fault == "foreign_owner":
        selected_w.owner_id = str(uuid4())
    if fault == "wrong_handoff":
        selected_h.id = str(uuid4())
    if fault == "old_attempt":
        selected_a.id = str(uuid4())
    if fault == "not_completed":
        selected_a.status = "running"
    if fault == "missing_result":
        selected_a.result_entry_id = None
    if fault == "wrong_agent":
        selected_h.recipient_agent_id = str(uuid4())
    row = session.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.handoff_attempt_id == a.id))
    original = row.envelope_sha256
    try:
        if fault == "corrupt_envelope":
            row.envelope_sha256 = "0" * 64
        with session.no_autoflush:
            assert reviews.result_recovery_digest(session, selected_w, selected_h, selected_a) is None
    finally:
        row.envelope_sha256 = original
