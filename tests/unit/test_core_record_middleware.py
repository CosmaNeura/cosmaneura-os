"""Actual OS record route/middleware ownership, with invented resources and no I/O."""
import asyncio
import json
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import BoundedSemaphore, Event, get_ident
from types import SimpleNamespace
from uuid import uuid4

import pytest
from tests.unit.test_core_capture_admission import selection

from cosmas_os.api import capture_deadline as boundary
from cosmas_os.api import core_record_routes as record
from cosmas_os.api.auth import RequestIdentity

BUDGET = 0.04
GRACE = 0.04


@pytest.fixture
def actual_record(monkeypatch):
    from cosmas_os.api import app as product
    selected = selection()
    events = []
    state = SimpleNamespace(behavior='success', release=Event(), events=events)
    identity = RequestIdentity(str(uuid4()), str(uuid4()), 'clerk_jwt', external_identity_id=str(uuid4()))
    class Session:
        def __init__(self):
            self.owner = get_ident()
            events.append('session')
            if state.behavior == 'pool':
                events.append('pool waiting')
                state.release.wait(2)
                events.append('pool returned')
        def rollback(self):
            assert get_ident() == self.owner
            events.append('rollback')
        def close(self):
            assert get_ident() == self.owner
            events.append('close')
        def expire_all(self):
            assert get_ident() == self.owner
            events.append('expire')
    def authenticate(*args, **kwargs):
        events.append('auth')
        if state.behavior == 'blocked':
            state.release.wait(2)
            events.append('identity returned')
        if state.behavior == 'unexpected':
            raise RuntimeError('private_exception_sentinel')
        if state.behavior == 'denied':
            raise record.ws.WorkspaceError('core_record_access_denied', 403)
        return identity
    @contextmanager
    def no_database(session, budget):
        budget.check()
        yield
    @contextmanager
    def connection(configuration, budget):
        events.append('connection')
        try:
            yield object()
        finally:
            events.append('port closed')
    def admit(*args, **kwargs):
        events.append('binding')
        return SimpleNamespace(appointment_ref=selected.appointment_ref, workspace_id=selected.workspace_id, checked_at=datetime.now(UTC))
    monkeypatch.setattr(product, 'SessionLocal', Session)
    monkeypatch.setattr(product, 'authenticate_request', authenticate)
    monkeypatch.setattr(product, 'settings', SimpleNamespace(workspace_available=True,
        workspace_core_record_available=True, workspace_draft_recovery_required=True,
        auth_mode='dev_headers', core_web_origin='https://core.example.invalid'))
    monkeypatch.setattr(product, 'core_record_connection', connection)
    monkeypatch.setattr(record, 'session_deadline', no_database)
    monkeypatch.setattr(record.workspace_capture, 'admit', admit)
    monkeypatch.setattr(record.ws, '_workspace', lambda *a: SimpleNamespace(appointment_id=uuid4(), patient_link_id=uuid4()))
    monkeypatch.setattr(record.ws, '_encounter', lambda *a: SimpleNamespace(source='cosmaneura_core', external_id=selected.appointment_ref))
    monkeypatch.setattr(record, 'DEADLINE_SECONDS', BUDGET)
    monkeypatch.setattr(record, 'ERROR_SEND_SECONDS', GRACE)
    monkeypatch.setattr(boundary, '_workers', BoundedSemaphore(1))
    monkeypatch.setattr(boundary, '_error_workers', BoundedSemaphore(2))
    state.app = product.app
    state.path = f'/workspaces/{selected.workspace_id}/cosmaneura-record/location'
    state.identity = identity
    try:
        yield state
    finally:
        state.release.set()


def scope(f, *, method='GET', path=None):
    value = path or f.path
    return {'type':'http', 'asgi':{'version':'3.0'}, 'http_version':'1.1', 'method':method,
            'scheme':'http', 'path':value, 'raw_path':value.encode(), 'root_path':'', 'query_string':b'',
            'headers':[(b'authorization',b'Bearer invented'),(b'x-cosmas-record-contract',b'1'),
                       (b'x-cosmas-draft-recovery',b'2')],
            'client':('127.0.0.1',1), 'server':('owned',1)}


async def settled(predicate):
    end = time.monotonic()+2
    while not predicate():
        assert time.monotonic() < end
        await asyncio.sleep(0.003)


async def invoke(f, *, send=None, request_scope=None):
    read=False
    messages=[]
    async def receive():
        nonlocal read
        if not read:
            read=True
            return {'type':'http.request','body':b'','more_body':False}
        await asyncio.Event().wait()
        return {'type':'http.disconnect'}
    async def collect(message):
        messages.append(message)
    await f.app(request_scope or scope(f), receive, send or collect)
    return messages


@pytest.mark.parametrize('behavior,status',[('success',200),('denied',403),('unexpected',503),('blocked',504)])
@pytest.mark.parametrize('stalled',['http.response.start','http.response.body'])
def test_actual_record_final_output_is_bounded(actual_record, behavior, status, stalled):
    f=actual_record
    f.behavior=behavior
    async def run():
        release=asyncio.Event()
        messages=[]
        async def send(message):
            messages.append(message)
            if message['type']==stalled:
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
        task=asyncio.create_task(invoke(f,send=send))
        started=time.monotonic()
        try:
            done,_=await asyncio.wait({task},timeout=0.22)
            assert done, 'actual record middleware sender escaped deadline plus grace'
            task.result()
            assert time.monotonic()-started < 0.22
            assert messages[0]['status']==status
            assert not any(b'private_exception_sentinel' in m.get('body',b'') for m in messages)
            if stalled=='http.response.start':
                assert len(messages)==1
            headers=dict(messages[0]['headers'])
            assert headers[b'cache-control']==b'no-store'
            assert headers[b'x-content-type-options']==b'nosniff'
            assert headers[b'referrer-policy']==b'no-referrer'
        finally:
            f.release.set()
            release.set()
            await asyncio.gather(task,return_exceptions=True)
            await settled(lambda: f.events.count('session')==f.events.count('close'))
            await asyncio.sleep(0.01)
    asyncio.run(run())


