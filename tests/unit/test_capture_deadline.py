"""Actual ASGI/dependency ownership and retained application phase tests, offline."""

import asyncio
import gc
import json
import time
from contextlib import AsyncExitStack
from contextvars import ContextVar
from threading import BoundedSemaphore, Event
from types import SimpleNamespace
from typing import Any, Never, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session
from tests.unit.test_core_capture_admission import NOW, core_handler, selection

from cosmas_os.adapters.core_capture_connection import BoundedCoreCaptureConnection
from cosmas_os.api import capture_deadline as boundary
from cosmas_os.application import capture_deadline as deadline
from cosmas_os.application import workspace_capture
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_capture import CoreCaptureAdmissionSnapshot

DELAY = 0.04


async def until(predicate, maximum=2):
    end = time.monotonic() + maximum
    while not predicate():
        assert time.monotonic() < end, 'private work failed to settle'
        await asyncio.sleep(0.005)


def isolated_app(monkeypatch, work, *, seconds=DELAY, cleanup=None, identity=None):
    events = []
    marker: ContextVar[str | None] = ContextVar('outer_unowned_sentinel', default=None)
    app = FastAPI()

    def sessions():
        assert marker.get() is None
        with deadline.own_capture_session(Session()) as session:
            events.append('session opened')
            try:
                yield session
            finally:
                if cleanup:
                    cleanup()
                events.append('session closed')

    def auth(s=Depends(sessions)):
        if identity:
            identity(s)
        events.append('identity')
        return 'owned identity'

    def connection():
        events.append('port opened')
        try:
            yield object()
        finally:
            events.append('port closed')

    @app.post('/workspaces/{workspace_id}/capture/admission')
    async def endpoint(request: Request, s=Depends(sessions), i=Depends(auth), p=Depends(connection)):
        await request.body()
        return await work(s, events)

    @app.get('/unrelated')
    async def unrelated():
        return {'ok': True}

    boundary.install_capture_boundaries(app, connection)
    monkeypatch.setattr(boundary, "CAPTURE_REQUEST_SECONDS", seconds)
    monkeypatch.setattr(boundary, '_workers', BoundedSemaphore(1))
    return app, events, marker


def test_sync_worker_keeps_resources_and_slot_after_public_timeout(monkeypatch):
    entered, release, cleaned = Event(), Event(), Event()
    def blocking(session, events):
        entered.set()
        release.wait(2)
        events.append('work settled')
        session.commit()  # Actual SQLAlchemy event must refuse this late commit.

    async def work(session, events):
        return await deadline.run_in_threadpool(blocking, session, events)

    async def run():
        app, events, marker = isolated_app(monkeypatch, work, cleanup=cleaned.set)
        token = marker.set('must not escape')
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://owned') as client:
                started = time.monotonic()
                response = await client.post(f'/workspaces/{uuid4()}/capture/admission', json={})
                assert time.monotonic() - started < 0.3
                assert response.status_code == 504 and entered.is_set()
                assert not cleaned.is_set() and 'port closed' not in events
                saturated = await client.post(f'/workspaces/{uuid4()}/capture/admission', json={})
                assert saturated.status_code == 503
                assert events.count('session opened') == 1
                assert (await client.get('/unrelated')).status_code == 200
                release.set()
                await until(cleaned.is_set)
                assert events.index('work settled') < events.index('port closed') < events.index('session closed')
        finally:
            marker.reset(token)
            release.set()
    asyncio.run(run())


def test_inner_timer_waits_for_sync_worker_before_dependency_close(monkeypatch):
    entered, release, cleaned = Event(), Event(), Event()
    def blocking():
        entered.set()
        release.wait(2)
        return {'private': 'late'}
    async def work(session, events):
        async with asyncio.timeout(0.01):
            return await deadline.run_in_threadpool(blocking)
    async def run():
        app, events, _ = isolated_app(monkeypatch, work, cleanup=cleaned.set)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://owned') as client:
            response = await client.post(f'/workspaces/{uuid4()}/capture/admission', json={})
            assert response.status_code == 504 and entered.is_set() and not cleaned.is_set()
            assert 'late' not in response.text
            release.set()
            await until(cleaned.is_set)
            assert events.index('port closed') < events.index('session closed')
    try:
        asyncio.run(run())
    finally:
        release.set()


