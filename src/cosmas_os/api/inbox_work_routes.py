"""Owner-private Inbox routes. No HTTP endpoint accepts external source snapshots."""

import asyncio
import re
import time
from uuid import UUID

from fastapi import Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from cosmas_os.api import inbox_work_schemas as schema
from cosmas_os.api.vendor_work_schemas import read_json
from cosmas_os.application import inbox_work as flow
from cosmas_os.application.workspace import WorkspaceError

SAFE = {
    "inbox_unavailable",
    "inbox_integrity",
    "invalid_inbox_request",
    "inbox_contract_required",
    "inbox_feature_disabled",
    "inbox_binding_unavailable",
    "inbox_source_changed",
    "inbox_version_changed",
    "inbox_workspace_changed",
    "inbox_review_required",
    "inbox_triage_required",
    "inbox_result_changed",
    "inbox_exception_unresolved",
    "inbox_history_limit",
    "inbox_idempotency_conflict",
}


def policy():
    return flow.DEFAULT_POLICY


def registry():
    return flow.no_registry


def failure(code, status):
    code = code if code in SAFE else "inbox_unavailable"
    return JSONResponse(
        {"contract_version": 1, "error": {"code": code}},
        status_code=status,
        headers={"Cache-Control": "no-store", "X-Cosmas-Inbox-Error": "1"},
    )


def register(
    app,
    get_session,
    identity_dependency,
    *,
    policy_dependency=policy,
    registry_dependency=registry,
    reauthenticate=None,
):
    @app.middleware("http")
    async def boundary(request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        private = bool(re.fullmatch(r"/inbox(?:/.*)?", request.url.path))
        values = request.headers.getlist("x-cosmas-inbox-contract")
        if values and not private:
            return failure("inbox_contract_required", 426)
        if not private:
            return await call_next(request)
        request.state.inbox_deadline = time.monotonic() + 15
        if values != ["1"] or request.query_params:
            return failure("inbox_contract_required", 426)
        try:
            async with asyncio.timeout(15):
                response = await call_next(request)
            if response.status_code >= 400 and response.headers.get("x-cosmas-inbox-error") != "1":
                return failure("inbox_unavailable", response.status_code)
            if "x-cosmas-inbox-error" in response.headers:
                del response.headers["x-cosmas-inbox-error"]
            response.headers["Cache-Control"] = "no-store"
            return response
        except (TimeoutError, SQLAlchemyError):
            return failure("inbox_unavailable", 503)

    async def body(request, model):
        if request.headers.getlist("content-type") != [
            "application/json"
        ] or request.headers.getlist("content-encoding"):
            flow.error("invalid_inbox_request", 400)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > 8192:
                flow.error("invalid_inbox_request", 413)
            data.extend(chunk)
        try:
            return read_json(bytes(data), model, maximum=8192)
        except (ValueError, UnicodeError, RecursionError):
            flow.error("invalid_inbox_request", 400)

    async def run(request, s, identity, call):
        def fence():
            if time.monotonic() >= request.state.inbox_deadline:
                flow.error("inbox_unavailable", 503)
            s.expire_all()
            if reauthenticate is not None:
                reauthenticate(request, s, identity)
                return
            current = identity_dependency(
                request=request,
                session=s,
                authorization=request.headers.get("authorization"),
                x_box_id=request.headers.get("x-box-id"),
                x_actor_principal_id=request.headers.get("x-actor-principal-id"),
            )
            if current != identity:
                flow.error("inbox_unavailable", 403)

        s.info["inbox_final_authority"] = fence
        try:
            await run_in_threadpool(fence)
            value = (
                await call() if asyncio.iscoroutinefunction(call) else await run_in_threadpool(call)
            )
            await run_in_threadpool(fence)
            return JSONResponse(value, headers={"Cache-Control": "no-store"})
        except WorkspaceError as exc:
            s.rollback()
            return failure(exc.code, exc.status)
        except SQLAlchemyError:
            s.rollback()
            return failure("inbox_unavailable", 503)
        finally:
            s.info.pop("inbox_final_authority", None)

    @app.get("/inbox")
    async def catalog(
        request: Request,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        gate=Depends(policy_dependency),
        installed=Depends(registry_dependency),
    ):
        return await run(
            request,
            s,
            identity,
            lambda: flow.catalog(
                s, identity.box_id, identity.principal_id, registry=installed, policy=gate
            ),
        )

    @app.post("/inbox/resolve")
    async def resolve(
        request: Request,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        gate=Depends(policy_dependency),
        installed=Depends(registry_dependency),
    ):
        async def call():
            q = await body(request, schema.Resolve)
            return await run_in_threadpool(
                flow.resolve,
                s,
                identity.box_id,
                identity.principal_id,
                q,
                registry=installed,
                policy=gate,
            )

        return await run(request, s, identity, call)

    @app.get("/inbox/{item_id}")
    async def detail(
        item_id: UUID,
        request: Request,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        gate=Depends(policy_dependency),
        installed=Depends(registry_dependency),
    ):
        return await run(
            request,
            s,
            identity,
            lambda: flow.detail(
                s,
                identity.box_id,
                identity.principal_id,
                str(item_id),
                registry=installed,
                policy=gate,
            ),
        )

    @app.get("/inbox/{item_id}/history")
    async def history(
        item_id: UUID,
        request: Request,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        gate=Depends(policy_dependency),
        installed=Depends(registry_dependency),
    ):
        return await run(
            request,
            s,
            identity,
            lambda: flow.history(
                s,
                identity.box_id,
                identity.principal_id,
                str(item_id),
                registry=installed,
                policy=gate,
            ),
        )

    @app.get("/inbox/{item_id}/sources/{source_id}")
    async def source(
        item_id: UUID,
        source_id: UUID,
        request: Request,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        gate=Depends(policy_dependency),
        installed=Depends(registry_dependency),
    ):
        return await run(
            request,
            s,
            identity,
            lambda: flow.read_source(
                s,
                identity.box_id,
                identity.principal_id,
                str(item_id),
                str(source_id),
                registry=installed,
                policy=gate,
            ),
        )

    @app.post("/inbox/{item_id}/{kind}")
    async def command(
        item_id: UUID,
        kind: str,
        request: Request,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        gate=Depends(policy_dependency),
        installed=Depends(registry_dependency),
    ):
        async def call():
            if kind not in schema.COMMANDS:
                flow.error("invalid_inbox_request", 400)
            q = await body(request, schema.COMMANDS[kind])
            return await run_in_threadpool(
                flow.command,
                s,
                identity.box_id,
                identity.principal_id,
                str(item_id),
                kind,
                q,
                registry=installed,
                policy=gate,
            )

        return await run(request, s, identity, call)
