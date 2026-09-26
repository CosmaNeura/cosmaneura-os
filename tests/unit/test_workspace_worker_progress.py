"""Real worker loops and HTTP readiness, with controlled work and no provider I/O."""

import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from cosmas_os.application import handoffs, routines
from cosmas_os.application.worker_progress import WorkerProgress, workspace_workers_ready
from cosmas_os.config import Settings
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION


def test_progress_requires_completed_pass_and_recovers_from_transient_failures():
    now = [100.0]
    progress = WorkerProgress(90, clock=lambda: now[0])
    assert not progress.is_ready()
    progress.succeeded()
    now[0] += 31  # A normal model request does not make a working consumer unready.
    assert progress.is_ready()
    progress.failed()
    progress.failed()
    assert progress.is_ready()
    progress.failed()
    assert not progress.is_ready()
    progress.succeeded()
    assert progress.is_ready()
    now[0] += 91
    assert not progress.is_ready()
    progress.succeeded()
    now[0] -= 1
    assert not progress.is_ready()
    progress.stopped()
    progress.succeeded()  # Late completion cannot revive a stopped lifetime.
    assert not progress.is_ready()


def test_only_enabled_workers_from_this_application_are_required():
    application = FastAPI()
    config = SimpleNamespace(workspace_llm_available=False, workspace_available=True,
                             workspace_routines_enabled=False)
    assert workspace_workers_ready(application, config)
    config.workspace_routines_enabled = True
    assert not workspace_workers_ready(application, config)
    progress = WorkerProgress(300)
    application.state.workspace_worker_progress = {"routines": progress}
    progress.succeeded()
    assert workspace_workers_ready(application, config)
    config.workspace_llm_available = True
    assert not workspace_workers_ready(application, config)
    assert not workspace_workers_ready(FastAPI(), config)


@pytest.mark.parametrize("worker", ["handoffs", "routines"])
def test_actual_loop_reports_empty_success_failure_recovery_and_exit(worker, monkeypatch):
    progress = WorkerProgress(300)
    expected = [True, True, True, False, True]
    calls, observed = [], []
    source = object()
    module = handoffs if worker == "handoffs" else routines

    def process(factory, *cursor, **kwargs):
        calls.append((factory, cursor, kwargs))
        if len(calls) in {2, 3, 4}:
            raise RuntimeError("PRIVATE invented processing failure")
        return False if worker == "handoffs" else ("page-2" if len(calls) == 1 else None)

    class Stop:
        done = False

        def is_set(self):
            return self.done

        async def wait(self):
            observed.append(progress.is_ready())
            if len(observed) == len(expected):
                self.done = True
                return
            raise TimeoutError

    monkeypatch.setattr(module, "process_next" if worker == "handoffs" else "process_batch", process)
    arguments = {} if worker == "handoffs" else {"incoming_sources": source}
    asyncio.run(module.run_worker("invented-factory", Stop(), progress=progress, **arguments))
    assert observed == expected
    assert not progress.is_ready()
    assert len(calls) == 5
    if worker == "routines":
        assert [call[1] for call in calls] == [(None,), ("page-2",), ("page-2",), ("page-2",), ("page-2",)]
        assert all(call[2]["incoming_sources"] is source for call in calls)


@pytest.mark.parametrize("worker", ["handoffs", "routines"])
def test_pending_pass_cannot_heartbeat_and_cancellation_clears_readiness(worker, monkeypatch):
    now = [100.0]
    progress = WorkerProgress(90, clock=lambda: now[0])
    entered, release = threading.Event(), threading.Event()
    module = handoffs if worker == "handoffs" else routines

    def process(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return None

    monkeypatch.setattr(module, "process_next" if worker == "handoffs" else "process_batch", process)

    async def exercise():
        stop = asyncio.Event()
        progress.succeeded()
        task = asyncio.create_task(module.run_worker(None, stop, progress=progress))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            now[0] += 31
            assert progress.is_ready()
            now[0] += 60
            assert not progress.is_ready()
            release.set()
            for _ in range(100):
                if progress.is_ready():
                    break
                await asyncio.sleep(0.01)
            assert progress.is_ready()
            task.cancel()  # Work has completed; cancellation only ends the idle loop.
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not progress.is_ready()
        finally:
            release.set()
            stop.set()
            if not task.done():
                await task

    asyncio.run(exercise())


def test_ordinary_lifespan_and_http_ready_include_worker_progress(monkeypatch):
    from cosmas_os.api import app as api

    configuration = Settings(
        _env_file=None, workspace_enabled=True, workspace_authenticated_enabled=True,
        workspace_routines_enabled=True, workspace_llm_backend="azure_gpt41",
        workspace_llm_api_key="invented-worker-key", auth_mode="clerk_jwt", synth_seed=False,
        clerk_issuer="https://identity.example.invalid",
        clerk_jwks_url="https://identity.example.invalid/.well-known/jwks.json",
        clerk_audience="invented", clerk_organization_id="invented",
        beta_box_id="00000000-0000-4000-8000-000000000001",
        cors_allowed_origins="http://127.0.0.1:5173", clerk_authorized_parties="http://127.0.0.1:5173",
        database_url="postgresql+psycopg://invented@127.0.0.1/w1a_w80_unused",
    )
    monkeypatch.setattr(api, "settings", configuration)
    monkeypatch.setattr(handoffs, "process_next", lambda factory: False)
    monkeypatch.setattr(routines, "process_batch", lambda *args, **kwargs: None)
    application = FastAPI(lifespan=api.lifespan)
    application.add_api_route("/ready", api.ready, methods=["GET"])
    application.add_api_route("/health", api.health, methods=["GET"])
    checks = []

    class Database:
        def execute(self, statement):
            checks.append(str(statement))
            return SimpleNamespace(scalar_one=lambda: EXPECTED_SCHEMA_REVISION)

    application.dependency_overrides[api.get_session] = lambda: Database()

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://local") as client:
            assert (await client.get("/ready")).status_code == 503
            async with api.lifespan(application):
                progress = application.state.workspace_worker_progress
                assert set(progress) == {"handoffs", "routines"}
                for _ in range(100):
                    if workspace_workers_ready(application, configuration):
                        break
                    await asyncio.sleep(0.01)
                response = await client.get("/ready")
                assert response.status_code == 200, response.text
                assert len(checks) == 2
                for _ in range(3):
                    progress["routines"].failed()
                response = await client.get("/ready")
                assert response.status_code == 503
                assert response.json() == {"detail": "runtime is not ready"}
                assert len(checks) == 2  # Unhealthy workers fail before another dependency check.
                assert (await client.get("/health")).status_code == 200
                progress["routines"].succeeded()
                assert (await client.get("/ready")).status_code == 200
            assert all(not state.is_ready() for state in progress.values())
            assert (await client.get("/ready")).status_code == 503

    asyncio.run(exercise())