def test_slow_sync_identity_never_starts_capture_and_keeps_session(monkeypatch):
    release, cleaned = Event(), Event()
    async def work(*_):
        pytest.fail('late identity admitted capture')
    def auth(session):
        release.wait(2)
        deadline.check_capture_deadline()
    async def run():
        app, events, _ = isolated_app(monkeypatch, work, identity=auth, cleanup=cleaned.set)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://owned') as client:
            response = await client.post(f'/workspaces/{uuid4()}/capture/admission', json={})
            assert response.status_code == 504 and not cleaned.is_set()
            assert 'port opened' not in events
            release.set()
            await until(cleaned.is_set)
    try:
        asyncio.run(run())
    finally:
        release.set()


def test_caller_cancel_does_not_close_live_worker(monkeypatch):
    entered, release, cleaned = Event(), Event(), Event()
    def blocking():
        entered.set()
        release.wait(2)
        return {'private': 'late'}
    async def work(*_):
        return await deadline.run_in_threadpool(blocking)
    async def run():
        app, _, _ = isolated_app(monkeypatch, work, seconds=2, cleanup=cleaned.set)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://owned') as client:
            task = asyncio.create_task(client.post(f'/workspaces/{uuid4()}/capture/admission', json={}))
            await until(entered.is_set)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not cleaned.is_set()
            release.set()
            await until(cleaned.is_set)
    try:
        asyncio.run(run())
    finally:
        release.set()


def test_session_affinity_and_late_sql_flush_commit_are_fenced():
    calls = []
    cursor = SimpleNamespace(execute=calls.append)
    connection = SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))
    budget = deadline.CaptureBudget(1)
    with deadline.capture_budget(budget), Session() as session:
        deadline.own_capture_session(session)
        deadline.capture_statement(connection, cursor, 'SELECT private', None, None, False)
        assert len(calls) == 2
        budget.cancel()
        with pytest.raises(deadline.CaptureDeadlineExceeded):
            deadline.capture_statement(connection, cursor, 'UPDATE private', None, None, False)
        with pytest.raises(deadline.CaptureDeadlineExceeded):
            deadline.capture_session_flush(session, None, None)
        with pytest.raises(deadline.CaptureDeadlineExceeded):
            session.commit()
        with pytest.raises(deadline.CaptureDeadlineExceeded):
            deadline.capture_connection_commit(connection)
    assert len(calls) == 2
    other = deadline.CaptureBudget(1)
    with deadline.capture_budget(other), pytest.raises(deadline.CaptureDeadlineExceeded):
        deadline.own_capture_session(session)
    with Session() as unrelated:
        unrelated.commit()  # Hook inert outside capture; no SQL involved.


