"""Default-off internal handoff routes; host supplies current independent Inbox grant."""

import asyncio
import re
import time
from uuid import UUID

from fastapi import Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from cosmas_os.api import inbox_handoff_schemas as schema
from cosmas_os.api.vendor_work_schemas import bounded, read_json
from cosmas_os.application import inbox_handoff as flow
from cosmas_os.application import inbox_work
from cosmas_os.application.workspace import WorkspaceError


def policy():
    return flow.DEFAULT_POLICY


def registry():
    return inbox_work.no_registry


def failure(code, status):
    safe = (
        code
        if code.startswith("inbox_handoff_") or code == "invalid_inbox_handoff"
        else "inbox_handoff_unavailable"
    )
    return JSONResponse(
        {"contract_version": 1, "error": {"code": safe}},
        status_code=status,
        headers={"Cache-Control": "no-store", "X-Cosmas-Inbox-Handoff-Error": "1"},
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
        private = bool(
            re.fullmatch(r"/(?:workspaces/[^/]+/)?inbox-handoffs(?:/.*)?", request.url.path)
        )
        header = request.headers.getlist("x-cosmas-inbox-handoff-contract")
        if header and not private:
            return failure("inbox_handoff_contract_required", 426)
        if not private:
            return await call_next(request)
        request.state.inbox_handoff_deadline = time.monotonic() + 15
        if header != ["1"] or request.query_params:
            return failure("inbox_handoff_contract_required", 426)
        try:
            async with asyncio.timeout(15):
                result = await call_next(request)
            if (
                result.status_code >= 400
                and result.headers.get("x-cosmas-inbox-handoff-error") != "1"
            ):
                return failure("inbox_handoff_unavailable", result.status_code)
            if "x-cosmas-inbox-handoff-error" in result.headers:
                del result.headers["x-cosmas-inbox-handoff-error"]
            result.headers["Cache-Control"] = "no-store"
            return result
        except (TimeoutError, SQLAlchemyError):
            return failure("inbox_handoff_unavailable", 503)

    async def body(request, model):
        if request.headers.getlist("content-type") != [
            "application/json"
        ] or request.headers.getlist("content-encoding"):
            flow.error("invalid_inbox_handoff", 400)
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 8192:
                flow.error("invalid_inbox_handoff", 413)
            raw.extend(chunk)
        try:
            return read_json(bytes(raw), model, maximum=8192)
        except (ValueError, UnicodeError, RecursionError):
            flow.error("invalid_inbox_handoff", 400)

    async def run(request, s, identity, call, maximum=65536):
        def fence():
            if time.monotonic() >= request.state.inbox_handoff_deadline:
                flow.error("inbox_handoff_unavailable", 503)
            s.expire_all()
            if reauthenticate is not None:
                reauthenticate(request, s, identity)
            else:
                current = identity_dependency(
                    request=request,
                    session=s,
                    authorization=request.headers.get("authorization"),
                    x_box_id=request.headers.get("x-box-id"),
                    x_actor_principal_id=request.headers.get("x-actor-principal-id"),
                )
                if current != identity:
                    flow.error("inbox_handoff_unavailable", 403)

        s.info["inbox_handoff_final_authority"] = fence
        try:
            await run_in_threadpool(fence)
            value = (
                await call() if asyncio.iscoroutinefunction(call) else await run_in_threadpool(call)
            )
            await run_in_threadpool(fence)
            return JSONResponse(bounded(value, maximum), headers={"Cache-Control": "no-store"})
        except WorkspaceError as exc:
            s.rollback()
            return failure(exc.code, exc.status)
        except (SQLAlchemyError, ValueError):
            s.rollback()
            return failure("inbox_handoff_unavailable", 503)
        finally:
            s.info.pop("inbox_handoff_final_authority", None)

    @app.get("/inbox-handoffs")
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
            131072,
        )

    @app.get("/inbox-handoffs/{ticket_id}")
    async def detail(
        ticket_id: UUID,
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
            lambda: flow.read(
                s,
                identity.box_id,
                identity.principal_id,
                str(ticket_id),
                registry=installed,
                policy=gate,
            ),
        )

    @app.post("/workspaces/{workspace_id}/inbox-handoffs/{kind}")
    async def private_command(
        workspace_id: UUID,
        kind: str,
        request: Request,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        gate=Depends(policy_dependency),
        installed=Depends(registry_dependency),
    ):
        async def call():
            if kind not in {"propose", "resolve"}:
                flow.error("invalid_inbox_handoff", 400)
            q = await body(request, schema.Propose if kind == "propose" else schema.Resolve)
            if kind == "resolve":
                return await run_in_threadpool(
                    flow.resolve, s, identity.box_id, identity.principal_id, str(workspace_id), q
                )
            return await run_in_threadpool(
                flow.propose,
                s,
                identity.box_id,
                identity.principal_id,
                str(workspace_id),
                q,
                registry=installed,
                policy=gate,
            )

        return await run(request, s, identity, call, 16384)

    @app.post("/inbox-handoffs/{ticket_id}/{kind}")
    async def command(
        ticket_id: UUID,
        kind: str,
        request: Request,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        gate=Depends(policy_dependency),
        installed=Depends(registry_dependency),
    ):
        async def call():
            if kind not in {"decide", "handoff", "result", "verify", "resolve"}:
                flow.error("invalid_inbox_handoff", 400)
            if kind == "resolve":
                q = await body(request, schema.Resolve)
                return await run_in_threadpool(
                    flow.resolve_ticket,
                    s,
                    identity.box_id,
                    identity.principal_id,
                    str(ticket_id),
                    q,
                )
            q = await body(request, schema.COMMANDS[kind])
            return await run_in_threadpool(
                flow.command,
                s,
                identity.box_id,
                identity.principal_id,
                str(ticket_id),
                kind,
                q,
                registry=installed,
                policy=gate,
            )

        return await run(request, s, identity, call, 16384)
