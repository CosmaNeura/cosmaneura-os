"""Wake hints carry no work and never replace the authoritative DB scan."""

import asyncio
import threading
from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from cosmas_os.application import handoff_wakeup as wake
from cosmas_os.models import ModelWorkAdmission


def test_registration_is_engine_scoped_with_one_fixed_hook_set_and_no_retained_engine():
    first, other = create_engine("sqlite://"), create_engine("sqlite://")

    async def exercise():
        with wake.subscribe_worker(lambda: Session(first)) as lanes:
            assert len(lanes) == 3
            assert all(isinstance(lane, wake.WorkerWakeup) for lane in lanes)
            lanes = tuple(lane for lane in lanes if isinstance(lane, wake.WorkerWakeup))
            assert all(event.contains(Session, name, handler) for name, handler in wake._EVENTS)
            with wake.subscribe_worker(lambda: Session(other)) as others:
                assert all(isinstance(lane, wake.WorkerWakeup) for lane in others)
                others = tuple(lane for lane in others if isinstance(lane, wake.WorkerWakeup))
                assert len(wake._subscribers) == 2
                for lane in lanes:
                    lane.signal()
                await asyncio.sleep(0)
                assert all(lane._event.is_set() for lane in lanes)
                assert not any(lane._event.is_set() for lane in others)
            assert len(wake._subscribers) == 1
        assert not wake._subscribers
        wake._install_hooks_once()
        assert all(event.contains(Session, name, handler) for name, handler in wake._EVENTS)
        with Session(first) as session:
            for name, handler in wake._EVENTS:
                assert tuple(getattr(session.dispatch, name)).count(handler) == 1

    for _ in range(3):
        asyncio.run(exercise())
    first.dispose()
    other.dispose()


def test_hint_before_wait_is_retained_and_hint_after_close_cannot_revive_worker():
    async def exercise():
        lane = wake.WorkerWakeup(asyncio.get_running_loop())
        stop = asyncio.Event()
        lane.clear_before_scan()
        lane.signal()
        await asyncio.sleep(0)
        await asyncio.wait_for(lane.wait(stop, timeout=2), 0.1)
        assert lane._event.is_set()
        lane.clear_before_scan()
        assert not lane._event.is_set()
        lane.signal()  # Callback queued before close.
        lane.close()
        await asyncio.sleep(0)
        assert not lane._event.is_set()
        stop.set()
        await asyncio.wait_for(lane.wait(stop, timeout=2), 0.1)

    asyncio.run(exercise())


def test_cross_thread_commit_hint_and_idle_timeout_do_not_leak_wait_tasks():
    async def exercise():
        lane = wake.WorkerWakeup(asyncio.get_running_loop())
        stop = asyncio.Event()
        worker = threading.Thread(target=lane.signal)
        worker.start()
        worker.join(timeout=1)
        await asyncio.wait_for(lane.wait(stop), 0.1)
        lane.clear_before_scan()
        before = set(asyncio.all_tasks())
        await lane.wait(stop, timeout=0.005)  # Cross-process/missed-hint polling fallback.
        assert set(asyncio.all_tasks()) == before

    asyncio.run(exercise())


def test_flush_only_reserved_private_admission_marks_current_transaction():
    engine = create_engine("sqlite://")
    row = ModelWorkAdmission(kind="private_handoff", state="reserved")

    async def exercise():
        with wake.subscribe_worker(lambda: Session(engine)):
            with Session(engine) as session:
                session.add(row)
                wake._after_flush(session, None)
                assert session.info[wake._PENDING] == {session.get_transaction()}
                session.rollback()
                assert wake._PENDING not in session.info
                session.add(ModelWorkAdmission(kind="conversation", state="reserved"))
                wake._after_flush(session, None)
                assert wake._PENDING not in session.info

    asyncio.run(exercise())
    engine.dispose()


def test_non_sqlalchemy_fixture_keeps_ordinary_polling_fallback():
    async def exercise():
        with wake.subscribe_worker("invented-factory") as lanes:
            assert lanes == (None, None, None)
        with wake.subscribe_worker(lambda: SimpleNamespace()) as lanes:
            assert lanes == (None, None, None)

    asyncio.run(exercise())
