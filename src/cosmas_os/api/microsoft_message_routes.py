"""Bounded explicit Microsoft message work, outside the clinical note lifecycle."""

import json
import re
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from cosmas_os.api import microsoft_message_schemas as schema
from cosmas_os.api.capture_deadline import CaptureBoundary
from cosmas_os.api.capture_schemas import read_capture_request
from cosmas_os.application import microsoft_message, model_work
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import run_in_threadpool

PATH = "/connections/microsoft/messages"
REVIEW_PATH = re.compile(r"^/workspaces/[0-9a-f-]{36}/microsoft-messages/review$")
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
           "X-Content-Type-Options": "nosniff"}


class MicrosoftMessageBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] == "http" and scope["method"] != "OPTIONS"
                and (scope["path"] == PATH or REVIEW_PATH.fullmatch(scope["path"]))):
            await CaptureBoundary(self.app, seconds=45, max_response_bytes=12_000_000
                                  if REVIEW_PATH.fullmatch(scope["path"]) else 131072,
                                  error_factory=lambda status: JSONResponse(
                                      {"detail": "microsoft_message_unavailable"}, status_code=status,
                                      headers=HEADERS))(scope, receive, send)
            return
        await self.app(scope, receive, send)


def router(*, runtime, configuration, identity_dependency, session_dependency, workspace_gate, fence):
    routes = APIRouter()

    def service():
        if not configuration().workspace_microsoft_message_available or runtime() is None:
            raise ws.WorkspaceError("microsoft_message_unavailable", 404)
        return runtime()

    def checked(request):
        if (request.query_params or request.headers.getlist("x-cosmas-microsoft-messages") != ["1"]
                or request.headers.getlist("content-encoding")):
            raise ws.WorkspaceError("invalid_microsoft_message_request", 422)

    @routes.post(PATH, dependencies=[Depends(workspace_gate)])
    async def action(request: Request, identity=Depends(identity_dependency), session=Depends(session_dependency)):
        checked(request)
        # The closed action accepts no provider content, account IDs or URLs.
        try:
            if (len(request.headers.getlist("authorization")) != 1
                    or len(request.headers.getlist("content-type")) != 1
                    or request.headers["content-type"].split(";", 1)[0].strip().lower() != "application/json"):
                raise ValueError
            raw = bytearray()
            async for chunk in request.stream():
                if len(raw) + len(chunk) > 8192:
                    raise ValueError
                raw.extend(chunk)
            from cosmas_os.api.capture_schemas import _unique_object

            body = schema.MESSAGE_COMMAND.validate_python(json.loads(raw, object_pairs_hook=_unique_object))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ws.WorkspaceError("invalid_microsoft_message_request", 422) from None
        port = service()
        def reauthenticate():
            fence(request, session, identity)
        scope = (session, identity.box_id, identity.principal_id, identity.external_identity_id)

        def execute():
            reauthenticate()
            if body.action == "status":
                return port.message_status(identity, session=session)
            if body.action == "list":
                return microsoft_message.list_observed(*scope, key=body.idempotency_key, port=port,
                                                    reauthenticate=reauthenticate)
            if body.action == "read":
                return microsoft_message.read_selected(*scope, key=body.idempotency_key,
                    observation_id=str(body.observation_id), observation_sha256=body.observation_sha256,
                    message_id=body.message_id, thread_id=body.thread_id, port=port,
                    reauthenticate=reauthenticate)
            if body.action == "inspect":
                return microsoft_message.inspect_read(*scope, read_id=str(body.read_id), port=port,
                                                   reauthenticate=reauthenticate)
            return microsoft_message.resolve_read(*scope, key=body.idempotency_key, kind=body.kind,
                                               port=port, reauthenticate=reauthenticate)

        return JSONResponse(await run_in_threadpool(execute), headers=HEADERS)

    @routes.post("/workspaces/{workspace_id}/microsoft-messages/review", dependencies=[Depends(workspace_gate)])
    async def review(workspace_id: UUID, request: Request, identity=Depends(identity_dependency),
                     session=Depends(session_dependency)):
        checked(request)
        body = await read_capture_request(request, schema.ReviewMessage, maximum_bytes=8192)
        port = service()

        def execute():
            fence(request, session, identity)
            workspace = ws._workspace(session, identity.box_id, identity.principal_id, str(workspace_id))
            result = microsoft_message.select_review(session, identity.box_id, identity.principal_id, str(workspace_id),
                expected=body.expected_revision, key=body.idempotency_key, read_id=str(body.read_id),
                source_sha256=body.source_sha256, patient_link_id=workspace.patient_link_id,
                reviewed_patient=body.reviewed_patient, reviewed_exact_message=body.reviewed_exact_message,
                reviewed_untrusted_source=body.reviewed_untrusted_source, port=port,
                external_identity_id=identity.external_identity_id,
                reauthenticate=lambda: fence(request, session, identity))
            result["workspace"] = model_work.project_workspace(session, result["workspace"])
            fence(request, session, identity)
            return result

        return JSONResponse(await run_in_threadpool(execute), headers=HEADERS)

    return routes
