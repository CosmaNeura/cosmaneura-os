"""Authenticated private inbound eFax commands and DB-only recovery."""

import asyncio
import re
import time
from uuid import UUID

from fastapi import Depends
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from cosmas_os.adapters.vendor_connectors.efax_inbound_json import parse_image_json
from cosmas_os.api import efax_inbound_schemas as schema
from cosmas_os.application import efax_inbound as ledger
from cosmas_os.application import efax_inbound_source as source
from cosmas_os.application.workspace import WorkspaceError


def unavailable(request):
    return None


def register(
    app, get_session, identity_dependency, *, execution_dependency=unavailable, reauthenticate=None
):
    def failure(exc, *, mark=True):
        code = exc.code if exc.code.startswith("efax_inbound_") else "efax_inbound_unavailable"
        if exc.status == 404:
            code = "efax_inbound_not_found"
        return JSONResponse(
            {"error": {"code": code}}, status_code=exc.status,
            headers={"Cache-Control": "no-store", **({"X-Cosmas-EFax-Private-Error": "1"} if mark else {})}
        )

    @app.middleware("http")
    async def boundary(request, call_next):
        private = (request.url.path == "/efax-inbound" or request.url.path.startswith(
            "/efax-inbound/"
        ) or re.fullmatch(r"/workspaces/[^/]+/efax-inbound-source(?:/resolve)?", request.url.path) is not None)
        if not private or request.method == "OPTIONS":
            return await call_next(request)
        request.state.efax_deadline = time.monotonic() + 45
        try:
            async with asyncio.timeout(45):
                response = await call_next(request)
            if response.status_code >= 400:
                # Authentication and path validation can fail before execute.
                # Keep their status useful to the client while exposing only
                # this private API's closed error shape.
                code = (
                    "efax_inbound_sign_in_required"
                    if response.status_code == 401
                    else "efax_inbound_access_denied"
                    if response.status_code == 403
                    else "efax_inbound_not_found"
                    if response.status_code == 404
                    else "efax_inbound_unavailable"
                )
                if response.status_code in {401, 403, 404, 422}:
                    if response.headers.get("X-Cosmas-EFax-Private-Error") == "1":
                        del response.headers["X-Cosmas-EFax-Private-Error"]
                        response.headers["Cache-Control"] = "no-store"
                        return response
                    return failure(WorkspaceError(code, response.status_code), mark=False)
            if "X-Cosmas-EFax-Private-Error" in response.headers:
                del response.headers["X-Cosmas-EFax-Private-Error"]
            response.headers["Cache-Control"] = "no-store"
            return response
        except (TimeoutError, SQLAlchemyError):
            return failure(WorkspaceError("efax_inbound_unavailable", 503), mark=False)

    def contract(request):
        if request.query_params or request.headers.getlist("x-cosmas-efax-inbound") != ["1"]:
            raise WorkspaceError("efax_inbound_client_update_required", 426)

    async def body(request, model, *, limit=8192):
        contract(request)
        if request.headers.getlist("content-type") != [
            "application/json"
        ] or request.headers.getlist("content-encoding"):
            raise WorkspaceError("efax_inbound_request_invalid", 400)
        data = bytearray()
        async for piece in request.stream():
            if len(data) + len(piece) > limit:
                raise WorkspaceError("efax_inbound_request_too_large", 413)
            data.extend(piece)
        try:
            return model.model_validate(parse_image_json(bytes(data)))
        except Exception:
            raise WorkspaceError("efax_inbound_request_invalid", 400) from None

    def fence(request, session, identity):
        if time.monotonic() >= request.state.efax_deadline:
            raise WorkspaceError("efax_inbound_unavailable", 503)
        session.expire_all()
        if reauthenticate is not None:
            reauthenticate(request, session, identity)
        else:
            current = identity_dependency(
                request=request,
                session=session,
                authorization=request.headers.get("authorization"),
                x_box_id=request.headers.get("x-box-id"),
                x_actor_principal_id=request.headers.get("x-actor-principal-id"),
            )
            if current != identity:
                raise WorkspaceError("efax_inbound_unavailable", 403)

    async def execute(request, session, identity, runtime, call, *, provider=False):
        try:
            contract(request)
            await run_in_threadpool(fence, request, session, identity)
            if provider:
                session.rollback()  # never retain request locks across provider I/O
                if runtime is None:
                    raise WorkspaceError("efax_inbound_not_configured", 409)
                result = await call()
            else:
                result = await run_in_threadpool(call)
            await run_in_threadpool(fence, request, session, identity)
            if isinstance(result, bytes):
                return Response(
                    result,
                    media_type="application/pdf",
                    headers={
                        "Cache-Control": "no-store",
                        "Content-Disposition": "attachment; filename=received-fax.pdf",
                        "X-Content-Type-Options": "nosniff",
                    },
                )
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except WorkspaceError as exc:
            session.rollback()
            return failure(exc)
        except (SQLAlchemyError, ValueError):
            session.rollback()
            return failure(WorkspaceError("efax_inbound_unavailable", 503))

    def current(runtime):
        return runtime.current if runtime is not None else None

    @app.post("/workspaces/{workspace_id}/efax-inbound-source")
    async def review_source(
        request: Request,
        workspace_id: UUID,
        session=Depends(get_session),
        identity=Depends(identity_dependency),
        runtime=Depends(execution_dependency),
    ):
        try:
            value = await body(request, source.EFaxSourceReviewCommand, limit=65536)
        except WorkspaceError as exc:
            return failure(exc)

        def save():
            return source.select_review(
                session, identity.box_id, identity.principal_id, str(workspace_id),
                expected=value.expected_revision, key=value.idempotency_key,
                **value.model_dump(exclude={"expected_revision", "idempotency_key"}),
                reauthenticate=lambda: fence(request, session, identity),
            )

        return await execute(request, session, identity, runtime, save)

    @app.post("/workspaces/{workspace_id}/efax-inbound-source/resolve")
    async def resolve_source(
        request: Request,
        workspace_id: UUID,
        session=Depends(get_session),
        identity=Depends(identity_dependency),
        runtime=Depends(execution_dependency),
    ):
        try:
            value = await body(request, schema.SourceResolve, limit=2048)
        except WorkspaceError as exc:
            return failure(exc)
        return await execute(request, session, identity, runtime,
            lambda: source.resolve_review(session, identity.box_id, identity.principal_id,
                str(workspace_id), key=value.idempotency_key))

    @app.get("/efax-inbound")
    async def status(
        request: Request,
        session=Depends(get_session),
        identity=Depends(identity_dependency),
        runtime=Depends(execution_dependency),
    ):
        def read():
            result = ledger.status(
                session, identity.box_id, identity.principal_id, current=current(runtime)
            )
            result["installations"] = (
                [
                    {
                        "installation_id": str(item.selection.connection_id),
                        "label": item.label,
                        "metadata_available": item.metadata_enabled,
                        "image_available": item.image_enabled,
                    }
                    for item in runtime.installations
                    if (str(item.selection.box_id), str(item.selection.owner_id))
                    == (identity.box_id, identity.principal_id)
                ]
                if runtime
                else []
            )
            return result

        return await execute(request, session, identity, runtime, read)

    @app.get("/efax-inbound/proposals/{ticket_id}")
    async def proposal(
        request: Request,
        ticket_id: UUID,
        session=Depends(get_session),
        identity=Depends(identity_dependency),
        runtime=Depends(execution_dependency),
    ):
        return await execute(
            request,
            session,
            identity,
            runtime,
            lambda: ledger.proposal(
                session,
                identity.box_id,
                identity.principal_id,
                str(ticket_id),
                current=current(runtime),
            ),
        )

    @app.get("/efax-inbound/documents/{operation_id}")
    async def document(
        request: Request,
        operation_id: UUID,
        session=Depends(get_session),
        identity=Depends(identity_dependency),
        runtime=Depends(execution_dependency),
    ):
        return await execute(
            request,
            session,
            identity,
            runtime,
            lambda: ledger.document(
                session,
                identity.box_id,
                identity.principal_id,
                str(operation_id),
                current=current(runtime),
            ),
        )

    def add(kind, model):
        async def command(
            request: Request,
            session=Depends(get_session),
            identity=Depends(identity_dependency),
            runtime=Depends(execution_dependency),
        ):
            try:
                value = await body(request, model)
            except WorkspaceError as exc:
                return failure(exc)
            box, owner = identity.box_id, identity.principal_id

            def local():
                if kind == "resolve":
                    method = (
                        ledger.recover
                        if value.kind == "command"
                        else ledger.resolve_observation
                        if value.kind == "observation"
                        else ledger.resolve_image
                    )
                    return method(
                        session,
                        box,
                        owner,
                        key=value.idempotency_key,
                        **({} if value.kind == "command" else {"current": current(runtime)}),
                    )
                if kind == "revoke":
                    return ledger.revoke_grant(
                        session, box, owner, value.grant_id, key=value.idempotency_key
                    )
                if kind == "grant":
                    item = (
                        next(
                            (
                                x
                                for x in runtime.installations
                                if str(x.selection.connection_id) == value.installation_id
                            ),
                            None,
                        )
                        if runtime
                        else None
                    )
                    return ledger.grant(
                        session,
                        box,
                        owner,
                        item,
                        key=value.idempotency_key,
                        reviewed_account=value.reviewed_account,
                        reviewed_mark_read=value.reviewed_mark_read,
                        image_enabled=value.image_enabled,
                        expires_at=value.expires_at,
                        current=current(runtime),
                    )
                args = value.model_dump(exclude={"idempotency_key"})
                method = ledger.propose_image if kind == "propose" else ledger.decide_image
                return method(
                    session, box, owner, key=value.idempotency_key, current=current(runtime), **args
                )

            provider = kind in {"observe", "acquire"}
            call = (
                (lambda: runtime.observe(box, owner, value))
                if kind == "observe"
                else (lambda: runtime.acquire(box, owner, value))
                if kind == "acquire"
                else local
            )
            return await execute(request, session, identity, runtime, call, provider=provider)

        app.add_api_route("/efax-inbound/" + kind, command, methods=["POST"])

    for kind, model in {
        "grant": schema.Grant,
        "revoke": schema.Revoke,
        "observe": schema.Observe,
        "propose": schema.Propose,
        "decide": schema.Decide,
        "acquire": schema.Acquire,
        "resolve": schema.Resolve,
    }.items():
        add(kind, model)
