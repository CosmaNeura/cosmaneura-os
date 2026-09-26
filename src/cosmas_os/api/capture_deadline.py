"""Before-dependency capture deadline with bounded, privately owned workers."""

import asyncio
import time
from concurrent.futures import Future
from contextlib import AsyncExitStack
from contextvars import Context
from threading import BoundedSemaphore, Lock, Thread

from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.routing import Match
from starlette.types import Message, Receive, Scope, Send

from cosmas_os.application.capture_deadline import (
    CaptureBudget,
    CaptureDeadlineExceeded,
    capture_budget,
)

CAPTURE_REQUEST_SECONDS = 120.0
ERROR_SEND_SECONDS = 0.25
# Largest existing source envelope (24 MiB), plus the facade's closed metadata.
# This outer cap does not replace any smaller operation/model/request validator.
MAX_CAPTURE_RESPONSE_BYTES = 24 * 1024 * 1024 + 8192
_workers = BoundedSemaphore(4)
_error_workers = BoundedSemaphore(4)


def problem(status: int, path: str) -> JSONResponse:
    # The boundary is outside the existing lane middlewares, so preserve their
    # closed error shapes without passing private exceptions through them.
    family = next((kind for kind in ("vendor", "finance", "membership")
                   if f"/{kind}-work" in path or kind == "vendor" and "/vendor-artifacts" in path), None)
    content = (
        {"contract_version": 1, "error": {"code": family + "_unavailable"}}
        if family else {"detail": "portal_work_unconfirmed" if "/portal-work" in path
                       else "capture_request_unconfirmed"}
    )
    return JSONResponse(content, status_code=status, headers={"Cache-Control": "no-store"})


class _Ownership:
    def __init__(self, workers: BoundedSemaphore):
        self.workers = workers
        self.lock = Lock()
        self.remaining = 2  # Private worker and public handler.

    def retain(self) -> None:
        with self.lock:
            self.remaining += 1

    def release(self) -> None:
        with self.lock:
            self.remaining -= 1
            if self.remaining == 0:
                self.workers.release()


