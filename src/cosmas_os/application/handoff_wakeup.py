"""Payload-free local wake hints; PostgreSQL remains the only work queue.

Three fixed Session hooks are installed once; only live workers are retained as
subscribers. A new reserved private admission signals its bound Engine's workers
after the outer commit, never a flush or a nested savepoint commit. Independent
processes retain the polling fallback.
"""

import asyncio
import threading
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from cosmas_os.models import ModelWorkAdmission

_PENDING = "cosmas_handoff_wakeup_transactions"
_lock = threading.RLock()
_subscribers: dict[Engine, set["WorkerWakeup"]] = {}
_hooks_installed = False


class WorkerWakeup:
    def __init__(self, loop):
        self._loop = loop
        self._event = asyncio.Event()
        self._active = True

    def clear_before_scan(self):
        self._event.clear()

    def signal(self):
        # Commit callbacks run in the API/model threadpool. Do not read asyncio
        # state there; the loop callback fences an already-closed subscription.
        try:
            self._loop.call_soon_threadsafe(self._signal_on_loop)
        except RuntimeError:
            pass  # Closed loop; the durable queue still has the admission.

    def _signal_on_loop(self):
        if self._active:
            self._event.set()

    async def wait(self, stop, *, timeout: float = 2):
        stopping = asyncio.create_task(stop.wait())
        waking = asyncio.create_task(self._event.wait())
        try:
            await asyncio.wait(
                (stopping, waking), timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in (stopping, waking):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stopping, waking, return_exceptions=True)

    def close(self):
        self._active = False
        self._event.clear()


def _engine(session):
    bind = session.get_bind(mapper=ModelWorkAdmission)
    return bind.engine if isinstance(bind, Connection) else bind


def _after_flush(session, _context):
    with _lock:
        if not _subscribers:
            return
    # A Session joined to an externally-owned Connection may commit only its
    # savepoint, while the actual database transaction is still uncommitted.
    # Such callers keep the durable polling fallback instead of an early hint.
    if isinstance(session.get_bind(mapper=ModelWorkAdmission), Connection):
        return
    if not any(
        isinstance(row, ModelWorkAdmission)
        and row.kind == "private_handoff"
        and row.state == "reserved"
        for row in session.new
    ):
        return
    with _lock:
        if _engine(session) not in _subscribers:
            return
    transaction = session.get_nested_transaction() or session.get_transaction()
    if transaction is not None:
        session.info.setdefault(_PENDING, set()).add(transaction)


def _after_commit(session):
    pending = session.info.get(_PENDING)
    if not pending:
        return
    nested = session.get_nested_transaction()
    if nested is not None:
        if nested in pending:
            pending.remove(nested)
            pending.add(nested.parent)
        return  # Savepoint success is not a durable admission.
    transaction = session.get_transaction()
    pending = session.info.pop(_PENDING, set())
    if transaction not in pending:
        return
    with _lock:
        subscribers = tuple(_subscribers.get(_engine(session), ()))
    for subscriber in subscribers:
        subscriber.signal()


def _transaction_end(session, transaction):
    pending = session.info.get(_PENDING)
    if pending is None:
        return
    if transaction.parent is None:
        session.info.pop(_PENDING, None)
    else:
        pending.discard(transaction)  # Rolled-back savepoint cannot wake on outer commit.


_EVENTS = (
    ("after_flush", _after_flush),
    ("after_commit", _after_commit),
    ("after_transaction_end", _transaction_end),
)


def _install_hooks_once():
    global _hooks_installed
    with _lock:
        if not _hooks_installed:
            for name, handler in _EVENTS:
                event.listen(Session, name, handler)
            _hooks_installed = True


# Runtime imports this module during worker startup, before accepting requests.
# Keeping this fixed set avoids mutating SQLAlchemy listener deques while a
# business transaction is concurrently dispatching an event during shutdown.
_install_hooks_once()


def _factory_engine(factory):
    # Existing isolated loop tests use non-SQLAlchemy stand-ins. They retain the
    # ordinary fallback; real application factories return a scoped Session.
    if not callable(factory):
        return None
    session = factory()
    if not isinstance(session, Session):
        return None
    try:
        bind = _engine(session)
        return bind if isinstance(bind, Engine) else None
    finally:
        session.close()


@contextmanager
def subscribe_worker(factory, *, lanes=3):
    engine = _factory_engine(factory)
    if engine is None:
        yield (None,) * lanes
        return
    wakeups = tuple(WorkerWakeup(asyncio.get_running_loop()) for _ in range(lanes))
    with _lock:
        _subscribers.setdefault(engine, set()).update(wakeups)
    try:
        yield wakeups
    finally:
        for wakeup in wakeups:
            wakeup.close()
        with _lock:
            subscribers = _subscribers.get(engine)
            if subscribers is not None:
                subscribers.difference_update(wakeups)
                if not subscribers:
                    del _subscribers[engine]