def test_actual_resistant_read_retains_capacity_and_its_session(actual_record):
    f=actual_record
    f.behavior='blocked'
    async def run():
        first=await invoke(f)
        assert first[0]['status']==504
        assert f.events==['session','auth']
        second=await invoke(f)
        assert second[0]['status']==503
        assert f.events==['session','auth'], 'timeout released capacity over live reader'
        f.release.set()
        await settled(lambda:'close' in f.events)
        assert f.events==['session','auth','identity returned','rollback','close']
        await asyncio.sleep(0.01)
        f.behavior='success'
        third=await invoke(f)
        assert third[0]['status']==200
        body=json.loads(b''.join(m.get('body',b'') for m in third))
        assert body['href'].startswith('https://core.example.invalid/notes/appointment_')
    asyncio.run(run())


def test_record_sender_and_saturation_delivery_have_finite_capacity(actual_record):
    f=actual_record
    async def run():
        release=asyncio.Event()
        streams=[]
        async def one():
            messages=[]
            streams.append(messages)
            async def send(message):
                messages.append(message)
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
            task=asyncio.create_task(invoke(f,send=send))
            try:
                done,_=await asyncio.wait({task},timeout=0.22)
                assert done, 'resistant sender escaped deadline during capacity probe'
                task.result()
            finally:
                if not task.done():
                    release.set()
                    await task
        try:
            for _ in range(6):
                await one()
            assert [m[0]['status'] if m else None for m in streams]==[200,503,503,None,None,None]
            assert f.events.count('session')==1
        finally:
            release.set()
            await asyncio.sleep(0.03)
    asyncio.run(run())


def test_record_boundary_inventory_is_exact(actual_record):
    from cosmas_os.api import app as product
    installer=getattr(record,'install_record_boundary',None)
    assert installer is not None
    # Research and account setup have their own disjoint outer boundaries.
    # The location boundary still owns exactly its reviewed GET inventory.
    boundaries = [item for item in product.app.user_middleware if item.cls is record.RecordMiddleware]
    assert len(boundaries) == 1
    assert [(route.path, route.methods) for route in boundaries[0].kwargs["routes"]] == [
        ("/workspaces/{workspace_id}/cosmaneura-record/location", {"GET"})]
    assert product.app.state.record_deadline_routes==[{'path':'/workspaces/{workspace_id}/cosmaneura-record/location','methods':['GET'],'seconds':30}]
    with pytest.raises(ValueError,match='record_boundary_already_installed'):
        installer(product.app)


def test_caller_cancel_keeps_live_reader_owned(actual_record):
    f=actual_record
    f.behavior='blocked'
    async def run():
        task=asyncio.create_task(invoke(f))
        await settled(lambda:'auth' in f.events)
        task.cancel()
        done,_=await asyncio.wait({task},timeout=0.1)
        assert done and task.cancelled()
        assert 'close' not in f.events
        denied=await invoke(f)
        assert denied[0]['status']==503 and f.events.count('session')==1
        f.release.set()
        await settled(lambda:'close' in f.events)
        assert 'connection' not in f.events and 'binding' not in f.events
        await asyncio.sleep(0.01)
    asyncio.run(run())


def test_reader_cap_refuses_large_body_before_private_output(actual_record, monkeypatch):
    f=actual_record
    monkeypatch.setattr(record, 'record_location', lambda *a: SimpleNamespace(model_dump=lambda **kw: {'private_oversize_sentinel':'x'*5000}))
    async def run():
        messages=await invoke(f)
        assert messages[0]['status']==503
        assert not any(b'private_oversize_sentinel' in m.get('body',b'') for m in messages)
    asyncio.run(run())


def test_wrong_method_retains_405_without_reader_admission(actual_record, monkeypatch):
    f=actual_record
    monkeypatch.setattr(boundary, '_workers', BoundedSemaphore(0))
    async def run():
        messages=await invoke(f,request_scope=scope(f,method='POST'))
        assert messages[0]['status']==405 and f.events==[]
    asyncio.run(run())


def test_cancel_link_race_is_immediate_and_removes_callback():
    budget=boundary.CaptureBudget(1)
    events=[]
    def callback():
        return events.append('cancel')
    budget.cancel()
    with budget.on_cancel(callback):
        assert events==['cancel']
        assert callback in budget._callbacks
    assert callback not in budget._callbacks


def test_late_session_factory_retains_slot_and_never_authenticates(actual_record):
    f=actual_record
    f.behavior='pool'
    async def run():
        first=await invoke(f)
        assert first[0]['status']==504
        assert f.events==['session','pool waiting']
        second=await invoke(f)
        assert second[0]['status']==503 and f.events.count('session')==1
        f.release.set()
        await settled(lambda:'close' in f.events)
        assert f.events==['session','pool waiting','pool returned','rollback','close']
        await asyncio.sleep(0.01)
    asyncio.run(run())
