"""Real PostgreSQL commit boundaries and product worker pickup; invented data only."""

import asyncio
import hashlib
import json
import os
import statistics
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.helpers.task_brief import REQUIREMENTS
from tests.integration.test_product_agent_tool_workflow import encounter

from cosmas_os.adapters.gpt41 import ENDPOINT, _context
from cosmas_os.application import handoff_wakeup as wake
from cosmas_os.application import handoffs
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.models import ModelWorkAdmission, WorkspaceEntry
from cosmas_os.ports.bot_capabilities import DraftBrief


@pytest.fixture
def operational(monkeypatch):
    monkeypatch.setattr(team.runtime_settings, "workspace_enabled", True)
    monkeypatch.setattr(team.runtime_settings, "workspace_agent_tools_enabled", True)
    monkeypatch.setattr(team.runtime_settings, "workspace_llm_backend", "azure_gpt41")
    monkeypatch.setattr(
        team.runtime_settings, "workspace_llm_api_key", SecretStr("invented-wake-key")
    )


def real_lanes(lanes):
    assert all(isinstance(lane, wake.WorkerWakeup) for lane in lanes)
    return tuple(lane for lane in lanes if isinstance(lane, wake.WorkerWakeup))


def model_dispatch(engine, claim):
    context = _context(claim.envelope["context"])
    handle = claim.envelope["tool_selection"]["sources"][0]

    def provider(request):
        assert str(request.url) == ENDPOINT
        body = json.loads(request.content)
        assert body["model"] == "gpt-4.1-dzus" and body["store"] is False
        tools = [m for m in body["messages"] if m["role"] == "tool"]
        message = {"role": "assistant", "content": None}
        if not tools:
            message["tool_calls"] = [
                {
                    "id": "invented_exact_read",
                    "type": "function",
                    "function": {
                        "name": "read_selected_source",
                        "arguments": json.dumps(
                            {key: handle[key] for key in ("entry_id", "revision", "sha256")}
                        ),
                    },
                }
            ]
        else:
            value = json.loads(tools[0]["content"])
            assert hashlib.sha256(value["data"]["content"].encode()).hexdigest() == handle["sha256"]
            assert value["receipt"]["actor_agent_id"] != value["receipt"]["initiated_by_human_id"]
            content = {
                "answer": "Invented private draft; no outside work occurred.",
                "source_ids": [p.entry_id for p in context.sources],
            }
            if claim.envelope["baseline"]["flags"]["can_handoff"]:
                content["handoffs"] = []
            if claim.envelope["baseline"]["flags"]["work_status"]:
                content["intent"] = "conversation"
            message["content"] = json.dumps(content)
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1",
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                "choices": [
                    {"finish_reason": "stop" if tools else "tool_calls", "message": message}
                ],
            },
        )

    return work.dispatch_claim(
        claim, session_factory=lambda: Session(engine), transport=httpx.MockTransport(provider)
    )


def prepared_case(engine):
    box, owner, wid = encounter(engine)
    with Session(engine) as session:
        snapshot = ws.read(session, box, owner, wid)
        admission, _ = work.reserve_conversation(
            session,
            box,
            owner,
            wid,
            expected=snapshot["revision"],
            team_revision=1,
            key="invented-wake-origin",
            role="chief",
            content="Prepare private draft tasks from the invented Scribe sources.",
        )
        claim = work.claim(session, box, owner, admission)
    assert claim is not None
    result = model_dispatch(engine, claim)
    with Session(engine) as session:
        work.settle(session, claim, result)
        row = session.get(ModelWorkAdmission, admission)
        assert row is not None and row.state == "completed"
        return box, owner, wid, row.result_entry_id


def stage_children(session, case, *, count=1):
    box, owner, wid, origin_id = case
    workspace = ws._workspace(session, box, owner, wid, writing=True)
    version, chief, settings = team.active_bot(session, box, owner, "chief", 1)
    context = work._context_for(
        session,
        workspace,
        version,
        settings,
        chief,
        {
            "role": "chief",
            "team_revision": 1,
            "content": "Prepare independent invented private drafts.",
        },
        handoff_roles=("visit_prep", "follow_up"),
    )
    origin = session.get(WorkspaceEntry, origin_id)
    assert origin is not None
    assignments = work.reserve_children(
        session,
        workspace,
        origin,
        version,
        chief,
        context,
        tuple(
            DraftBrief(role, "Prepare an invented private draft.", REQUIREMENTS)
            for role in ("visit_prep", "follow_up")[:count]
        ),
        external_identity_id=None,
    )
    assert len(assignments) == count
    assert tuple(item.assignment.recipient_role for item in assignments) == (
        "visit_prep", "follow_up"
    )[:count]
    assert all(
        item.attempt.status == "queued" and item.attempt.error_code is None
        for item in assignments
    )
    session.flush()


