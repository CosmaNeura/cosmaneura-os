"""Explicit calendar-summary reads and review, separate from scheduling."""

import json
import re
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from cosmas_os.api import google_calendar_schemas as schema
from cosmas_os.api.capture_deadline import CaptureBoundary
from cosmas_os.api.capture_schemas import _unique_object, read_capture_request
from cosmas_os.application import google_calendar, model_work
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import run_in_threadpool

PATH = "/connections/google/calendar-summaries"
REVIEW_PATH = re.compile(r"^/workspaces/[0-9a-f-]{36}/google-calendar/review$")
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}


class GoogleCalendarBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] == "http" and scope["method"] != "OPTIONS"
                and (scope["path"] == PATH or REVIEW_PATH.fullmatch(scope["path"]))):
            await CaptureBoundary(self.app, seconds=45, max_response_bytes=12_000_000
                if REVIEW_PATH.fullmatch(scope["path"]) else 131072,
                error_factory=lambda status: JSONResponse({"detail": "google_calendar_unavailable"},
                    status_code=status, headers=HEADERS))(scope, receive, send)
            return
        await self.app(scope, receive, send)


def router(*, runtime, configuration, identity_dependency, session_dependency, workspace_gate, fence):
    routes = APIRouter()

    def service():
        if not configuration().workspace_google_calendar_available or runtime() is None:
            raise ws.WorkspaceError("google_calendar_unavailable", 404)
        return runtime()

    def checked(request):
        if (request.query_params or request.headers.getlist("x-cosmas-google-calendar") != ["1"]
                or request.headers.getlist("content-encoding")):
            raise ws.WorkspaceError("invalid_google_calendar_request", 422)

    @routes.post(PATH, dependencies=[Depends(workspace_gate)])
    async def action(request: Request, identity=Depends(identity_dependency), session=Depends(session_dependency)):
        checked(request)
        try:
            if (len(request.headers.getlist("authorization")) != 1
                    or len(request.headers.getlist("content-type")) != 1
                    or request.headers["content-type"].split(";", 1)[0].strip().lower() != "application/json"):
                raise ValueError
            raw = bytearray()
            async for chunk in request.stream():
                if len(raw) + len(chunk) > 4096:
                    raise ValueError
                raw.extend(chunk)
            body = schema.CALENDAR_COMMAND.validate_python(json.loads(raw, object_pairs_hook=_unique_object))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ws.WorkspaceError("invalid_google_calendar_request", 422) from None
        port = service()

        def reauthenticate():
            fence(request, session, identity)

        scope = (session, identity.box_id, identity.principal_id, identity.external_identity_id)

        def execute():
            reauthenticate()
            if body.action == "status":
                result = port.calendar_status(identity, session=session)
                if body.include_private_notebook is True:
                    result = {**result, "private_notebook_review": True}
            elif body.action == "observe":
                result = google_calendar.observe(*scope, key=body.idempotency_key, port=port,
                    reauthenticate=reauthenticate)
            elif body.action == "inspect":
                result = google_calendar.inspect_observation(*scope, observation_id=str(body.observation_id),
                    port=port, reauthenticate=reauthenticate)
            else:
                result = google_calendar.resolve_observation(*scope, key=body.idempotency_key, port=port,
                    reauthenticate=reauthenticate)
            reauthenticate()
            if service() is not port:
                raise ws.WorkspaceError("google_calendar_unavailable", 404)
            return result

        return JSONResponse(await run_in_threadpool(execute), headers=HEADERS)

    @routes.post("/workspaces/{workspace_id}/google-calendar/review", dependencies=[Depends(workspace_gate)])
    async def review(workspace_id: UUID, request: Request, identity=Depends(identity_dependency),
                     session=Depends(session_dependency)):
        checked(request)
        body = await read_capture_request(request, schema.ReviewCalendar, maximum_bytes=4096)
        port = service()

        def execute():
            fence(request, session, identity)
            result = google_calendar.select_review(session, identity.box_id, identity.principal_id, str(workspace_id),
                expected=body.expected_revision, key=body.idempotency_key, observation_id=str(body.observation_id),
                observation_sha256=body.observation_sha256, event_id=body.event_id, event_sha256=body.event_sha256,
                reviewed_visit=body.reviewed_visit, reviewed_private_notebook=body.reviewed_private_notebook,
                reviewed_exact_summary=body.reviewed_exact_summary,
                reviewed_untrusted_source=body.reviewed_untrusted_source, port=port,
                external_identity_id=identity.external_identity_id,
                reauthenticate=lambda: fence(request, session, identity))
            result["workspace"] = model_work.project_workspace(session, result["workspace"])
            fence(request, session, identity)
            return result

        return JSONResponse(await run_in_threadpool(execute), headers=HEADERS)

    return routes