@pytest.mark.parametrize('phase', ['exchange', 'resolve', 'binding', 'admission', 'prep', 'note'])
def test_retained_admission_stops_after_late_remote_phase(monkeypatch, phase):
    selected = selection()
    events = []
    budget = deadline.CaptureBudget(1)
    account = SimpleNamespace(id='account', core_actor_ref=selected.expected_actor_ref,
                              core_tenant_ref=selected.expected_tenant_ref)
    class PrivateSession:
        def expire_all(self):
            deadline.check_capture_deadline()
        def scalar(self, statement):
            deadline.check_capture_deadline()
            from cosmas_os.models import CoreCaptureAccount
            from cosmas_os.private_recording_models import PrivateRecordingTransfer
            entity = statement.column_descriptions[0]['entity']
            return account if entity is CoreCaptureAccount else None if entity is PrivateRecordingTransfer else object()
        def commit(self):
            deadline.check_capture_deadline()
            events.append('commit')
        def rollback(self):
            events.append('rollback')
    monkeypatch.setattr(workspace_capture.ws, '_workspace', lambda *a, **k: SimpleNamespace(appointment_id='a', patient_link_id='p', owner_id='actor'))
    monkeypatch.setattr(workspace_capture.ws, '_encounter', lambda *a, owner: SimpleNamespace(source='cosmaneura_core', external_id=selected.appointment_ref))
    session_id = uuid4()
    class Port:
        def value(self, name, value):
            events.append(name)
            if phase == name:
                budget.cancel()
            return value
        def exchange_context(self, *a):
            return self.value('exchange', object())
        def resolve_context(self, *a):
            return self.value('resolve', object())
        def resolve_binding(self, *a):
            return self.value('binding', SimpleNamespace(workspace_id=selected.workspace_id,
                binding_ref='invented-binding', appointment_ref=selected.appointment_ref))
        def admit_capture(self, *a, **kwargs):
            return self.value('admission', SimpleNamespace(session_id=session_id,
                workspace_id=selected.workspace_id, binding_ref='invented-binding',
                appointment_ref=selected.appointment_ref))
        def encounter_context(self, *a):
            return self.value('prep', SimpleNamespace())
        def capture_note(self, *a):
            return self.value('note', SimpleNamespace())
    from pydantic import SecretStr

    from cosmas_os.ports.core_notes import CoreNoteSelection
    args: dict[str, Any] = dict(box='box', actor='actor', external_identity_id='external', workspace_id=str(selected.workspace_id),
                bearer=SecretStr('invented'), reauthenticate=lambda: None, port=Port(),
                attestation=None, idempotency_key='invented')
    if phase == 'prep':
        args['prep'] = True
    if phase == 'note':
        args.update(expected_session_id=session_id, note_selection=CoreNoteSelection(action='read', schema_ref='doctor_note_schema_' + '0' * 25 + '1'),
                    finalize_note=lambda result: events.append('finalizer'))
    with deadline.capture_budget(budget), pytest.raises(deadline.CaptureDeadlineExceeded):
        workspace_capture.admit(cast(Session, PrivateSession()), **args)
    position = events.index(phase)
    assert events[position+1:] == ['rollback']
    assert 'finalizer' not in events


def test_late_token_never_dispatches_capture_http():
    calls = []
    budget = deadline.CaptureBudget(1)
    def token():
        budget.cancel()
        return 'synthetic_PRIVATE_workload'
    selected = selection()
    port = BoundedCoreCaptureConnection('https://core.example', token, budget,
        transport_factory=lambda: httpx.MockTransport(core_handler(selected, calls)), now=lambda: NOW)
    from pydantic import SecretStr
    try:
        token_value = port.exchange_context(selected, SecretStr('synthetic_PRIVATE_jwt'))
        assert len(calls) == 1
        with pytest.raises((ConnectorUnavailable, deadline.CaptureDeadlineExceeded)):
            port.resolve_context(selected, token_value)
        assert len(calls) == 1
    finally:
        port.close()


def test_bounded_real_adapter_preserves_successful_admission_protocol():
    selected, calls = selection(), []
    budget = deadline.CaptureBudget(2)
    port = BoundedCoreCaptureConnection('https://core.example', lambda: 'synthetic_PRIVATE_workload', budget,
        transport_factory=lambda: httpx.MockTransport(core_handler(selected, calls)), now=lambda: NOW)
    from pydantic import SecretStr
    try:
        token = port.exchange_context(selected, SecretStr('synthetic_PRIVATE_jwt'))
        credential = port.resolve_context(selected, token)
        binding = port.resolve_binding(selected, credential)
        result = port.admit_capture(binding, credential, None, 'invented')
        assert isinstance(result, CoreCaptureAdmissionSnapshot) and len(calls) == 4
    finally:
        port.close()


