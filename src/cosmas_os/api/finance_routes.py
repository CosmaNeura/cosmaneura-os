"""Separately negotiated private financial HTTP surface, default off."""

import asyncio
import re
import time
from functools import wraps
from uuid import UUID

from fastapi import Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from cosmas_os.api import finance_work_schemas as schema
from cosmas_os.api import vendor_work_schemas as shared
from cosmas_os.application import finance_events, finance_execution
from cosmas_os.application import finance_work as work
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import capture_async, run_in_threadpool
from cosmas_os.finance_models import FinanceWorkRevision

UUID_PATH = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
ROOT = rf"/workspaces/{UUID_PATH}/finance-work"
PRIVATE = re.compile(
    rf"{ROOT}(?:/(?:options|resolve|{UUID_PATH}(?:/(?:decide|withdraw|submit|reconcile|result|verify|observations))?))?"
)
EVENT = re.compile(rf"/finance-events/stripe/{UUID_PATH}")
SAFE_ERRORS = {
    "invalid_finance_request",
    "finance_contract_required",
    "finance_work_unavailable",
    "finance_unavailable",
    "finance_feature_disabled",
    "finance_source_changed",
    "finance_selection_changed",
    "finance_idempotency_conflict",
    "finance_revision_changed",
    "finance_history_limit",
    "finance_private_text_forbidden",
    "finance_approval_expired",
    "finance_submit_already_claimed",
    "finance_original_account_unavailable",
    "finance_reference_unavailable",
    "finance_read_in_progress",
    "finance_evidence_changed",
    "finance_result_changed",
    "finance_exception_unresolved",
}


def failure(code, status):
    if code not in SAFE_ERRORS:
        code = (
            "finance_work_unavailable"
            if status in {401, 403, 404}
            else "invalid_finance_request"
            if status in {400, 413, 422}
            else "finance_unavailable"
        )
    return JSONResponse(
        {"contract_version": 1, "error": {"code": code}},
        status_code=status,
        headers={"Cache-Control": "no-store", "X-Cosmas-Finance-Error": "1"},
    )


def finance_errors(endpoint):
    @wraps(endpoint)
    async def wrapped(*args, **kwargs):
        try:
            return await endpoint(*args, **kwargs)
        except ws.WorkspaceError as exc:
            # Keep approved finance errors inside this closed protocol instead
            # of the application's generic workspace exception response.
            return failure(exc.code, exc.status)

    return wrapped


async def command(request, model, maximum=2048):
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        work.error("invalid_finance_request", 400)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > maximum:
            work.error("invalid_finance_request", 413)
        data.extend(chunk)
    try:
        return shared.read_json(bytes(data), model, maximum)
    except (ValueError, UnicodeError, RecursionError):
        work.error("invalid_finance_request", 400)


