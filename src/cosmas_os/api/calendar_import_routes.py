"""Authenticated, bounded calendar-file intake; no provider or URL transport."""

import json
import re
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from cosmas_os.api import calendar_import_schemas as schema
from cosmas_os.api.capture_deadline import CaptureBoundary
from cosmas_os.api.capture_schemas import _unique_object
from cosmas_os.application import calendar_imports, model_work
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import run_in_threadpool

PATH = re.compile(r"^/workspaces/[0-9a-f-]{36}/calendar-imports(?:/review)?$", re.I)
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}
MAX_BODY = 1_402_200


class CalendarImportBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] != "OPTIONS" and PATH.fullmatch(scope["path"]):
            await CaptureBoundary(self.app, seconds=45, max_response_bytes=12_000_000,
                error_factory=lambda status: JSONResponse({"detail": "calendar_import_unavailable"},
                    status_code=status, headers=HEADERS))(scope, receive, send)
            return
        await self.app(scope, receive, send)


def router(*, configuration, identity_dependency, session_dependency, workspace_gate, fence):
    routes = APIRouter()

    def supported(identity):
        if (getattr(identity, "auth_mode", None) != "clerk_jwt"
                or getattr(identity, "external_identity_id", None) is None):
            raise ws.WorkspaceError("calendar_import_unavailable", 404)

    def available():
        if not configuration().workspace_calendar_import_available:
            raise ws.WorkspaceError("calendar_import_unavailable", 404)

    def checked(request):
        if (request.query_params or request.headers.getlist("x-cosmas-calendar-import") != ["1"]
                or request.headers.getlist("content-encoding")
                or len(request.headers.getlist("authorization")) != 1
                or len(request.headers.getlist("content-type")) != 1
                or request.headers["content-type"].split(";", 1)[0].strip().lower() != "application/json"):
            raise ws.WorkspaceError("invalid_calendar_import_request", 422)

    async def decoded(request, limit):
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > limit:
                raise ValueError
            raw.extend(chunk)
        return json.loads(raw, object_pairs_hook=_unique_object)

    async def preflight(request, identity, session, wid):
        supported(identity)
        checked(request)

        def authorize():
            fence(request, session, identity)
            # Current custody is checked before the first body chunk is consumed.
            calendar_imports.authorize_request(session, identity.box_id, identity.principal_id,
                identity.external_identity_id, wid)
            # No owner/workspace locks may cross client-controlled body streaming.
            # This transaction contains only the authenticated preflight reads.
            session.commit()

        await run_in_threadpool(authorize)

    @routes.post("/workspaces/{workspace_id}/calendar-imports", dependencies=[Depends(workspace_gate)])
    async def action(workspace_id: UUID, request: Request, identity=Depends(identity_dependency), session=Depends(session_dependency)):
        wid = str(workspace_id)
        await preflight(request, identity, session, wid)
        try:
            body = schema.COMMAND.validate_python(await decoded(request, MAX_BODY))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ws.WorkspaceError("invalid_calendar_import_request", 422) from None

        def reauthenticate():
            fence(request, session, identity)

        def execute():
            reauthenticate()
            scope = (session, identity.box_id, identity.principal_id, identity.external_identity_id, wid)
            if body.action == "status":
                return calendar_imports.status(*scope, enabled=configuration().workspace_calendar_import_available,
                                               reauthenticate=reauthenticate)
            available()
            if body.action == "list":
                result = calendar_imports.list_imports(*scope, reauthenticate=reauthenticate)
            elif body.action == "upload":
                result = calendar_imports.upload(*scope, key=body.idempotency_key, byte_sha256=body.byte_sha256,
                    file_base64=body.file_base64, window=body.window.model_dump(mode="json"),
                    reported_source=body.reported_source, reauthenticate=reauthenticate)
            elif body.action == "inspect":
                result = calendar_imports.inspect_import(*scope, import_id=str(body.import_id), reauthenticate=reauthenticate)
            elif body.action == "resolve":
                result = calendar_imports.resolve_import(*scope, key=body.idempotency_key, reauthenticate=reauthenticate)
            else:
                result = calendar_imports.revoke_import(*scope, expected=body.expected_revision,
                    key=body.idempotency_key, import_id=str(body.import_id), source_sha256=body.source_sha256,
                    reauthenticate=reauthenticate)
                result["workspace"] = model_work.project_workspace(session, result["workspace"])
            reauthenticate()
            available()
            return result

        return JSONResponse(await run_in_threadpool(execute), headers=HEADERS)

    @routes.post("/workspaces/{workspace_id}/calendar-imports/review", dependencies=[Depends(workspace_gate)])
    async def review(workspace_id: UUID, request: Request, identity=Depends(identity_dependency), session=Depends(session_dependency)):
        wid = str(workspace_id)
        await preflight(request, identity, session, wid)
        available()
        try:
            body = schema.Review.model_validate(await decoded(request, 4096))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ws.WorkspaceError("invalid_calendar_import_review", 422) from None

        def execute():
            fence(request, session, identity)
            result = calendar_imports.select_review(session, identity.box_id, identity.principal_id,
                identity.external_identity_id, wid, expected=body.expected_revision, key=body.idempotency_key,
                import_id=str(body.import_id), source_sha256=body.source_sha256, item_index=body.item_index,
                item_sha256=body.item_sha256, reviewed_visit=body.reviewed_visit,
                reviewed_exact_summary=body.reviewed_exact_summary, reviewed_untrusted_source=body.reviewed_untrusted_source,
                reauthenticate=lambda: fence(request, session, identity))
            result["workspace"] = model_work.project_workspace(session, result["workspace"])
            fence(request, session, identity)
            available()
            return result

        return JSONResponse(await run_in_threadpool(execute), headers=HEADERS)
    return routes
