"""Capture ownership, cancellation and publication admission fences."""

import asyncio
import time
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event, Lock, RLock
from typing import Any, TypeVar

from sqlalchemy import Engine, event
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool as _threadpool

T = TypeVar("T")


class CaptureDeadlineExceeded(TimeoutError):
    pass


class CaptureBudget:
    def __init__(self, seconds: float):
        if not 0 < seconds <= 120:
            raise ValueError("invalid_capture_deadline")
        self.expires_at = time.monotonic() + seconds
        self.cancelled = Event()
        self._lock = Lock()
        self._callbacks: set[Callable[[], None]] = set()
        self.serial = RLock()

    def check(self) -> float:
        remaining = self.expires_at - time.monotonic()
        if self.cancelled.is_set() or remaining <= 0:
            raise CaptureDeadlineExceeded("capture_request_unconfirmed")
        return remaining

    def cancel(self) -> None:
        with self._lock:
            if self.cancelled.is_set():
                return
            self.cancelled.set()
            callbacks = tuple(self._callbacks)
        for callback in callbacks:
            callback()

    @contextmanager
    def on_cancel(self, callback: Callable[[], None]) -> Iterator[None]:
        """Link a privately owned protocol budget without borrowing its resources."""
        with self._lock:
            self._callbacks.add(callback)
            canceled = self.cancelled.is_set()
        try:
            if canceled:
                callback()
            yield
        finally:
            with self._lock:
                self._callbacks.discard(callback)

    def run(self, operation: Callable[[], Coroutine[Any, Any, T]]) -> T:
        """Cancel owned transport I/O, never the dependency graph."""
        self.check()
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("capture_transport_requires_worker")

        async def execute():
            loop, task = asyncio.get_running_loop(), asyncio.current_task()
            assert task is not None

            def cancel_active():
                try:
                    loop.call_soon_threadsafe(task.cancel)
                except RuntimeError:
                    pass

            with self._lock:
                self._callbacks.add(cancel_active)
            try:
                async with asyncio.timeout(self.check()):
                    result = await operation()
                    self.check()
                    return result
            except (asyncio.CancelledError, TimeoutError):
                self.cancel()
                raise CaptureDeadlineExceeded("capture_request_unconfirmed") from None
            finally:
                with self._lock:
                    self._callbacks.discard(cancel_active)

        return asyncio.run(execute())


_budget: ContextVar[CaptureBudget | None] = ContextVar("os_capture_budget", default=None)


def current_budget() -> CaptureBudget | None:
    return _budget.get()


@contextmanager
def capture_budget(budget: CaptureBudget) -> Iterator[None]:
    token = _budget.set(budget)
    try:
        budget.check()
        yield
    finally:
        _budget.reset(token)


def check_capture_deadline() -> float | None:
    budget = current_budget()
    return budget.check() if budget is not None else None


def own_capture_session(session: Session) -> Session:
    """Called at existing fresh Session factory seams, before any source SQL."""
    budget = current_budget()
    if budget is not None:
        budget.check()
        if session.info.get("os_capture_owner", budget) is not budget:
            raise CaptureDeadlineExceeded("capture_session_not_owned")
        session.info["os_capture_owner"] = budget
    return session


def new_capture_session(factory):
    session = factory()
    try:
        return own_capture_session(session)
    except BaseException:
        session.close()
        raise


async def capture_async(operation):
    def check():
        budget = current_budget()
        task = asyncio.current_task()
        if budget is not None and task is not None and task.cancelling():
            budget.cancel()
        check_capture_deadline()

    check()
    try:
        result = await operation()
    except asyncio.CancelledError:
        budget = current_budget()
        if budget is not None:
            budget.cancel()
        raise
    check()
    return result


async def run_in_threadpool(function, *args, **kwargs):
    """Hold dependencies until a canceled sync invocation actually settles.

    The public request never cancels its private ASGI dependency graph. This
    helper additionally handles shorter timers inside existing lane code.
    Unrelated calls retain Starlette's original behavior.
    """
    budget = current_budget()
    if budget is None:
        return await _threadpool(function, *args, **kwargs)
    cleanup = isinstance(getattr(function, "__self__", None), Session) and getattr(
        function, "__name__", None
    ) in {"rollback", "close"}

    def invoke():
        with budget.serial:
            if not cleanup:
                budget.check()
            result = function(*args, **kwargs)
            if not cleanup:
                budget.check()
            return result

    work = asyncio.create_task(_threadpool(invoke))
    canceled = False
    while not work.done():
        try:
            await asyncio.shield(work)
        except asyncio.CancelledError:
            canceled = True
            budget.cancel()
        except BaseException:
            break
    if canceled:
        if not work.cancelled():
            work.exception()
        raise asyncio.CancelledError
    return work.result()


def _session_budget(session):
    budget = current_budget()
    if budget is not None:
        budget.check()
        # Additional runtime Sessions are constructed by their retained private
        # factories. Bind their first transaction to this request; never reassign
        # a Session already used by a different capture request.
        if session.info.setdefault("os_capture_owner", budget) is not budget:
            raise CaptureDeadlineExceeded("capture_session_not_owned")
    return budget


@event.listens_for(Session, "after_begin")
def capture_session_begin(session, _transaction, _connection):
    _session_budget(session)


@event.listens_for(Session, "before_flush")
def capture_session_flush(session, _context, _instances):
    _session_budget(session)


@event.listens_for(Session, "before_commit")
def capture_session_commit(session):
    _session_budget(session)


@event.listens_for(Engine, "before_cursor_execute")
def capture_statement(connection, cursor, _statement, _parameters, _context, _many):
    budget = current_budget()
    if budget is None:
        return
    budget.check()
    if connection.dialect.name != "postgresql":
        raise CaptureDeadlineExceeded("capture_database_unavailable")
    cursor.execute(f"SET LOCAL statement_timeout = {max(1, int(budget.check() * 1000))}")
    cursor.execute(f"SET LOCAL lock_timeout = {max(1, min(2000, int(budget.check() * 1000)))}")
    budget.check()


@event.listens_for(Engine, "commit")
def capture_connection_commit(_connection):
    # Session.before_commit precedes its flush; also fence the DBAPI commit.
    check_capture_deadline()


def core_phase(function, *args, **kwargs):
    check_capture_deadline()
    result = function(*args, **kwargs)
    check_capture_deadline()
    return result


class DeadlineCorePort:
    """Guard real and injected ports; keep their validators unchanged."""

    def __init__(self, port):
        self.port = port

    def exchange_context(self, *args, **kwargs):
        return core_phase(self.port.exchange_context, *args, **kwargs)

    def resolve_context(self, *args, **kwargs):
        return core_phase(self.port.resolve_context, *args, **kwargs)

    def resolve_binding(self, *args, **kwargs):
        return core_phase(self.port.resolve_binding, *args, **kwargs)

    def encounter_context(self, *args, **kwargs):
        return core_phase(self.port.encounter_context, *args, **kwargs)

    def admit_capture(self, *args, **kwargs):
        return core_phase(self.port.admit_capture, *args, **kwargs)

    def perform_capture_operation(self, *args, **kwargs):
        return core_phase(self.port.perform_capture_operation, *args, **kwargs)

    def capture_note(self, *args, **kwargs):
        return core_phase(self.port.capture_note, *args, **kwargs)

    def close(self):
        return self.port.close()
