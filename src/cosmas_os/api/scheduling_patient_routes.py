"""Private human patient correspondence; lookup/verify never books a visit."""

import json
import re
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from cosmas_os.api.capture_deadline import CaptureBoundary
from cosmas_os.api.capture_schemas import _unique_object
from cosmas_os.api.scheduling_patient_schemas import PATIENT_SETUP_COMMAND
from cosmas_os.application import scheduling_patient_setup as service
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import run_in_threadpool

PATH = re.compile(r"^/workspaces/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/scheduling-patient/setup$")
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}


class SchedulingPatientBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] != "OPTIONS" and PATH.fullmatch(scope["path"]):
            await CaptureBoundary(self.app, seconds=40, max_response_bytes=16384,
                error_factory=lambda status: JSONResponse({"detail": "scheduling_patient_response_unconfirmed"},
                    status_code=status, headers=HEADERS))(scope, receive, send)
            return
        await self.app(scope, receive, send)


def router(*, configuration, connection, identity_dependency, session_dependency, workspace_gate, fence):
    routes = APIRouter()

    def gate():
        if not configuration().workspace_scheduling_patient_setup_available:
            raise ws.WorkspaceError("scheduling_patient_setup_unavailable", 404)

    @routes.post("/workspaces/{workspace_id}/scheduling-patient/setup",
        dependencies=[Depends(workspace_gate), Depends(gate)])
    async def action(workspace_id: UUID, request: Request, identity=Depends(identity_dependency),
                     session=Depends(session_dependency)):
        if (identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None):
            raise ws.WorkspaceError("scheduling_access_unavailable", 403)
        try:
            if (request.query_params or request.headers.getlist("x-cosmas-scheduling-patient") != ["1"]
                or request.headers.getlist("content-encoding")
                or len(request.headers.getlist("authorization")) != 1
                or len(request.headers.getlist("content-type")) != 1
                or request.headers["content-type"].split(";", 1)[0].strip().lower() != "application/json"):
                raise ValueError
            raw = bytearray()
            async for chunk in request.stream():
                if len(raw) + len(chunk) > 4096:
                    raise ValueError
                raw.extend(chunk)
            body = PATIENT_SETUP_COMMAND.validate_python(json.loads(raw, object_pairs_hook=_unique_object,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError())))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ws.WorkspaceError("invalid_scheduling_patient_request", 422) from None

        def reauthenticate():
            gate()
            fence(request, session, identity)

        def execute():
            reauthenticate()
            scope = (session, identity.box_id, identity.principal_id, str(workspace_id), identity.external_identity_id)
            common = {"configuration": configuration(), "reauthenticate": reauthenticate}
            if body.action == "status":
                return service.status(*scope, **common)
            if body.action == "inspect":
                return service.inspect(*scope, request_id=str(body.request_id), **common)
            if body.action == "resolve":
                return service.resolve(*scope, kind=body.kind, key=str(body.idempotency_key), **common)
            # Create the provider client only for explicit new lookup/verify.
            port = connection(request)
            if body.action == "preview":
                return service.preview(*scope, expected_revision=body.expected_revision,
                    key=str(body.idempotency_key), search=body.search, port=port, **common)
            return service.confirm(*scope, expected_revision=body.expected_revision,
                key=str(body.idempotency_key), preview_id=str(body.preview_id), preview_sha256=body.preview_sha256,
                choice_ref=str(body.choice_ref), identity_sha256=body.identity_sha256,
                reviewed_same_patient=body.reviewed_same_patient, reviewed_exact_identity=body.reviewed_exact_identity,
                port=port, **common)

        return JSONResponse(await run_in_threadpool(execute), headers=HEADERS)

    return routes
