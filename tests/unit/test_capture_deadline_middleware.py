"""Final ASGI output across the real middleware chain, with no network or DB."""
import asyncio
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from tests.unit.test_core_capture_admission import NOW, ref

from cosmas_os.api import capture_deadline as boundary
from cosmas_os.ports.core_capture import CoreCaptureAdmissionSnapshot


def scope(path):
    return {'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
            'path':path,'raw_path':path.encode(),'root_path':'','query_string':b'',
            'headers':[(b'content-type',b'application/json'),(b'authorization',b'Bearer invented')],
            'client':('127.0.0.1',1),'server':('owned',1)}


async def final_send_probe(app, path, error):
    began=time.monotonic()
    entered=asyncio.Event()
    release=asyncio.Event()
    messages=[]
    read=False
    async def receive():
        nonlocal read
        if not read:
            read=True
            return {'type':'http.request','body':json.dumps({'idempotency_key':'invented'}).encode(),'more_body':False}
        await release.wait()
        return {'type':'http.disconnect'}
    async def send(message):
        messages.append(message)
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
    task=asyncio.create_task(app(scope(path),receive,send))
    try:
        await asyncio.wait_for(entered.wait(),1)
        done,_=await asyncio.wait({task},timeout=0.32)
        assert done, 'final middleware/network sender escaped request budget plus static grace'
        assert time.monotonic()-began < 0.34
        assert len(messages)==1
        assert messages[0]['status']==(503 if error else 200)
    finally:
        release.set()
        await asyncio.gather(task,return_exceptions=True)
        await asyncio.sleep(0.01)


@pytest.mark.parametrize('error',[False,True])
def test_actual_fastapi_middleware_final_send_stays_bounded(monkeypatch,error):
    app=FastAPI()
    @app.middleware('http')
    async def existing_middleware(request,call_next):
        return await call_next(request)
    def connection():
        return object()
    @app.post('/selected')
    async def selected(port=Depends(connection)):
        if error:
            raise RuntimeError('private_unhandled_sentinel')
        return {'value':'private_success_sentinel'}
    boundary.install_capture_boundaries(app,connection)
    monkeypatch.setattr(boundary,'CAPTURE_REQUEST_SECONDS',0.02)
    for route in app.routes:
        if isinstance(route,APIRoute) and isinstance(route.app,boundary.CaptureBoundary):
            monkeypatch.setattr(route.app,'seconds',0.02)
    asyncio.run(final_send_probe(app,'/selected',error))


@pytest.mark.parametrize('error',[False,True])
def test_actual_os_middleware_final_send_stays_bounded(monkeypatch,error):
    from cosmas_os.api import app as product
    identity=SimpleNamespace(box_id=str(uuid4()),principal_id=str(uuid4()),auth_mode='clerk_jwt',external_identity_id=str(uuid4()))
    def session():
        yield object()
    async def execute(request,workspace_id,*args,**kwargs):
        if error:
            raise RuntimeError('private_unhandled_sentinel')
        return CoreCaptureAdmissionSnapshot(contract_version='1',operation_ref=ref('scribe_admission'),
            binding_ref=ref('scribe_capture_binding'),workspace_id=workspace_id,
            appointment_ref=ref('appointment'),consent_record_id=uuid4(),session_id=uuid4(),
            status='admitted',request_nonce=uuid4(),checked_at=NOW)
    for key,value in {product.get_session:session,product._identity:lambda:identity,
                      product._capture_connection:lambda:object(),product._workspace_gate:lambda:None,
                      product._capture_gate:lambda:None}.items():
        monkeypatch.setitem(product.app.dependency_overrides,key,value)
    monkeypatch.setattr(product,'_execute_workspace_capture',execute)
    # Leave setup/cleanup time while probing a short independent error-send grace.
    monkeypatch.setattr(boundary,'CAPTURE_REQUEST_SECONDS',0.2)
    monkeypatch.setattr(boundary,'ERROR_SEND_SECONDS',0.04)
    for route in product.app.routes:
        if isinstance(route,APIRoute) and isinstance(route.app,boundary.CaptureBoundary):
            monkeypatch.setattr(route.app,'seconds',0.02)
    asyncio.run(final_send_probe(product.app,f'/workspaces/{uuid4()}/capture/admission',error))


def test_thread_start_failure_uses_bounded_static_output(monkeypatch):
    app = FastAPI()
    def connection():
        return object()
    @app.post('/selected')
    async def selected(port=Depends(connection)):
        pytest.fail('worker did not start')
    def start():
        raise RuntimeError('private_thread_failure')
    monkeypatch.setattr(boundary, 'Thread', lambda **kwargs: SimpleNamespace(start=start))
    monkeypatch.setattr(boundary, 'CAPTURE_REQUEST_SECONDS', 0.02)
    boundary.install_capture_boundaries(app, connection)
    asyncio.run(final_send_probe(app, '/selected', True))
