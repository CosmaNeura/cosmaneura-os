"""Real route execution with invented resources; no database or sockets."""

import asyncio
import inspect
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from threading import get_ident
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.testclient import TestClient
from tests.unit import test_core_capture_admission as core_fixture
from tests.unit.test_core_capture_admission import core_handler, selection

from cosmas_os.adapters.core_record_connection import BoundedCoreRecordConnection
from cosmas_os.api import core_record_routes as route
from cosmas_os.api.auth import RequestIdentity
from cosmas_os.models import CoreCaptureAccount, ExternalIdentity


def test_slow_initial_identity_cannot_begin_core_work(monkeypatch):
    monkeypatch.setattr(route, "DEADLINE_SECONDS", 0.025, raising=False)
    events = []

    class Session:
        def rollback(self):
            events.append("rollback")

        def close(self):
            events.append("close")

    def sessions():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    identity = RequestIdentity(
        str(uuid4()), str(uuid4()), "clerk_jwt", external_identity_id=str(uuid4())
    )

    def authenticate(
        request: Request,
        session=Depends(sessions),
        authorization=Header(None),
        x_box_id=Header(None),
        x_actor_principal_id=Header(None),
    ):
        assert request.method == "GET"
        assert request.url.path.endswith("/cosmaneura-record/location")
        assert request.headers["authorization"] == authorization == "Bearer invented"
        assert request.headers["x-cosmas-record-contract"] == "1"
        assert x_box_id is None and x_actor_principal_id is None
        time.sleep(0.12)
        events.append("identity_returned")
        return identity

    def gate(response: Response, request: Request):
        response.headers["Cache-Control"] = "no-store"

    def capture():
        yield object()

    @contextmanager
    def connection(_settings, _budget):
        events.append("connection")
        yield object()

    def admitted(*args, **kwargs):
        events.append("core_work")
        raise ValueError("invented absence")

    monkeypatch.setattr(route.workspace_capture, "admit", admitted)
    if hasattr(route, "session_deadline"):

        @contextmanager
        def no_database(_session, budget):
            budget.check()
            yield

        monkeypatch.setattr(route, "session_deadline", no_database)
    configuration = SimpleNamespace(
        workspace_core_record_available=True, core_web_origin="https://core.example.invalid"
    )
    kwargs: dict[str, Any] = dict(
        settings=lambda: configuration, identity_dependency=authenticate, workspace_gate=gate
    )
    if "session_factory" in inspect.signature(route.router).parameters:
        kwargs.update(session_factory=Session, connection_factory=connection)
    else:
        kwargs.update(get_session=sessions, capture_connection=capture)
    app = FastAPI()
    app.include_router(route.router(**kwargs))
    route.install_record_boundary(app)
    # Baseline's WorkspaceError has no app handler in this small fixture.
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            f"/workspaces/{uuid4()}/cosmaneura-record/location",
            headers={"Authorization": "Bearer invented", "X-Cosmas-Record-Contract": "1"},
        )
    assert response.status_code == 504
    assert "core_work" not in events and "connection" not in events
    # Public timeout no longer waits for the independently owned reader.
    until = time.monotonic() + 1
    while "close" not in events:
        assert time.monotonic() < until
        time.sleep(0.002)
    assert "identity_returned" in events
    assert events.index("identity_returned") < events.index("close")


