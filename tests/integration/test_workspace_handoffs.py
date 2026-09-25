from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from cosmas_os.adapters.gpt41 import _context
from cosmas_os.api import app as api_module
from cosmas_os.application import conversation, handoffs, model_work
from cosmas_os.application import provider_team as team
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    AppointmentObservation,
    Decision,
    ModelWorkAdmission,
    Operation,
    PatientLink,
    Principal,
    Ticket,
    WorkspaceEntry,
    WorkspaceHandoff,
    WorkspaceHandoffAttempt,
    WorkspaceReply,
)
from cosmas_os.ports.bot_capabilities import BotReply, DraftBrief, ModelCallFailure


def prepare(s, seed):
    box, owner = seed["box_id"], seed["owner_id"]
    link = PatientLink(
        box_id=box,
        source_pair_key="handoff:" + str(uuid4()),
        label="Invented handoff",
        state="confirmed",
        confirmed_by_principal_id=owner,
        attested_at=datetime.now(UTC),
    )
    s.add(link)
    s.flush()
    appointment = AppointmentObservation(
        box_id=box,
        patient_link_id=link.id,
        external_id=str(uuid4()),
        source="synthetic",
        start_at=datetime.now(UTC),
        patient_label="Invented handoff",
    )
    s.add(appointment)
    s.commit()
    w = ws.create(s, box, owner, appointment.id, "create-handoff")
    config = team.save(
        s, box, owner, expected=0, key="team", configuration=team.default_configuration()
    )
    return box, owner, w, config, link.id


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(conversation.runtime_settings, "workspace_enabled", True)
    monkeypatch.setattr(conversation.runtime_settings, "workspace_llm_backend", "azure_gpt41")
    monkeypatch.setattr(
        conversation.runtime_settings, "workspace_llm_api_key", SecretStr("invented-test-only")
    )
    calls = []

    def review(context):
        calls.append(context)
        if context.role == "chief" and context.handoff_roles:
            return BotReply(
                "Queuing a draft.",
                context.sources,
                "azure_gpt41",
                handoffs=(DraftBrief("scribe", "Organize a draft from saved sources."),),
            )
        backend = (
            "azure_gpt41_source_draft_v1"
            if context.draft_only and context.role == "scribe"
            else "azure_gpt41"
        )
        return BotReply("Invented draft for human review.", context.sources, backend)

    monkeypatch.setattr(model_work, "dispatch_claim", lambda claim: review(_context(claim.envelope["context"])))
    return calls


@pytest.fixture
def case(session, seeded, model):
    return prepare(session, seeded)


def assign(s, case, **kwargs):
    box, owner, w, config, _ = case
    result = conversation.ask(
        s,
        box,
        owner,
        w["id"],
        **{
            "model_contract": True,
            "expected": 1,
            "team_revision": config["revision"],
            "role": "chief",
            "content": "Ask Scribe to organize a private draft.",
            **kwargs,
            "key": str(kwargs.get("key", "invented-question")).ljust(8, "_"),
        },
    )

    assert result["outcome"] == "saved", result
    entry = result["saved_entry"]
    return {"entry_id": entry["id"], "entry_revision": entry["revision"],
            "workspace": ws.read(s,box,owner,w["id"])}


def worker(s):
    @contextmanager
    def factory():
        yield s

    return handoffs.process_next(factory)


def test_delivery_is_durable_attributed_idempotent_and_has_no_external_actions(
    session, case, model
):
    before = [
        session.scalar(select(func.count()).select_from(t)) for t in (Ticket, Decision, Operation)
    ]
    result = assign(session, case)
    h = result["workspace"]["handoffs"][0]
    assert h["status"] == "queued" and h["context_revision"] == 1
    assert assign(session, case)["entry_id"] == result["entry_id"] and len(model) == 1
    assert worker(session)
    box, owner, w, config, _ = case
    updated = ws.read(session, box, owner, w["id"])
    h = updated["handoffs"][0]
    assert h["status"] == "completed" and h["attempt_count"] == 1
    entry = updated["entries"][-1]
    assert entry["id"] == h["result_entry_id"] and entry["kind"] == "handoff_result"
    assert entry["origin"] == "agent_handoff" and entry["reply"]["role"] == "scribe"
    stored = session.get(WorkspaceReply, entry["id"])
    assert stored.agent_id == next(
        b["agent_id"] for b in config["members"] if b["role"] == "scribe"
    )
    assert model[-1].handoff_roles == () and model[-1].context_revision == 1
    assert not worker(session) and len(model) == 2
    assert before == [
        session.scalar(select(func.count()).select_from(t)) for t in (Ticket, Decision, Operation)
    ]


