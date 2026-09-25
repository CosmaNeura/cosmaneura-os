from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from cosmas_os.api import app as api
from cosmas_os.application import conversation, provider_team
from cosmas_os.application import follow_up as follow
from cosmas_os.application import note_review as notes
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.domain.enums import DecisionKind
from cosmas_os.domain.rules import AuthorizationError, DomainError
from cosmas_os.models import (
    ActionRevision,
    AppointmentObservation,
    Decision,
    EncounterWorkspace,
    FollowUpReceipt,
    FollowUpSource,
    Operation,
    PatientLink,
    Principal,
)


@pytest.fixture(autouse=True)
def enable(monkeypatch):
    monkeypatch.setattr(api.settings, "workspace_enabled", True)


def prepare(s, seed):
    box, actor = seed["box_id"], seed["owner_id"]
    link = PatientLink(box_id=box, source_pair_key=str(uuid4()), label="Invented follow-up",
                       state="confirmed", confirmed_by_principal_id=actor, attested_at=datetime.now(UTC))
    s.add(link)
    s.flush()
    appt = AppointmentObservation(box_id=box, patient_link_id=link.id, external_id=str(uuid4()),
        source="synthetic", start_at=datetime.now(UTC), patient_label="Invented follow-up person")
    s.add(appt)
    s.commit()
    w = ws.create(s, box, actor, appt.id, "create-follow-up")
    w = notes.save(s, box, actor, w["id"], expected=1, key="private-note", base_note_id=None,
        source_reply_id=None, content="Private invented agenda; do not copy this sentence.")["workspace"]
    n = w["note"]["latest"]
    w = notes.review(s, box, actor, w["id"], n["id"], expected=2, key="review-follow-note",
        content_hash=n["content_hash"], source_hash=n["source_fingerprint"])["workspace"]
    return box, actor, w, link.id


@pytest.fixture
def case(session, seeded):
    return prepare(session, seeded)


def count(s, model, case):
    return s.scalar(select(func.count()).select_from(model).where(model.box_id == case[0]))


def propose(s, case, **changes):
    box, actor, w, _ = case
    return follow.propose(s, box, actor, w["id"], **{"expected": 3, "key": "propose-follow-up",
        "note_id": w["note"]["latest"]["id"], "body": "Invented invitation to confirm the next visit.",
        "due_date": date(2026, 9, 25), "expected_outcome": "The next visit is confirmed.", "share": True, **changes})


def decide(s, case, item, **changes):
    return follow.decide(s, case[0], case[1], case[2]["id"], item["ticket_id"],
        **{"revision_id": item["revision_id"], "digest": item["payload_hash"], "choice": "approve", **changes})


def complete(s, case, item, **changes):
    return follow.complete(s, case[0], case[1], case[2]["id"], item["ticket_id"],
        **{"revision_id": item["revision_id"], "digest": item["payload_hash"], "key": "completion-test",
            "evidence": "Invented person confirmed the proposed visit in the rehearsal.", **changes})


def test_private_provenance_shared_selected_text_and_exact_f8_loop(session, case):
    created = propose(session, case)
    item = created["workspace"]["follow_ups"][0]
    r = session.get(ActionRevision, item["revision_id"])
    assert r.content == item["body"] and "Private invented" not in str(r.payload)
    assert set(r.payload) == {"action", "channel", "body", "target_ref", "owner_id", "due_date", "expected_outcome"}
    assert count(session, Operation, case) == 0
    assert count(session, Decision, case) == 0
    assert propose(session, case)["workspace"]["follow_ups"][0]["ticket_id"] == item["ticket_id"]
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        propose(session, case, body="Changed payload")
    sent = decide(session, case, item)["workspace"]
    assert sent["revision"] == 6 and sent["follow_ups"][0]["state"] == "sent"
    assert [r["kind"] for r in sent["follow_ups"][0]["receipts"]] == ["local_delivery"]
    assert decide(session, case, item)["workspace"]["revision"] == 6
    closed = complete(session, case, item)["workspace"]
    assert closed["follow_ups"][0]["state"] == "closed"
    assert len(closed["follow_ups"][0]["receipts"]) == 2
    assert complete(session, case, item)["workspace"]["revision"] == 7
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        complete(session, case, item, evidence="Changed result")
    assert count(session, Operation, case) == 1
    assert count(session, Decision, case) == 1
    assert svc.list_queue(svc.Container(session), case[0])[0]["lane"] == follow.LANE


