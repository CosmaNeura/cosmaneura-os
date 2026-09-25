"""Bounded signed read-only AI activity; no admission or inference route."""

import asyncio
import json
import re
import time

from fastapi import Depends
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from cosmas_os.api.auth import RequestIdentity
from cosmas_os.api.model_activity_schemas import MAX_RESPONSE_BYTES
from cosmas_os.application import model_activity
from cosmas_os.application import workspace as ws

PREFIX = "/provider-team/activity"
PATH = re.compile(r"^/provider-team/activity/(attention|recent)(?:/(a1[0-9a-f]{128}))?$")
DEADLINE_SECONDS = 15
ERRORS = {
    401: "activity_authentication_required",
    403: "activity_access_denied",
    404: "activity_unavailable",
    405: "invalid_activity_request",
    422: "invalid_activity_request",
    426: "workspace_client_update_required",
    503: "activity_unavailable",
    504: "activity_timeout",
}


def failure(code, status):
    return JSONResponse({"detail": code}, status_code=status, headers={"Cache-Control": "no-store"})


def register(app, get_session, identity_dependency, *, gate, reauthenticate, enabled=lambda: False):
    @app.middleware("http")
    async def boundary(request, call_next):
        if request.method == "OPTIONS" or not (
            request.url.path == PREFIX or request.url.path.startswith(PREFIX + "/")
        ):
            return await call_next(request)
        if not PATH.fullmatch(request.url.path):
            return failure("invalid_activity_request", 422)
        if request.method != "GET":
            return failure("invalid_activity_request", 405)
        if request.headers.getlist("x-cosmas-team-contract") != ["2"]:
            return failure("team_contract_required", 426)
        if request.headers.getlist("x-cosmas-draft-recovery") != ["2"]:
            return failure("workspace_client_update_required", 426)
        if request.headers.getlist("x-cosmas-activity-contract") not in ([], ["1"], ["2"]):
            return failure("workspace_client_update_required", 426)
        if (
            request.scope.get("query_string")
            or request.headers.getlist("content-encoding")
            or request.headers.getlist("transfer-encoding")
            or request.headers.getlist("content-length") not in ([], ["0"])
            or len(request.headers.getlist("authorization")) > 1
        ):
            return failure("invalid_activity_request", 422)
        request.state.activity_deadline = time.monotonic() + DEADLINE_SECONDS
        try:
            async with asyncio.timeout(DEADLINE_SECONDS):
                async for chunk in request.stream():
                    if chunk:
                        return failure("invalid_activity_request", 422)
                response = await call_next(request)
            if response.status_code >= 400:
                return failure(
                    ERRORS.get(response.status_code, "activity_unavailable"), response.status_code
                )
            response.headers["Cache-Control"] = "no-store"
            return response
        except TimeoutError:
            return failure("activity_timeout", 504)
        except (SQLAlchemyError, ValueError):
            return failure("activity_unavailable", 503)

    async def current_activity(
        request: Request,
        view: str,
        cursor: str | None = None,
        session=Depends(get_session),
        identity: RequestIdentity = Depends(identity_dependency),
    ):
        def fence():
            if time.monotonic() >= request.state.activity_deadline:
                raise ws.WorkspaceError("activity_timeout", 504)
            gate(Response(), request)
            if not enabled():
                raise ws.WorkspaceError("activity_unavailable", 404)
            if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
                raise ws.WorkspaceError("activity_access_denied", 403)
            session.expire_all()
            reauthenticate(request, session, identity)

        def inspect():
            fence()
            external_identity_id = identity.external_identity_id
            if external_identity_id is None:
                raise ws.WorkspaceError("activity_access_denied", 403)
            value = model_activity.read(
                session,
                identity.box_id,
                identity.principal_id,
                view=view,
                cursor=cursor,
                external_identity_id=external_identity_id,
                reauthenticate=fence,
                time_contract=2 if request.headers.get("x-cosmas-activity-contract") == "2" else 1,
            )
            raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("bounded activity response required")
            fence()
            return Response(
                raw, media_type="application/json", headers={"Cache-Control": "no-store"}
            )

        try:
            return await run_in_threadpool(inspect)
        except ws.WorkspaceError as error:
            return failure(ERRORS.get(error.status, "activity_unavailable"), error.status)
        except (ValueError, TypeError, KeyError):
            return failure("activity_unavailable", 503)

    app.add_api_route(PREFIX + "/{view}", current_activity, methods=["GET"])
    app.add_api_route(PREFIX + "/{view}/{cursor}", current_activity, methods=["GET"])