@pytest.mark.parametrize("pause", [False, True, "retired"])
def test_chief_assigns_exact_same_template_instances_and_rechecks_configuration(session, case, monkeypatch, pause):
    box, owner, w, initial, _ = case
    config = deepcopy(initial["configuration"])
    address = str(uuid4())
    config["bots"].append({**config["bots"][0], "instance_id": address, "name": "Second Scribe"})
    installed = team.save(session, box, owner, expected=1, key="extra", configuration=config)
    calls = []
    def review(context):
        calls.append(context)
        return BotReply("Fixture draft", (), "azure_gpt41_source_draft_v1" if context.draft_only else "azure_gpt41",
                        handoffs=(DraftBrief("scribe", "Baseline draft"), DraftBrief(address, "Extra draft")) if context.role == "chief" else ())
    monkeypatch.setattr(model_work, "dispatch_claim", lambda claim: review(_context(claim.envelope["context"])))
    result = assign(session, case, team_revision=2)
    targets = {t["address"]: t for t in calls[0].handoff_targets}
    assert targets[address]["name"] == "Second Scribe" and targets[address]["role"] == "scribe"
    handoff_items = result["workspace"]["handoffs"]
    assert {h["recipient_key"] for h in handoff_items} == {"scribe", address}
    assert {h["recipient_role"] for h in handoff_items} == {"scribe"}
    assert len({h["recipient_agent_id"] for h in handoff_items}) == 2
    if pause:
        config["bots"][-1]["enabled"] = False
        if pause == "retired":
            config["bots"][-1]["retired"] = True
        team.save(session, box, owner, expected=2, key="pause", configuration=config)
    assert worker(session) and worker(session) and not worker(session)
    items = ws.read(session, box, owner, w["id"])["handoffs"]
    if pause:
        assert all(h["status"] == "failed" for h in items)
        assert len(calls) == 1
        if pause == "retired":
            retired_handoff = next(h for h in items if h["recipient_key"] == address)
            with pytest.raises(ws.WorkspaceError, match="team_revision_conflict"):
                handoffs.retry(session, box, owner, w["id"], retired_handoff["id"], expected=4,
                    previous_attempt=retired_handoff["attempt_id"], key="retired-retry")
            assert session.get(WorkspaceHandoff, retired_handoff["id"]).recipient_agent_id == installed["members"][-1]["agent_id"]
    else:
        assert all(h["status"] == "completed" for h in items)
        assert len(calls) == 3
        by_address = {team.bot_address(m): m["agent_id"] for m in installed["members"]}
        for item in items:
            assert session.get(WorkspaceReply, item["result_entry_id"]).agent_id == by_address[item["recipient_key"]]


def test_assignment_withholds_changed_saved_context(session, case, model):
    assign(session, case)
    box, owner, w, _, _ = case
    ws.append(
        session,
        box,
        owner,
        w["id"],
        expected=3,
        key="later-note",
        kind="scratchpad",
        content="Later text outside the assigned snapshot",
    )
    assert worker(session)
    current=ws.read(session,box,owner,w["id"])["handoffs"][0]
    assert current["status"]=="failed" and current["error_code"]=="source_changed"
    assert len(model)==1 and current["result_entry_id"] is None


def test_new_handoff_does_not_reuse_an_earlier_unreviewed_assistant_draft(session, case, model):
    assign(session, case, role="scribe", key="prior-draft")
    assign(session, case, expected=2)
    assert worker(session)
    assert model[-1].history == ()
    assert model[-1].draft_only


@pytest.mark.parametrize("change", ["owner", "recipient", "issuer", "link", "settings"])
def test_access_and_configuration_are_rechecked_before_delivery(session, case, model, change):
    result = assign(session, case)
    box, owner, _, config, link_id = case
    if change == "owner":
        session.get(Principal, owner).state = "disabled"
    elif change in {"recipient", "issuer"}:
        role = "scribe" if change == "recipient" else "chief"
        pid = next(m["agent_id"] for m in config["members"] if m["role"] == role)
        session.get(Principal, pid).state = "disabled"
    elif change == "link":
        session.get(PatientLink, link_id).revoked_at = datetime.now(UTC)
    else:
        settings = deepcopy(config["configuration"])
        settings["practice_context"] = "Changed since assignment"
        team.save(session, box, owner, expected=1, key="new-settings", configuration=settings)
    session.commit()
    assert worker(session)
    attempt = session.get(WorkspaceHandoffAttempt, result["workspace"]["handoffs"][0]["attempt_id"])
    assert attempt.status == "failed" and len(model) == 1
    assert attempt.result_entry_id is None


