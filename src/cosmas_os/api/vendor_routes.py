"""Closed vendor HTTP boundary, including whole-request deadlines and raw PDFs."""

import asyncio
import re
import time
from typing import get_args
from uuid import UUID

from fastapi import Depends
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from cosmas_os.api import vendor_retirement_schemas
from cosmas_os.api import vendor_work_schemas as schema
from cosmas_os.application import (
    fax_status,
    vendor_artifacts,
    vendor_events,
    vendor_execution,
    vendor_preparation_retirement,
    vendor_retirement,
    vendor_settings,
    vendor_settings_admission,
    vendor_settings_execution,
    vendor_shared,
    vendor_work,
)
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import capture_async, run_in_threadpool
from cosmas_os.config import settings
from cosmas_os.ports.vendor_artifacts import ArtifactStoreError
from cosmas_os.vendor_models import VendorWorkRevision

UUID_PATH = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
WORK_ROOT = rf"/workspaces/{UUID_PATH}/vendor-work"
ARTIFACT_ROOT = rf"/workspaces/{UUID_PATH}/vendor-artifacts"
PRACTICE_ROOT = rf"/practice-work/{UUID_PATH}"
PRIVATE_PATH = re.compile(
    rf"(?:/workspaces/{UUID_PATH}/vendor-preparations/retire|{WORK_ROOT}(?:/(?:options|resolve|{UUID_PATH}(?:/(?:decide|withdraw|publish|submit|reconcile|observations|status|result|verify|retire))?))?|{ARTIFACT_ROOT}(?:/(?:resolve|{UUID_PATH}/content))?)"
)
SHARED_PATH = re.compile(
    rf"(?:/practice-work|/practice-work/pages/{UUID_PATH}|{PRACTICE_ROOT}(?:/(?:handoffs|result|vendor-command/resolve))?)"
)
SHARED_NEW = re.compile(rf"{PRACTICE_ROOT}/(?:result|vendor-command/resolve)")
EVENT_PATH = re.compile(rf"/vendor-events/(?:spruce|srfax|documo)/{UUID_PATH}")