@pytest.mark.parametrize(
    "boundary",
    ["outer_commit", "nested_commit", "outer_rollback", "nested_rollback", "flush_rollback"],
)
def test_actual_pg_only_outer_committed_admission_wakes(engine, operational, boundary):
    case = prepared_case(engine)

    async def exercise():
        with wake.subscribe_worker(lambda: Session(engine)) as lanes:
            lanes = real_lanes(lanes)
            with Session(engine) as session:
                if boundary.startswith("nested"):
                    nested = session.begin_nested()
                    stage_children(session, case)
                    nested.commit() if boundary == "nested_commit" else nested.rollback()
                else:
                    stage_children(session, case)
                await asyncio.sleep(0)
                assert not any(lane._event.is_set() for lane in lanes)
                if boundary in {"outer_commit", "nested_commit", "nested_rollback"}:
                    session.commit()
                else:
                    session.rollback()
                await asyncio.sleep(0)
                assert all(lane._event.is_set() for lane in lanes) == (
                    boundary in {"outer_commit", "nested_commit"}
                )
                assert wake._PENDING not in session.info
        assert not wake._subscribers

    asyncio.run(exercise())
    # Keep other worker tests isolated from these intentionally unexecuted insertions.
    while work.process_next(
        lambda: Session(engine), dispatch=lambda claim: model_dispatch(engine, claim)
    ):
        pass


def test_caller_owned_pg_transaction_never_signals_a_session_savepoint_commit(engine, operational):
    case = prepared_case(engine)

    async def exercise():
        with wake.subscribe_worker(lambda: Session(engine)) as lanes:
            lanes = real_lanes(lanes)
            with engine.connect() as connection:
                outer = connection.begin()
                with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                    stage_children(session, case)
                    session.commit()
                    await asyncio.sleep(0)
                    assert not any(lane._event.is_set() for lane in lanes)
                    assert wake._PENDING not in session.info
                outer.rollback()

    asyncio.run(exercise())


def test_actual_commit_wakes_all_same_engine_workers_but_not_an_independent_engine(
    engine, operational
):
    from sqlalchemy import create_engine

    case = prepared_case(engine)
    other = create_engine(engine.url)

    async def exercise():
        with wake.subscribe_worker(lambda: Session(engine)) as first:
            first = real_lanes(first)
            with wake.subscribe_worker(lambda: Session(engine)) as second:
                second = real_lanes(second)
                with wake.subscribe_worker(lambda: Session(other)) as independent:
                    independent = real_lanes(independent)
                    with Session(engine) as session:
                        stage_children(session, case)
                        session.commit()
                    await asyncio.sleep(0)
                    assert all(lane._event.is_set() for lane in (*first, *second))
                    assert not any(lane._event.is_set() for lane in independent)
                assert len(wake._subscribers[engine]) == 6
            assert len(wake._subscribers[engine]) == 3
        assert not wake._subscribers

    try:
        asyncio.run(exercise())
    finally:
        other.dispose()
    while work.process_next(
        lambda: Session(engine), dispatch=lambda claim: model_dispatch(engine, claim)
    ):
        pass


def test_nested_rollback_then_new_outer_admission_still_wakes(engine, operational):
    case = prepared_case(engine)

    async def exercise():
        with wake.subscribe_worker(lambda: Session(engine)) as lanes:
            lanes = real_lanes(lanes)
            with Session(engine) as session:
                nested = session.begin_nested()
                stage_children(session, case)
                nested.rollback()
                stage_children(session, case)
                session.commit()
            await asyncio.sleep(0)
            assert all(lane._event.is_set() for lane in lanes)

    asyncio.run(exercise())
    while work.process_next(
        lambda: Session(engine), dispatch=lambda claim: model_dispatch(engine, claim)
    ):
        pass