def test_recipient_source_exclusions_limit_chiefs_available_handoffs(session, case, model):
    box, owner, _, config, _ = case
    settings = deepcopy(config["configuration"])
    settings["bots"][0]["include_notebook"] = False
    team.save(session, box, owner, expected=1, key="exclude", configuration=settings)
    result=conversation.ask(session,box,owner,case[2]["id"],expected=1,team_revision=2,
        key="excluded-recipient",role="chief",content="Prepare an invented private draft",model_contract=True)
    assert result["outcome"]=="failed" and result["reason"]=="model_unavailable"
    assert not ws.read(session,box,owner,case[2]["id"])["handoffs"]
    assert "scribe" not in model[-1].handoff_roles
    session.rollback()


def test_failure_requires_explicit_bounded_retry_and_preserves_receipts(
    session, case, model, monkeypatch
):
    result = assign(session, case)
    box, owner, w, _, _ = case
    h = result["workspace"]["handoffs"][0]

    def unavailable(context):
        raise ModelCallFailure(dispatch="response_received", outcome="invalid_output")

    monkeypatch.setattr(model_work, "dispatch_claim", unavailable)
    assert worker(session)
    failed = ws.read(session, box, owner, w["id"])["handoffs"][0]
    assert failed["error_code"] == "model_unavailable" and "PRIVATE" not in str(failed)
    assert not worker(session)
    for number in (2, 3):
        args = dict(expected=number+1, previous_attempt=failed["attempt_id"], key=f"retry-request-{number}")
        r = handoffs.retry(session, box, owner, w["id"], h["id"], **args)
        assert r["recorded"]["attempt_number"] == number
        assert (
            handoffs.retry(session, box, owner, w["id"], h["id"], **args)["recorded"]["attempt_number"]
            == number
        )
        assert worker(session)
        failed = ws.read(session, box, owner, w["id"])["handoffs"][0]
    with pytest.raises(ws.WorkspaceError, match="handoff_limit"):
        handoffs.retry(
            session,
            box,
            owner,
            w["id"],
            h["id"],
            expected=5,
            previous_attempt=failed["attempt_id"],
            key="retry-request-4",
        )
    assert [a["status"] for a in failed["attempts"]] == ["failed"] * 3


def test_interrupted_attempt_is_visible_and_never_automatically_replayed(session, case, model):
    result = assign(session, case)
    h = result["workspace"]["handoffs"][0]
    attempt = session.get(WorkspaceHandoffAttempt, h["attempt_id"])
    admission=session.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.handoff_attempt_id==attempt.id))
    assert model_work.claim(session,attempt.box_id,attempt.owner_id,admission.id) is not None
    handoffs.recover_interrupted(session, now=datetime.now(UTC) + timedelta(seconds=180))
    assert attempt.status == "interrupted" and attempt.error_code == "dispatch_interrupted"
    assert not worker(session) and len(model) == 1
    box, owner, w, _, _ = case
    handoffs.retry(
        session, box, owner, w["id"], h["id"], expected=3, previous_attempt=attempt.id, key="resume-handoff"
    )
    assert worker(session)
    assert ws.read(session, box, owner, w["id"])["handoffs"][0]["status"] == "completed"


def test_database_rejects_rewritten_assignment_or_terminal_receipt(session, case):
    result = assign(session, case)
    h = result["workspace"]["handoffs"][0]
    assert worker(session)
    for sql, value in [
        ("UPDATE workspace_handoffs SET brief='replaced' WHERE id=:id", h["id"]),
        (
            "UPDATE workspace_handoff_attempts SET status='running', completed_at=NULL, result_entry_id=NULL WHERE id=:id",
            h["attempt_id"],
        ),
        ("DELETE FROM workspace_handoff_attempts WHERE id=:id", h["attempt_id"]),
    ]:
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(text(sql), {"id": value})


def test_other_owner_cannot_read_or_retry_private_handoff(session, case):
    result = assign(session, case)
    box, _, w, _, _ = case
    other = Principal(
        box_id=box, principal_type="human", display_name="Other invented owner", is_owner=True
    )
    session.add(other)
    session.commit()
    h = result["workspace"]["handoffs"][0]
    with pytest.raises(ws.WorkspaceError, match="workspace_unavailable"):
        handoffs.retry(
            session,
            box,
            other.id,
            w["id"],
            h["id"],
            expected=2,
            previous_attempt=h["attempt_id"],
            key="steal",
        )


