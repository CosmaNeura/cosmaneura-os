"""One cancellation fence for the location route and its privately owned worker."""

import asyncio
import time
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from threading import Event, Lock
from typing import Any, Protocol, TypeVar

from sqlalchemy import event
from sqlalchemy.orm import Session

T = TypeVar("T")


class SessionDeadline(Protocol):
    def check(self) -> float: ...


class RecordDeadlineExceeded(TimeoutError):
    pass


class RecordDeadline:
    def __init__(self, seconds: float = 30):
        if not 0 < seconds <= 30:
            raise ValueError("invalid_record_deadline")
        self.when = time.monotonic() + seconds
        self.cancelled = Event()
        self._lock = Lock()
        self._callbacks: set[Callable[[], None]] = set()

    def check(self) -> float:
        remaining = self.when - time.monotonic()
        if self.cancelled.is_set() or remaining <= 0:
            raise RecordDeadlineExceeded("core_record_unavailable")
        return remaining

    def cancel(self) -> None:
        self.cancelled.set()
        with self._lock:
            callbacks = tuple(self._callbacks)
        for callback in callbacks:
            callback()

    def run(self, operation: Callable[[], Coroutine[Any, Any, T]]) -> T:
        """Run bounded async I/O in this worker, never in the request event loop."""
        self.check()
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("record_transport_requires_worker")

        async def execute() -> T:
            loop = asyncio.get_running_loop()
            task = asyncio.current_task()
            assert task is not None

            def cancel_active() -> None:
                try:
                    loop.call_soon_threadsafe(task.cancel)
                except RuntimeError:
                    # The worker closed its own loop after completing cleanup.
                    pass

            with self._lock:
                self._callbacks.add(cancel_active)
            try:
                async with asyncio.timeout(self.check()):
                    result = await operation()
                    self.check()
                    return result
            except (asyncio.CancelledError, TimeoutError):
                raise RecordDeadlineExceeded("core_record_unavailable") from None
            finally:
                with self._lock:
                    self._callbacks.discard(cancel_active)

        return asyncio.run(execute())


@contextmanager
def session_deadline(session: Session, budget: SessionDeadline, *, allow_writes: bool = False) -> Iterator[None]:
    """Apply fresh local limits to every source statement and read-only commit.

    Session acquisition and pool health/connection initialization may finish late;
    the first source statement then refuses. The worker owns all cleanup.
    """
    connections = []

    def before_statement(connection, cursor, statement, parameters, context, executemany):
        milliseconds = max(1, int(budget.check() * 1000))
        raw = connection.connection.cursor()
        try:
            raw.execute(f"SET LOCAL statement_timeout = {milliseconds}")
            lock_milliseconds = max(1, min(2000, int(budget.check() * 1000)))
            raw.execute(f"SET LOCAL lock_timeout = {lock_milliseconds}")
        finally:
            raw.close()
        budget.check()

    def began(_session, _transaction, connection):
        budget.check()
        if connection.dialect.name != "postgresql":
            raise ValueError("record_database_unavailable")
        event.listen(connection, "before_cursor_execute", before_statement)
        connections.append(connection)

    def before_commit(current):
        budget.check()
        if not allow_writes and (current.new or current.dirty or current.deleted):
            raise ValueError("record_write_not_allowed")

    def before_flush(*_args):
        budget.check()
        if not allow_writes:
            raise ValueError("record_write_not_allowed")

    budget.check()
    event.listen(session, "after_begin", began)
    event.listen(session, "before_commit", before_commit)
    event.listen(session, "before_flush", before_flush)
    try:
        yield
    finally:
        for connection in connections:
            event.remove(connection, "before_cursor_execute", before_statement)
        event.remove(session, "after_begin", began)
        event.remove(session, "before_commit", before_commit)
        event.remove(session, "before_flush", before_flush)
