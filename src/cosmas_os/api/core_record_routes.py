"""Bounded bridge to the existing Core screen with worker-owned resources."""

from contextvars import Context
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import SecretStr
from starlette.requests import Request
from starlette.routing import Match

from cosmas_os.adapters.core_record_connection import record_connection
from cosmas_os.api.capture_deadline import CaptureBoundary
from cosmas_os.application import workspace as ws
from cosmas_os.application import workspace_capture
from cosmas_os.application.capture_deadline import current_budget, run_in_threadpool
from cosmas_os.application.core_record_deadline import (
    RecordDeadline,
    RecordDeadlineExceeded,
    session_deadline,
)
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_record_location import record_location

DEADLINE_SECONDS = 30
ERROR_SEND_SECONDS = 0.25
MAX_RESPONSE_BYTES = 4096
HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def problem(status, code="core_record_unavailable"):
    return JSONResponse({"detail": code}, status_code=status, headers=HEADERS)


class RecordRoute(APIRoute):
    """Keep the closed local error contract inside the outer ownership boundary."""
    async def handle(self, scope, receive, send):
        if self.methods is not None and scope["method"] not in self.methods:
            await super().handle(scope, receive, send)
            return
        if not isinstance(scope.get("state", {}).get("core_record_deadline"), RecordDeadline):
            await problem(503)(scope, receive, send)
            return
        try:
            await super().handle(scope, receive, send)
        except (TimeoutError, RecordDeadlineExceeded):
            await problem(504)(scope, receive, send)
        except ws.WorkspaceError as error:
            await problem(error.status, error.code)(scope, receive, send)
        except HTTPException as error:
            await problem(error.status_code, error.detail)(scope, receive, send)


class RecordMiddleware:
    """Only the existing location GET; full middleware output and cleanup are owned."""
    def __init__(self, app, *, routes, max_response_bytes=MAX_RESPONSE_BYTES, error_factory=problem):
        self.app, self.routes = app, routes
        self.max_response_bytes, self.error_factory = max_response_bytes, error_factory

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not any(route.matches(scope)[0] == Match.FULL for route in self.routes):
            await self.app(scope, receive, send)
            return

        async def private(current_scope, current_receive, current_send):
            owner = current_budget()
            assert owner is not None
            budget = RecordDeadline(min(DEADLINE_SECONDS, owner.check()))
            budget.when = owner.expires_at
            current_scope.setdefault("state", {})["core_record_deadline"] = budget
            with owner.on_cancel(budget.cancel):
                try:
                    await self.app(current_scope, current_receive, current_send)
                finally:
                    budget.cancel()

        async def final_send(message):
            if message["type"] == "http.response.start":
                required = {k.lower().encode(): v.encode() for k, v in HEADERS.items()}
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in required]
                message = {**message, "headers": [*headers, *required.items()]}
            await send(message)

        await CaptureBoundary(private, DEADLINE_SECONDS, max_response_bytes=self.max_response_bytes,
                              error_factory=self.error_factory, error_send_seconds=ERROR_SEND_SECONDS)(
            scope, receive, final_send)


def install_record_boundary(app):
    """Install after all other middleware; reject unreviewed route inventory drift."""
    if any(item.cls is RecordMiddleware for item in app.user_middleware):
        raise ValueError("record_boundary_already_installed")
    # FastAPI 0.141 preserves included routers as branches. Use its effective
    # contexts so matching retains the installed prefix/method semantics.
    candidates = []
    for route in app.routes:
        if isinstance(route, RecordRoute):
            candidates.append(route)
        else:
            contexts = getattr(route, "effective_route_contexts", None)
            if contexts is not None:
                candidates.extend(context for context in contexts()
                                  if isinstance(context.original_route, RecordRoute))
    routes = tuple(candidates)
    if len(routes) != 1 or routes[0].path != "/workspaces/{workspace_id}/cosmaneura-record/location" or routes[0].methods != {"GET"}:
        raise ValueError("record_route_inventory")
    app.add_middleware(RecordMiddleware, routes=routes)
    app.state.record_deadline_routes = [{"path": routes[0].path, "methods": ["GET"], "seconds": DEADLINE_SECONDS}]


