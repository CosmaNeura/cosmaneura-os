"""Late receive failure must fence private output and leave no orphan exception."""

import asyncio
import gc
from threading import BoundedSemaphore, Event

import pytest

from cosmas_os.api import capture_deadline as boundary


@pytest.mark.parametrize("operation_fails", [False, True])
@pytest.mark.parametrize("receive_fault", ["exception", "invalid_packet"])
def test_late_receive_failure_settles_and_withholds_later_private_body(
    monkeypatch, operation_fails, receive_fault
):
    workers = BoundedSemaphore(1)
    monkeypatch.setattr(boundary, "_workers", workers)
    receiving = Event()

    async def application(scope, receive, send):
        await receive()
        assert await asyncio.to_thread(receiving.wait, 1)
        if operation_fails:
            raise ValueError("Invented private operation failed")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"invented private result"})

    async def exercise():
        loop = asyncio.get_running_loop()
        unobserved = []
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: unobserved.append(context))
        release = asyncio.Event()
        released = asyncio.Event()
        first = True
        messages = []

        async def receive():
            nonlocal first
            if first:
                first = False
                return {"type": "http.request", "body": b"{}", "more_body": False}
            receiving.set()
            await release.wait()
            released.set()
            if receive_fault == "exception":
                raise OSError("Invented receive-side transport failure")
            return {"type": "http.request", "body": b"unexpected second packet"}

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.start":
                release.set()
                await released.wait()
                # Let the completed receive and its settlement callbacks run
                # before the sender accepts another response message.
                await asyncio.sleep(0)
                await asyncio.sleep(0)

        try:
            await asyncio.wait_for(
                boundary.CaptureBoundary(application, 2)(
                    {"type": "http", "method": "POST"}, receive, send
                ),
                3,
            )
            await asyncio.sleep(0)
            gc.collect()
            await asyncio.sleep(0)
            observed = {
                "unobserved": [value.get("message") for value in unobserved],
                "private_body_sent": any(
                    m.get("body") == b"invented private result" for m in messages
                ),
            }
            assert observed == {"unobserved": [], "private_body_sent": False}
            assert [m["status"] for m in messages if m["type"] == "http.response.start"] == [
                503 if operation_fails else 200
            ]
            assert workers.acquire(blocking=False), "Request ownership was not released"
            workers.release()
        finally:
            loop.set_exception_handler(previous)

    asyncio.run(exercise())
