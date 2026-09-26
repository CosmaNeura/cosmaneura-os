"""Bounded authenticated routes for local reviewed portal work."""

import asyncio
import time
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from cosmas_os.api import portal_setup_routes
from cosmas_os.api import portal_work_schemas as schema
from cosmas_os.api.vendor_work_schemas import read_json
from cosmas_os.application import portal_work as work
from cosmas_os.application import portal_work_execution as execution
from cosmas_os.application.capture_deadline import capture_async, run_in_threadpool
from cosmas_os.application.workspace import WorkspaceError


def default_policy():
    return work.DEFAULT_POLICY


def no_execution():
    return None


def register(
    app,
    get_session,
    identity_dependency,
    *,
    catalog_dependency=portal_setup_routes.installed_catalog,
    policy_dependency=default_policy,
    execution_dependency=no_execution,
    execution_factory_dependency=no_execution,
    session_factory=None,
    core_connection=no_execution,
    current_core_note=None,
):
    def failure(code, status):
        return JSONResponse(
            {"detail": code}, status_code=status, headers={"Cache-Control": "no-store"}
        )

    async def execute(request, s, identity, call):
        def fence():
            s.expire_all()
            current = identity_dependency(
                request=request,
                session=s,
                authorization=request.headers.get("authorization"),
                x_box_id=request.headers.get("x-box-id"),
                x_actor_principal_id=request.headers.get("x-actor-principal-id"),
            )
            if current != identity:
                raise WorkspaceError("portal_work_unavailable", 403)

        try:
            if request.query_params or request.headers.getlist("x-cosmas-portal-work-contract") != [
                "1"
            ]:
                raise WorkspaceError("portal_work_client_update_required", 426)
            s.info["portal_work_authority"] = fence
            async with asyncio.timeout(45):
                await run_in_threadpool(fence)
                result = await call()
                await run_in_threadpool(fence)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except WorkspaceError as exc:
            await run_in_threadpool(s.rollback)
            return failure(
                exc.code
                if exc.code.startswith(("portal_work_", "invalid_portal_work_"))
                else "portal_work_unavailable",
                exc.status,
            )
        except HTTPException as exc:
            await run_in_threadpool(s.rollback)
            return failure("portal_work_unavailable", exc.status_code)
        except (SQLAlchemyError, TimeoutError):
            await run_in_threadpool(s.rollback)
            return failure("portal_work_unconfirmed", 503)
        finally:
            s.info.pop("portal_work_authority", None)

    async def body(request, model):
        try:
            if request.headers.getlist("content-type") != [
                "application/json"
            ] or request.headers.getlist("content-encoding"):
                raise ValueError
            data = bytearray()
            async with asyncio.timeout(15):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > 16384:
                        raise ValueError
                    data.extend(chunk)
            return read_json(bytes(data), model, maximum=16384)
        except (ValueError, TypeError, TimeoutError):
            raise WorkspaceError("invalid_portal_work_request", 422) from None

    def discover(s, identity, wid, tid, kind, value):
        w = work.owner(s, identity.box_id, identity.principal_id, str(wid))
        old, _ = work.old_receipt(s, w, kind, value)
        if old:
            if tid is not None and old.ticket_id != str(tid):
                raise WorkspaceError("portal_work_idempotency_conflict", 409)
            return work.response(old), None
        if kind == "propose":
            return None, value.source.note_id
        _, row, _ = work.bound(s, w, str(tid), value)
        return None, row.note_id

    async def current(request, s, identity, wid, tid, kind, value, port, apply):
        recovered, note_id = await run_in_threadpool(discover, s, identity, wid, tid, kind, value)
        await run_in_threadpool(s.rollback)
        if recovered is not None:
            return recovered
        if current_core_note is None:
            # Application validation refuses a linked Core note without a current receipt.
            return await run_in_threadpool(apply, None)
        return await current_core_note(request, wid, s, identity, port, apply, note_id=note_id)

    prefix = "/workspaces/{workspace_id}/portal-work"

    @app.get(prefix)
    async def catalog(
        request: Request,
        workspace_id: UUID,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
    ):
        return await execute(
            request,
            s,
            identity,
            lambda: run_in_threadpool(
                work.catalog, s, identity.box_id, identity.principal_id, str(workspace_id)
            ),
        )

    @app.get(prefix + "/{ticket_id}")
    async def detail(
        request: Request,
        workspace_id: UUID,
        ticket_id: UUID,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
    ):
        return await execute(
            request,
            s,
            identity,
            lambda: run_in_threadpool(
                work.detail,
                s,
                identity.box_id,
                identity.principal_id,
                str(workspace_id),
                str(ticket_id),
            ),
        )

    @app.get(prefix + "/{ticket_id}/observations")
    async def observations(
        request: Request,
        workspace_id: UUID,
        ticket_id: UUID,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
    ):
        return await execute(
            request,
            s,
            identity,
            lambda: run_in_threadpool(
                work.observations,
                s,
                identity.box_id,
                identity.principal_id,
                str(workspace_id),
                str(ticket_id),
            ),
        )

    @app.post(prefix + "/resolve")
    async def resolve(
        request: Request,
        workspace_id: UUID,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
    ):
        async def call():
            value = await body(request, schema.Resolve)
            return await run_in_threadpool(
                work.resolve, s, identity.box_id, identity.principal_id, str(workspace_id), value
            )

        return await execute(request, s, identity, call)

    @app.post(prefix)
    async def propose(
        request: Request,
        workspace_id: UUID,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        catalog=Depends(catalog_dependency),
        policy=Depends(policy_dependency),
        port=Depends(core_connection),
    ):
        async def call():
            value = await body(request, schema.Proposal)
            return await current(
                request,
                s,
                identity,
                workspace_id,
                None,
                "propose",
                value,
                port,
                lambda checked: work.propose(
                    s,
                    identity.box_id,
                    identity.principal_id,
                    str(workspace_id),
                    value,
                    catalog=catalog,
                    policy=policy,
                    core_checked=checked,
                ),
            )

        return await execute(request, s, identity, call)

    def add(kind, model):
        async def command(
            request: Request,
            workspace_id: UUID,
            ticket_id: UUID,
            s=Depends(get_session),
            identity=Depends(identity_dependency),
            catalog=Depends(catalog_dependency),
            policy=Depends(policy_dependency),
            runtime=Depends(execution_dependency),
            factory=Depends(execution_factory_dependency),
            port=Depends(core_connection),
        ):
            async def call():
                value = await body(request, model)
                args = (
                    s,
                    identity.box_id,
                    identity.principal_id,
                    str(workspace_id),
                    str(ticket_id),
                    kind,
                    value,
                )
                if kind in {"submit", "status"}:
                    recovered, _ = await run_in_threadpool(
                        discover, s, identity, workspace_id, ticket_id, kind, value
                    )
                    await run_in_threadpool(s.rollback)
                    if recovered is not None:
                        return recovered
                    if runtime is None and factory is None:
                        raise WorkspaceError("portal_work_io_disabled", 403)
                    deadline = time.monotonic() + 40
                    selected_runtime = runtime
                    if factory is not None:

                        async def identity_current():
                            def check():
                                if session_factory is None or time.monotonic() >= deadline:
                                    return False
                                with session_factory() as current_session:
                                    current_identity = identity_dependency(
                                        request=request,
                                        session=current_session,
                                        authorization=request.headers.get("authorization"),
                                        x_box_id=request.headers.get("x-box-id"),
                                        x_actor_principal_id=request.headers.get(
                                            "x-actor-principal-id"
                                        ),
                                    )
                                    return (
                                        current_identity == identity and time.monotonic() < deadline
                                    )

                            try:
                                return await run_in_threadpool(check)
                            except Exception:
                                return False

                        selected_runtime = factory(identity_current)
                    if selected_runtime is None:
                        raise WorkspaceError("portal_work_io_disabled", 403)
                    if kind == "submit":
                        admitted = await current(
                            request,
                            s,
                            identity,
                            workspace_id,
                            ticket_id,
                            kind,
                            value,
                            port,
                            lambda checked: execution.claim(
                                *args, catalog=catalog, policy=policy, core_checked=checked
                            ),
                        )
                        # An identical concurrent request may commit before the Core check.
                        if isinstance(admitted, dict):
                            return admitted
                        receipt, inv = admitted
                    else:
                        receipt, inv = await run_in_threadpool(
                            execution.claim, *args, catalog=catalog, policy=policy
                        )
                    if inv is not None:
                        await capture_async(lambda: selected_runtime.invoke(inv, deadline=deadline))
                    return receipt
                if kind == "decide" and value.choice == "approve":
                    return await current(
                        request,
                        s,
                        identity,
                        workspace_id,
                        ticket_id,
                        kind,
                        value,
                        port,
                        lambda checked: work.local_command(
                            *args, catalog=catalog, policy=policy, core_checked=checked
                        ),
                    )
                return await run_in_threadpool(
                    work.local_command, *args, catalog=catalog, policy=policy
                )

            return await execute(request, s, identity, call)

        app.add_api_route(prefix + "/{ticket_id}/" + kind, command, methods=["POST"])

    for kind, model in schema.COMMANDS.items():
        add(kind, model)
