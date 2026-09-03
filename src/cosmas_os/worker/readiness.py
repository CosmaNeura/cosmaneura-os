from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from celery import bootsteps, signals
from sqlalchemy import create_engine, text

from cosmas_os.config import settings
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION

WORKER_READINESS_HOST = "0.0.0.0"  # noqa: S104 - Container Apps probes the container IP.
WORKER_READINESS_PORT = 8001
WORKER_HEARTBEAT_MAX_AGE_SECONDS = 15.0
WORKER_CONTROL_PING_TIMEOUT_SECONDS = 1.5
WORKER_DATABASE_CONNECT_TIMEOUT_SECONDS = 2
WORKER_DATABASE_STATEMENT_TIMEOUT_MILLISECONDS = 1500
_SERVICE_ATTRIBUTE = "_cosmas_worker_readiness_service"


@dataclass(frozen=True)
class WorkerReadinessSnapshot:
    hostname: str | None
    last_heartbeat_at: float | None


class WorkerReadinessState:
    """Thread-safe proof that this worker reached ready and is still advancing."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._hostname: str | None = None
        self._last_heartbeat_at: float | None = None

    def mark_ready(self, hostname: str) -> None:
        normalized = hostname.strip()
        with self._lock:
            self._hostname = normalized or None
            self._last_heartbeat_at = self._clock() if normalized else None

    def mark_heartbeat(self) -> None:
        with self._lock:
            if self._hostname is not None:
                self._last_heartbeat_at = self._clock()

    def mark_not_ready(self) -> None:
        with self._lock:
            self._hostname = None
            self._last_heartbeat_at = None

    def snapshot(self) -> WorkerReadinessSnapshot:
        with self._lock:
            return WorkerReadinessSnapshot(self._hostname, self._last_heartbeat_at)

    def heartbeat_is_current(self, *, max_age_seconds: float) -> bool:
        snapshot = self.snapshot()
        if snapshot.hostname is None or snapshot.last_heartbeat_at is None:
            return False
        age = self._clock() - snapshot.last_heartbeat_at
        return 0 <= age <= max_age_seconds


class WorkerReadinessProbe:
    """Fail closed unless worker progress, Celery round-trip, and DB schema all pass."""

    def __init__(
        self,
        state: WorkerReadinessState,
        *,
        celery_ping: Callable[[str], bool],
        database_check: Callable[[], bool],
        heartbeat_max_age_seconds: float = WORKER_HEARTBEAT_MAX_AGE_SECONDS,
    ) -> None:
        self._state = state
        self._celery_ping = celery_ping
        self._database_check = database_check
        self._heartbeat_max_age_seconds = heartbeat_max_age_seconds

    def is_ready(self) -> bool:
        snapshot = self._state.snapshot()
        if snapshot.hostname is None or not self._state.heartbeat_is_current(
            max_age_seconds=self._heartbeat_max_age_seconds
        ):
            return False
        try:
            # The directed control round-trip proves this exact consumer can
            # receive and answer through the configured broker.
            if not self._celery_ping(snapshot.hostname):
                return False
            return self._database_check()
        except Exception:  # noqa: BLE001 - probes expose no dependency details
            return False


def celery_worker_responds(
    app: Any,
    hostname: str,
    *,
    timeout_seconds: float = WORKER_CONTROL_PING_TIMEOUT_SECONDS,
) -> bool:
    replies = app.control.ping(destination=[hostname], timeout=timeout_seconds)
    for reply in replies or []:
        payload = reply.get(hostname) if isinstance(reply, dict) else None
        if isinstance(payload, dict) and payload.get("ok") == "pong":
            return True
    return False


def database_schema_is_current() -> bool:
    connect_args: dict[str, int | str] = {}
    if settings.database_url.startswith("postgresql+psycopg://"):
        connect_args["connect_timeout"] = WORKER_DATABASE_CONNECT_TIMEOUT_SECONDS
        connect_args["options"] = (
            f"-c statement_timeout={WORKER_DATABASE_STATEMENT_TIMEOUT_MILLISECONDS}"
        )
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            return revision == EXPECTED_SCHEMA_REVISION
    finally:
        engine.dispose()


class _ReadinessRequestHandler(BaseHTTPRequestHandler):
    server_version = "cosmas-worker"
    sys_version = ""

    def __init__(
        self,
        *args: Any,
        readiness_check: Callable[[], bool],
        **kwargs: Any,
    ) -> None:
        self._readiness_check = readiness_check
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/ready":
            self._send_json(HTTPStatus.NOT_FOUND, {"status": "not_found"})
            return
        try:
            ready = self._readiness_check()
        except Exception:  # noqa: BLE001 - HTTP boundary must fail closed
            ready = False
        status = HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE
        self._send_json(status, {"status": "ready" if ready else "not_ready"})

    def _send_json(self, status: HTTPStatus, value: dict[str, str]) -> None:
        body = json.dumps(value, separators=(",", ":")).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Probe requests are intentionally quiet; dependency errors and URLs
        # must never be reflected into ordinary container logs.
        return


class _ProbeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


class WorkerReadinessHTTPServer:
    def __init__(
        self,
        readiness_check: Callable[[], bool],
        *,
        host: str = WORKER_READINESS_HOST,
        port: int = WORKER_READINESS_PORT,
    ) -> None:
        self._readiness_check = readiness_check
        self._host = host
        self._port = port
        self._server: _ProbeHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            return self._port
        return int(self._server.server_address[1])

    def start(self) -> None:
        if self._server is not None:
            return
        handler = partial(_ReadinessRequestHandler, readiness_check=self._readiness_check)
        server = _ProbeHTTPServer((self._host, self._port), handler)
        thread = threading.Thread(
            target=server.serve_forever,
            name="worker-readiness-http",
            daemon=True,
        )
        self._server = server
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        server, thread = self._server, self._thread
        if server is None:
            return
        self._server = None
        self._thread = None
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=2)


@dataclass
class WorkerReadinessService:
    state: WorkerReadinessState
    probe: WorkerReadinessProbe
    http_server: WorkerReadinessHTTPServer
    startup_check: Callable[[], bool]

    def start(self) -> None:
        try:
            startup_ready = self.startup_check()
        except Exception:  # noqa: BLE001 - never log a dependency exception/URL
            raise RuntimeError("worker readiness preflight failed") from None
        if not startup_ready:
            raise RuntimeError("worker readiness preflight failed")
        self.http_server.start()

    def stop(self) -> None:
        self.state.mark_not_ready()
        self.http_server.stop()


class WorkerReadinessBootstep(bootsteps.StartStopStep):
    """Gate consumer startup on DB/schema readiness, then serve probe traffic."""

    label = "CosmasWorkerReadiness"

    @staticmethod
    def _service(parent: Any) -> WorkerReadinessService:
        service = getattr(parent.app, _SERVICE_ATTRIBUTE, None)
        if not isinstance(service, WorkerReadinessService):
            raise RuntimeError("worker readiness service is not installed")
        return service

    def start(self, parent: Any) -> None:
        # Celery's Consumer bootstep is always last, so this gate completes
        # before the worker can reserve an application task.
        self._service(parent).start()

    def stop(self, parent: Any) -> None:
        self._service(parent).stop()

    def terminate(self, parent: Any) -> None:
        self.stop(parent)


def install_worker_readiness(app: Any) -> WorkerReadinessService:
    """Attach one private HTTP readiness service to the Celery main process."""

    state = WorkerReadinessState()
    probe = WorkerReadinessProbe(
        state,
        celery_ping=lambda hostname: celery_worker_responds(app, hostname),
        database_check=database_schema_is_current,
    )
    http_server = WorkerReadinessHTTPServer(probe.is_ready)
    service = WorkerReadinessService(
        state=state,
        probe=probe,
        http_server=http_server,
        startup_check=database_schema_is_current,
    )
    setattr(app, _SERVICE_ATTRIBUTE, service)
    app.steps["worker"].add(WorkerReadinessBootstep)

    def on_worker_ready(*, sender: Any = None, **_: Any) -> None:
        hostname = getattr(sender, "hostname", "")
        state.mark_ready(hostname if isinstance(hostname, str) else "")

    def on_heartbeat(**_: Any) -> None:
        state.mark_heartbeat()

    def on_worker_shutting_down(**_: Any) -> None:
        state.mark_not_ready()

    signals.worker_ready.connect(on_worker_ready, weak=False)
    signals.heartbeat_sent.connect(on_heartbeat, weak=False)
    signals.worker_shutting_down.connect(on_worker_shutting_down, weak=False)
    return service