class CaptureBoundary:
    """Own the original ASGI dependency graph until its actual cleanup completes."""

    def __init__(self, app, seconds=CAPTURE_REQUEST_SECONDS, *, failure_path="",
                 max_response_bytes=None, error_factory=None,
                 error_send_seconds=None):
        self.app, self.seconds, self.failure_path = app, seconds, failure_path
        self.max_response_bytes = MAX_CAPTURE_RESPONSE_BYTES if max_response_bytes is None else max_response_bytes
        self.error_factory = error_factory
        self.error_send_seconds = error_send_seconds

    _settling: set[asyncio.Future] = set()

    @classmethod
    def _abandon(cls, task: asyncio.Future) -> None:
        cls._settling.add(task)
        task.cancel()

        def settled(result):
            cls._settling.discard(result)
            if not result.cancelled():
                result.exception()

        task.add_done_callback(settled)

    @classmethod
    async def _send_until(
        cls,
        message: Message,
        send: Send,
        expires_at: float,
        ownership: _Ownership | None = None,
    ) -> None:
        if expires_at <= time.monotonic():
            raise CaptureDeadlineExceeded
        task = asyncio.ensure_future(send(message))
        if ownership is not None:
            ownership.retain()
            task.add_done_callback(lambda _: ownership.release())
        try:
            done, _ = await asyncio.wait(
                {task}, timeout=max(0, expires_at - time.monotonic())
            )
            if not done:
                cls._abandon(task)
                raise CaptureDeadlineExceeded
            task.result()
        except asyncio.CancelledError:
            cls._abandon(task)
            raise

    async def _fail(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        ownership: _Ownership | None = None,
    ) -> None:
        error_slot = ownership is None
        if error_slot:
            if not _error_workers.acquire(blocking=False):
                return  # Even saturated error delivery has bounded ownership.
            ownership = _Ownership(_error_workers)
            ownership.release()  # No private application worker was admitted.
        expires_at = time.monotonic() + (ERROR_SEND_SECONDS if self.error_send_seconds is None else self.error_send_seconds)

        async def bounded_send(message):
            await self._send_until(message, send, expires_at, ownership)

        try:
            response = problem(status, self.failure_path) if self.error_factory is None else self.error_factory(status)
            await response(scope, receive, bounded_send)
        except CaptureDeadlineExceeded:
            return
        finally:
            if error_slot:
                assert ownership is not None
                ownership.release()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        seconds = self.seconds
        for key in ("vendor_deadline", "finance_deadline", "membership_deadline"):
            when = scope.get("state", {}).get(key)
            if when is not None:
                seconds = min(seconds, max(0, when - time.monotonic()))
        if seconds <= 0:
            await self._fail(scope, receive, send, 504)
            return
        budget = CaptureBudget(seconds)
        workers = _workers
        if not workers.acquire(blocking=False):
            await self._fail(scope, receive, send, 503)
            return
        ownership = _Ownership(workers)
        parent_loop = asyncio.get_running_loop()
        outcome: Future[tuple[int, list[Message]]] = Future()
        private_scope = {**scope, "state": dict(scope.get("state", {}))}
        body_finished = asyncio.Event()
        disconnected = asyncio.Event()
        receive_lock = asyncio.Lock()

        async def receive_main():
            ownership.retain()
            try:
                async with receive_lock:
                    budget.check()
                    message = await receive()
                    budget.check()
                    if message["type"] == "http.disconnect":
                        disconnected.set()
                        body_finished.set()
                        budget.cancel()
                    elif message["type"] == "http.request" and not message.get(
                        "more_body", False
                    ):
                        body_finished.set()
                    return message
            finally:
                ownership.release()

        async def watch_disconnect():
            # Do not consume a byte before the authenticated route asks for it.
            # Once its final body packet has arrived, own the remaining receive
            # side so a caller disconnect also fences already-running phases.
            await body_finished.wait()
            if not disconnected.is_set():
                await receive_main()
            if not disconnected.is_set():
                raise ValueError("invalid_capture_receive")

        async def serve():
            # Public cancellation fences permission but never cancels this task:
            # FastAPI must not close dependencies over a live synchronous worker.
            messages: list[Message] = []
            length = 0

            async def receive_private():
                budget.check()
                future = asyncio.run_coroutine_threadsafe(receive_main(), parent_loop)
                waiting_input = asyncio.wrap_future(future)
                try:
                    done, _ = await asyncio.wait({waiting_input}, timeout=budget.check())
                    if not done:
                        budget.cancel()
                        self._abandon(waiting_input)
                        raise CaptureDeadlineExceeded
                    message = waiting_input.result()
                    budget.check()
                    return message
                except asyncio.CancelledError:
                    budget.cancel()
                    self._abandon(waiting_input)
                    raise

            async def buffered(message: Message):
                nonlocal length
                budget.check()
                if message["type"] == "http.response.body":
                    length += len(message.get("body", b""))
                if length > self.max_response_bytes or len(messages) >= 4:
                    raise ValueError("capture_response_too_large")
                messages.append(message)

            budget.check()
            async with AsyncExitStack() as files:
                # FastAPI's form/file stack is normally owned by outer middleware.
                # Never borrow it across this worker boundary. Inner dependency
                # stacks are created by the retained request_response function.
                private_scope["fastapi_middleware_astack"] = files
                await self.app(private_scope, receive_private, buffered)
            budget.check()
            return 200, messages

        def run():
            try:
                with capture_budget(budget):
                    result = asyncio.run(serve())
            except (CaptureDeadlineExceeded, asyncio.CancelledError):
                result = (504, [])
            except BaseException:
                # Known HTTP/domain handlers run inside this private graph.
                # Unexpected errors must not reach outer ServerErrorMiddleware,
                # whose independent 500 sender would escape this deadline.
                result = (503, [])
            finally:
                # Includes async-generator, dependency and executor cleanup.
                # A resistant worker retains this slot; later requests fail closed.
                ownership.release()
            outcome.set_result(result)

        try:
            thread = Thread(
                target=lambda: Context().run(run),
                daemon=True,
                name="os-capture-request",
            )
            thread.start()
        except BaseException:
            ownership.release()
            ownership.release()
            budget.cancel()
            await self._fail(scope, receive, send, 503)
            return
        waiting = asyncio.wrap_future(outcome)
        ownership.retain()
        watching = asyncio.create_task(watch_disconnect())

        def watching_finished(result):
            # A receive failure may arrive while public sending is suspended,
            # after the worker won the initial wait. Fence the next body chunk
            # immediately and observe the error even on that late path.
            try:
                if not result.cancelled():
                    result.exception()
            finally:
                try:
                    budget.cancel()
                finally:
                    ownership.release()

        watching.add_done_callback(watching_finished)
        try:
            done, _ = await asyncio.wait(
                {waiting, watching},
                timeout=max(0, budget.expires_at - time.monotonic()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if watching in done:
                budget.cancel()
                if disconnected.is_set():
                    return
                # A failed receive grants no further work or private response.
                try:
                    watching.result()
                except CaptureDeadlineExceeded:
                    await self._fail(scope, receive, send, 504, ownership)
                except Exception:
                    await self._fail(scope, receive, send, 503, ownership)
                return
            if not done:
                budget.cancel()
                await self._fail(scope, receive, send, 504, ownership)
                return
            status, messages = waiting.result()
            try:
                budget.check()
            except CaptureDeadlineExceeded:
                status, messages = 504, []
            if status != 200:
                budget.cancel()
                await self._fail(scope, receive, send, status, ownership)
                return
            for message in messages:
                try:
                    budget.check()
                    await self._send_until(message, send, budget.expires_at, ownership)
                except CaptureDeadlineExceeded:
                    # Public headers may have been admitted. Never append an
                    # alternate status or another body chunk to partial output.
                    return
        finally:
            budget.cancel()
            if not watching.done():
                self._abandon(watching)
            ownership.release()


class CaptureMiddleware:
    """Outer user ASGI boundary; final output is never an intermediate stream."""

    def __init__(self, app, plans):
        self.app, self.plans = app, plans

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            for route, seconds in self.plans:
                match, _ = route.matches(scope)
                if match == Match.FULL:
                    await CaptureBoundary(self.app, min(seconds, CAPTURE_REQUEST_SECONDS), failure_path=route.path)(
                        scope, receive, send
                    )
                    return
        await self.app(scope, receive, send)


def install_capture_boundaries(app, connection_dependency):
    """Select exact dependency-bearing routes, wrap the complete middleware graph.

    Install last, after all existing middleware and route factories. FastAPI's
    outer ServerErrorMiddleware uses a direct send wrapper and receives no raw
    private worker error. Existing BaseHTTPMiddleware instances all stay inside.
    """
    def uses(dependant):
        return dependant.call is connection_dependency or any(
            uses(child) for child in dependant.dependencies
        )

    if any(item.cls is CaptureMiddleware for item in app.user_middleware):
        raise ValueError("capture_boundary_already_installed")
    inventory, plans = [], []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not uses(route.dependant):
            continue
        path = route.path
        seconds = (
            15 if "/membership-work" in path
            else 30 if "/vendor-work" in path or "/vendor-artifacts" in path or "/finance-work" in path
            else 45 if "/portal-work" in path
            else CAPTURE_REQUEST_SECONDS
        )
        plans.append((route, seconds))
        inventory.append({"path": path, "methods": sorted(route.methods or []), "seconds": seconds})
    app.add_middleware(CaptureMiddleware, plans=tuple(plans))
    app.state.capture_deadline_routes = inventory
    return inventory
