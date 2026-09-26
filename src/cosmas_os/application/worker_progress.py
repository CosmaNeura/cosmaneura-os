"""Process-local progress of private workspace workers; contains no work data."""

import threading
import time
from collections.abc import Callable

HANDOFF_MAX_AGE_SECONDS = 90.0
ROUTINE_MAX_AGE_SECONDS = 300.0
MAX_CONSECUTIVE_FAILURES = 3


class WorkerProgress:
    """Only completed passes establish readiness; starting a timer cannot do so.

    Uses the monotonic clock and thread-safe probe pattern of worker/readiness.py.
    Readiness runs in the API's threadpool while the worker reports on its loop.
    """

    def __init__(self, max_age_seconds: float, *, clock: Callable[[], float] = time.monotonic):
        if not 0 < max_age_seconds <= ROUTINE_MAX_AGE_SECONDS:
            raise ValueError("invalid worker progress interval")
        self._clock = clock
        self._max_age = max_age_seconds
        self._lock = threading.Lock()
        self._last_success: float | None = None
        self._failures = 0
        self._stopped = False

    def succeeded(self) -> None:
        with self._lock:
            if not self._stopped:
                self._last_success = self._clock()
                self._failures = 0

    def failed(self) -> None:
        with self._lock:
            self._failures = min(MAX_CONSECUTIVE_FAILURES, self._failures + 1)

    def stopped(self) -> None:
        with self._lock:
            self._stopped = True

    def is_ready(self) -> bool:
        with self._lock:
            if (self._stopped or self._last_success is None
                    or self._failures >= MAX_CONSECUTIVE_FAILURES):
                return False
            age = self._clock() - self._last_success
            return 0 <= age <= self._max_age


def workspace_workers_ready(application, settings) -> bool:
    expected = set()
    if settings.workspace_llm_available:
        expected.add("handoffs")
    if settings.workspace_available and settings.workspace_routines_enabled:
        expected.add("routines")
    if not expected:
        return True
    progress = getattr(application.state, "workspace_worker_progress", {})
    return isinstance(progress, dict) and all(
        isinstance(progress.get(name), WorkerProgress) and progress[name].is_ready()
        for name in expected
    )
