"""Bounded authenticated inbox surface; runtime installation is explicit/default closed."""

import asyncio

from fastapi import Depends
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from cosmas_os.api import fax_inbound_schemas as schema
from cosmas_os.application import fax_inbound as ledger
from cosmas_os.application import fax_inbound_source as source
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.ports.fax_inbound import bounded_json

HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}


def register(app, get_session, identity_dependency, *, execution_dependency, reauthenticate):
    async def execute(request, session, identity, runtime, call, *, provider=False):
        try:
            if request.query_params or request.headers.getlist("x-cosmas-fax-inbound") != ["1"]:
                ledger.fail("fax_inbound_client_update_required", 426)
            async with asyncio.timeout(45):
                await run_in_threadpool(reauthenticate, request, session, identity)
                await run_in_threadpool(
                    ledger.owner, session, identity.box_id, identity.principal_id
                )
                if runtime is None or runtime.enabled() is not True:
                    ledger.fail("fax_inbound_not_configured", 409)
                if provider:
                    session.rollback()
                    result = await call()
                else:
                    result = await run_in_threadpool(call)
                await run_in_threadpool(reauthenticate, request, session, identity)
                if isinstance(result, bytes):
                    return Response(
                        result,
                        media_type="application/pdf",
                        headers={
                            **HEADERS,
                            "Content-Disposition": 'attachment; filename="received-fax.pdf"',
                        },
                    )
                return JSONResponse(result, headers=HEADERS)
        except WorkspaceError as exc:
            session.rollback()
            return JSONResponse({"error": exc.code}, status_code=exc.status, headers=HEADERS)
        except (Exception, asyncio.CancelledError):
            session.rollback()
            return JSONResponse(
                {"error": "fax_inbound_unavailable"}, status_code=503, headers=HEADERS
            )

    async def body(request, model, *, limit=8192):
        if request.headers.getlist("content-type") != [
            "application/json"
        ] or request.headers.getlist("content-encoding"):
            ledger.fail("fax_inbound_request_invalid", 400)
        data = bytearray()
        async for part in request.stream():
            if len(data) + len(part) > limit:
                ledger.fail("fax_inbound_request_too_large", 413)
            data.extend(part)
        try:
            return model.model_validate(bounded_json(bytes(data)))
        except Exception:
            ledger.fail("fax_inbound_request_invalid", 400)

    # Use Request explicitly so FastAPI does not mistake it for a query field.
    from uuid import UUID

    from starlette.requests import Request

    @app.post("/workspaces/{workspace_id}/fax-inbound-source")
    async def review_source(
        workspace_id: UUID,
        request: Request,
        session=Depends(get_session),
        identity=Depends(identity_dependency),
        runtime=Depends(execution_dependency),
    ):
        try:
            value = await body(request, source.FaxSourceReviewCommand, limit=65536)
        except WorkspaceError as exc:
            return JSONResponse({"error": exc.code}, status_code=exc.status, headers=HEADERS)
        return await execute(request, session, identity, runtime,
            lambda: source.select_review(session, identity.box_id, identity.principal_id,
                str(workspace_id), expected=value.expected_revision, key=value.idempotency_key,
                **value.model_dump(exclude={"expected_revision", "idempotency_key"}),
                reauthenticate=lambda: reauthenticate(request, session, identity)))

    @app.post("/workspaces/{workspace_id}/fax-inbound-source/resolve")
    async def resolve_source(
        workspace_id: UUID,
        request: Request,
        session=Depends(get_session),
        identity=Depends(identity_dependency),
        runtime=Depends(execution_dependency),
    ):
        try:
            value = await body(request, schema.Resolve, limit=2048)
        except WorkspaceError as exc:
            return JSONResponse({"error": exc.code}, status_code=exc.status, headers=HEADERS)
        return await execute(request, session, identity, runtime,
            lambda: source.resolve_review(session, identity.box_id, identity.principal_id,
                str(workspace_id), key=value.idempotency_key))

    @app.get("/fax-inbound")
    async def status(
        request: Request,
        session=Depends(get_session),
        identity=Depends(identity_dependency),
        runtime=Depends(execution_dependency),
    ):
        def read():
            from sqlalchemy import select

            from cosmas_os.fax_inbound_models import FaxInboundGrant

            grants = session.scalars(
                select(FaxInboundGrant)
                .where(
                    FaxInboundGrant.box_id == identity.box_id,
                    FaxInboundGrant.owner_id == identity.principal_id,
                )
                .order_by(FaxInboundGrant.reviewed_at.desc())
                .limit(100)
            ).all()
            installed = [
                i
                for i in runtime.installations
                if str(i.selection.box_id) == identity.box_id
                and str(i.selection.owner_id) == identity.principal_id
            ]
            return {
                "contract_version": 1,
                "installations": [
                    {
                        "connection_id": str(i.selection.connection_id),
                        "label": i.label,
                        "vendor": i.selection.vendor,
                        "metadata_available": runtime.current(i),
                        "image_available": i.image_enabled and runtime.current(i),
                        "image_block_reason": "download_host_unverified"
                        if i.selection.vendor == "spruce"
                        else None,
                    }
                    for i in installed
                ],
                "grants": [
                    {
                        "grant_id": g.id,
                        "label": g.label,
                        "image_enabled": g.image_enabled,
                        "expires_at": g.expires_at.isoformat(),
                        "state": "revoked"
                        if g.revoked_at
                        else "expired"
                        if g.expires_at <= ledger.now(session)
                        else "granted"
                        if runtime.current(ledger.installation(g.installation))
                        else "installation_changed",
                    }
                    for g in grants
                ],
            }

        return await execute(request, session, identity, runtime, read)

    def endpoint(path, model, action, provider=False):
        async def command(
            request: Request,
            session=Depends(get_session),
            identity=Depends(identity_dependency),
            runtime=Depends(execution_dependency),
        ):
            try:
                command = await body(request, model)
            except WorkspaceError as exc:
                return JSONResponse({"error": exc.code}, status_code=exc.status, headers=HEADERS)

            async def provider_call():
                with ledger.public_command(command.model_dump(mode="json")):
                    return await action(session, identity, runtime, command)

            def local_call():
                with ledger.public_command(command.model_dump(mode="json")):
                    return action(session, identity, runtime, command)

            response = await execute(
                request,
                session,
                identity,
                runtime,
                provider_call if provider else local_call,
                provider=provider,
            )
            if response.status_code == 200:
                import json

                result = json.loads(bytes(response.body))
                if model is not schema.Resolve:
                    result["public_request_sha256"] = ledger.commitment(
                        command.model_dump(mode="json")
                    )
                result.pop("receipt_sha256", None)
                result["receipt_sha256"] = ledger.commitment(result)
                return JSONResponse(result, headers=HEADERS)
            return response

        app.add_api_route(
            path,
            command,
            methods=["POST"],
            openapi_extra={
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": model.model_json_schema()}},
                }
            },
        )

    def grant(s, identity, runtime, c):
        matches = [
            i
            for i in runtime.installations
            if str(i.selection.connection_id) == c.connection_id
            and str(i.selection.box_id) == identity.box_id
            and str(i.selection.owner_id) == identity.principal_id
        ]
        if len(matches) != 1:
            ledger.fail("fax_inbound_installation_unavailable", 404)
        return ledger.grant(
            s,
            identity.box_id,
            identity.principal_id,
            matches[0],
            key=c.idempotency_key,
            reviewed_account=c.reviewed_account,
            image_enabled=c.image_enabled,
            expires_at=c.expires_at,
            current=runtime.current,
        )

    endpoint("/fax-inbound/grant", schema.Grant, grant)
    endpoint(
        "/fax-inbound/revoke",
        schema.Revoke,
        lambda s, i, r, c: ledger.revoke(
            s, i.box_id, i.principal_id, c.grant_id, key=c.idempotency_key
        ),
    )
    endpoint(
        "/fax-inbound/observe",
        schema.Observe,
        lambda s, i, r, c: r.observe(i.box_id, i.principal_id, c),
        True,
    )
    endpoint(
        "/fax-inbound/propose",
        schema.Propose,
        lambda s, i, r, c: ledger.propose(
            s,
            i.box_id,
            i.principal_id,
            key=c.idempotency_key,
            **c.model_dump(exclude={"idempotency_key"}),
            current=r.current,
        ),
    )
    endpoint(
        "/fax-inbound/decide",
        schema.Decide,
        lambda s, i, r, c: ledger.decide(
            s,
            i.box_id,
            i.principal_id,
            key=c.idempotency_key,
            **c.model_dump(exclude={"idempotency_key"}),
            current=r.current,
        ),
    )
    endpoint(
        "/fax-inbound/acquire",
        schema.Acquire,
        lambda s, i, r, c: r.acquire(i.box_id, i.principal_id, c),
        True,
    )
    endpoint(
        "/fax-inbound/resolve",
        schema.Resolve,
        lambda s, i, r, c: ledger.resolve(
            s, i.box_id, i.principal_id, key=c.idempotency_key, current=r.current
        ),
    )

    @app.get("/fax-inbound/proposal/{ticket_id}/{revision_id}")
    async def proposal(
        ticket_id: str,
        revision_id: str,
        request: Request,
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
                ticket_id,
                revision_id,
                current=runtime.current,
            ),
        )

    @app.get("/fax-inbound/document/{operation_id}")
    async def document(
        operation_id: str,
        request: Request,
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
                operation_id,
                current=runtime.current,
            ),
        )
