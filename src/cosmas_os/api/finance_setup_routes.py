"""Bounded owner financial settings routes; no service I/O or credential input."""

import asyncio
from uuid import UUID

from fastapi import Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from cosmas_os.api import finance_setup_schemas as schema
from cosmas_os.api.vendor_work_schemas import read_json
from cosmas_os.application import finance_settings as flow
from cosmas_os.application.workspace import WorkspaceError


def installed_catalog(request: Request):
    from cosmas_os.adapters.managed_services import managed_services

    runtime = managed_services(request.app)
    return runtime.finance_catalog if runtime is not None else flow.EMPTY_CATALOG


def setup_policy():
    return flow.DEFAULT_POLICY


def register(
    app,
    get_session,
    identity_dependency,
    *,
    reauthenticate=None,
    policy_dependency=setup_policy,
    catalog_dependency=installed_catalog,
):
    def failure(exc):
        code = (
            exc.code
            if exc.code.startswith("finance_") or exc.code == "invalid_finance_setup_request"
            else "finance_setup_unavailable"
        )
        return JSONResponse(
            {"error": {"code": code}}, status_code=exc.status, headers={"Cache-Control": "no-store"}
        )

    def contract(request):
        if request.query_params or request.headers.getlist("x-cosmas-finance-setup-contract") != [
            "1"
        ]:
            raise WorkspaceError("finance_setup_client_update_required", 426)

    async def execute(request, session, identity, call):
        def fence():
            session.expire_all()
            if reauthenticate is not None:
                reauthenticate(request, session, identity)
                return
            current = identity_dependency(
                session=session,
                authorization=request.headers.get("authorization"),
                x_box_id=request.headers.get("x-box-id"),
                x_actor_principal_id=request.headers.get("x-actor-principal-id"),
            )
            if current != identity:
                raise WorkspaceError("finance_setup_unavailable", 403)

        try:
            contract(request)
            session.info["finance_setup_authority"] = fence
            await run_in_threadpool(fence)
            result = await run_in_threadpool(call)
            await run_in_threadpool(fence)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except WorkspaceError as exc:
            session.rollback()
            return failure(exc)
        except SQLAlchemyError:
            session.rollback()
            return failure(WorkspaceError("finance_setup_unavailable", 503))
        finally:
            session.info.pop("finance_setup_authority", None)

    async def body(request, model):
        try:
            contract(request)
            if request.headers.getlist("content-type") != [
                "application/json"
            ] or request.headers.getlist("content-encoding"):
                raise ValueError
            data = bytearray()
            async with asyncio.timeout(15):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > 8192:
                        raise WorkspaceError("finance_setup_request_too_large", 413)
                    data.extend(chunk)
            return read_json(bytes(data), model, maximum=8192)
        except (ValueError, TypeError, TimeoutError, UnicodeError, RecursionError):
            raise WorkspaceError("invalid_finance_setup_request", 400) from None

    @app.get("/finance-setup")
    async def catalog(
        request: Request,
        session=Depends(get_session),
        identity=Depends(identity_dependency),
        installed=Depends(catalog_dependency),
        policy=Depends(policy_dependency),
    ):
        return await execute(
            request,
            session,
            identity,
            lambda: flow.catalog(
                session, identity.box_id, identity.principal_id, installed, policy=policy
            ),
        )

    @app.get("/finance-setup/{setup_id}")
    async def detail(
        request: Request,
        setup_id: UUID,
        session=Depends(get_session),
        identity=Depends(identity_dependency),
        installed=Depends(catalog_dependency),
        policy=Depends(policy_dependency),
    ):
        return await execute(
            request,
            session,
            identity,
            lambda: flow.detail(
                session,
                identity.box_id,
                identity.principal_id,
                str(setup_id),
                installed,
                policy=policy,
            ),
        )

    @app.get("/finance-setup/{setup_id}/history")
    async def history(
        request: Request,
        setup_id: UUID,
        session=Depends(get_session),
        identity=Depends(identity_dependency),
    ):
        return await execute(
            request,
            session,
            identity,
            lambda: flow.history(session, identity.box_id, identity.principal_id, str(setup_id)),
        )

    @app.post("/finance-setup/resolve")
    async def resolve(
        request: Request, session=Depends(get_session), identity=Depends(identity_dependency)
    ):
        try:
            value = await body(request, schema.Resolve)
        except WorkspaceError as exc:
            return failure(exc)
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
            policy=Depends(policy_dependency),
        ):
            try:
                value = await body(request, model)
            except WorkspaceError as exc:
                return failure(exc)
            method = (
                flow.propose if kind in {"propose_account", "propose_customer"} else flow.command
            )
            return await execute(
                request,
                session,
                identity,
                lambda: method(
                    session,
                    identity.box_id,
                    identity.principal_id,
                    kind,
                    value,
                    installed,
                    policy=policy,
                ),
            )

        app.add_api_route("/finance-setup/" + kind, command, methods=["POST"])

    for kind, model in schema.COMMANDS.items():
        add(kind, model)
