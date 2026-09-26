"""Closed owner membership review API. Register before the app's outer CORS layer."""

import asyncio
import re
import time
from uuid import UUID

from fastapi import Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from cosmas_os.api import membership_work_schemas as schema
from cosmas_os.api.membership_retirement_schemas import MembershipRetire
from cosmas_os.api.vendor_work_schemas import read_json
from cosmas_os.application import membership_retirement, membership_saved_evidence
from cosmas_os.application import membership_work as flow
from cosmas_os.application.capture_deadline import run_in_threadpool
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.membership_models import MembershipWork

ROOT = r"/workspaces/[0-9a-f-]{36}/membership-work"
SAFE = {
    "membership_work_unavailable",
    "membership_unavailable",
    "invalid_membership_request",
    "membership_contract_required",
    "membership_feature_disabled",
    "membership_source_changed",
    "membership_evidence_changed",
    "membership_revision_changed",
    "membership_result_changed",
    "membership_exception_unresolved",
    "membership_idempotency_conflict",
    "membership_history_limit",
    "membership_retirement_unavailable",
}


def policy():
    return flow.DEFAULT_POLICY


def no_core_connection():
    return None


def failure(code, status):
    if code not in SAFE:
        code = (
            "membership_work_unavailable" if status in {401, 403, 404} else "membership_unavailable"
        )
    return JSONResponse(
        {"contract_version": 1, "error": {"code": code}},
        status_code=status,
        headers={"Cache-Control": "no-store", "X-Cosmas-Membership-Error": "1"},
    )


