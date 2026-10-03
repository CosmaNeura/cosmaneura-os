"""Actual SQL admission/claim/tool/settle concurrency with invented HTTP model.

Barriers measure workflow overlap and custody; never model latency/cost qualification.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Lock

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.helpers.task_brief import REQUIREMENTS
from tests.integration.test_handoff_wakeup import prepared_case
from tests.integration.test_product_agent_tool_workflow import operational as operational
from tests.integration.test_product_agent_tool_workflow import read_call, response

from cosmas_os.adapters.gpt41 import ENDPOINT, _context
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    ModelWorkAdmission,
    WorkspaceEntry,
    WorkspaceHandoffAttempt,
    WorkspaceReply,
)
from cosmas_os.ports.bot_capabilities import DraftBrief, ModelCallFailure


def dispatch(engine, claim):
    # Each dispatch owns its reader sessions; peers can legitimately hold owner
    # locks while settling, so global NOWAIT probes are not a concurrency proof.
    readers = []
    calls = []
    handle = claim.envelope["tool_selection"]["sources"][0]
    context = _context(claim.envelope["context"])

    def factory():
        session = Session(engine)
        readers.append(session)
        return session

    def provider(request):
        assert str(request.url) == ENDPOINT
        assert all(not session.in_transaction() for session in readers)
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(200, json=response(calls=[read_call(handle)]))
        assert len(calls) == 2
        tool = json.loads(body["messages"][-1]["content"])
        assert tool["receipt"]["admission_id"] == claim.admission_id
        assert tool["receipt"]["initiated_by_human_id"] == claim.owner
        assert tool["receipt"]["actor_agent_id"] != claim.owner
        output = {
            "answer": "Invented private preparation completed; clinician review is required.",
            "source_ids": [source.entry_id for source in context.sources],
        }
        if claim.envelope["baseline"]["flags"]["work_status"]:
            output["intent"] = "conversation"
        if claim.envelope["baseline"]["flags"]["can_handoff"]:
            output["handoffs"] = []
        if claim.envelope["baseline"]["flags"]["source_draft"]:
            output = {
                "excerpts": [
                    {"source_id": handle["entry_id"], "quote": tool["data"]["content"][:120]}
                ],
                "needs_from_clinician": ["Which missing details should be confirmed?"],
            }
        return httpx.Response(200, json=response(output))

    return work.dispatch_claim(
        claim, session_factory=factory, transport=httpx.MockTransport(provider)
    )


def children(engine, case):
    box, owner, wid, origin_id = case
    with Session(engine) as s:
        workspace = ws._workspace(s, box, owner, wid, writing=True)
        version, chief, settings = team.active_bot(s, box, owner, "chief", 1)
        context = work._context_for(
            s,
            workspace,
            version,
            settings,
            chief,
            {
                "role": "chief",
                "team_revision": 1,
                "content": "Prepare independent invented draft tasks.",
            },
            handoff_roles=("scribe", "visit_prep", "follow_up"),
        )
        queued, refused = work.reserve_children(
            s,
            workspace,
            s.get(WorkspaceEntry, origin_id),
            version,
            chief,
            context,
            tuple(
                DraftBrief(role, "Prepare an invented private draft.", REQUIREMENTS)
                for role in ("scribe", "visit_prep", "follow_up")
            ),
            external_identity_id=None,
        )
        assert (queued, refused) == (3, 0)
        s.commit()
        return list(
            s.scalars(
                select(ModelWorkAdmission.id).where(
                    ModelWorkAdmission.workspace_id == wid,
                    ModelWorkAdmission.kind == "private_handoff",
                )
            )
        )


def counts(engine, case):
    with Session(engine) as s:
        return tuple(
            s.scalar(select(func.count()).select_from(model).where(model.workspace_id == case[2]))
            for model in (ModelWorkAdmission, WorkspaceReply, WorkspaceHandoffAttempt)
        )


def test_three_accounts_three_specialists_concurrent_claim_replay_settlement_and_isolation(
    engine, operational, tmp_path
):
    cases = [prepared_case(engine) for _ in range(3)]
    queued_at = time.monotonic()
    ids = [(case, aid) for case in cases for aid in children(engine, case)]
    assert len(ids) == 9
    barrier = Barrier(9)
    lock = Lock()
    measurements = []

    def run(pair):
        case, aid = pair
        with Session(engine) as s:
            claim = work.claim(s, case[0], case[1], aid)
        assert claim is not None
        picked = time.monotonic()
        with Session(engine) as duplicate:
            assert work.claim(duplicate, case[0], case[1], aid) is None
        barrier.wait(timeout=15)
        started = time.monotonic()
        try:
            result = dispatch(engine, claim)
        except ModelCallFailure as failure:
            with lock:
                measurements.append(
                    {
                        "failed_role": claim.envelope["context"]["role"],
                        "dispatch": failure.dispatch,
                        "outcome": failure.outcome,
                    }
                )
            raise
        dispatched = time.monotonic()
        with Session(engine) as s:
            work.settle(s, claim, result)
        # Lose the return value after commit and repeat the exact settlement;
        # the retained dispatch/envelope may never create a second draft.
        with Session(engine) as reopened:
            work.settle(reopened, claim, result)
        with lock:
            measurements.append(
                {
                    "workspace": case[2],
                    "admission": aid,
                    "queue_to_claim_ms": (picked - queued_at) * 1000,
                    "dispatch_ms": (dispatched - started) * 1000,
                }
            )
        return claim

    with ThreadPoolExecutor(max_workers=9) as pool:
        futures = [pool.submit(run, pair) for pair in ids]
        claims = []
        failures = []
        for future in futures:
            try:
                claims.append(future.result())
            except Exception as error:
                failures.append(type(error).__name__)
        assert not failures, str(measurements) + str(failures)
    assert len({c.dispatch_id for c in claims}) == 9
    for case in cases:
        with Session(engine) as s:
            rows = list(
                s.scalars(
                    select(ModelWorkAdmission).where(
                        ModelWorkAdmission.workspace_id == case[2],
                        ModelWorkAdmission.kind == "private_handoff",
                    )
                )
            )
            assert len(rows) == 3 and all(r.state == "completed" for r in rows)
            assert len({r.result_entry_id for r in rows}) == 3
            assert (
                s.scalar(
                    select(func.count())
                    .select_from(WorkspaceReply)
                    .where(WorkspaceReply.workspace_id == case[2])
                )
                == 4
            )
        foreign = next(c for c in claims if c.box != case[0])
        with Session(engine) as denied:
            with pytest.raises(ws.WorkspaceError) as error:
                work.claim(denied, case[0], case[1], foreign.admission_id)
            assert error.value.status == 404
    (tmp_path / "model-concurrency-recovery.json").write_text(
        json.dumps(
            {
                "boundary": "Actual PostgreSQL and product tool dispatch, synthetic HTTP responses; barriers deliberately synchronize dispatch. Queue/dispatch measurements are not real model p95 or cost.",
                "accounts": 3,
                "specialists": 9,
                "unique_dispatches": 9,
                "measurements": measurements,
            },
            indent=2,
        )
    )


def test_timeout_expiry_and_late_settlement_remain_unknown_without_automatic_duplicate(
    engine, operational
):
    case = prepared_case(engine)
    aid = children(engine, case)[0]
    with Session(engine) as s:
        claim = work.claim(s, case[0], case[1], aid)
    assert claim is not None
    calls = []

    def timeout(request):
        assert str(request.url) == ENDPOINT
        calls.append(request)
        raise httpx.ReadTimeout("invented timeout", request=request)

    try:
        work.dispatch_claim(
            claim, session_factory=lambda: Session(engine), transport=httpx.MockTransport(timeout)
        )
        pytest.fail("Timeout must not produce a successful draft")
    except ModelCallFailure as failure:
        captured = failure
    failure = captured
    assert isinstance(failure, ModelCallFailure)
    with Session(engine) as s:
        work.settle(s, claim, failure)
    assert len(calls) == 1
    before = counts(engine, case)
    with Session(engine) as s:
        row = s.get(ModelWorkAdmission, aid)
        assert row.state == "unknown" and row.result_entry_id is None
        assert work.claim(s, case[0], case[1], aid) is None
    assert counts(engine, case) == before
    # A different admission crosses an abandoned lease with a delayed real
    # synthetic response. Recovery does not grant dispatch or save that draft.
    with Session(engine) as s:
        second = s.scalar(
            select(ModelWorkAdmission.id).where(
                ModelWorkAdmission.workspace_id == case[2], ModelWorkAdmission.state == "reserved"
            )
        )
        delayed = work.claim(s, case[0], case[1], second)
        row = s.get(ModelWorkAdmission, second)
        expires = row.lease_ends_at
    result = dispatch(engine, delayed)
    with Session(engine) as s:
        work.recover_expired(s, clock=lambda: expires + timedelta(seconds=1))
    with Session(engine) as s:
        work.settle(s, delayed, result, clock=lambda: expires + timedelta(seconds=2))
        row = s.get(ModelWorkAdmission, second)
        assert row.state == "unknown" and row.result_entry_id is None
        assert work.claim(s, case[0], case[1], second) is None
    assert counts(engine, case) == before