def test_auth_error_and_unrelated_route_semantics_survive_boundary(monkeypatch):
    async def work(*_):
        return {'ok': True}
    def auth(_):
        raise HTTPException(403, 'retained_access_denied')
    async def run():
        app, events, _ = isolated_app(monkeypatch, work, identity=auth, seconds=1)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://owned') as client:
            result = await client.post(f'/workspaces/{uuid4()}/capture/admission', json={})
            assert result.status_code == 403 and result.json()['detail'] == 'retained_access_denied'
            assert events[-1] == 'session closed'
            assert (await client.get('/unrelated')).json() == {'ok': True}
    asyncio.run(run())


def test_installed_product_inventory_is_exact_and_other_routes_unwrapped():
    from cosmas_os.api.app import app
    inventory = app.state.capture_deadline_routes
    assert len(inventory) == 36
    counts = {}
    for entry in inventory:
        assert entry['methods'] == ['POST']
        counts[entry['seconds']] = counts.get(entry['seconds'], 0) + 1
    assert counts == {120: 13, 30: 11, 45: 7, 15: 5}
    assert {entry['path'] for entry in inventory if '/handoffs/' in entry['path'] and entry['path'].endswith(('/review','/revision'))} == {
        '/workspaces/{workspace_id}/handoffs/{handoff_id}/review',
        '/workspaces/{workspace_id}/handoffs/{handoff_id}/revision',
    }
    for route in app.routes:
        if isinstance(route, APIRoute):
            found = any(i['path'] == route.path and 'POST' in (route.methods or set()) for i in inventory)
            assert not isinstance(route.app, boundary.CaptureBoundary)
            assert found == any(i[0] is route for i in cast(Any, next(item for item in app.user_middleware if item.cls is boundary.CaptureMiddleware).kwargs["plans"]))
    assert sum(item.cls is boundary.CaptureMiddleware for item in app.user_middleware) == 1


@pytest.mark.parametrize('index', range(36))
def test_every_installed_core_callback_route_bounds_slow_body(monkeypatch, index):
    from cosmas_os.api import app as product
    selected = cast(Any, next(item for item in product.app.user_middleware if item.cls is boundary.CaptureMiddleware).kwargs['plans'])[index][0]
    monkeypatch.setattr(boundary, 'CAPTURE_REQUEST_SECONDS', DELAY)
    workers = BoundedSemaphore(1)
    monkeypatch.setattr(boundary, '_workers', workers)
    identity = SimpleNamespace(box_id=str(uuid4()), principal_id=str(uuid4()), auth_mode='clerk_jwt', external_identity_id=str(uuid4()))
    events = []
    monkeypatch.setattr(product, "authenticate_request", lambda *args, **kwargs: identity)
    def sessions():
        with deadline.own_capture_session(Session()) as session:
            try:
                yield session
            finally:
                events.append('closed')
    def connection():
        yield object()
    overrides = {product.get_session: sessions, product._identity: lambda: identity,
                 product._capture_connection: connection, product._workspace_gate: lambda: None,
                 product._capture_gate: lambda: None, product._capture_note_gate: lambda: None,
                 product._prep_gate: lambda: None, product._prep_work_gate: lambda: None}
    for key, value in overrides.items():
        monkeypatch.setitem(product.app.dependency_overrides, key, value)
    params = {name: str(uuid4()) for name in ('workspace_id', 'ticket_id', 'note_id', 'handoff_id')}
    path = selected.path.format(**params)
    monkeypatch.setattr(product.settings, 'workspace_enabled', True)
    monkeypatch.setattr(product.settings, 'database_url', 'postgresql+psycopg://invented:invented@127.0.0.1:1/w1a_offline_deadline')
    lane_headers = []
    if '/handoffs/' in path and path.endswith(('/review','/revision')):
        lane_headers.extend([(b'x-cosmas-model-contract',b'1'),(b'x-cosmas-handoff-review',b'1')])
    for family, header in [('vendor','x-cosmas-vendor-contract'),('finance','x-cosmas-finance-contract'),
                           ('portal','x-cosmas-portal-work-contract'),('membership','x-cosmas-membership-contract')]:
        if f'/{family}-work' in path or family == 'vendor' and '/vendor-artifacts' in path:
            lane_headers.append((header.encode(), b'1'))
    scope = {'type':'http','asgi':{'version':'3.0'}, 'http_version':'1.1','method':'POST','scheme':'http',
             'path':path,'raw_path':path.encode(),'root_path':'','query_string':b'', 'path_params':params,
             'headers':[(b'content-type',b'application/json'),(b'authorization',b'Bearer invented'), *lane_headers],
             'client':('127.0.0.1',1),'server':('owned',1),'app':product.app}
    async def run():
        messages = []
        async def receive():
            return await asyncio.Future()
        async def send(message):
            messages.append(message)
        # This shard has already built a large object graph. A generation-2
        # collection during the deadline wait blocks the loop past the bound.
        # Collect that backlog before the clock starts.
        gc.collect()
        started = time.monotonic()
        await product.app(scope, receive, send)
        assert time.monotonic() - started < 0.35
        assert messages[0]['status'] == 504, (selected.path, messages)
        assert b'unconfirmed' in messages[1]['body'] or b'unavailable' in messages[1]['body']
        # A request with a built-in body parameter may not construct deps yet.
        def slot_free():
            free = workers.acquire(blocking=False)
            if free:
                workers.release()
            return free
        await until(slot_free)
    asyncio.run(run())


