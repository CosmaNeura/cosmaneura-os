"""Fresh signed account context; no patient source or stored command grants authority."""

import asyncio
import json
import time
from typing import Literal
from uuid import UUID

from fastapi import Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from cosmas_os.api.auth import RequestIdentity
from cosmas_os.application import workspace as ws

PATH = "/provider-team/identity"
MAX_RESPONSE_BYTES = 1024
DEADLINE_SECONDS = 15


class IdentityContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal[1]
    box_id: UUID
    actor_id: UUID
    recovery_scope: str = Field(pattern=r"^[a-f0-9]{64}$")


def failure(code, status):
    return JSONResponse({"detail": code}, status_code=status, headers={"Cache-Control": "no-store"})


def register(app, get_session, identity_dependency, *, gate, reauthenticate, recovery_scope):
    @app.middleware("http")
    async def boundary(request, call_next):
        if request.method == "OPTIONS" or not (
            request.url.path == PATH or request.url.path.startswith(PATH + "/")
        ):
            return await call_next(request)
        if request.url.path != PATH:
            return failure("identity_unavailable", 404)
        if request.method != "GET":
            return failure("invalid_identity_request", 405)
        if request.headers.getlist("x-cosmas-team-contract") != ["2"]:
            return failure("team_contract_required", 426)
        if request.headers.getlist("x-cosmas-draft-recovery") != ["2"]:
            return failure("workspace_client_update_required", 426)
        if (
            request.scope.get("query_string")
            or request.headers.getlist("content-encoding")
            or request.headers.getlist("transfer-encoding")
            or request.headers.getlist("content-length") not in ([], ["0"])
            or len(request.headers.getlist("authorization")) > 1
        ):
            return failure("invalid_identity_request", 422)
        request.state.identity_deadline = time.monotonic() + DEADLINE_SECONDS
        try:
            async with asyncio.timeout(DEADLINE_SECONDS):
                async for chunk in request.stream():
                    if chunk:
                        return failure("invalid_identity_request", 422)
                result = await call_next(request)
            if result.status_code >= 400:
                codes = {
                    401: "identity_authentication_required",
                    403: "identity_access_denied",
                    404: "identity_unavailable",
                    426: "workspace_client_update_required",
                    504: "identity_timeout",
                }
                return failure(
                    codes.get(result.status_code, "identity_unavailable"), result.status_code
                )
            result.headers["Cache-Control"] = "no-store"
            return result
        except TimeoutError:
            return failure("identity_timeout", 504)
        except SQLAlchemyError:
            return failure("identity_unavailable", 503)

    @app.get(PATH)
    async def current_identity(
        request: Request,
        session=Depends(get_session),
        identity: RequestIdentity = Depends(identity_dependency),
    ):
        def fence():
            if time.monotonic() >= request.state.identity_deadline:
                raise ws.WorkspaceError("identity_timeout", 504)
            gate(Response(), request)
            if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
                raise ws.WorkspaceError("identity_access_denied", 403)
            session.expire_all()
            reauthenticate(request, session, identity)
            ws._human(session, identity.box_id, identity.principal_id)

        def inspect():
            fence()
            value = recovery_scope(
                {
                    "contract_version": 1,
                    "box_id": identity.box_id,
                    "actor_id": identity.principal_id,
                },
                identity,
            )
            closed = IdentityContext.model_validate(value).model_dump(mode="json")
            raw = json.dumps(closed, ensure_ascii=True, separators=(",", ":")).encode()
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("bounded identity response required")
            fence()
            return Response(
                raw, media_type="application/json", headers={"Cache-Control": "no-store"}
            )

        try:
            return await run_in_threadpool(inspect)
        except ValueError:
            return failure("identity_unavailable", 503)