@pytest.fixture
def fixture(monkeypatch):
    selected = selection()
    now = datetime.now(UTC)
    monkeypatch.setattr(core_fixture, "NOW", now)
    f = SimpleNamespace(
        events=[],
        dispatches=[],
        calls=[],
        identity_valid=True,
        patient_valid=True,
        slow=None,
        after=lambda path: None,
        selected=selected,
        marker=ContextVar("invented_request_resource", default=None),
    )
    f.configuration = SimpleNamespace(
        workspace_core_record_available=True, core_web_origin="https://core.example.invalid"
    )
    f.identity = RequestIdentity(
        str(uuid4()), str(uuid4()), "clerk_jwt", external_identity_id=str(uuid4())
    )
    account = SimpleNamespace(
        id=uuid4(),
        core_actor_ref=selected.expected_actor_ref,
        core_tenant_ref=selected.expected_tenant_ref,
    )
    workspace = SimpleNamespace(
        appointment_id=uuid4(), patient_link_id=uuid4(), owner_id=f.identity.principal_id
    )
    appointment = SimpleNamespace(source="cosmaneura_core", external_id=selected.appointment_ref)

    class Session:
        def __init__(self):
            self.owner = get_ident()
            f.events.append(("session", self.owner))

        def check(self, name):
            assert get_ident() == self.owner
            f.events.append((name, self.owner))

        def scalar(self, statement):
            self.check("sql")
            entity = statement.column_descriptions[0]["entity"]
            assert entity in {ExternalIdentity, CoreCaptureAccount}
            return account if entity is CoreCaptureAccount else object()

        def expire_all(self):
            self.check("expire")

        def commit(self):
            self.check("commit")

        def rollback(self):
            self.check("rollback")

        def close(self):
            self.check("close")

    @contextmanager
    def no_database(_session, budget):
        budget.check()
        yield

    monkeypatch.setattr(route, "session_deadline", no_database)

    def authenticate(**kwargs):
        request = kwargs["request"]
        assert isinstance(request, Request)
        assert request.method == "GET" and request.url.path.endswith("/cosmaneura-record/location")
        assert request.headers["authorization"] == kwargs["authorization"]
        assert kwargs["session"].owner == get_ident()
        assert kwargs["x_box_id"] is None and kwargs["x_actor_principal_id"] is None
        assert kwargs["authorization"] == "Bearer synthetic_PRIVATE_jwt"
        assert f.marker.get() is None
        if not f.identity_valid:
            raise route.ws.WorkspaceError("core_record_access_denied", 403)
        f.events.append(("auth", get_ident()))
        return f.identity

    def encounter(*args, owner):
        assert owner == f.identity.principal_id
        if not f.patient_valid:
            raise route.ws.WorkspaceError("encounter_unavailable", 404)
        return appointment

    monkeypatch.setattr(route.ws, "_workspace", lambda *args, **kwargs: workspace)
    monkeypatch.setattr(route.ws, "_encounter", encounter)

    def gate(response: Response, request: Request):
        assert request.headers["x-cosmas-draft-recovery"] == "2"
        f.events.append(("gate", get_ident()))

    async def handler(request):
        path = request.url.path
        f.dispatches.append(path)
        if f.slow == path:
            await asyncio.sleep(1)
        response = core_handler(selected, f.calls)(request)
        f.after(path)
        return response

    @contextmanager
    def connection(configuration, budget):
        f.events.append(("connection", get_ident()))
        port = BoundedCoreRecordConnection(
            "https://core.example.invalid",
            lambda: "synthetic_PRIVATE_workload",
            budget,
            now=lambda: now,
            transport_factory=lambda: httpx.MockTransport(handler),
        )
        try:
            yield port
        finally:
            port.close()
            f.events.append(("port_closed", get_ident()))

    f.app = FastAPI()
    f.app.include_router(
        route.router(
            settings=lambda: f.configuration,
            session_factory=Session,
            identity_dependency=authenticate,
            workspace_gate=gate,
            connection_factory=connection,
        )
    )
    route.install_record_boundary(f.app)
    f.path = f"/workspaces/{selected.workspace_id}/cosmaneura-record/location"
    f.headers = {
        "Authorization": "Bearer synthetic_PRIVATE_jwt",
        "X-Cosmas-Record-Contract": "1",
        "X-Cosmas-Draft-Recovery": "2",
    }
    return f


PATHS = [
    "/embed/v1/context-tokens/exchange",
    "/service/v1/agent/mount-context/resolve",
    "/service/v1/agent/scribe/capture-bindings/resolve",
]


def test_actual_application_chain_keeps_current_authority_and_private_worker(fixture):
    f = fixture
    f.marker.set("request-owned-must-not-enter-worker")
    with TestClient(f.app) as client:
        response = client.get(f.path, headers=f.headers)
    assert response.status_code == 200, response.text
    assert (
        response.json()["href"]
        == f.configuration.core_web_origin + "/notes/" + f.selected.appointment_ref
    )
    assert response.headers["cache-control"] == "no-store"
    assert f.dispatches == PATHS
    names = [name for name, thread in f.events]
    assert names.count("gate") == names.count("auth") == 6
    assert names.index("port_closed") < names.index("close")
    assert len({thread for name, thread in f.events}) == 1


@pytest.mark.parametrize("phase", PATHS)
@pytest.mark.parametrize("change", ["identity", "patient", "disabled", "origin"])
def test_changed_current_scope_prevents_next_phase_or_disclosure(fixture, phase, change):
    f = fixture

    def mutate(path):
        if path == phase:
            if change == "identity":
                f.identity_valid = False
            elif change == "patient":
                f.patient_valid = False
            elif change == "disabled":
                f.configuration.workspace_core_record_available = False
            else:
                f.configuration.core_web_origin = "https://changed.invalid"

    f.after = mutate
    with TestClient(f.app) as client:
        response = client.get(f.path, headers=f.headers)
    assert response.status_code in {403, 404, 409}, response.text
    assert "href" not in response.text
    assert f.dispatches == PATHS[: PATHS.index(phase) + 1]


@pytest.mark.parametrize("phase", PATHS)
def test_timeout_of_each_dispatched_phase_never_starts_the_next(fixture, monkeypatch, phase):
    f = fixture
    monkeypatch.setattr(route, "DEADLINE_SECONDS", 0.08)
    f.slow = phase
    with TestClient(f.app) as client:
        response = client.get(f.path, headers=f.headers)
    assert response.status_code == 504
    assert f.dispatches == PATHS[: PATHS.index(phase) + 1]
    names = [name for name, thread in f.events]
    assert names.index("port_closed") < names.index("close")
    assert len({thread for name, thread in f.events}) == 1