@pytest.mark.parametrize('error', [False, True])
def test_resistant_sender_cannot_publish_next_message(monkeypatch, error):
    sent, settled = [], Event()
    release = asyncio.Event()
    async def app(scope, receive, send):
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'private_sentinel'})
    async def run():
        nonlocal release
        release = asyncio.Event()
        async def receive():
            return await asyncio.Future()
        async def send(message):
            sent.append(message)
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            settled.set()
        if error:
            workers = BoundedSemaphore(1)
            assert workers.acquire(False)
            monkeypatch.setattr(boundary, '_workers', workers)
        else:
            monkeypatch.setattr(boundary, '_workers', BoundedSemaphore(1))
        monkeypatch.setattr(boundary, 'ERROR_SEND_SECONDS', DELAY)
        started = time.monotonic()
        await boundary.CaptureBoundary(app, DELAY)({'type':'http','method':'POST'}, receive, send)
        assert time.monotonic() - started < 0.2
        assert len(sent) == 1 and not settled.is_set()
        assert sent[0]['status'] == (503 if error else 200)
        release.set()
        await until(settled.is_set)
        assert len(sent) == 1
    asyncio.run(run())


def test_fastapi_0141_middleware_file_stack_is_owned_by_private_worker(monkeypatch):
    entered, release, private_closed = Event(), Event(), Event()
    outer_stack = AsyncExitStack()
    async def app(scope, receive, send):
        files = scope['fastapi_middleware_astack']
        assert isinstance(files, AsyncExitStack) and files is not outer_stack
        async def close_files():
            private_closed.set()
        files.push_async_callback(close_files)
        def blocking():
            entered.set()
            release.wait(2)
        await deadline.run_in_threadpool(blocking)
    async def run():
        async def receive():
            return await asyncio.Future()
        messages = []
        async def send(message):
            messages.append(message)
        async with outer_stack:
            await boundary.CaptureBoundary(app, DELAY)(
                {'type':'http','method':'POST','fastapi_middleware_astack':outer_stack},receive,send)
        assert entered.is_set() and not private_closed.is_set()
        assert messages[0]['status'] == 504
        release.set()
        await until(private_closed.is_set)
    monkeypatch.setattr(boundary, '_workers', BoundedSemaphore(1))
    try:
        asyncio.run(run())
    finally:
        release.set()