def router(
    *,
    settings,
    session_factory,
    identity_dependency,
    workspace_gate,
    connection_factory=record_connection,
):
    routes = APIRouter(route_class=RecordRoute)

    @routes.get("/workspaces/{workspace_id}/cosmaneura-record/location")
    async def location(request: Request, workspace_id: UUID):
        budget = request.state.core_record_deadline
        if request.headers.getlist("x-cosmas-record-contract") != ["1"]:
            raise ws.WorkspaceError("core_record_contract_required", 426)
        if (
            request.query_params
            or request.headers.getlist("content-encoding")
            or len(request.headers.getlist("authorization")) != 1
            or request.headers.getlist("content-length") not in ([], ["0"])
            or request.headers.getlist("transfer-encoding")
            or any(name in request.headers for name in ("x-box-id", "x-actor-principal-id"))
        ):
            raise ws.WorkspaceError("invalid_core_record_request", 422)
        async for chunk in request.stream():
            budget.check()
            if chunk:
                raise ws.WorkspaceError("invalid_core_record_request", 422)
        authorization = request.headers["authorization"]

        def read():
            budget.check()
            session = session_factory()
            try:
                with session_deadline(session, budget):

                    def available():
                        budget.check()
                        # Existing gate remains authoritative and runs in this worker.
                        workspace_gate(response=Response(), request=request)
                        budget.check()
                        if not settings().workspace_core_record_available:
                            raise ws.WorkspaceError("core_record_unavailable", 404)

                    def authenticate():
                        available()
                        value = identity_dependency(
                            session=session,
                            authorization=authorization,
                            x_box_id=None,
                            x_actor_principal_id=None,
                        )
                        budget.check()
                        return value

                    identity = authenticate()
                    if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
                        raise ws.WorkspaceError("core_record_access_denied", 403)
                    origin = settings().core_web_origin

                    def current():
                        if authenticate() != identity:
                            raise ws.WorkspaceError("core_record_access_denied", 403)
                        if settings().core_web_origin != origin:
                            raise ws.WorkspaceError("core_record_unavailable", 409)
                        budget.check()

                    budget.check()
                    with connection_factory(settings(), budget) as port:
                        budget.check()
                        if port is None:
                            raise ws.WorkspaceError("core_record_unavailable", 503)
                        binding = workspace_capture.admit(
                            session,
                            box=identity.box_id,
                            actor=identity.principal_id,
                            external_identity_id=identity.external_identity_id,
                            workspace_id=str(workspace_id),
                            bearer=SecretStr(authorization.partition(" ")[2]),
                            reauthenticate=current,
                            port=port,
                            attestation=None,
                            idempotency_key="record-location",
                            binding_only=True,
                        )
                        budget.check()
                        session.expire_all()
                        current()
                        workspace = ws._workspace(
                            session, identity.box_id, identity.principal_id, str(workspace_id)
                        )
                        appointment = ws._encounter(
                            session,
                            identity.box_id,
                            workspace.appointment_id,
                            workspace.patient_link_id,
                            owner=identity.principal_id,
                        )
                        budget.check()
                        if (
                            appointment.source != "cosmaneura_core"
                            or appointment.external_id != binding.appointment_ref
                        ):
                            raise ws.WorkspaceError("capture_context_changed", 409)
                        result = record_location(origin, workspace_id, binding)
                        budget.check()
                        return result
            except (ConnectorUnavailable, ValueError):
                budget.check()
                raise ws.WorkspaceError("core_record_unavailable", 503) from None
            finally:
                try:
                    session.rollback()
                finally:
                    session.close()

        # The outer boundary owns disconnect/cancellation and remains admitted
        # until this helper really settles. The fresh Context keeps the original
        # reader-specific SQL/Session ownership independent from capture work.
        result = await run_in_threadpool(Context().run, read)
        budget.check()
        return JSONResponse(result.model_dump(mode="json"), headers=HEADERS)

    return routes
