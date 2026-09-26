"""Bounded authenticated owner administration without portal network effects."""

import asyncio
from uuid import UUID

from fastapi import Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from cosmas_os.api import portal_setup_schemas as schema
from cosmas_os.api.vendor_work_schemas import read_json
from cosmas_os.application import portal_setup as flow
from cosmas_os.application.workspace import WorkspaceError


def installed_catalog():
    return flow.EMPTY_CATALOG


def register(app, get_session, identity_dependency, *, catalog_dependency=installed_catalog):
    async def execute(request, session, identity, call):
        def fence():
            session.expire_all()
            current = identity_dependency(
                request=request,
                session=session,
                authorization=request.headers.get("authorization"),
                x_box_id=request.headers.get("x-box-id"),
                x_actor_principal_id=request.headers.get("x-actor-principal-id"),
            )
            if current != identity:
                raise WorkspaceError("portal_setup_unavailable", 403)

        try:
            if request.query_params or request.headers.getlist("x-cosmas-portal-contract") != ["1"]:
                raise WorkspaceError("portal_client_update_required", 426)
            session.info["portal_setup_authority"] = fence
            await run_in_threadpool(fence)
            result = await run_in_threadpool(call)
            await run_in_threadpool(fence)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except WorkspaceError as exc:
            session.rollback()
            code = (
                exc.code
                if exc.code.startswith("portal_") or exc.code == "invalid_portal_request"
                else "portal_setup_unavailable"
            )
            return JSONResponse(
                {"detail": code}, status_code=exc.status, headers={"Cache-Control": "no-store"}
            )
        except SQLAlchemyError:
            session.rollback()
            return JSONResponse(
                {"detail": "portal_setup_unavailable"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        finally:
            session.info.pop("portal_setup_authority", None)

    async def body(request, model):
        try:
            if request.headers.getlist("content-type") != [
                "application/json"
            ] or request.headers.getlist("content-encoding"):
                raise ValueError
            data = bytearray()
            async with asyncio.timeout(15):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > 8192:
                        raise ValueError
                    data.extend(chunk)
            return read_json(bytes(data), model, maximum=8192)
        except (ValueError, TypeError, TimeoutError):
            raise WorkspaceError("invalid_portal_request", 422) from None

    @app.get("/portal-setup")
    async def catalog(
        request: Request,
        session=Depends(get_session),
        identity=Depends(identity_dependency),
        installed=Depends(catalog_dependency),
    ):
        return await execute(
            request,
            session,
            identity,
            lambda: flow.catalog(session, identity.box_id, identity.principal_id, installed),
        )

    @app.get("/portal-setup/{connection_id}")
    async def detail(
        request: Request,
        connection_id: UUID,
        session=Depends(get_session),
        identity=Depends(identity_dependency),
        installed=Depends(catalog_dependency),
    ):
        return await execute(
            request,
            session,
            identity,
            lambda: flow.detail(
                session, identity.box_id, identity.principal_id, str(connection_id), installed
            ),
        )

    @app.get("/portal-setup/{connection_id}/history")
    async def history(
        request: Request,
        connection_id: UUID,
        session=Depends(get_session),
        identity=Depends(identity_dependency),
    ):
        return await execute(
            request,
            session,
            identity,
            lambda: flow.history(
                session, identity.box_id, identity.principal_id, str(connection_id)
            ),
        )

    @app.post("/portal-setup/resolve")
    async def resolve(
        request: Request, session=Depends(get_session), identity=Depends(identity_dependency)
    ):
        try:
            value = await body(request, schema.Resolve)
        except WorkspaceError as exc:
            return JSONResponse(
                {"detail": exc.code}, status_code=exc.status, headers={"Cache-Control": "no-store"}
            )
        return await execute(
            request,
            session,
            identity,
            lambda: flow.resolve(session, identity.box_id, identity.principal_id, value),
        )

    def add(kind, model):
        async def command(
            request: Request,
            session=Depends(get_session),
            identity=Depends(identity_dependency),
            installed=Depends(catalog_dependency),
        ):
            try:
                value = await body(request, model)
            except WorkspaceError as exc:
                return JSONResponse(
                    {"detail": exc.code},
                    status_code=exc.status,
                    headers={"Cache-Control": "no-store"},
                )
            call = (
                (
                    lambda: flow.propose(
                        session, identity.box_id, identity.principal_id, value, installed
                    )
                )
                if kind == "propose"
                else (
                    lambda: flow.command(
                        session, identity.box_id, identity.principal_id, kind, value, installed
                    )
                )
            )
            return await execute(request, session, identity, call)

        app.add_api_route("/portal-setup/" + kind, command, methods=["POST"])

    for kind, model in schema.COMMANDS.items():
        add(kind, model)