@pytest.mark.parametrize('phase', ['exchange', 'capture-admissions'])
def test_actual_product_capture_graph_refuses_late_core_response(monkeypatch, phase):
    from cosmas_os.api import app as product
    from cosmas_os.models import CoreCaptureAccount
    selected = selection()
    route = next(r for r in product.app.routes if isinstance(r, APIRoute) and r.path.endswith('/capture/admission'))
    monkeypatch.setattr(boundary, 'CAPTURE_REQUEST_SECONDS', DELAY)
    monkeypatch.setattr(boundary, '_workers', BoundedSemaphore(1))
    release, entered, closed = Event(), Event(), Event()
    calls, events = [], []
    identity = SimpleNamespace(box_id=str(uuid4()), principal_id=str(uuid4()), auth_mode='clerk_jwt', external_identity_id=str(uuid4()))
    account = SimpleNamespace(id='account', core_actor_ref=selected.expected_actor_ref, core_tenant_ref=selected.expected_tenant_ref)
    class PrivateSession:
        def expire_all(self):
            deadline.check_capture_deadline()
        def scalar(self, statement):
            deadline.check_capture_deadline()
            events.append('sql')
            return account if statement.column_descriptions[0]['entity'] is CoreCaptureAccount else object()
        def commit(self):
            deadline.check_capture_deadline()
            events.append('commit')
        def rollback(self):
            events.append('rollback')
        def close(self):
            events.append('session closed')
            closed.set()
    def sessions():
        session = PrivateSession()
        try:
            yield session
        finally:
            session.close()
    def mutate(name, *_):
        if name == phase:
            events.append('remote admitted')
            entered.set()
            release.wait(2)
            events.append('remote settled')
    def connection():
        budget = deadline.current_budget()
        assert budget is not None
        port = BoundedCoreCaptureConnection('https://core.example', lambda: 'synthetic_PRIVATE_workload', budget,
            transport_factory=lambda: httpx.MockTransport(core_handler(selected, calls, mutate)), now=lambda: NOW)
        try:
            yield port
        finally:
            port.close()
            events.append('port closed')
    monkeypatch.setattr(product, 'authenticate_request', lambda *a, **k: identity)
    monkeypatch.setattr(workspace_capture.ws, '_workspace', lambda *a, **k: SimpleNamespace(appointment_id='a', patient_link_id='p', owner_id=identity.principal_id))
    monkeypatch.setattr(workspace_capture.ws, '_encounter', lambda *a, owner: SimpleNamespace(source='cosmaneura_core', external_id=selected.appointment_ref))
    for key,value in {product.get_session:sessions, product._identity:lambda: identity,
                     product._capture_connection:connection, product._workspace_gate:lambda: None,
                     product._capture_gate:lambda: None}.items():
        monkeypatch.setitem(product.app.dependency_overrides,key,value)
    path = route.path.format(workspace_id=selected.workspace_id)
    scope = {'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
             'path':path,'raw_path':path.encode(),'root_path':'','query_string':b'',
             'path_params':{'workspace_id':str(selected.workspace_id)},
             'headers':[(b'content-type',b'application/json'),(b'authorization',b'Bearer synthetic_PRIVATE_jwt')],
             'client':('127.0.0.1',1),'server':('owned',1),'app':product.app}
    async def run():
        body = json.dumps({'idempotency_key':'invented'}).encode()
        read = False
        async def receive():
            nonlocal read
            if not read:
                read = True
                return {'type':'http.request','body':body,'more_body':False}
            return await asyncio.Future()
        messages=[]
        async def send(message):
            messages.append(message)
        started=time.monotonic()
        await product.app(scope,receive,send)
        assert time.monotonic()-started < 0.3
        assert messages[0]['status']==504 and entered.is_set() and not closed.is_set()
        assert b'synthetic_PRIVATE' not in messages[1]['body']
        release.set()
        await until(closed.is_set)
        after = events[events.index('remote settled')+1:]
        assert 'sql' not in after and 'commit' not in after
        assert events.index('remote settled') < events.index('port closed') < events.index('session closed')
        assert len(calls)==(1 if phase=='exchange' else 4)
    try:
        asyncio.run(run())
    finally:
        release.set()


