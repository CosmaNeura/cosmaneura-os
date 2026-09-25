"""Unsent financial revisions invalidate current approval without rewriting history."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_finance_api import client as client
from tests.integration.test_finance_api import headers, root
from tests.integration.test_finance_work import POLICY, approved, bound, call, proposal
from tests.integration.test_finance_work import finance_case as finance_case
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import immediate
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.api import finance_work_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import finance_execution as execution
from cosmas_os.application import finance_setup as setup
from cosmas_os.application import finance_work as work
from cosmas_os.application import services
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.finance_models import FinanceSubmitClaim
from cosmas_os.models import ActionRevision, EncounterWorkspace, Operation


def revise(c, tid, d, **extra):
    summary = d["summary"]
    return proposal(
        c,
        amount=23456,
        due_date="2026-10-03",
        expected_outcome="Invented revised payment amount and review.",
        revises={
            "ticket_id": tid,
            "expected_version": summary["version"],
            "revision_id": summary["revision_id"],
            "payload_hash": summary["payload_hash"],
        },
        **extra,
    )


@pytest.mark.parametrize("prior_state", ["pending", "approved"])
def test_actual_finance_revision_requires_fresh_review_and_preserves_original_receipts(
    session, client, finance_case, tmp_path, prior_state
):
    import json

    c = finance_case
    h = headers(c)
    url = root(c)
    if prior_state == "approved":
        tid, saved, d = approved(session, c)
    else:
        saved = call(session, c, work.propose, proposal(c), policy=POLICY)
        tid = saved["effect"]["ticket_id"]
        d = call(session, c, work.detail, tid)
    old = deepcopy(d)
    old_action = session.get(ActionRevision, d["summary"]["revision_id"])
    old_payload = deepcopy(old_action.payload)
    w = session.get(EncounterWorkspace, c["wid"])
    customer = setup.review_customer(
        session,
        c["box"],
        c["actor"],
        c["finance_connection"]["id"],
        w.patient_link_id,
        "cus_Revised",
        label="Invented revised customer mapping",
    )
    request = revise(
        c, tid, d, customer={k: customer[k] for k in ["id", "revision", "public_sha256"]}
    )
    changed = client.post(url, headers=h, json=request.public())
    assert changed.status_code == 200, changed.text
    d = client.get(url + "/" + tid, headers=h).json()
    schema.FinanceDetail.model_validate(d)
    assert changed.json()["effect"]["ticket_id"] == tid
    assert (
        d["summary"]["state"] == "pending_approval"
        and d["summary"]["version"] == old["summary"]["version"] + 1
    )
    assert (
        d["summary"]["revision_id"] != old["summary"]["revision_id"]
        and d["summary"]["operation_id"] != old["summary"]["operation_id"]
    )
    assert d["review"]["amount"] == 23456 and d["review"]["customer"]["id"] == customer["id"]
    assert d["review"]["processor_confirmation"] == "not_requested" and d["latest_result"] is None
    assert session.get(ActionRevision, old_action.id).payload == old_payload
    assert session.get(Operation, d["summary"]["operation_id"]) is None
    old_op = session.get(Operation, old["summary"]["operation_id"])
    assert (
        old_op is None
        if prior_state == "pending"
        else old_op.status == "cancelled" and old_op.attempt_count == 0
    )
    assert session.get(FinanceSubmitClaim, old["summary"]["operation_id"]) is None
    replay = client.post(url, headers=h, json=request.public())
    assert replay.json()["effect"] == changed.json()["effect"]
    old_resolve = client.post(
        url + "/resolve",
        headers=h,
        json={
            "command_kind": saved["command_kind"],
            "idempotency_key": saved["idempotency_key"],
            "request_sha256": saved["request_sha256"],
        },
    )
    assert old_resolve.json()["effect"] == saved["effect"]
    obsolete = schema.FinanceDecision(
        **bound(old, review_sha256=old["review_sha256"], choice="approve")
    )
    assert (
        client.post(url + "/" + tid + "/decide", headers=h, json=obsolete.public()).status_code
        == 409
    )
    with pytest.raises(ws.WorkspaceError):
        call(
            session,
            c,
            execution.claim_submit,
            tid,
            public.BoundCommand(**bound(old)),
            policy=POLICY,
        )
    decision = schema.FinanceDecision(
        **bound(d, review_sha256=d["review_sha256"], choice="approve")
    )
    fresh = client.post(url + "/" + tid + "/decide", headers=h, json=decision.public())
    assert fresh.status_code == 200, fresh.text
    immediate(session)
    assert session.get(Operation, d["summary"]["operation_id"]).attempt_count == 0
    (tmp_path / "actual-finance-revision-fixtures.json").write_text(
        json.dumps(
            {
                "prior_detail": old,
                "revision_request": request.public(),
                "revision_receipt": changed.json(),
                "pending_detail": d,
                "revision_replayed": replay.json(),
                "old_resolved": old_resolve.json(),
                "approval_request": decision.public(),
                "approval_receipt": fresh.json(),
            },
            indent=2,
        )
        + "\n"
    )


@pytest.mark.parametrize("wrong", ["version", "revision", "payload", "operation", "claimed"])
def test_finance_revision_rejects_stale_or_spent_prior(session, finance_case, wrong):
    c = finance_case
    tid, _, d = approved(session, c)
    if wrong == "claimed":
        call(
            session, c, execution.claim_submit, tid, public.BoundCommand(**bound(d)), policy=POLICY
        )
        d = call(session, c, work.detail, tid)
    request = revise(c, tid, d).public()
    if wrong == "version":
        request["revises"]["expected_version"] += 1
    elif wrong == "revision":
        request["revises"]["revision_id"] = str(uuid4())
    elif wrong == "payload":
        request["revises"]["payload_hash"] = "0" * 64
    elif wrong == "operation":
        request["proposed_operation_id"] = d["summary"]["operation_id"]
    with pytest.raises(ws.WorkspaceError):
        call(
            session, c, work.propose, schema.FinanceProposal.model_validate(request), policy=POLICY
        )
    assert call(session, c, work.detail, tid)["summary"] == d["summary"]


def test_finance_revision_cannot_target_another_workspace(
    session, finance_case, seeded, monkeypatch
):
    c = finance_case
    tid, _, d = approved(session, c)
    original_create = ws.create
    monkeypatch.setattr(
        ws, "create", lambda s, b, a, v, k: original_create(s, b, a, v, k + str(uuid4()))
    )
    other = globals()["finance_case"].__wrapped__(
        session, globals()["vendor_case"].__wrapped__(session, seeded)
    )
    with pytest.raises(ws.WorkspaceError, match="finance_work_unavailable"):
        call(session, other, work.propose, revise(other, tid, d), policy=POLICY)
    assert call(session, c, work.detail, tid)["summary"] == d["summary"]


def test_direct_sql_cannot_restore_superseded_revision_or_reset_old_operation(
    session, finance_case
):
    c = finance_case
    tid, _, d = approved(session, c)
    request = revise(c, tid, d)
    changed = call(session, c, work.propose, request, policy=POLICY)
    immediate(session)
    current = call(session, c, work.detail, tid)
    for statement, values in [
        (
            "UPDATE tickets SET current_revision_id=:rid, version=version+1, state='pending_approval' WHERE id=:tid",
            {"rid": d["summary"]["revision_id"], "tid": tid},
        ),
        (
            "UPDATE operations SET status='pending', completed_at=NULL WHERE id=:oid",
            {"oid": d["summary"]["operation_id"]},
        ),
    ]:
        with session.begin_nested() as nested:
            with pytest.raises(DBAPIError):
                session.execute(text(statement), values)
                immediate(session)
            nested.rollback()
    assert current["summary"]["revision_id"] == changed["effect"]["revision_id"]


@pytest.mark.parametrize("winner", ["revision", "submit"])
def test_committed_revision_and_submit_serialize_one_current_intent(
    engine, tmp_path, monkeypatch, winner
):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "vendor_work_enabled", True)
    with Session(engine, expire_on_commit=False) as s:
        seeded = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented payment revision race",
        )
        c = globals()["finance_case"].__wrapped__(
            s, globals()["vendor_case"].__wrapped__(s, seeded)
        )
        tid, _, prior = approved(s, c)
        request = revise(c, tid, prior)
        submit = public.BoundCommand(**bound(prior))
        s.commit()
    paused, release, second_started = Event(), Event(), Event()

    def apply(kind, first=False):
        with Session(engine, expire_on_commit=False) as s:
            if first:

                def fence():
                    paused.set()
                    assert release.wait(5)

                s.info["finance_final_authority"] = fence
            else:
                second_started.set()
            try:
                value = (
                    call(s, c, work.propose, request, policy=POLICY)
                    if kind == "revision"
                    else call(s, c, execution.claim_submit, tid, submit, policy=POLICY)[0]
                )
                return "recorded", value
            except ws.WorkspaceError as exc:
                s.rollback()
                return "rejected", str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(apply, winner, True)
        assert paused.wait(5)
        second = pool.submit(apply, "submit" if winner == "revision" else "revision")
        assert second_started.wait(5)
        release.set()
        a, b = first.result(timeout=5), second.result(timeout=5)
    assert a[0] == "recorded" and b[0] == "rejected", (a, b)
    with Session(engine) as s:
        current = call(s, c, work.detail, tid)
        old_operation = s.get(Operation, prior["summary"]["operation_id"])
        claim = s.get(FinanceSubmitClaim, old_operation.id)
        if winner == "revision":
            assert current["summary"]["revision_id"] == a[1]["effect"]["revision_id"]
            assert current["summary"]["state"] == "pending_approval"
            assert old_operation.status == "cancelled" and old_operation.attempt_count == 0
            assert claim is None
        else:
            assert current["summary"]["revision_id"] == prior["summary"]["revision_id"]
            assert old_operation.status == "running" and old_operation.attempt_count == 1
            assert claim is not None
            with pytest.raises(ws.WorkspaceError, match="finance_submit_already_claimed"):
                call(s, c, work.propose, revise(c, tid, current), policy=POLICY)
