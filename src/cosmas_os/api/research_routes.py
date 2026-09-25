"""Signed private research routes using the existing bounded worker owner."""

import json
from contextvars import Context
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request
from starlette.routing import Match

from cosmas_os.api.capture_deadline import CaptureBoundary
from cosmas_os.api.research_schemas import (
    DEADLINE_SECONDS,
    MAX_HISTORY_BYTES,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    Resolve,
    Save,
    Search,
)
from cosmas_os.application import research
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import (
    CaptureBudget,
    capture_budget,
    current_budget,
    new_capture_session,
    run_in_threadpool,
)
from cosmas_os.models import ExternalIdentity, Principal
from cosmas_os.ports.research import catalog

HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}
INVENTORY = {
    ("GET", "/research/catalog"),
    ("GET", "/workspaces/{workspace_id}/research"),
    ("GET", "/workspaces/{workspace_id}/research/saved"),
    ("POST", "/workspaces/{workspace_id}/research/search"),
    ("POST", "/workspaces/{workspace_id}/research/resolve"),
    ("POST", "/workspaces/{workspace_id}/research/{run_id}/save"),
    ("POST", "/workspaces/{workspace_id}/research/{run_id}/save/resolve"),
}


def problem(status, code="research_unavailable"):
    return JSONResponse({"detail": code}, status_code=status, headers=HEADERS)


class ResearchRoute(APIRoute):
    async def handle(self, scope, receive, send):
        try:
            await super().handle(scope, receive, send)
        except ws.WorkspaceError as error:
            await problem(error.status, error.code)(scope, receive, send)
        except HTTPException as error:
            await problem(error.status_code, "research_access_denied")(scope, receive, send)
        except TimeoutError:
            await problem(504, "research_timeout")(scope, receive, send)
        except (ValueError, TypeError, KeyError, SQLAlchemyError):
            await problem(503)(scope, receive, send)


class ResearchMiddleware:
    def __init__(self, app, *, routes, cors_options):
        self.app, self.routes, self.cors_options = app, routes, cors_options

    async def __call__(self, scope, receive, send):
        route = next((r for r in self.routes if r.matches(scope)[0] == Match.FULL), None) if scope["type"] == "http" else None
        if route is None:
            await self.app(scope, receive, send)
            return

        async def private(inner, incoming, outgoing):
            owner = current_budget()
            assert owner is not None
            inner.setdefault("state", {})["research_deadline"] = owner
            await self.app(inner, incoming, outgoing)

        def error(status):
            response = problem(status)
            return CORSMiddleware(response, **self.cors_options) if self.cors_options else response

        async def final_send(message):
            if message["type"] == "http.response.start":
                required = {key.lower().encode(): value.encode() for key, value in HEADERS.items()}
                headers = [(key, value) for key, value in message.get("headers", []) if key.lower() not in required]
                message = {**message, "headers": [*headers, *required.items()]}
            await send(message)

        cap = MAX_HISTORY_BYTES if route.path.endswith("/research") else MAX_RESPONSE_BYTES
        await CaptureBoundary(private, DEADLINE_SECONDS, max_response_bytes=cap,
                              error_factory=error, error_send_seconds=0.25)(scope, receive, final_send)


def install_research_boundary(app):
    if any(item.cls is ResearchMiddleware for item in app.user_middleware):
        raise ValueError("research boundary already installed")
    routes = []
    for route in app.routes:
        if isinstance(route, ResearchRoute):
            routes.append(route)
        elif getattr(route, "effective_route_contexts", None) is not None:
            routes.extend(r for r in route.effective_route_contexts() if isinstance(r.original_route, ResearchRoute))
    actual = {(method, route.path) for route in routes for method in route.methods}
    if actual != INVENTORY or len(routes) != len(INVENTORY):
        raise ValueError("research route inventory changed")
    cors = [item.kwargs for item in app.user_middleware if item.cls is CORSMiddleware]
    if len(cors) > 1:
        raise ValueError("ambiguous research origin policy")
    app.add_middleware(ResearchMiddleware, routes=tuple(routes), cors_options=cors[0] if cors else None)


