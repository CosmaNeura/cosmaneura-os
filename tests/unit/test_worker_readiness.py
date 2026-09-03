from __future__ import annotations

import http.client
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from cosmas_os.config import settings
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION
from cosmas_os.worker.readiness import (
    WorkerReadinessBootstep,
    WorkerReadinessHTTPServer,
    WorkerReadinessProbe,
    WorkerReadinessService,
    WorkerReadinessState,
    celery_worker_responds,
    database_schema_is_current,
)


def test_probe_requires_ready_signal_and_current_heartbeat() -> None:
    now = [100.0]
    calls: list[tuple[str, str]] = []
    state = WorkerReadinessState(clock=lambda: now[0])
    probe = WorkerReadinessProbe(
        state,
        celery_ping=lambda hostname: calls.append(("celery", hostname)) or True,
        database_check=lambda: calls.append(("database", "checked")) or True,
        heartbeat_max_age_seconds=15,
    )

    assert probe.is_ready() is False
    assert calls == []

    state.mark_ready("celery@test-worker")
    assert probe.is_ready() is True
    assert calls == [("celery", "celery@test-worker"), ("database", "checked")]

    calls.clear()
    now[0] = 116.0
    assert probe.is_ready() is False
    assert calls == []

    state.mark_heartbeat()
    assert probe.is_ready() is True

    state.mark_not_ready()
    assert probe.is_ready() is False


def test_probe_fails_closed_on_celery_or_database_failure() -> None:
    state = WorkerReadinessState(clock=lambda: 10.0)
    state.mark_ready("celery@test-worker")
    database_calls: list[bool] = []

    broker_down = WorkerReadinessProbe(
        state,
        celery_ping=lambda _: False,
        database_check=lambda: database_calls.append(True) or True,
    )
    assert broker_down.is_ready() is False
    assert database_calls == []

    database_down = WorkerReadinessProbe(
        state,
        celery_ping=lambda _: True,
        database_check=lambda: False,
    )
    assert database_down.is_ready() is False

    dependency_error = WorkerReadinessProbe(
        state,
        celery_ping=lambda _: (_ for _ in ()).throw(RuntimeError("secret broker URL")),
        database_check=lambda: True,
    )
    assert dependency_error.is_ready() is False


def test_directed_celery_ping_requires_expected_worker_pong() -> None:
    class Control:
        def __init__(self, replies):
            self.replies = replies
            self.call = None

        def ping(self, *, destination, timeout):
            self.call = (destination, timeout)
            return self.replies

    class App:
        def __init__(self, replies):
            self.control = Control(replies)

    responding = App([{"celery@test-worker": {"ok": "pong"}}])
    assert celery_worker_responds(responding, "celery@test-worker") is True
    assert responding.control.call == (["celery@test-worker"], 1.5)

    wrong_worker = App([{"celery@other-worker": {"ok": "pong"}}])
    assert celery_worker_responds(wrong_worker, "celery@test-worker") is False

    malformed = App([{"celery@test-worker": {"ok": "not-pong"}}])
    assert celery_worker_responds(malformed, "celery@test-worker") is False


def test_database_check_requires_exact_schema_revision(monkeypatch, tmp_path) -> None:
    database_path = tmp_path / "readiness.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64))"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": EXPECTED_SCHEMA_REVISION},
        )
    engine.dispose()
    monkeypatch.setattr(settings, "database_url", database_url)

    assert database_schema_is_current() is True

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE alembic_version SET version_num = 'stale_revision'")
        )
    engine.dispose()

    assert database_schema_is_current() is False


def test_http_probe_returns_only_generic_status() -> None:
    readiness = [False]
    server = WorkerReadinessHTTPServer(
        lambda: readiness[0],
        host="127.0.0.1",
        port=0,
    )
    server.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=2)
        connection.request("GET", "/ready")
        response = connection.getresponse()
        body = response.read()
        assert response.status == 503
        assert json.loads(body) == {"status": "not_ready"}
        assert b"secret" not in body
        connection.close()

        readiness[0] = True
        connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=2)
        connection.request("GET", "/ready")
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {"status": "ready"}
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=2)
        connection.request("GET", "/unknown")
        response = connection.getresponse()
        assert response.status == 404
        assert json.loads(response.read()) == {"status": "not_found"}
        connection.close()
    finally:
        server.stop()


def test_http_probe_hides_unexpected_checker_errors() -> None:
    def fail() -> bool:
        raise RuntimeError("postgresql://user:secret@example.invalid/cosmas_os")

    server = WorkerReadinessHTTPServer(fail, host="127.0.0.1", port=0)
    server.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=2)
        connection.request("GET", "/ready")
        response = connection.getresponse()
        body = response.read()
        assert response.status == 503
        assert json.loads(body) == {"status": "not_ready"}
        assert b"secret" not in body
        connection.close()
    finally:
        server.stop()


def test_bootstep_blocks_consumer_start_when_database_preflight_fails() -> None:
    state = WorkerReadinessState()
    http_server = WorkerReadinessHTTPServer(lambda: False, host="127.0.0.1", port=0)
    service = WorkerReadinessService(
        state=state,
        probe=WorkerReadinessProbe(
            state,
            celery_ping=lambda _: True,
            database_check=lambda: True,
        ),
        http_server=http_server,
        startup_check=lambda: False,
    )
    parent = SimpleNamespace(app=SimpleNamespace(_cosmas_worker_readiness_service=service))

    with pytest.raises(RuntimeError, match="worker readiness preflight failed"):
        WorkerReadinessBootstep(parent).start(parent)

    # No probe listener is created when the preflight gate fails.
    assert http_server.port == 0