def test_commit_between_empty_scan_and_wait_is_retained_and_worker_stop_removes_subscribers(
    engine, operational, monkeypatch
):
    case = prepared_case(engine)
    actual_scan = handoffs.process_next
    original_dispatch = work.dispatch_claim
    empty_scans = threading.Event()
    release_scans = threading.Event()
    picked = threading.Event()
    lock = threading.Lock()
    initial_scans = [0]

    def scan(factory):
        # Registration must precede the first authoritative scan.
        assert len(wake._subscribers[engine]) == 3
        worked = actual_scan(factory)
        if not worked and not release_scans.is_set():
            with lock:
                initial_scans[0] += 1
                if initial_scans[0] == 3:
                    empty_scans.set()
            assert release_scans.wait(5)
        return worked

    def dispatch(claim, **kwargs):
        if kwargs:
            return original_dispatch(claim, **kwargs)
        picked.set()
        return model_dispatch(engine, claim)

    monkeypatch.setattr(handoffs, "process_next", scan)
    monkeypatch.setattr(work, "dispatch_claim", dispatch)

    async def exercise():
        stop = asyncio.Event()
        runner = asyncio.create_task(handoffs.run_worker(lambda: Session(engine), stop))
        try:
            assert await asyncio.to_thread(empty_scans.wait, 3)
            with Session(engine) as session:
                stage_children(session, case)
                session.commit()
            # Deliver the commit hint while every lane is still returning its
            # stale empty scan. It must survive until those lanes start waiting.
            await asyncio.sleep(0)
            release_scans.set()
            assert await asyncio.to_thread(picked.wait, 1)
        finally:
            release_scans.set()
            stop.set()
            await runner
        assert not wake._subscribers
        from sqlalchemy import event

        assert all(event.contains(Session, name, handler) for name, handler in wake._EVENTS)

    asyncio.run(exercise())
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(ModelWorkAdmission).where(
                    ModelWorkAdmission.workspace_id == case[2],
                    ModelWorkAdmission.kind == "private_handoff",
                )
            )
        )
        assert len(rows) == 1 and rows[0].state == "completed"


def test_business_commits_racing_last_worker_shutdown_do_not_fail_or_retain_subscribers(
    engine, operational, monkeypatch
):
    original_signal = wake.WorkerWakeup.signal
    entering, release = threading.Event(), threading.Event()

    def delayed_signal(lane):
        entering.set()
        assert release.wait(5)
        original_signal(lane)

    monkeypatch.setattr(wake.WorkerWakeup, "signal", delayed_signal)
    cases = [prepared_case(engine) for _ in range(6)]

    def commit(case):
        with Session(engine) as session:
            stage_children(session, case)
            session.commit()
            assert wake._PENDING not in session.info

    async def exercise():
        for case in cases:
            entering.clear()
            release.clear()
            with wake.subscribe_worker(lambda: Session(engine)) as lanes:
                lanes = real_lanes(lanes)
                committing = asyncio.create_task(asyncio.to_thread(commit, case))
                try:
                    assert await asyncio.to_thread(entering.wait, 3)
                except BaseException:
                    release.set()
                    await committing
                    raise
            assert not wake._subscribers
            release.set()
            await committing
            await asyncio.sleep(0)
            assert not any(lane._event.is_set() for lane in lanes)

    asyncio.run(exercise())
    while work.process_next(
        lambda: Session(engine), dispatch=lambda claim: model_dispatch(engine, claim)
    ):
        pass