@pytest.mark.parametrize("phase,label", [
    ("proposed", "awaiting human approval"),
    ("sent", "local delivery recorded"),
    ("completed", "completed · human recorded"),
])
def test_chat_reads_current_receipts_without_creating_or_repeating_work(session, case, monkeypatch, phase, label):
    monkeypatch.setattr(conversation.runtime_settings, "workspace_llm_backend", "disabled")
    w = propose(session, case)["workspace"]
    item = w["follow_ups"][0]
    if phase != "proposed":
        w = decide(session, case, item)["workspace"]
    if phase == "completed":
        w = complete(session, case, item)["workspace"]
    team = provider_team.save(session, case[0], case[1], expected=0, key="receipt-reader-team",
        configuration=provider_team.default_configuration())
    operations = count(session, Operation, case)
    receipts = count(session, FollowUpReceipt, case)
    captured = []
    original = conversation.generate_reply

    def generate(context):
        captured.append(context)
        return original(context)

    monkeypatch.setattr(conversation, "generate_reply", generate)
    result = conversation.ask(session, case[0], case[1], w["id"], expected=w["revision"],
        team_revision=team["revision"], key="read-follow-up-facts", role="follow_up",
        content="What is the current follow-up status?")
    reply = result["workspace"]["entries"][-1]["reply"]
    assert label in reply["content"]
    assert "2026-09-25" in reply["content"]
    assert len(captured[0].follow_ups) == 1
    assert captured[0].follow_ups[0].ticket_id == item["ticket_id"]
    assert "Private invented agenda" not in repr(captured[0])
    assert item["body"] not in repr(captured[0])
    assert count(session, Operation, case) == operations
    assert count(session, FollowUpReceipt, case) == receipts
    assert count(session, FollowUpSource, case) == 1


@pytest.mark.parametrize("change", [{"share": False}, {"share": 1}, {"body": " "},
    {"expected_outcome": ""}, {"body": "x" * 4001}, {"due_date": "2026-09-25"}])
def test_proposal_requires_deliberate_share_and_bounded_fields(session, case, change):
    with pytest.raises(ws.WorkspaceError, match="invalid_follow_up"):
        propose(session, case, **change)
    assert count(session, FollowUpSource, case) == 0