def router(*, settings, session_factory, identity_dependency, workspace_gate, port_factory):
    routes = APIRouter(route_class=ResearchRoute)

    async def execute(request, action, workspace_id=None, run_id=None):
        budget = getattr(request.state, "research_deadline", None)
        if not isinstance(budget, CaptureBudget):
            raise ws.WorkspaceError("research_unavailable", 503)
        if request.headers.getlist("x-cosmas-research-contract") != ["1"]:
            raise ws.WorkspaceError("research_contract_required", 426)
        if (len(request.headers.getlist("authorization")) != 1
                or any(name in request.headers for name in ("x-box-id", "x-actor-principal-id"))
                or request.headers.getlist("content-encoding")
                or len(request.headers.getlist("content-length")) > 1):
            raise ws.WorkspaceError("invalid_research_request", 422)
        query = request.query_params
        if action in {"history", "saved_history"}:
            if (list(query.keys()) not in (["bot"], ["bot", "before"])
                    or any(len(query.getlist(name)) != 1 for name in query.keys())):
                raise ws.WorkspaceError("invalid_research_request", 422)
            try:
                for name in query.keys():
                    value = UUID(query[name])
                    if str(value) != query[name] or value.version != 4:
                        raise ValueError()
            except ValueError:
                raise ws.WorkspaceError("invalid_research_request", 422) from None
        elif query:
            raise ws.WorkspaceError("invalid_research_request", 422)
        body = bytearray()
        async for chunk in request.stream():
            budget.check()
            body.extend(chunk)
            if len(body) > MAX_REQUEST_BYTES or request.method == "GET" and body:
                raise ws.WorkspaceError("invalid_research_request", 422)
        command = None
        if request.method == "POST":
            if request.headers.getlist("content-type") != ["application/json"]:
                raise ws.WorkspaceError("invalid_research_request", 422)

            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate JSON key")
                    result[key] = value
                return result

            try:
                json.loads(body, object_pairs_hook=unique)
                schema = Search if action == "search" else Save if action == "save" else Resolve
                command = schema.model_validate_json(bytes(body))
            except (ValueError, ValidationError, RecursionError):
                raise ws.WorkspaceError("invalid_research_request", 422) from None

        def work():
            with capture_budget(budget):
                return owned_work()

        def owned_work():
            session = new_capture_session(session_factory)
            try:
                with capture_budget(budget):
                    def authenticate():
                        budget.check()
                        workspace_gate(response=Response(), request=request)
                        value = identity_dependency(session=session, authorization=request.headers["authorization"],
                                                    x_box_id=None, x_actor_principal_id=None)
                        if value.auth_mode != "clerk_jwt" or value.external_identity_id is None:
                            raise ws.WorkspaceError("research_access_denied", 403)
                        budget.check()
                        return value

                    identity = authenticate()
                    # Freeze the selected mapping/credential for this lookup. Recovery
                    # deliberately remains independent of current publisher settings.
                    config = settings().model_copy(deep=True)
                    configured = port_factory.configured(config) if action in {"catalog", "search"} else frozenset()
                    selection = port_factory.selection(config) if action == "search" else None

                    def current():
                        # Refresh only identity rows. Expiring the whole Session
                        # here would discard a pending result or workspace revision.
                        for entity in tuple(session.identity_map.values()):
                            if isinstance(entity, (ExternalIdentity, Principal)):
                                session.expire(entity)
                        binding = session.scalar(select(ExternalIdentity).where(
                            ExternalIdentity.id == identity.external_identity_id,
                            ExternalIdentity.active.is_(True),
                        ).with_for_update(read=True).execution_options(populate_existing=True))
                        if binding is None:
                            raise ws.WorkspaceError("research_access_denied", 403)
                        if authenticate() != identity:
                            raise ws.WorkspaceError("research_access_denied", 403)
                        if action == "search":
                            latest = settings()
                            if (not latest.workspace_research_available or not latest.workspace_research_io_enabled
                                    or port_factory.selection(latest) != selection):
                                raise ws.WorkspaceError("research_unavailable", 409)

                    box, owner = identity.box_id, identity.principal_id
                    wid = str(workspace_id)
                    if action == "catalog":
                        result = catalog(enabled=config.workspace_research_available and config.workspace_research_io_enabled,
                                         configured=configured)
                    elif action == "history":
                        result = research.history(session, box, owner, wid, bot=query["bot"], before=query.get("before"))
                    elif action == "saved_history":
                        result = research.saved_history(session, box, owner, wid, bot=query["bot"], before=query.get("before"))
                    elif action == "search":
                        current()
                        with port_factory(config) as port:
                            result = research.search(session, box, owner, wid, request=command, configured=configured,
                                                     port=port, check=budget.check, reauthenticate=current)
                    elif action == "resolve":
                        assert isinstance(command, Resolve)
                        result = research.resolve(session, box, owner, wid, key=command.idempotency_key)
                    elif action == "save":
                        result = research.save(session, box, owner, wid, str(run_id), request=command,
                                               check=budget.check, reauthenticate=current)
                    else:
                        assert isinstance(command, Resolve)
                        result = research.resolve_save(session, box, owner, wid, str(run_id), key=command.idempotency_key)
                    current()
                    raw = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
                    if len(raw) > (MAX_HISTORY_BYTES if action == "history" else MAX_RESPONSE_BYTES):
                        raise ws.WorkspaceError("research_result_too_large", 503)
                    budget.check()
                    return raw
            finally:
                try:
                    session.rollback()
                finally:
                    session.close()

        result = await run_in_threadpool(Context().run, work)
        budget.check()
        return Response(result, media_type="application/json", headers=HEADERS)

    @routes.get("/research/catalog")
    async def source_catalog(request: Request):
        return await execute(request, "catalog")

    @routes.get("/workspaces/{workspace_id}/research")
    async def recent(request: Request, workspace_id: UUID):
        return await execute(request, "history", workspace_id)

    @routes.get("/workspaces/{workspace_id}/research/saved")
    async def saved_packets(request: Request, workspace_id: UUID):
        return await execute(request, "saved_history", workspace_id)

    @routes.post("/workspaces/{workspace_id}/research/search")
    async def search(request: Request, workspace_id: UUID):
        return await execute(request, "search", workspace_id)

    @routes.post("/workspaces/{workspace_id}/research/resolve")
    async def resolve(request: Request, workspace_id: UUID):
        return await execute(request, "resolve", workspace_id)

    @routes.post("/workspaces/{workspace_id}/research/{run_id}/save")
    async def save(request: Request, workspace_id: UUID, run_id: UUID):
        return await execute(request, "save", workspace_id, run_id)

    @routes.post("/workspaces/{workspace_id}/research/{run_id}/save/resolve")
    async def resolve_save(request: Request, workspace_id: UUID, run_id: UUID):
        return await execute(request, "resolve_save", workspace_id, run_id)

    return routes