def test_worker_picks_committed_product_tasks_before_polling_timeout_and_records_latency(
    engine, operational, monkeypatch, tmp_path
):
    # Each mode uses the same actual DB services, exact tool HTTP fixture and
    # three production worker lanes. Only the local wake optimization differs.
    actual_scan = handoffs.process_next
    actual_subscribe = wake.subscribe_worker
    original_dispatch = work.dispatch_claim
    timings, errors = {}, []

    @contextmanager
    def no_hint(_factory, *, lanes=3):
        yield (None,) * lanes

    async def batch(cases, *, count):
        stop = asyncio.Event()
        empty = threading.Event()
        scan_lock = threading.Lock()
        scans = [0]
        picks = []
        submitted = {}
        commit_elapsed = {}
        active_dispatches, peak_dispatches = [0], [0]

        def scan(factory):
            worked = actual_scan(factory)
            if not worked:
                with scan_lock:
                    scans[0] += 1
                    if scans[0] >= 3:
                        empty.set()
            return worked

        def measured(claim, **kwargs):
            if kwargs:
                return original_dispatch(claim, **kwargs)
            with scan_lock:
                active_dispatches[0] += 1
                peak_dispatches[0] = max(peak_dispatches[0], active_dispatches[0])
            try:
                picked = time.monotonic()
                picks.append((claim.workspace_id, picked))
                return model_dispatch(engine, claim)
            except Exception:
                errors.append("dispatch_failed")
                raise
            finally:
                with scan_lock:
                    active_dispatches[0] -= 1

        monkeypatch.setattr(handoffs, "process_next", scan)
        monkeypatch.setattr(work, "dispatch_claim", measured)
        runner = asyncio.create_task(handoffs.run_worker(lambda: Session(engine), stop))
        try:
            assert await asyncio.to_thread(empty.wait, 3)
            # Burst of two independent recipients for each of six encounters.
            for case in cases:
                with Session(engine) as session:
                    stage_children(session, case, count=count)
                    before = time.monotonic()
                    session.commit()
                    submitted[case[2]] = time.monotonic()
                    commit_elapsed[case[2]] = (submitted[case[2]] - before) * 1000
            expected = len(cases) * count
            deadline = time.monotonic() + 15
            while len(picks) < expected and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            assert len(picks) == expected
            # Wait for actual settlement, not only fake provider entry.
            while time.monotonic() < deadline:
                with Session(engine) as session:
                    pending = list(
                        session.scalars(
                            select(ModelWorkAdmission).where(
                                ModelWorkAdmission.workspace_id.in_(submitted),
                                ModelWorkAdmission.state.in_(work.ACTIVE),
                            )
                        )
                    )
                if not pending:
                    break
                await asyncio.sleep(0.01)
            assert not pending
            with Session(engine) as session:
                completed = list(
                    session.scalars(
                        select(ModelWorkAdmission).where(
                            ModelWorkAdmission.workspace_id.in_(submitted),
                            ModelWorkAdmission.kind == "private_handoff",
                        )
                    )
                )
                assert len(completed) == expected and all(
                    row.state == "completed" for row in completed
                )
                assert len({row.dispatch_id for row in completed}) == expected
            # The synchronous commit return is a conservative timestamp after
            # durable commit. A racing lane may already have claimed by then.
            values = sorted(max(0, (picked - submitted[wid]) * 1000) for wid, picked in picks)
            return {
                "pickup_ms": values,
                "p50_ms": statistics.median(values),
                "p95_ms": values[max(0, int(len(values) * 0.95 + 0.999) - 1)],
                "samples": len(values),
                "empty_scans": scans[0],
                "commit_return_ms": sorted(commit_elapsed.values()),
                "completed": len(completed),
                "peak_adapter_dispatches": peak_dispatches[0],
            }
        finally:
            stop.set()
            await runner
            assert not wake._subscribers

    async def mode(name, hinted):
        monkeypatch.setattr(wake, "subscribe_worker", actual_subscribe if hinted else no_hint)
        # Build source-identical encounters before starting the measured workers.
        cases = await asyncio.to_thread(lambda: [prepared_case(engine) for _ in range(12)])
        idle = []
        for case in cases[:6]:
            idle.append(await batch([case], count=1))
        idle_values = sorted(value for sample in idle for value in sample["pickup_ms"])
        timings[name] = {
            "idle": {
                "pickup_ms": idle_values,
                "p50_ms": statistics.median(idle_values),
                "p95_ms": idle_values[-1],
                "samples": len(idle_values),
                "completed": sum(sample["completed"] for sample in idle),
                "commit_return_ms": sorted(
                    value for sample in idle for value in sample["commit_return_ms"]
                ),
                "peak_adapter_dispatches": max(
                    sample["peak_adapter_dispatches"] for sample in idle
                ),
            },
            "concurrent_burst": await batch(cases[6:], count=2),
        }

    asyncio.run(mode("polling", False))
    asyncio.run(mode("committed_local_hint", True))
    assert not errors
    # Compare equivalent idle medians rather than a hardware-dependent SLA.
    # Full completion, exact unique dispatches and bounded capacity gate both
    # modes; concurrent queue timings remain measurements, not a latency claim.
    assert timings["committed_local_hint"]["idle"]["p50_ms"] < timings["polling"]["idle"]["p50_ms"]
    assert all(
        result["peak_adapter_dispatches"] <= 3
        for mode_timings in timings.values()
        for result in mode_timings.values()
    )
    root = Path(os.environ.get("COSMAS_HANDOFF_WAKE_EVIDENCE_DIR", str(tmp_path)))
    root.mkdir(parents=True, exist_ok=True)
    (root / "pickup-latency.json").write_text(
        json.dumps(
            {
                "synthetic_only": True,
                "boundary": "Actual PostgreSQL admission/claim/tool/settlement; fake HTTP model. Timestamp is synchronous commit return to adapter entry; it includes claim/source checks. Idle and concurrent queue measurements are separate and are not model or human latency.",
                "lanes": 3,
                "errors": errors,
                "timings": timings,
            },
            indent=2,
        )
        + "\n"
    )