def failure(code, status=409):
    if status == 409 and code in {"core_note_changed", "capture_notebook_changed"}:
        code = "vendor_source_changed"
    if code not in get_args(schema.ErrorCode):
        code = "vendor_work_unavailable" if status in {401, 403, 404} else "vendor_unavailable"
    return JSONResponse(
        {"contract_version": 1, "error": {"code": code}},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


def negotiated(request, *, required=False):
    values = request.headers.getlist("x-cosmas-vendor-contract")
    if values == ["1"]:
        return True
    if values or required:
        raise ws.WorkspaceError("vendor_contract_required", 426)
    return False


async def read_body(request, maximum):
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise ws.WorkspaceError("invalid_vendor_request", 400)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > maximum:
            raise ws.WorkspaceError("invalid_vendor_request", 413)
        data.extend(chunk)
    return bytes(data)


async def command(request, model, maximum=2048):
    try:
        return schema.read_json(await read_body(request, maximum), model, maximum)
    except (ValueError, UnicodeError, RecursionError):
        raise ws.WorkspaceError("invalid_vendor_request", 400) from None


def empty_installed_catalog():
    return vendor_settings.EMPTY_CATALOG


def install(
    app,
    *,
    get_session,
    identity_dependency,
    core_connection,
    current_core_note,
    execution_factory_dependency,
    artifact_store_dependency,
    event_route_dependency,
    reauthenticate,
    session_factory,
    installed_catalog_dependency=empty_installed_catalog,
):
    def vendor_session(
        session=Depends(get_session), catalog=Depends(installed_catalog_dependency)
    ):
        previous = session.info.get("vendor_managed_selection_guard")

        def guard(w, connection_id, *, mutating=True):
            return vendor_settings_admission.require(
                session, w, connection_id, catalog, mutating=mutating
            )

        session.info["vendor_managed_selection_guard"] = guard
        try:
            yield session
        finally:
            if previous is None:
                session.info.pop("vendor_managed_selection_guard", None)
            else:
                session.info["vendor_managed_selection_guard"] = previous

    @app.middleware("http")
    async def vendor_boundary(request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        private_path = PRIVATE_PATH.fullmatch(path) is not None
        shared_path = SHARED_PATH.fullmatch(path) is not None
        has_vendor = bool(request.headers.getlist("x-cosmas-vendor-contract"))
        new_shared = SHARED_NEW.fullmatch(path) is not None
        event_path = EVENT_PATH.fullmatch(path) is not None
        if has_vendor and not (private_path or shared_path):
            return failure("vendor_contract_required", 426)
        if request.headers.getlist("x-cosmas-artifact-write-key") and not (
            private_path and request.method == "PUT" and path.endswith("/content")
        ):
            return failure("invalid_vendor_request", 400)
        active = private_path or new_shared or has_vendor and shared_path or event_path
        if not active:
            return await call_next(request)
        try:
            if not event_path:
                negotiated(request, required=True)
            if (
                not settings.workspace_available
                or event_path
                and not settings.vendor_events_enabled
            ):
                return failure("vendor_work_unavailable", 404)
            pairs = request.query_params.multi_items()
            paged = request.method == "GET" and (
                path.endswith("/vendor-work") or path.endswith("/observations")
            )
            if pairs and (
                not paged
                or len(pairs) != 1
                or pairs[0][0] != "cursor"
                or not 1 <= len(pairs[0][1]) <= 512
            ):
                return failure("invalid_vendor_request", 400)
            binary = path.endswith("/content") and request.method in {"GET", "PUT"}
            seconds = 10 if event_path else 60 if binary else 30
            request.state.vendor_deadline = time.monotonic() + seconds
            async with asyncio.timeout(seconds):
                response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            # Existing auth/validation handlers must not leak exception/provider
            # details into the closed new protocol.
            if response.status_code >= 400 and response.headers.get("x-cosmas-vendor-error") != "1":
                code = (
                    "invalid_vendor_request"
                    if response.status_code in {400, 413, 422}
                    else "vendor_contract_required"
                    if response.status_code == 426
                    else "vendor_work_unavailable"
                    if response.status_code in {401, 403, 404}
                    else "vendor_unavailable"
                )
                return failure(code, response.status_code)
            if "x-cosmas-vendor-error" in response.headers:
                del response.headers["x-cosmas-vendor-error"]
            return response
        except TimeoutError:
            return failure("vendor_unavailable", 503)
        except ws.WorkspaceError as exc:
            return failure(exc.code, exc.status)
        except (ValueError, SQLAlchemyError):
            return failure("vendor_unavailable", 503)

    def fence(request, session, identity):
        def check():
            if time.monotonic() >= request.state.vendor_deadline:
                raise ws.WorkspaceError("vendor_unavailable", 503)
            reauthenticate(request, session, identity)

        session.info["vendor_final_authority"] = check
        return check

    async def run(request, session, identity, action):
        check = fence(request, session, identity)
        try:
            result = await run_in_threadpool(action)
            await run_in_threadpool(check)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except ws.WorkspaceError as exc:
            result = failure(exc.code, exc.status)
            result.headers["X-Cosmas-Vendor-Error"] = "1"
            return result
        finally:
            session.info.pop("vendor_final_authority", None)

    async def current(request, session, identity, wid, tid, kind, body, port, apply):
        check = fence(request, session, identity)

        def discover():
            w = vendor_work._owner(session, identity.box_id, identity.principal_id, str(wid))
            prior, _ = vendor_work._receipt(session, w, identity.principal_id, kind, body)
            if prior:
                if tid and prior.ticket_id != str(tid):
                    vendor_work.error("vendor_idempotency_conflict")
                return True, None
            if hasattr(body, "source"):
                return False, body.source.note_id
            r = session.get(VendorWorkRevision, body.revision_id)
            if (
                r is None
                or r.workspace_id != str(wid)
                or r.owner_id != identity.principal_id
                or r.ticket_id != str(tid)
            ):
                vendor_work.error("vendor_work_unavailable", 404)
            return False, r.note_id

        try:
            replay, note_id = await run_in_threadpool(discover)
            await run_in_threadpool(session.rollback)
            result = (
                await run_in_threadpool(apply, None)
                if replay
                else await current_core_note(
                    request, wid, session, identity, port, apply, note_id=note_id
                )
            )
            await run_in_threadpool(check)
            return result
        finally:
            session.info.pop("vendor_final_authority", None)

    async def protected(action):
        try:
            return await action()
        except ws.WorkspaceError as exc:
            response = failure(exc.code, exc.status)
            response.headers["X-Cosmas-Vendor-Error"] = "1"
            return response

    @app.post("/vendor-events/{vendor}/{route_id}")
    async def event(
        request: Request,
        vendor: str,
        route_id: UUID,
        session=Depends(vendor_session),
        lookup=Depends(event_route_dependency),
    ):
        async def action():
            if EVENT_PATH.fullmatch(request.url.path) is None or lookup is None:
                vendor_work.error("vendor_work_unavailable", 404)
            route = lookup(vendor, str(route_id))
            if (
                type(route) is not vendor_events.EventRoute
                or route.vendor != vendor
                or route.route_id != str(route_id)
            ):
                vendor_work.error("vendor_work_unavailable", 404)
            signatures = request.headers.getlist("x-spruce-signature")
            if vendor == "spruce" and len(signatures) != 1:
                vendor_work.error("invalid_vendor_request", 400)
            data = bytearray()
            async for chunk in request.stream():
                if len(data) + len(chunk) > 1048576:
                    vendor_work.error("invalid_vendor_request", 413)
                data.extend(chunk)

            def check():
                if time.monotonic() >= request.state.vendor_deadline:
                    vendor_work.error("vendor_unavailable", 503)

            session.info["vendor_final_authority"] = check
            try:
                result = await run_in_threadpool(
                    vendor_events.ingest,
                    session,
                    route,
                    bytes(data),
                    signature=signatures[0] if signatures else None,
                )
                check()
                return JSONResponse(result, headers={"Cache-Control": "no-store"})
            finally:
                session.info.pop("vendor_final_authority", None)

        return await protected(action)

    @app.get("/workspaces/{workspace_id}/vendor-work/options")
    async def options(
        request: Request,
        workspace_id: UUID,
        session=Depends(vendor_session),
        identity=Depends(identity_dependency),
    ):
        return await run(
            request,
            session,
            identity,
            lambda: vendor_work.options(
                session, identity.box_id, identity.principal_id, str(workspace_id)
            ),
        )

    @app.get("/workspaces/{workspace_id}/vendor-work")
    async def catalog(
        request: Request,
        workspace_id: UUID,
        cursor: str | None = None,
        session=Depends(vendor_session),
        identity=Depends(identity_dependency),
    ):
        return await run(
            request,
            session,
            identity,
            lambda: vendor_work.catalog(
                session, identity.box_id, identity.principal_id, str(workspace_id), cursor
            ),
        )

    @app.post("/workspaces/{workspace_id}/vendor-work")
    async def propose(
        request: Request,
        workspace_id: UUID,
        session=Depends(vendor_session),
        identity=Depends(identity_dependency),
        port=Depends(core_connection),
    ):
        async def action():
            body = await command(request, schema.VendorProposal, 32768)
            return await current(
                request,
                session,
                identity,
                workspace_id,
                None,
                "propose",
                body,
                port,
                lambda checked: vendor_work.propose(
                    session,
                    identity.box_id,
                    identity.principal_id,
                    str(workspace_id),
                    body,
                    core_checked=checked,
                ),
            )

        return await protected(action)

    @app.post("/workspaces/{workspace_id}/vendor-work/resolve")
    async def resolve(
        request: Request,
        workspace_id: UUID,
        session=Depends(vendor_session),
        identity=Depends(identity_dependency),
    ):
        async def action():
            body = await command(request, schema.VendorResolve)
            return await run(
                request,
                session,
                identity,
                lambda: vendor_work.resolve(
                    session, identity.box_id, identity.principal_id, str(workspace_id), body
                ),
            )

        return await protected(action)

    @app.post("/workspaces/{workspace_id}/vendor-preparations/retire")
    async def retire_preparation(
        request: Request,
        workspace_id: UUID,
        session=Depends(vendor_session),
        identity=Depends(identity_dependency),
    ):
        async def action():
            body = await command(request, vendor_retirement_schemas.VendorPreparationRetire, 33792)
            return await run(request, session, identity, lambda: vendor_preparation_retirement.retire(
                session, identity.box_id, identity.principal_id, str(workspace_id), body
            ))
        return await protected(action)

    @app.post("/workspaces/{workspace_id}/vendor-work/{ticket_id}/retire")
    async def retire(
        request: Request,
        workspace_id: UUID,
        ticket_id: UUID,
        session=Depends(vendor_session),
        identity=Depends(identity_dependency),
    ):
        async def action():
            body = await command(request, vendor_retirement_schemas.VendorRetire, 4096)
            return await run(request, session, identity, lambda: vendor_retirement.retire(
                session, identity.box_id, identity.principal_id, str(workspace_id), str(ticket_id), body
            ))
        return await protected(action)

    @app.get("/workspaces/{workspace_id}/vendor-work/{ticket_id}")
    async def detail(
        request: Request,
        workspace_id: UUID,
        ticket_id: UUID,
        session=Depends(vendor_session),
        identity=Depends(identity_dependency),
    ):
        return await run(
            request,
            session,
            identity,
            lambda: vendor_work.detail(
                session, identity.box_id, identity.principal_id, str(workspace_id), str(ticket_id)
            ),
        )

    @app.get("/workspaces/{workspace_id}/vendor-work/{ticket_id}/status")
    async def saved_fax_status(request: Request, workspace_id: UUID, ticket_id: UUID,
                               session=Depends(vendor_session), identity=Depends(identity_dependency)):
        return await run(request, session, identity, lambda: fax_status.read(
            session, identity.box_id, identity.principal_id, str(workspace_id), str(ticket_id)))

    @app.get("/workspaces/{workspace_id}/vendor-work/{ticket_id}/observations")
    async def observations(
        request: Request,
        workspace_id: UUID,
        ticket_id: UUID,
        cursor: str | None = None,
        session=Depends(vendor_session),
        identity=Depends(identity_dependency),
    ):
        return await run(
            request,
            session,
            identity,
            lambda: vendor_work.observations(
                session,
                identity.box_id,
                identity.principal_id,
                str(workspace_id),
                str(ticket_id),
                cursor,
            ),
        )

    @app.post("/workspaces/{workspace_id}/vendor-work/{ticket_id}/decide")
    async def decide(
        request: Request,
        workspace_id: UUID,
        ticket_id: UUID,
        session=Depends(vendor_session),
        identity=Depends(identity_dependency),
        port=Depends(core_connection),
    ):
        async def action():
            body = await command(request, schema.VendorDecision)

            def apply(checked):
                return vendor_work.decide(
                    session,
                    identity.box_id,
                    identity.principal_id,
                    str(workspace_id),
                    str(ticket_id),
                    body,
                    core_checked=checked,
                )

            if body.choice == "reject":
                return await run(request, session, identity, lambda: apply(None))
            return await current(
                request, session, identity, workspace_id, ticket_id, "decide", body, port, apply
            )

        return await protected(action)

    def local_route(kind, model, function, maximum=2048):
        async def endpoint(
            request: Request,
            workspace_id: UUID,
            ticket_id: UUID,
            session=Depends(vendor_session),
            identity=Depends(identity_dependency),
        ):
            async def action():
                body = await command(request, model, maximum)
                return await run(
                    request,
                    session,
                    identity,
                    lambda: function(
                        session,
                        identity.box_id,
                        identity.principal_id,
                        str(workspace_id),
                        str(ticket_id),
                        body,
                    ),
                )

            return await protected(action)

        app.add_api_route(
            "/workspaces/{workspace_id}/vendor-work/{ticket_id}/" + kind, endpoint, methods=["POST"]
        )

    local_route("withdraw", schema.BoundCommand, vendor_work.withdraw)
    local_route("publish", schema.VendorPublication, vendor_work.publish)
    local_route("result", schema.VendorResult, vendor_work.record_result, 16384)
    local_route("verify", schema.VendorVerify, vendor_work.verify)

    def provider_route(kind):
        async def endpoint(
            request: Request,
            workspace_id: UUID,
            ticket_id: UUID,
            session=Depends(vendor_session),
            identity=Depends(identity_dependency),
            port=Depends(core_connection),
            factory=Depends(execution_factory_dependency),
        ):
            async def action():
                body = await command(request, schema.BoundCommand)

                def replay_only():
                    w = vendor_work._owner(
                        session, identity.box_id, identity.principal_id, str(workspace_id)
                    )
                    old, _ = vendor_work._receipt(session, w, identity.principal_id, kind, body)
                    if old and old.ticket_id != str(ticket_id):
                        vendor_work.error("vendor_idempotency_conflict")
                    return vendor_work.command_response(session, old) if old else None

                replay = await run_in_threadpool(replay_only)
                if replay is not None:
                    await run_in_threadpool(reauthenticate, request, session, identity)
                    return replay
                await run_in_threadpool(session.rollback)
                if factory is None:
                    vendor_work.error("vendor_feature_disabled", 403)

                async def identity_current():
                    try:
                        if time.monotonic() >= request.state.vendor_deadline:
                            return False
                        with session_factory() as auth_session:
                            await run_in_threadpool(reauthenticate, request, auth_session, identity)
                        return True
                    except Exception:
                        return False

                runtime = factory(identity_current)
                if type(runtime) not in {
                    vendor_execution.VendorExecution,
                    vendor_settings_execution.VendorSettingsExecution,
                }:
                    vendor_work.error("vendor_unavailable", 503)

                def runtime_admission():
                    w = vendor_work._owner(
                        session, identity.box_id, identity.principal_id,
                        str(workspace_id), writing=True,
                    )
                    previous, _ = vendor_work._receipt(
                        session, w, identity.principal_id, kind, body
                    )
                    if previous is not None:
                        return  # Exact recorded replay never admits new provider I/O.
                    revision = session.get(VendorWorkRevision, body.revision_id)
                    if (
                        revision is None
                        or revision.workspace_id != str(workspace_id)
                        or revision.owner_id != identity.principal_id
                        or revision.ticket_id != str(ticket_id)
                    ):
                        vendor_work.error("vendor_work_unavailable", 404)
                    if not vendor_settings_admission.runtime_matches(
                        session, revision.connection_version_id, runtime
                    ):
                        vendor_work.error("vendor_selection_changed")
                    if type(runtime) is vendor_settings_execution.VendorSettingsExecution:
                        vendor_settings_admission.require(
                            session, w, revision.connection_version_id,
                            runtime.installed_catalog(), mutating=kind == "submit",
                        )

                def apply(checked):
                    runtime_admission()
                    return vendor_execution.claim_submit(
                        session,
                        identity.box_id,
                        identity.principal_id,
                        str(workspace_id),
                        str(ticket_id),
                        body,
                        core_checked=checked,
                    )

                def apply_read():
                    runtime_admission()
                    return vendor_execution.claim_read(
                        session, identity.box_id, identity.principal_id,
                        str(workspace_id), str(ticket_id), body,
                    )

                if kind == "submit":
                    result = await current(
                        request,
                        session,
                        identity,
                        workspace_id,
                        ticket_id,
                        "submit",
                        body,
                        port,
                        apply,
                    )
                else:
                    check = fence(request, session, identity)
                    try:
                        result = await run_in_threadpool(apply_read)
                        await run_in_threadpool(check)
                    finally:
                        session.info.pop("vendor_final_authority", None)
                receipt, invocation = result
                if invocation is not None:
                    await capture_async(lambda: runtime.invoke(invocation, deadline=request.state.vendor_deadline))
                # Saved claim is immutable; remote outcome is read separately.
                await run_in_threadpool(reauthenticate, request, session, identity)
                return receipt

            return await protected(action)

        app.add_api_route(
            "/workspaces/{workspace_id}/vendor-work/{ticket_id}/" + kind, endpoint, methods=["POST"]
        )

    provider_route("submit")
    provider_route("reconcile")

    @app.post("/workspaces/{workspace_id}/vendor-artifacts")
    async def artifact_intent(
        request: Request,
        workspace_id: UUID,
        session=Depends(vendor_session),
        identity=Depends(identity_dependency),
        port=Depends(core_connection),
    ):
        async def action():
            body = await command(request, schema.VendorArtifactIntent)
            return await current(
                request,
                session,
                identity,
                workspace_id,
                None,
                "artifact_intent",
                body,
                port,
                lambda checked: vendor_artifacts.intent(
                    session,
                    identity.box_id,
                    identity.principal_id,
                    str(workspace_id),
                    body,
                    core_checked=checked,
                ),
            )

        return await protected(action)

    @app.post("/workspaces/{workspace_id}/vendor-artifacts/resolve")
    async def artifact_resolve(
        request: Request,
        workspace_id: UUID,
        session=Depends(vendor_session),
        identity=Depends(identity_dependency),
    ):
        async def action():
            body = await command(request, schema.VendorArtifactResolve)
            return await run(
                request,
                session,
                identity,
                lambda: vendor_artifacts.resolve(
                    session, identity.box_id, identity.principal_id, str(workspace_id), body
                ),
            )

        return await protected(action)

    @app.put("/workspaces/{workspace_id}/vendor-artifacts/{artifact_id}/content")
    async def artifact_content(
        request: Request,
        workspace_id: UUID,
        artifact_id: UUID,
        session=Depends(vendor_session),
        identity=Depends(identity_dependency),
        store=Depends(artifact_store_dependency),
    ):
        async def action():
            keys = request.headers.getlist("x-cosmas-artifact-write-key")
            if len(keys) != 1 or request.headers.get("content-type") != "application/pdf":
                vendor_work.error("invalid_vendor_request", 400)
            check = fence(request, session, identity)
            try:
                admission = await run_in_threadpool(
                    vendor_artifacts.begin_content,
                    session,
                    identity.box_id,
                    identity.principal_id,
                    str(workspace_id),
                    str(artifact_id),
                    keys[0],
                    storage_available=store is not None,
                )
                if admission.token is None:
                    await run_in_threadpool(check)
                    return admission.response
                token = admission.token
                limit = token.scope.document.byte_length
                data = bytearray()
                async for chunk in request.stream():
                    if len(data) + len(chunk) > limit:
                        await run_in_threadpool(
                            vendor_artifacts.settle_content, session_factory, token, "input_invalid"
                        )
                        vendor_work.error("artifact_changed", 400)
                    data.extend(chunk)
                await run_in_threadpool(check)

                async def store_and_settle():
                    outcome = await run_in_threadpool(
                        vendor_artifacts.write_content,
                        store,
                        token,
                        bytes(data),
                        deadline=request.state.vendor_deadline,
                    )
                    await run_in_threadpool(
                        vendor_artifacts.settle_content, session_factory, token, outcome
                    )

                task = asyncio.create_task(store_and_settle())
                request.app.state.vendor_local_storage_tasks.add(task)
                task.add_done_callback(request.app.state.vendor_local_storage_tasks.discard)
                await asyncio.shield(task)
                await run_in_threadpool(check)
                metadata = admission.response
                resolved = schema.VendorArtifactResolve(
                    artifact_id=str(artifact_id),
                    command_kind="artifact_content",
                    idempotency_key=keys[0],
                    request_sha256=metadata["request_sha256"],
                )
                return await run_in_threadpool(
                    vendor_artifacts.resolve,
                    session,
                    identity.box_id,
                    identity.principal_id,
                    str(workspace_id),
                    resolved,
                )
            finally:
                session.info.pop("vendor_final_authority", None)

        return await protected(action)

    @app.get("/workspaces/{workspace_id}/vendor-artifacts/{artifact_id}/content")
    async def artifact_preview(
        request: Request,
        workspace_id: UUID,
        artifact_id: UUID,
        session=Depends(vendor_session),
        identity=Depends(identity_dependency),
        store=Depends(artifact_store_dependency),
    ):
        async def action():
            if store is None:
                vendor_work.error("artifact_unavailable", 503)
            check = fence(request, session, identity)
            try:
                token = await run_in_threadpool(
                    vendor_artifacts.preview,
                    session,
                    identity.box_id,
                    identity.principal_id,
                    str(workspace_id),
                    str(artifact_id),
                )
                try:
                    data = await run_in_threadpool(
                        store.read_verified, token.scope, deadline=request.state.vendor_deadline
                    )
                except ArtifactStoreError as exc:
                    if exc.code == "artifact_changed":
                        await run_in_threadpool(
                            vendor_artifacts.quarantine_preview, session_factory, token
                        )
                    vendor_work.error("artifact_unavailable", 503)
                await run_in_threadpool(check)
                exact = await run_in_threadpool(
                    vendor_artifacts.finish_preview,
                    session,
                    identity.box_id,
                    identity.principal_id,
                    str(workspace_id),
                    token,
                    data,
                    deadline=request.state.vendor_deadline,
                )
                return Response(
                    exact,
                    media_type="application/pdf",
                    headers={
                        "Cache-Control": "no-store",
                        "Content-Disposition": "inline; filename=document.pdf",
                    },
                )
            finally:
                session.info.pop("vendor_final_authority", None)

        return await protected(action)

    @app.post("/practice-work/{ticket_id}/result")
    async def staff_result(
        request: Request,
        ticket_id: UUID,
        session=Depends(vendor_session),
        identity=Depends(identity_dependency),
    ):
        async def action():
            body = await command(request, schema.VendorStaffResult, 16384)
            return await run(
                request,
                session,
                identity,
                lambda: vendor_shared.record_result(
                    session, identity.box_id, identity.principal_id, str(ticket_id), body
                ),
            )

        return await protected(action)

    @app.post("/practice-work/{ticket_id}/vendor-command/resolve")
    async def staff_resolve(
        request: Request,
        ticket_id: UUID,
        session=Depends(vendor_session),
        identity=Depends(identity_dependency),
    ):
        async def action():
            body = await command(request, schema.VendorStaffResolve)
            return await run(
                request,
                session,
                identity,
                lambda: vendor_shared.resolve(
                    session, identity.box_id, identity.principal_id, str(ticket_id), body
                ),
            )

        return await protected(action)

    app.state.vendor_local_storage_tasks = set()
    # Shared existing routes call these same helpers for exact new request bodies.
    app.state.vendor_run = run
    app.state.vendor_protected = protected
