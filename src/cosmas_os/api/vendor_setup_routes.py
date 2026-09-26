"""Bounded owner delivery settings routes; no service I/O or credential input."""

import asyncio
import time
from uuid import UUID

from fastapi import Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from cosmas_os.api import vendor_setup_schemas as schema
from cosmas_os.api.vendor_work_schemas import read_json
from cosmas_os.application import vendor_settings as flow
from cosmas_os.application.workspace import WorkspaceError

SAFE_ERRORS = {
    "vendor_setup_unavailable",
    "invalid_vendor_setup_request",
    "vendor_setup_client_update_required",
    "vendor_setup_request_too_large",
    "vendor_installation_changed",
    "vendor_patient_unavailable",
    "vendor_setup_integrity",
    "vendor_setup_idempotency_conflict",
    "vendor_account_changed",
    "vendor_permission_expired",
    "vendor_setup_changed",
    "vendor_setup_limit",
    "vendor_setup_already_exists",
    "vendor_setup_disabled",
    "vendor_setup_revision_required",
    "vendor_binding_unavailable",
    "vendor_setup_inactive",
}


def installed_catalog():
    return flow.EMPTY_CATALOG


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
    @app.middleware("http")
    async def boundary(request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        private = request.url.path == "/vendor-settings" or request.url.path.startswith(
            "/vendor-settings/"
        )
        if request.headers.getlist("x-cosmas-vendor-setup-contract") and not private:
            return failure(WorkspaceError("vendor_setup_client_update_required", 426), marked=False)
        if not private:
            return await call_next(request)
        request.state.vendor_setup_deadline = time.monotonic() + 15
        try:
            async with asyncio.timeout(15):
                response = await call_next(request)
            if response.status_code >= 400 and response.headers.get("x-cosmas-vendor-setup-error") != "1":
                return failure(WorkspaceError("vendor_setup_unavailable", response.status_code), marked=False)
            if "x-cosmas-vendor-setup-error" in response.headers:
                del response.headers["x-cosmas-vendor-setup-error"]
            response.headers["Cache-Control"] = "no-store"
            return response
        except (TimeoutError, SQLAlchemyError):
            return failure(WorkspaceError("vendor_setup_unavailable", 503), marked=False)

    def failure(exc, *, marked=True):
        code = exc.code if exc.code in SAFE_ERRORS else "vendor_setup_unavailable"
        headers = {"Cache-Control": "no-store"}
        if marked:
            headers["X-Cosmas-Vendor-Setup-Error"] = "1"
        return JSONResponse(
            {"error": {"code": code}}, status_code=exc.status, headers=headers
        )

    def contract(request):
        if request.query_params or request.headers.getlist("x-cosmas-vendor-setup-contract") != [
            "1"
        ]:
            raise WorkspaceError("vendor_setup_client_update_required", 426)

    async def execute(request, session, identity, call):
        def fence():
            if time.monotonic() >= request.state.vendor_setup_deadline:
                raise WorkspaceError("vendor_setup_unavailable", 503)
            session.expire_all()
            if reauthenticate is not None:
                reauthenticate(request, session, identity)
                return
            current = identity_dependency(
                request=request,
                session=session,
                authorization=request.headers.get("authorization"),
                x_box_id=request.headers.get("x-box-id"),
                x_actor_principal_id=request.headers.get("x-actor-principal-id"),
            )
            if current != identity:
                raise WorkspaceError("vendor_setup_unavailable", 403)

        try:
            contract(request)
            session.info["vendor_setup_authority"] = fence
            await run_in_threadpool(fence)
            result = await run_in_threadpool(call)
            await run_in_threadpool(fence)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except WorkspaceError as exc:
            session.rollback()
            return failure(exc)
        except SQLAlchemyError:
            session.rollback()
            return failure(WorkspaceError("vendor_setup_unavailable", 503))
        finally:
            session.info.pop("vendor_setup_authority", None)

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
                        raise WorkspaceError("vendor_setup_request_too_large", 413)
                    data.extend(chunk)
            return read_json(bytes(data), model, maximum=8192)
        except (ValueError, TypeError, TimeoutError, UnicodeError, RecursionError):
            raise WorkspaceError("invalid_vendor_setup_request", 400) from None

    @app.get("/vendor-settings")
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

    @app.get("/vendor-settings/{setup_id}")
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

    @app.get("/vendor-settings/{setup_id}/history")
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

    @app.post("/vendor-settings/resolve")
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
                flow.propose if kind in {"propose_account", "propose_recipient"} else flow.command
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

        app.add_api_route("/vendor-settings/" + kind, command, methods=["POST"])

    for kind, model in schema.COMMANDS.items():
        add(kind, model)