@pytest.mark.parametrize("change", ["note", "evidence"])
def test_source_edit_invalidates_unexecuted_approval(session, case, monkeypatch, change):
    item = propose(session, case)["workspace"]["follow_ups"][0]
    original = follow.deliver
    monkeypatch.setattr(follow, "deliver", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated API exit")))
    with pytest.raises(RuntimeError):
        decide(session, case, item)
    monkeypatch.setattr(follow, "deliver", original)
    if change == "note":
        notes.save(session, case[0], case[1], case[2]["id"], expected=5, key="changed-note",
            base_note_id=case[2]["note"]["latest"]["id"], source_reply_id=None, content="Changed note.")
    else:
        ws.append(session, case[0], case[1], case[2]["id"], expected=5, key="changed-evidence",
            kind="evidence", source_label="Invented correction", content="Changed evidence.")
    with pytest.raises(ws.WorkspaceError, match="needs_current_review"):
        decide(session, case, item)
    assert count(session, FollowUpReceipt, case) == 0
    cancelled = decide(session, case, item, choice="reject")["workspace"]["follow_ups"][0]
    assert cancelled["state"] == "rejected" and cancelled["operation_status"] == "failed"


def test_pending_intent_recovers_without_new_operation(session, case, monkeypatch):
    item = propose(session, case)["workspace"]["follow_ups"][0]
    original = follow.deliver
    monkeypatch.setattr(follow, "deliver", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated API exit")))
    with pytest.raises(RuntimeError):
        decide(session, case, item)
    op = session.scalar(select(Operation).where(Operation.box_id == case[0]))
    assert op.status == "pending"
    opid = op.id
    monkeypatch.setattr(follow, "deliver", original)
    decide(session, case, item)
    assert session.scalar(select(Operation).where(Operation.box_id == case[0])).id == opid
    assert count(session, FollowUpReceipt, case) == 1


def test_local_effect_and_receipt_roll_back_together_on_failed_commit(session, case, monkeypatch):
    item = propose(session, case)["workspace"]["follow_ups"][0]
    real_commit = session.commit
    calls = 0
    def fail_delivery_commit():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated interrupted delivery commit")
        real_commit()
    monkeypatch.setattr(session, "commit", fail_delivery_commit)
    with pytest.raises(RuntimeError):
        decide(session, case, item)
    session.rollback()
    monkeypatch.setattr(session, "commit", real_commit)
    assert count(session, FollowUpReceipt, case) == 0
    op = session.scalar(select(Operation).where(Operation.box_id == case[0]))
    assert op.status == "pending" and op.attempt_count == 0
    decide(session, case, item)
    assert count(session, Operation, case) == 1 and count(session, FollowUpReceipt, case) == 1


def test_unreviewed_new_note_cannot_create_a_proposal(session, case):
    w = notes.save(session, case[0], case[1], case[2]["id"], expected=3, key="new-unreviewed",
        base_note_id=case[2]["note"]["latest"]["id"], source_reply_id=None, content="Changed note.")["workspace"]
    for note_id in (case[2]["note"]["latest"]["id"], w["note"]["latest"]["id"]):
        with pytest.raises(ws.WorkspaceError, match="needs_current_review"):
            propose(session, case, expected=4, note_id=note_id)
    assert count(session, FollowUpSource, case) == 0


def test_existing_work_can_finish_after_notebook_history_limit(session, case):
    item = propose(session, case)["workspace"]["follow_ups"][0]
    session.get(EncounterWorkspace, case[2]["id"]).revision = 500
    session.commit()
    decide(session, case, item)
    assert complete(session, case, item)["workspace"]["follow_ups"][0]["state"] == "closed"


def test_exact_binding_required_and_no_legacy_bypass(session, case):
    item = propose(session, case)["workspace"]["follow_ups"][0]
    for kw in ({"digest": "0" * 64}, {"revision_id": str(uuid4())}):
        with pytest.raises(ws.WorkspaceError, match="approval_changed"):
            decide(session, case, item, **kw)
    with pytest.raises(ws.WorkspaceError, match="delivery_required"):
        complete(session, case, item)
    with pytest.raises(ws.WorkspaceError, match="approval_required"):
        follow.deliver(session, case[0], case[1], case[2]["id"], item["ticket_id"],
            revision_id=item["revision_id"], digest=item["payload_hash"])
    c, tid, actor = svc.Container(session), item["ticket_id"], case[1]
    for action in (lambda: svc.decide(c, tid, actor, DecisionKind.APPROVE),
                   lambda: svc.edit_revision(c, tid, actor, "Bypass"), lambda: svc.close_ticket(c, tid, actor),
                   lambda: svc.simulate_upload_and_verify(c, tid, actor, b"front", b"back")):
        with pytest.raises(AuthorizationError, match="private workspace"):
            action()
    op = Operation(box_id=case[0], ticket_id=tid, action_revision_id=item["revision_id"],
        idempotency_key="bypass-op", adapter=follow.ADAPTER)
    session.add(op)
    session.flush()
    with pytest.raises(DomainError, match="configured execution backend"):
        svc.execute_operation(c, op.id)


@pytest.mark.parametrize("kind", ["other_human", "agent", "disabled", "revoked", "other_box"])
def test_private_scope_and_revocation_before_action(session, case, kind):
    item = propose(session, case)["workspace"]["follow_ups"][0]
    box, actor, w, link_id = case
    if kind in {"other_human", "agent"}:
        p = Principal(box_id=box, display_name="Other invented principal", state="active",
                      principal_type="agent" if kind == "agent" else "human", is_owner=True)
        session.add(p)
        session.flush()
        actor = p.id
    elif kind == "disabled":
        session.get(Principal, actor).state = "disabled"
    elif kind == "revoked":
        session.get(PatientLink, link_id).revoked_at = datetime.now(UTC)
    else:
        box = svc.provision_box(svc.Container(session), "Other invented Box")["box_id"]
    session.commit()
    with pytest.raises(ws.WorkspaceError):
        decide(session, (box, actor, w, link_id), item)
    assert count(session, FollowUpReceipt, case) == 0


def test_history_and_bound_action_are_immutable(session, case):
    item = propose(session, case)["workspace"]["follow_ups"][0]
    delivered = decide(session, case, item)["workspace"]["follow_ups"][0]
    for table, column, rowid, field in (
        ("follow_up_sources", "ticket_id", item["ticket_id"], "request_hash"),
        ("follow_up_receipts", "id", delivered["receipts"][0]["id"], "content"),
        ("action_revisions", "id", item["revision_id"], "content"),
    ):
        for sql in (f"UPDATE {table} SET {field}='changed' WHERE {column}=:id", f"DELETE FROM {table} WHERE {column}=:id"):
            with pytest.raises(DBAPIError), session.begin_nested():
                session.execute(text(sql), {"id": rowid})


def test_api_is_gated_redacts_validation_and_ignores_client_authority(session, case, monkeypatch):
    connection = session.connection()

    def request_session():
        # Reuse fixture data and its outer transaction, not a prior request's
        # Session and retained capture ownership.
        with Session(bind=connection, autoflush=False,
                     join_transaction_mode="create_savepoint") as current:
            yield current

    class FixtureClient(TestClient):
        def request(self, *args, **kwargs):
            session.flush()
            try:
                return super().request(*args, **kwargs)
            finally:
                session.expire_all()

    api.app.dependency_overrides[api.get_session] = request_session
    headers = {"X-Box-Id": case[0], "X-Actor-Principal-Id": case[1]}
    body = {"expected_revision": 3, "idempotency_key": "api-proposal", "note_id": case[2]["note"]["latest"]["id"],
        "body": "Invented selected text.", "due_date": "2026-09-25", "expected_outcome": "Invented result", "share": True}
    path = f'/workspaces/{case[2]["id"]}/follow-ups'
    try:
        with FixtureClient(api.app) as client:
            bad = client.post(path, headers=headers, json={**body, "target_ref": "secret-input"})
            assert bad.status_code == 422 and "secret-input" not in bad.text
            assert bad.headers["cache-control"] == "no-store"
            good = client.post(path, headers=headers, json=body)
            assert good.status_code == 200
            item = good.json()["workspace"]["follow_ups"][0]
            approved = client.post(path + f'/{item["ticket_id"]}/decide', headers=headers,
                json={"revision_id": item["revision_id"], "payload_hash": item["payload_hash"], "choice": "approve"})
            assert approved.status_code == 200 and approved.json()["workspace"]["follow_ups"][0]["state"] == "sent"
            monkeypatch.setattr(api.settings, "workspace_enabled", False)
            assert client.post(path, headers=headers, json=body).status_code == 404
            with pytest.raises(ws.WorkspaceError, match="connection_required"):
                propose(session, case)
    finally:
        api.app.dependency_overrides.clear()


def test_concurrent_approval_and_completion_have_one_operation_and_receipt(engine):
    with Session(engine) as s:
        case = prepare(s, svc.provision_box(svc.Container(s), "Invented concurrency"))
        item = propose(s, case)["workspace"]["follow_ups"][0]
    for action in (decide, complete):
        barrier = Barrier(2)
        def run(_, barrier=barrier, action=action):
            with Session(engine) as s:
                barrier.wait(timeout=10)
                return action(s, case, item)["workspace"]["follow_ups"][0]["state"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            expected = "sent" if action is decide else "closed"
            assert list(pool.map(run, (1, 2))) == [expected, expected]
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Operation).where(Operation.ticket_id == item["ticket_id"])) == 1
        assert s.scalar(select(func.count()).select_from(FollowUpReceipt).where(FollowUpReceipt.ticket_id == item["ticket_id"])) == 2
        assert ws.read(s, case[0], case[1], case[2]["id"])["follow_ups"][0]["state"] == "closed"