def register(
    app,
    get_session,
    identity_dependency,
    *,
    policy_dependency=policy,
    reauthenticate=None,
    core_connection_dependency=no_core_connection,
    current_core_note=None,
):
    @app.middleware("http")
    async def boundary(request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        private = bool(re.fullmatch(ROOT + r"(?:/.*)?", request.url.path))
        values = request.headers.getlist("x-cosmas-membership-contract")
        if values and not private:
            return failure("membership_contract_required", 426)
        if not private:
            return await call_next(request)
        request.state.membership_deadline = time.monotonic() + 15
        if values != ["1"] or request.query_params:
            return failure("membership_contract_required", 426)
        try:
            async with asyncio.timeout(15):
                response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response
        except (TimeoutError, SQLAlchemyError):
            return failure("membership_unavailable", 503)

    async def body(request, model, maximum=8192):
        if request.headers.getlist("content-type") != [
            "application/json"
        ] or request.headers.getlist("content-encoding"):
            flow.error("invalid_membership_request", 400)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > maximum:
                flow.error("invalid_membership_request", 413)
            data.extend(chunk)
        try:
            return read_json(bytes(data), model, maximum=maximum)
        except (ValueError, UnicodeError, RecursionError):
            flow.error("invalid_membership_request", 400)

    async def run(request, s, identity, call):
        def fence():
            if time.monotonic() >= request.state.membership_deadline:
                flow.error("membership_unavailable", 503)
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
                flow.error("membership_work_unavailable", 403)

        s.info["membership_final_authority"] = fence
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
            return failure("membership_unavailable", 503)
        finally:
            s.info.pop("membership_final_authority", None)

    async def apply_current(request, s, identity, wid, tid, kind, value, port, gate):
        def apply(checked):
            if kind == "propose":
                return flow.propose(
                    s,
                    identity.box_id,
                    identity.principal_id,
                    str(wid),
                    value,
                    policy=gate,
                    core_checked=checked,
                )
            return flow.command(
                s,
                identity.box_id,
                identity.principal_id,
                str(wid),
                str(tid),
                kind,
                value,
                policy=gate,
                core_checked=checked,
            )

        def discover():
            w = flow.owner(s, identity.box_id, identity.principal_id, str(wid), policy=gate)
            previous, _ = flow.saved(s, w, kind, value)
            if previous is not None:
                if tid is not None and previous.ticket_id != str(tid):
                    flow.error("membership_idempotency_conflict")
                return None
            if kind == "withdraw":
                return None
            if kind == "propose":
                return value.source.note_id
            r = s.get(MembershipWork, str(tid))
            if r is None or (r.workspace_id, r.owner_id) != (str(wid), identity.principal_id):
                flow.error("membership_work_unavailable", 404)
            return r.note_id

        note_id = await run_in_threadpool(discover)
        await run_in_threadpool(s.rollback)
        if note_id is None or current_core_note is None:
            return await run_in_threadpool(apply, None)
        return await current_core_note(request, wid, s, identity, port, apply, note_id=note_id)

    def add_read(suffix, method, has_ticket=False):
        if has_ticket:

            async def read_ticket(
                request: Request,
                workspace_id: UUID,
                ticket_id: UUID,
                s=Depends(get_session),
                identity=Depends(identity_dependency),
                gate=Depends(policy_dependency),
            ):
                return await run(
                    request,
                    s,
                    identity,
                    lambda: method(
                        s,
                        identity.box_id,
                        identity.principal_id,
                        str(workspace_id),
                        str(ticket_id),
                        policy=gate,
                    ),
                )

            endpoint = read_ticket
        else:

            async def read_list(
                request: Request,
                workspace_id: UUID,
                s=Depends(get_session),
                identity=Depends(identity_dependency),
                gate=Depends(policy_dependency),
            ):
                return await run(
                    request,
                    s,
                    identity,
                    lambda: method(
                        s, identity.box_id, identity.principal_id, str(workspace_id), policy=gate
                    ),
                )

            endpoint = read_list

        app.add_api_route(
            "/workspaces/{workspace_id}/membership-work" + suffix,
            endpoint,
            methods=["GET"],
            name="membership_" + method.__name__,
        )

    add_read("/options", flow.options)
    add_read("", flow.catalog)
    add_read("/{ticket_id}", flow.detail, True)
    add_read("/{ticket_id}/history", flow.history, True)

    @app.get("/workspaces/{workspace_id}/membership-work/{ticket_id}/results/{result_receipt_id}/finance-evidence")
    async def saved_finance_evidence(
        request: Request,
        workspace_id: UUID,
        ticket_id: UUID,
        result_receipt_id: UUID,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        gate=Depends(policy_dependency),
    ):
        return await run(
            request, s, identity,
            lambda: membership_saved_evidence.finance_evidence(
                s, identity.box_id, identity.principal_id, str(workspace_id),
                str(ticket_id), str(result_receipt_id), policy=gate,
            ),
        )

    @app.post("/workspaces/{workspace_id}/membership-work/resolve")
    async def resolve(
        request: Request,
        workspace_id: UUID,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        gate=Depends(policy_dependency),
    ):
        try:
            value = await body(request, schema.Resolve)
        except WorkspaceError as exc:
            return failure(exc.code, exc.status)
        return await run(
            request,
            s,
            identity,
            lambda: flow.resolve(
                s, identity.box_id, identity.principal_id, str(workspace_id), value, policy=gate
            ),
        )

    @app.post("/workspaces/{workspace_id}/membership-work/retire")
    async def retire(
        request: Request,
        workspace_id: UUID,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        gate=Depends(policy_dependency),
    ):
        try:
            value = await body(request, MembershipRetire, maximum=16384)
        except WorkspaceError as exc:
            return failure(exc.code, exc.status)
        return await run(
            request,
            s,
            identity,
            lambda: membership_retirement.retire(
                s, identity.box_id, identity.principal_id, str(workspace_id), value, policy=gate
            ),
        )

    def add_command(kind):
        if kind == "propose":

            async def proposal_endpoint(
                request: Request,
                workspace_id: UUID,
                s=Depends(get_session),
                identity=Depends(identity_dependency),
                gate=Depends(policy_dependency),
                port=Depends(core_connection_dependency),
            ):
                try:
                    value = await body(request, schema.Proposal)
                except WorkspaceError as exc:
                    return failure(exc.code, exc.status)

                async def call():
                    return await apply_current(
                        request, s, identity, workspace_id, None, kind, value, port, gate
                    )

                return await run(request, s, identity, call)

            endpoint = proposal_endpoint
            suffix = ""
        else:

            async def bound_endpoint(
                request: Request,
                workspace_id: UUID,
                ticket_id: UUID,
                s=Depends(get_session),
                identity=Depends(identity_dependency),
                gate=Depends(policy_dependency),
                port=Depends(core_connection_dependency),
            ):
                try:
                    value = await body(request, schema.COMMANDS[kind])
                except WorkspaceError as exc:
                    return failure(exc.code, exc.status)

                async def call():
                    return await apply_current(
                        request, s, identity, workspace_id, ticket_id, kind, value, port, gate
                    )

                return await run(request, s, identity, call)

            endpoint = bound_endpoint
            suffix = "/{ticket_id}/" + kind
        app.add_api_route(
            "/workspaces/{workspace_id}/membership-work" + suffix,
            endpoint,
            methods=["POST"],
            name="membership_" + kind,
        )

    for kind in schema.COMMANDS:
        add_command(kind)