def test_slow_body_expires_before_session_or_auth(fixture, monkeypatch):
    f = fixture
    monkeypatch.setattr(route, "DEADLINE_SECONDS", 0.02)
    sent = []

    async def receive():
        await asyncio.sleep(1)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(
        f.app(
            {
                "type": "http",
                "method": "GET",
                "scheme": "https",
                "path": f.path,
                "query_string": b"",
                "headers": [(k.lower().encode(), v.encode()) for k, v in f.headers.items()],
            },
            receive,
            send,
        )
    )
    assert sent[0]["status"] == 504 and f.events == [] and f.dispatches == []


def test_disconnect_cancels_active_http_without_next_phase(fixture):
    f = fixture
    f.slow = PATHS[0]
    sent = []

    async def invoke():
        received = False

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": b"", "more_body": False}
            while not f.dispatches:
                await asyncio.sleep(0.001)
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        await f.app(
            {
                "type": "http",
                "method": "GET",
                "scheme": "https",
                "path": f.path,
                "query_string": b"",
                "headers": [(k.lower().encode(), v.encode()) for k, v in f.headers.items()],
            },
            receive,
            send,
        )

    asyncio.run(invoke())
    # A disconnected caller receives no new response; cleanup remains private.
    assert sent == [] and f.dispatches == PATHS[:1]
    until = time.monotonic() + 1
    while not any(name == "close" for name, _ in f.events):
        assert time.monotonic() < until
        time.sleep(0.002)
    names = [name for name, thread in f.events]
    assert names.index("port_closed") < names.index("close")


def test_slow_output_headers_cannot_admit_private_location_body(monkeypatch):
    monkeypatch.setattr(route, "DEADLINE_SECONDS", 0.02)
    app = FastAPI()
    routes = route.APIRouter(route_class=route.RecordRoute)

    @routes.get("/workspaces/{workspace_id}/cosmaneura-record/location")
    async def output():
        return {"href": "https://core.example.invalid/private"}

    app.include_router(routes)
    route.install_record_boundary(app)
    sent = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.start":
            await asyncio.sleep(0.08)

    asyncio.run(
        app(
            {
                "type": "http",
                "method": "GET",
                "path": f"/workspaces/{uuid4()}/cosmaneura-record/location",
                "query_string": b"",
                "headers": [],
            },
            receive,
            send,
        )
    )
    assert not any(b"private" in message.get("body", b"") for message in sent)


@pytest.mark.parametrize(
    "kind", ["off", "unsigned", "wrong-contract", "query", "encoding", "legacy-actor"]
)
def test_preflight_denial_never_constructs_core_connection(fixture, kind):
    f = fixture
    if kind == "off":
        f.configuration.workspace_core_record_available = False
    if kind == "unsigned":
        f.identity = RequestIdentity(str(uuid4()), str(uuid4()), "dev_headers")
    if kind == "wrong-contract":
        f.headers["X-Cosmas-Record-Contract"] = "2"
    if kind == "query":
        f.path += "?destination=elsewhere"
    if kind == "encoding":
        f.headers["Content-Encoding"] = "gzip"
    if kind == "legacy-actor":
        f.headers["X-Actor-Principal-ID"] = "invented"
    with TestClient(f.app) as client:
        response = client.get(f.path, headers=f.headers)
    assert response.status_code in {403, 404, 422, 426}
    assert response.headers["cache-control"] == "no-store"
    assert not f.dispatches and not any(name == "connection" for name, _ in f.events)


@pytest.mark.parametrize("fault", ["denial", "work-timeout"])
def test_error_response_send_has_a_finite_grace(fixture, monkeypatch, fault):
    f = fixture
    monkeypatch.setattr(route, "DEADLINE_SECONDS", 0.03)
    monkeypatch.setattr(route, "ERROR_SEND_SECONDS", 0.03, raising=False)
    if fault == "denial":
        f.configuration.workspace_core_record_available = False
    else:
        f.slow = PATHS[0]
    sent = []

    async def invoke():
        received = False

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.sleep(1)
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)
            await asyncio.sleep(0.3)

        await f.app(
            {
                "type": "http",
                "method": "GET",
                "path": f.path,
                "query_string": b"",
                "headers": [(k.lower().encode(), v.encode()) for k, v in f.headers.items()],
            },
            receive,
            send,
        )

    started = time.monotonic()
    asyncio.run(invoke())
    assert time.monotonic() - started < 0.2
    assert sent[0]["status"] == (404 if fault == "denial" else 504)
    assert not any(b"href" in message.get("body", b"") for message in sent)
