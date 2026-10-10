"""Bounded signed metadata attachment after device-local recording has started."""
import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from cosmas_os.api.capture_schemas import _unique_object
from cosmas_os.application import private_recording as service
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import CaptureBudget, capture_budget, run_in_threadpool
from cosmas_os.ports.private_recording import (
    AttachRecording,
    BindRecordingVisit,
    FinishRecording,
    LinkRecording,
)


def router(*, workspace_gate, get_session, identity, fence):
    def contract(request: Request):
        if request.headers.getlist("x-cosmas-private-recording") != ["1"]:
            raise ws.WorkspaceError("private_recording_contract_required", 426)
        if (request.query_params or request.headers.getlist("content-encoding")
                or request.headers.getlist("transfer-encoding")
                or len(request.headers.getlist("authorization")) != 1):
            raise ws.WorkspaceError("invalid_private_recording_request", 422)

    routes = APIRouter(dependencies=[Depends(workspace_gate), Depends(contract)])

    async def body(request, model):
        try:
            if (len(request.headers.getlist("content-type")) != 1
                    or request.headers["content-type"].split(";", 1)[0].lower() != "application/json"):
                raise ValueError
            raw = bytearray()
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    if len(raw) + len(chunk) > 4096:
                        raise ValueError
                    raw.extend(chunk)
            return model.model_validate(json.loads(raw, object_pairs_hook=_unique_object,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError())))
        except (ValueError, TypeError, UnicodeError, RecursionError, ValidationError):
            raise ws.WorkspaceError("invalid_private_recording_request", 422) from None
        except TimeoutError:
            raise ws.WorkspaceError("private_recording_timeout", 504) from None

    async def invoke(request, session, member, function, *args, mutating=False):
        if member.auth_mode != "clerk_jwt" or member.external_identity_id is None:
            raise ws.WorkspaceError("private_recording_access_denied", 403)
        def current():
            fence(request, session, member)
        def operation():
            current()
            result = function(session, member.box_id, member.principal_id, *args,
                external=member.external_identity_id, **({"fence": current} if mutating else {}))
            current()
            return result
        try:
            with capture_budget(CaptureBudget(10)):
                result = await run_in_threadpool(operation)
            raw = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
            if len(raw) > 16384:
                raise ws.WorkspaceError("private_recording_unavailable", 503)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except TimeoutError:
            raise ws.WorkspaceError("private_recording_timeout", 504) from None

    @routes.post("/workspaces/{wid}/private-recordings")
    async def attach(wid: UUID, request: Request, session=Depends(get_session), member=Depends(identity)):
        command = await body(request, AttachRecording)
        return await invoke(request, session, member, service.attach, str(wid), command, mutating=True)

    @routes.post("/workspaces/{wid}/private-recordings/resolve")
    async def resolve(wid: UUID, request: Request, session=Depends(get_session), member=Depends(identity)):
        command = await body(request, AttachRecording)
        return await invoke(request, session, member, service.resolve, str(wid), command)

    @routes.get("/workspaces/{wid}/private-recordings/{rid}")
    async def read(wid: UUID, rid: UUID, request: Request, session=Depends(get_session), member=Depends(identity)):
        if request.headers.getlist("content-length") not in ([], ["0"]):
            raise ws.WorkspaceError("invalid_private_recording_request", 422)
        return await invoke(request, session, member, service.read, str(wid), str(rid))

    @routes.post("/workspaces/{wid}/private-recordings/{rid}/finish")
    async def finish(wid: UUID, rid: UUID, request: Request, session=Depends(get_session), member=Depends(identity)):
        command = await body(request, FinishRecording)
        return await invoke(request, session, member, service.finish, str(wid), str(rid), command, mutating=True)

    @routes.post("/workspaces/{wid}/private-recordings/{rid}/link")
    async def link(wid: UUID, rid: UUID, request: Request, session=Depends(get_session), member=Depends(identity)):
        command = await body(request, LinkRecording)
        return await invoke(request, session, member, service.link, str(wid), str(rid), command, mutating=True)
    @routes.get("/workspaces/{wid}/private-recordings/{rid}/visit-binding")
    async def read_visit_binding(wid: UUID, rid: UUID, request: Request, session=Depends(get_session), member=Depends(identity)):
        if request.headers.getlist("content-length") not in ([], ["0"]):
            raise ws.WorkspaceError("invalid_private_recording_request", 422)
        return await invoke(request, session, member, service.read_visit_binding, str(wid), str(rid))

    @routes.post("/workspaces/{wid}/private-recordings/{rid}/visit-binding")
    async def bind_visit(wid: UUID, rid: UUID, request: Request, session=Depends(get_session), member=Depends(identity)):
        command = await body(request, BindRecordingVisit)
        return await invoke(request, session, member, service.bind_visit, str(wid), str(rid), command, mutating=True)
    return routes