def test_actual_sqlalchemy_commit_event_rejects_after_prior_work_expired():
    from sqlalchemy import Engine
    from sqlalchemy.engine import URL
    from sqlalchemy.engine.default import DefaultDialect
    from sqlalchemy.engine.interfaces import DBAPIConnection
    from sqlalchemy.pool import StaticPool
    calls=[]
    class DBAPI:
        autocommit: bool = False
        def __getattr__(self, name: str) -> Never:
            raise AttributeError(name)
        def cursor(self, *args, **kwargs) -> Never:
            raise AssertionError("commit regression must not issue SQL")
        def rollback(self):
            calls.append('rollback')
        def commit(self):
            calls.append('commit')
        def close(self):
            calls.append('close')
    engine = Engine(StaticPool(creator=lambda: cast(DBAPIConnection, DBAPI())),DefaultDialect(),URL.create('synthetic'))
    budget=deadline.CaptureBudget(1)
    try:
        with deadline.capture_budget(budget),engine.connect() as connection:
            connection.begin()
            budget.cancel()
            with pytest.raises(deadline.CaptureDeadlineExceeded):
                connection.commit()
    finally:
        engine.dispose()
    assert 'commit' not in calls


def test_actual_flush_hook_refuses_before_connection_acquisition():
    from sqlalchemy import Integer
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
    class Base(DeclarativeBase):
        pass
    class Draft(Base):
        __tablename__='invented_deadline_draft'
        id: Mapped[int] = mapped_column(Integer,primary_key=True)
    budget=deadline.CaptureBudget(1)
    with deadline.capture_budget(budget), Session() as session:
        deadline.own_capture_session(session)
        session.add(Draft(id=1))
        budget.cancel()
        with pytest.raises(deadline.CaptureDeadlineExceeded):
            session.flush()


def test_peer_disconnect_fences_worker_without_closing_its_dependencies(monkeypatch):
    entered, release, finished = Event(), Event(), Event()
    sent=[]
    async def app(scope,receive,send):
        await receive()
        with deadline.own_capture_session(Session()) as session:
            def work():
                entered.set()
                release.wait(2)
                with pytest.raises(deadline.CaptureDeadlineExceeded):
                    session.commit()
            try:
                await deadline.run_in_threadpool(work)
            finally:
                finished.set()
    async def run():
        disconnected=asyncio.Event()
        first=True
        async def receive():
            nonlocal first
            if first:
                first=False
                return {'type':'http.request','body':b'{}','more_body':False}
            await disconnected.wait()
            return {'type':'http.disconnect'}
        async def send(message):
            sent.append(message)
        task=asyncio.create_task(boundary.CaptureBoundary(app,2)({'type':'http','method':'POST'},receive,send))
        await until(entered.is_set)
        disconnected.set()
        await asyncio.wait_for(task,0.3)
        assert not finished.is_set() and sent==[]
        release.set()
        await until(finished.is_set)
    monkeypatch.setattr(boundary,'_workers',BoundedSemaphore(1))
    try:
        asyncio.run(run())
    finally:
        release.set()


def test_cancel_suppressing_async_operation_cannot_start_next_phase():
    async def run():
        budget=deadline.CaptureBudget(2)
        entered=asyncio.Event()
        events=[]
        async def operation():
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                return 'late private result'
        async def apply():
            with deadline.capture_budget(budget):
                await deadline.capture_async(operation)
                events.append('published')
        task=asyncio.create_task(apply())
        await entered.wait()
        task.cancel()
        with pytest.raises(deadline.CaptureDeadlineExceeded):
            await task
        assert events==[] and budget.cancelled.is_set()
    asyncio.run(run())
