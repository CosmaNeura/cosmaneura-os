"""Private bounded package read independent of an encounter notebook."""

import json
from contextvars import Context
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from fastapi.routing import APIRoute
from pydantic import SecretStr
from starlette.requests import Request
from starlette.responses import Response as WireResponse

from cosmas_os.adapters.core_visit_prep import visit_prep_connection
from cosmas_os.api.capture_schemas import CaptureBotSelection
from cosmas_os.api.core_record_routes import HEADERS, RecordMiddleware
from cosmas_os.api.core_record_routes import problem as record_problem
from cosmas_os.application import visit_prep
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import run_in_threadpool
from cosmas_os.application.core_record_deadline import session_deadline
from cosmas_os.ports.core_encounters import Closed, Digest
from cosmas_os.ports.core_visit_prep import PrepRef

PATH = "/provider-team/visit-prep/read"


class Command(Closed):
    preparation_ref: PrepRef
    connection_sha256: Digest
    workspace_id: UUID
    request_nonce: UUID
    bot: CaptureBotSelection


def problem(status, *args):
    return record_problem(status, "visit_prep_unavailable")


class VisitPrepRoute(APIRoute):
    async def handle(self, scope, receive, send):
        try:
            if "core_record_deadline" not in scope.get("state", {}):
                await problem(503)(scope, receive, send)
                return
            await super().handle(scope, receive, send)
        except TimeoutError:
            await problem(504)(scope, receive, send)
        except ws.WorkspaceError as error:
            await problem(error.status)(scope, receive, send)
        except HTTPException as error:
            await problem(error.status_code)(scope, receive, send)
        except Exception:
            await problem(503)(scope, receive, send)


class VisitPrepMiddleware(RecordMiddleware):
    async def __call__(self, scope, receive, send):
        # No slash redirect or query-selected preparation credentials.
        if scope["type"] == "http" and scope["path"].rstrip("/") == PATH:
            if scope["path"] != PATH or scope["method"] not in {"POST", "OPTIONS"}:
                await problem(422)(scope, receive, send)
                return
        await super().__call__(scope, receive, send)


def install(app, **dependencies):
    routes = router(**dependencies)
    app.include_router(routes)
    installed = [r for r in routes.routes if isinstance(r, VisitPrepRoute)]
    if len(installed) != 1:
        raise ValueError("visit_prep_route_inventory")
    app.add_middleware(
        VisitPrepMiddleware,
        routes=tuple(installed),
        max_response_bytes=262144,
        error_factory=problem,
        deadline_seconds=15,
    )


def router(
    *,
    settings,
    session_factory,
    identity_dependency,
    workspace_gate,
    connection_factory=visit_prep_connection,
):
    routes = APIRouter(route_class=VisitPrepRoute)

    @routes.post(PATH)
    async def read(request: Request):
        budget = request.state.core_record_deadline
        headers = request.headers
        if headers.getlist("x-cosmas-visit-prep-contract") != ["1"]:
            raise ws.WorkspaceError("visit_prep_unavailable", 426)
        if (
            request.scope.get("query_string")
            or headers.getlist("content-encoding")
            or headers.getlist("content-type") != ["application/json"]
            or len(headers.getlist("authorization")) != 1
            or any(name in headers for name in ("x-box-id", "x-actor-principal-id"))
            or len(headers.getlist("content-length")) > 1
        ):
            raise ws.WorkspaceError("visit_prep_unavailable", 422)
        raw = bytearray()
        async for chunk in request.stream():
            budget.check()
            if len(raw) + len(chunk) > 2048:
                raise ws.WorkspaceError("visit_prep_unavailable", 413)
            raw.extend(chunk)
        try:
            from cosmas_os.adapters.core_visit_prep import _pairs

            length = headers.get("content-length")
            if length is not None and (
                not length.isascii()
                or not length.isdigit()
                or len(length) > 4
                or int(length) != len(raw)
            ):
                raise ValueError
            command = Command.model_validate(
                json.loads(
                    raw.decode("utf-8"),
                    object_pairs_hook=_pairs,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                )
            )
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ws.WorkspaceError("visit_prep_unavailable", 422) from None
        authorization = headers["authorization"]

        def execute():
            session = session_factory()
            config = settings()
            policy = (
                config.core_capture_origin,
                config.core_connection_tenant_ref,
                config.core_visit_prep_scope,
                config.core_visit_prep_managed_identity_client_id,
            )
            try:
                with session_deadline(session, budget):

                    def authenticate():
                        budget.check()
                        workspace_gate(response=Response(), request=request)
                        current = settings()
                        if not current.workspace_visit_prep_available or policy != (
                            current.core_capture_origin,
                            current.core_connection_tenant_ref,
                            current.core_visit_prep_scope,
                            current.core_visit_prep_managed_identity_client_id,
                        ):
                            raise ws.WorkspaceError("visit_prep_unavailable", 503)
                        value = identity_dependency(
                            request=request,
                            session=session,
                            authorization=authorization,
                            x_box_id=None,
                            x_actor_principal_id=None,
                        )
                        if value.auth_mode != "clerk_jwt" or value.external_identity_id is None:
                            raise ws.WorkspaceError("visit_prep_unavailable", 403)
                        return value

                    identity = authenticate()

                    def reauthenticate():
                        if authenticate() != identity:
                            raise ws.WorkspaceError("visit_prep_unavailable", 403)

                    with connection_factory(config, budget) as port:
                        return visit_prep.read(
                            session,
                            identity=identity,
                            command=command,
                            tenant_ref=policy[1],
                            bearer=SecretStr(authorization.partition(" ")[2]),
                            port=port,
                            reauthenticate=reauthenticate,
                            budget=budget,
                        )
            finally:
                try:
                    session.rollback()
                finally:
                    session.close()

        body = await run_in_threadpool(Context().run, execute)
        budget.check()
        return WireResponse(body, media_type="application/json", headers=HEADERS)

    return routes
