"""Bounded provider onboarding; all identity and tenancy come from the server."""

import json
from contextvars import Context

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from cosmas_os.adapters.core_appointment_setup import CoreSetupChanged
from cosmas_os.adapters.core_encounters import CoreDiscoveryDenied, CoreEncounterConnection
from cosmas_os.api.core_record_routes import HEADERS, RecordMiddleware
from cosmas_os.application import core_connection
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import run_in_threadpool
from cosmas_os.application.core_record_deadline import RecordDeadline, session_deadline
from cosmas_os.ports.athena_schedule import AthenaCommand
from cosmas_os.ports.athena_visit_links import AthenaVisitLinkCommand
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_appointment_setup import AppointmentSetupCommand

PATH = "/connections/cosmaneura/read"
MAX_BYTES = 69_632


def problem(status, code="core_connection_unavailable"):
    return JSONResponse({"detail":code}, status_code=status, headers=HEADERS)


class ConnectionRoute(APIRoute):
    async def handle(self, scope, receive, send):
        if not isinstance(scope.get("state", {}).get("core_record_deadline"), RecordDeadline):
            await problem(503)(scope, receive, send)
            return
        try:
            await super().handle(scope, receive, send)
        except TimeoutError:
            await problem(504)(scope, receive, send)
        except ws.WorkspaceError as error:
            await problem(error.status, error.code)(scope, receive, send)
        except HTTPException as error:
            await problem(error.status_code)(scope, receive, send)
        except (SQLAlchemyError, ConnectorUnavailable, ValueError, TypeError):
            await problem(503)(scope, receive, send)


class ConnectionMiddleware(RecordMiddleware):
    """Reuse reader ownership with a separate route inventory and response cap."""


def install_boundary(app):
    if any(item.cls is ConnectionMiddleware for item in app.user_middleware):
        raise ValueError("connection_boundary_already_installed")
    candidates = []
    for route in app.routes:
        if isinstance(route, ConnectionRoute):
            candidates.append(route)
        else:
            contexts = getattr(route, "effective_route_contexts", None)
            if contexts is not None:
                candidates.extend(c for c in contexts() if isinstance(c.original_route, ConnectionRoute))
    if len(candidates) != 1 or candidates[0].path != PATH or candidates[0].methods != {"POST"}:
        raise ValueError("connection_route_inventory")
    app.add_middleware(ConnectionMiddleware, routes=tuple(candidates), max_response_bytes=MAX_BYTES,
                       error_factory=problem)


def router(*, settings, session_factory, identity_dependency, workspace_gate,
           connection_factory=CoreEncounterConnection):
    routes = APIRouter(route_class=ConnectionRoute)

    @routes.post(PATH)
    async def connection(request: Request):
        budget = request.state.core_record_deadline
        headers = request.headers
        if headers.getlist("x-cosmas-connection-contract") != ["1"]:
            raise ws.WorkspaceError("core_connection_contract_required", 426)
        if (request.query_params or headers.getlist("content-encoding")
            or any(len(headers.getlist(name)) != 1 for name in ("authorization", "content-type"))
            or headers["content-type"].split(";", 1)[0].strip().lower() != "application/json"
            or len(headers.getlist("content-length")) > 1
            or any(name in headers for name in ("x-box-id", "x-actor-principal-id"))):
            raise ws.WorkspaceError("invalid_core_connection_request", 422)
        length = headers.get("content-length")
        if length is not None and (not length.isascii() or not length.isdigit()
                                  or len(length) > 4 or int(length) > 2048):
            raise ws.WorkspaceError("invalid_core_connection_request", 422)
        raw = bytearray()
        async for chunk in request.stream():
            budget.check()
            if len(raw)+len(chunk) > 2048:
                raise ws.WorkspaceError("invalid_core_connection_request", 422)
            raw.extend(chunk)
        if length is not None and len(raw) != int(length):
            raise ws.WorkspaceError("invalid_core_connection_request", 422)
        def pairs(values):
            result = {}
            for key, value in values:
                if key in result:
                    raise ValueError("duplicate_field")
                result[key] = value
            return result
        try:
            command = core_connection.COMMAND_ADAPTER.validate_python(json.loads(
                raw.decode("utf-8"), object_pairs_hook=pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_number"))))
            if isinstance(command, core_connection.ConnectionCommand):
                command.validate_selection()
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ws.WorkspaceError("invalid_core_connection_request", 422) from None
        authorization = headers["authorization"]

        def execute():
            budget.check()
            session = session_factory()
            try:
                with session_deadline(session, budget, allow_writes=command.action in {"connect", "open"}):
                    config = settings()
                    scope = (config.core_capture_origin, config.core_connection_tenant_ref)

                    def authenticate():
                        budget.check()
                        workspace_gate(response=Response(), request=request)
                        current = settings()
                        if not current.workspace_core_connection_available:
                            raise ws.WorkspaceError("core_connection_unavailable", 404)
                        if isinstance(command, AppointmentSetupCommand) and not current.workspace_core_appointment_setup_available:
                            raise ws.WorkspaceError("core_connection_unavailable", 404)
                        if isinstance(command, AthenaVisitLinkCommand) and not current.workspace_athena_visit_link_available:
                            raise ws.WorkspaceError("core_connection_unavailable", 404)
                        if isinstance(command, AthenaCommand) and not current.workspace_athena_connection_available:
                            raise ws.WorkspaceError("core_connection_unavailable", 404)
                        if (current.core_capture_origin, current.core_connection_tenant_ref) != scope:
                            raise ws.WorkspaceError("core_connection_changed", 409)
                        value = identity_dependency(request=request, session=session, authorization=authorization,
                            x_box_id=None, x_actor_principal_id=None)
                        if value.auth_mode != "clerk_jwt" or value.external_identity_id is None:
                            raise ws.WorkspaceError("core_connection_access_denied", 403)
                        budget.check()
                        return value

                    identity = authenticate()
                    def reauthenticate():
                        if authenticate() != identity:
                            raise ws.WorkspaceError("core_connection_access_denied", 403)

                    port = connection_factory(scope[0], budget)
                    try:
                        return core_connection.execute(session, identity=identity, command=command,
                            tenant_ref=scope[1], bearer=SecretStr(authorization.partition(" ")[2]),
                            port=port, reauthenticate=reauthenticate, budget=budget)
                    except CoreSetupChanged:
                        raise ws.WorkspaceError("core_connection_changed", 409) from None
                    except CoreDiscoveryDenied:
                        raise ws.WorkspaceError("core_connection_access_denied", 403) from None
                    finally:
                        port.close()
            finally:
                try:
                    session.rollback()
                finally:
                    session.close()

        result = await run_in_threadpool(Context().run, execute)
        budget.check()
        return JSONResponse(result, headers=HEADERS)

    return routes