def install(
    app,
    *,
    get_session,
    identity_dependency,
    policy_dependency,
    execution_factory_dependency,
    event_route_dependency,
    core_connection,
    current_core_note,
    reauthenticate,
    session_factory,
):
    @app.middleware("http")
    async def boundary(request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        private, event = (
            bool(PRIVATE.fullmatch(request.url.path)),
            bool(EVENT.fullmatch(request.url.path)),
        )
        values = request.headers.getlist("x-cosmas-finance-contract")
        if values and not private:
            return failure("finance_contract_required", 426)
        if not private and not event:
            return await call_next(request)
        if private and values != ["1"]:
            return failure("finance_contract_required", 426)
        pairs = request.query_params.multi_items()
        paged = request.method == "GET" and (
            request.url.path.endswith("/finance-work") or request.url.path.endswith("/observations")
        )
        if pairs and (
            not paged
            or len(pairs) != 1
            or pairs[0][0] != "cursor"
            or not 1 <= len(pairs[0][1]) <= 512
        ):
            return failure("invalid_finance_request", 400)
        seconds = 10 if event else 30
        request.state.finance_deadline = time.monotonic() + seconds
        try:
            async with asyncio.timeout(seconds):
                result = await call_next(request)
            result.headers["Cache-Control"] = "no-store"
            if result.status_code >= 400 and result.headers.get("x-cosmas-finance-error") != "1":
                result = failure(
                    "invalid_finance_request"
                    if result.status_code in {400, 413, 422}
                    else "finance_work_unavailable"
                    if result.status_code in {401, 403, 404}
                    else "finance_unavailable",
                    result.status_code,
                )
            if "x-cosmas-finance-error" in result.headers:
                del result.headers["x-cosmas-finance-error"]
            return result
        except ws.WorkspaceError as exc:
            return failure(exc.code, exc.status)
        except (TimeoutError, ValueError, SQLAlchemyError):
            return failure("finance_unavailable", 503)

    def fence(request, s, identity):
        def check():
            if time.monotonic() >= request.state.finance_deadline:
                work.error("finance_unavailable", 503)
            reauthenticate(request, s, identity)

        s.info["finance_final_authority"] = check
        return check

    async def run(request, s, identity, apply):
        check = fence(request, s, identity)
        try:
            result = await run_in_threadpool(apply)
            await run_in_threadpool(check)
            return result
        finally:
            s.info.pop("finance_final_authority", None)

    async def current(request, s, identity, wid, tid, kind, body, port, apply):
        check = fence(request, s, identity)

        def discover():
            w = work.owner(s, identity.box_id, identity.principal_id, str(wid))
            previous, _ = work.receipt(s, w, identity.principal_id, kind, body)
            if previous:
                if tid and previous.ticket_id != str(tid):
                    work.error("finance_idempotency_conflict")
                return True, None
            if kind == "propose":
                return False, body.source.note_id
            r = s.get(FinanceWorkRevision, body.revision_id)
            if r is None or (r.workspace_id, r.owner_id, r.ticket_id) != (
                str(wid),
                identity.principal_id,
                str(tid),
            ):
                work.error("finance_work_unavailable", 404)
            return False, r.note_id

        try:
            replay, note_id = await run_in_threadpool(discover)
            await run_in_threadpool(s.rollback)
            result = (
                await run_in_threadpool(apply, None)
                if replay
                else await current_core_note(
                    request, wid, s, identity, port, apply, note_id=note_id
                )
            )
            await run_in_threadpool(check)
            return result
        finally:
            s.info.pop("finance_final_authority", None)

    @app.get("/workspaces/{workspace_id}/finance-work/options")
    @finance_errors
    async def options(
        request: Request,
        workspace_id: UUID,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        policy=Depends(policy_dependency),
    ):
        return await run(
            request,
            s,
            identity,
            lambda: work.options(
                s, identity.box_id, identity.principal_id, str(workspace_id), policy=policy
            ),
        )

    @app.get("/workspaces/{workspace_id}/finance-work")
    @finance_errors
    async def catalog(
        request: Request,
        workspace_id: UUID,
        cursor: str | None = None,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
    ):
        return await run(
            request,
            s,
            identity,
            lambda: work.catalog(
                s, identity.box_id, identity.principal_id, str(workspace_id), cursor
            ),
        )

    @app.get("/workspaces/{workspace_id}/finance-work/{ticket_id}")
    @finance_errors
    async def detail(
        request: Request,
        workspace_id: UUID,
        ticket_id: UUID,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
    ):
        return await run(
            request,
            s,
            identity,
            lambda: work.detail(
                s, identity.box_id, identity.principal_id, str(workspace_id), str(ticket_id)
            ),
        )

    @app.get("/workspaces/{workspace_id}/finance-work/{ticket_id}/observations")
    @finance_errors
    async def observations(
        request: Request,
        workspace_id: UUID,
        ticket_id: UUID,
        cursor: str | None = None,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
    ):
        return await run(
            request,
            s,
            identity,
            lambda: work.observations(
                s, identity.box_id, identity.principal_id, str(workspace_id), str(ticket_id), cursor
            ),
        )

    @app.post("/workspaces/{workspace_id}/finance-work")
    @finance_errors
    async def propose(
        request: Request,
        workspace_id: UUID,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        policy=Depends(policy_dependency),
        port=Depends(core_connection),
    ):
        body = await command(request, schema.FinanceProposal, 16384)
        return await current(
            request,
            s,
            identity,
            workspace_id,
            None,
            "propose",
            body,
            port,
            lambda checked: work.propose(
                s,
                identity.box_id,
                identity.principal_id,
                str(workspace_id),
                body,
                policy=policy,
                core_checked=checked,
            ),
        )

    @app.post("/workspaces/{workspace_id}/finance-work/resolve")
    @finance_errors
    async def resolve(
        request: Request,
        workspace_id: UUID,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
    ):
        body = await command(request, schema.FinanceResolve)
        return await run(
            request,
            s,
            identity,
            lambda: work.resolve(
                s, identity.box_id, identity.principal_id, str(workspace_id), body
            ),
        )

    @app.post("/workspaces/{workspace_id}/finance-work/{ticket_id}/decide")
    @finance_errors
    async def decide(
        request: Request,
        workspace_id: UUID,
        ticket_id: UUID,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        policy=Depends(policy_dependency),
        port=Depends(core_connection),
    ):
        body = await command(request, schema.FinanceDecision)
        return await current(
            request,
            s,
            identity,
            workspace_id,
            ticket_id,
            "decide",
            body,
            port,
            lambda checked: work.decide(
                s,
                identity.box_id,
                identity.principal_id,
                str(workspace_id),
                str(ticket_id),
                body,
                policy=policy,
                core_checked=checked,
            ),
        )

    def local_route(kind, model, action, maximum=2048):
        async def endpoint(
            request: Request,
            workspace_id: UUID,
            ticket_id: UUID,
            s=Depends(get_session),
            identity=Depends(identity_dependency),
        ):
            body = await command(request, model, maximum)
            return await run(
                request,
                s,
                identity,
                lambda: action(
                    s,
                    identity.box_id,
                    identity.principal_id,
                    str(workspace_id),
                    str(ticket_id),
                    body,
                ),
            )

        app.add_api_route(
            "/workspaces/{workspace_id}/finance-work/{ticket_id}/" + kind,
            finance_errors(endpoint),
            methods=["POST"],
        )

    local_route("withdraw", shared.BoundCommand, work.withdraw)
    local_route("result", schema.FinanceResult, work.record_result, 16384)
    local_route("verify", schema.FinanceVerify, work.verify)

    def provider_route(kind):
        async def endpoint(
            request: Request,
            workspace_id: UUID,
            ticket_id: UUID,
            s=Depends(get_session),
            identity=Depends(identity_dependency),
            policy=Depends(policy_dependency),
            port=Depends(core_connection),
            factory=Depends(execution_factory_dependency),
        ):
            body = await command(request, shared.BoundCommand)

            def replay_only():
                w = work.owner(s, identity.box_id, identity.principal_id, str(workspace_id))
                old, _ = work.receipt(s, w, identity.principal_id, kind, body)
                if old and old.ticket_id != str(ticket_id):
                    work.error("finance_idempotency_conflict")
                return work.response(s, old) if old else None

            replay = await run(request, s, identity, replay_only)
            if replay is not None:
                return replay
            await run_in_threadpool(s.rollback)
            if factory is None:
                work.error("finance_feature_disabled", 403)

            async def identity_current():
                if time.monotonic() >= request.state.finance_deadline:
                    return False
                try:
                    with session_factory() as auth_session:
                        await run_in_threadpool(reauthenticate, request, auth_session, identity)
                    return True
                except Exception:
                    return False

            runtime = factory(identity_current)
            from cosmas_os.application.finance_settings_execution import FinanceSettingsExecution

            if (
                type(runtime) not in {finance_execution.FinanceExecution, FinanceSettingsExecution}
                or runtime.policy != policy
            ):
                work.error("finance_unavailable", 503)
            if kind == "submit":
                receipt, invocation = await current(
                    request,
                    s,
                    identity,
                    workspace_id,
                    ticket_id,
                    "submit",
                    body,
                    port,
                    lambda checked: finance_execution.claim_submit(
                        s,
                        identity.box_id,
                        identity.principal_id,
                        str(workspace_id),
                        str(ticket_id),
                        body,
                        policy=policy,
                        core_checked=checked,
                    ),
                )
            else:
                receipt, invocation = await run(
                    request,
                    s,
                    identity,
                    lambda: finance_execution.claim_read(
                        s,
                        identity.box_id,
                        identity.principal_id,
                        str(workspace_id),
                        str(ticket_id),
                        body,
                        policy=policy,
                    ),
                )
            await run_in_threadpool(s.rollback)
            if invocation is not None:
                await capture_async(lambda: runtime.invoke(invocation, deadline=request.state.finance_deadline))
            await run_in_threadpool(reauthenticate, request, s, identity)
            return receipt

        app.add_api_route(
            "/workspaces/{workspace_id}/finance-work/{ticket_id}/" + kind,
            finance_errors(endpoint),
            methods=["POST"],
        )

    provider_route("submit")
    provider_route("reconcile")

    @app.post("/finance-events/stripe/{route_id}")
    @finance_errors
    async def event(
        request: Request,
        route_id: UUID,
        s=Depends(get_session),
        policy=Depends(policy_dependency),
        lookup=Depends(event_route_dependency),
    ):
        if not policy.events_enabled or lookup is None or EVENT.fullmatch(request.url.path) is None:
            work.error("finance_work_unavailable", 404)
        route = lookup(str(route_id))
        if type(route) is not finance_events.FinanceEventRoute or route.route_id != str(route_id):
            work.error("finance_work_unavailable", 404)
        signatures = request.headers.getlist("stripe-signature")
        if len(signatures) != 1:
            work.error("invalid_finance_request", 400)
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 1048576:
                work.error("invalid_finance_request", 413)
            raw.extend(chunk)

        def check():
            if time.monotonic() >= request.state.finance_deadline:
                work.error("finance_unavailable", 503)

        s.info["finance_final_authority"] = check
        try:
            return await run_in_threadpool(
                finance_events.ingest, s, route, bytes(raw), signatures[0], policy=policy
            )
        finally:
            s.info.pop("finance_final_authority", None)