def test_two_processors_publish_one_recipient_result(engine, model):
    with Session(engine) as s:
        seed = svc.provision_box(svc.Container(s), "Invented handoff concurrency")
        case = prepare(s, seed)
        result = assign(s, case)
    barrier = Barrier(2)

    def run(_):
        barrier.wait()
        return handoffs.process_next(lambda: Session(engine))

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, range(2)))
    assert sum(outcomes) == 1 and len(model) == 2
    with Session(engine) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(WorkspaceEntry)
                .where(
                    WorkspaceEntry.workspace_id == case[2]["id"],
                    WorkspaceEntry.kind == "handoff_result",
                )
            )
            == 1
        )
        attempt = s.get(WorkspaceHandoffAttempt, result["workspace"]["handoffs"][0]["attempt_id"])
        assert attempt.status == "completed"


def test_model_budget_reserves_queued_drafts_and_bounds_new_work(session, case, model):
    for revision in range(1, 50):
        assign(session, case, expected=revision, key=f"ordinary-{revision}", role="visit_prep")
    result = assign(session, case, expected=50, key="last-turn")
    assert model[-1].handoff_roles == () and result["workspace"]["handoffs"] == []
    assert handoffs.model_usage_count(session, case[2]["id"]) == 50
    with pytest.raises(ws.WorkspaceError, match="workspace_model_turn_limit"):
        assign(session, case, expected=51, key="over-budget", role="visit_prep")
    assert len(model) == 50


def test_database_handoff_scope_cannot_target_another_providers_bot(session, case):
    result = assign(session, case)
    seed = svc.provision_box(svc.Container(session), "Different invented practice")
    _, _, _, config, _ = prepare(session, seed)
    original = session.get(WorkspaceHandoff, result["workspace"]["handoffs"][0]["id"])
    values = {
        column.name: getattr(original, column.name)
        for column in WorkspaceHandoff.__table__.columns
        if column.name not in {"id", "created_at"}
    }
    values["recipient_role"] = "follow_up"
    values["recipient_agent_id"] = config["members"][0]["agent_id"]
    with pytest.raises(DBAPIError), session.begin_nested():
        session.add(WorkspaceHandoff(**values))
        session.flush()


def test_recovery_uses_dispatch_lease_without_holding_inference_locks(engine, model):
    with Session(engine) as s:
        seed = svc.provision_box(svc.Container(s), "Invented recovery concurrency")
        result = assign(s, prepare(s, seed))
        aid = result["workspace"]["handoffs"][0]["attempt_id"]
        a = s.get(WorkspaceHandoffAttempt, aid)
        admission=s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.handoff_attempt_id==aid))
        at=datetime.now(UTC)
        claimed=model_work.claim(s,a.box_id,a.owner_id,admission.id,clock=lambda:at)
    with Session(engine) as recovery:
        handoffs.recover_interrupted(recovery,now=at+timedelta(seconds=60))
        assert recovery.get(WorkspaceHandoffAttempt,aid).status=="running"
        handoffs.recover_interrupted(recovery,now=at+timedelta(seconds=91))
        assert recovery.get(WorkspaceHandoffAttempt,aid).status=="interrupted"
        model_work.settle(recovery,claimed,BotReply("Late private result",(),"azure_gpt41_source_draft_v1"),clock=lambda:at+timedelta(seconds=92))
        assert recovery.get(WorkspaceHandoffAttempt,aid).result_entry_id is None


def test_api_retry_scope_and_validation_do_not_echo_briefs(session, case, monkeypatch):
    result = assign(session, case)
    h = result["workspace"]["handoffs"][0]
    box, owner, w, _, _ = case

    async def paused_worker(factory, stop):
        await stop.wait()

    monkeypatch.setattr(handoffs, "run_worker", paused_worker)
    api_module.app.dependency_overrides[api_module.get_session] = lambda: session
    try:
        with TestClient(api_module.app) as client:
            route = f"/workspaces/{w['id']}/handoffs/{h['id']}/retry"
            headers = {"X-Box-Id": box, "X-Actor-Principal-Id": owner, "X-Cosmas-Model-Contract":"1"}
            response = client.post(
                route, headers=headers, json={"brief": "PRIVATE INVALID PAYLOAD"}
            )
            assert response.status_code == 422 and "PRIVATE" not in response.text
            body = {
                "expected_revision": 2,
                "previous_attempt_id": h["attempt_id"],
                "idempotency_key": "api-retry",
            }
            assert client.post(route, headers=headers, json=body).status_code == 409
            monkeypatch.setattr(api_module.settings, "workspace_enabled", False)
            assert client.post(route, headers=headers, json=body).status_code == 404
    finally:
        api_module.app.dependency_overrides.clear()


def test_disabled_workspace_never_processes_queued_work(monkeypatch):
    monkeypatch.setattr(handoffs.runtime_settings, "workspace_enabled", False)
    assert not handoffs.process_next(
        lambda: pytest.fail("A disabled workspace must not open a job session")
    )
