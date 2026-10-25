"""Actual authenticated EHR reservation/recovery routes; synthetic provider bridge only."""

import json
import re
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from cosmas_os.adapters.ehr_read_runtime import select_runtime
from cosmas_os.api import ehr_read_schemas as schema
from cosmas_os.api.capture_deadline import CaptureBoundary
from cosmas_os.api.capture_schemas import _unique_object
from cosmas_os.application import ehr_reads, elation_sandbox_installation, model_work
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import run_in_threadpool

PATH = "/connections/ehr/reads"
REVIEW_PATH = re.compile(r"^/workspaces/[0-9a-f-]{36}/ehr-read/review$")
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}


class EhrReadBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] == "http" and scope["method"] != "OPTIONS"
                and (scope["path"] == PATH or REVIEW_PATH.fullmatch(scope["path"]))):
            await CaptureBoundary(self.app, seconds=45, max_response_bytes=12_000_000
                if REVIEW_PATH.fullmatch(scope["path"]) else 131072,
                error_factory=lambda status: JSONResponse({"detail": "ehr_read_unavailable"},
                    status_code=status, headers=HEADERS))(scope, receive, send)
            return
        await self.app(scope, receive, send)


def router(*, runtime, configuration, identity_dependency, session_dependency, workspace_gate, fence):
    routes = APIRouter()

    def service(provider=None):
        port = select_runtime(runtime(), provider or "elation")
        if not configuration().workspace_ehr_read_available or port is None:
            raise ws.WorkspaceError("ehr_read_unavailable", 404)
        return port

    def checked(request):
        if (request.query_params or request.headers.getlist("x-cosmas-ehr-read") != ["1"]
                or request.headers.getlist("content-encoding")):
            raise ws.WorkspaceError("invalid_ehr_read_request", 422)

    def supported_identity(identity):
        if (getattr(identity, "auth_mode", None) != "clerk_jwt"
                or getattr(identity, "external_identity_id", None) is None):
            raise ws.WorkspaceError("ehr_read_unavailable", 404)

    async def decoded(request):
        if (len(request.headers.getlist("authorization")) != 1
                or len(request.headers.getlist("content-type")) != 1
                or request.headers["content-type"].split(";", 1)[0].strip().lower() != "application/json"):
            raise ValueError
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 4096:
                raise ValueError
            raw.extend(chunk)
        return json.loads(raw, object_pairs_hook=_unique_object)

    @routes.post(PATH, dependencies=[Depends(workspace_gate)])
    async def action(request: Request, identity=Depends(identity_dependency), session=Depends(session_dependency)):
        supported_identity(identity)
        checked(request)
        try:
            body = schema.EHR_COMMAND.validate_python(await decoded(request))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ws.WorkspaceError("invalid_ehr_read_request", 422) from None

        def reauthenticate():
            fence(request, session, identity)

        scope = (session, identity.box_id, identity.principal_id, identity.external_identity_id)

        def execute():
            reauthenticate()
            if body.action == "status":
                result = ehr_reads.status(*scope, enabled=configuration().workspace_ehr_read_available,
                    port=runtime(), reauthenticate=reauthenticate, provider=body.provider, include_problems=body.include_problems is True)
                if body.include_problems is True and not configuration().workspace_elation_problems_enabled:
                    result["problems"] = "not_enabled"
                return result
            port = service(body.provider)
            if body.action == "install":
                result = elation_sandbox_installation.install(*scope, key=body.idempotency_key,
                    installation_id=str(body.installation_id), installation_sha256=body.installation_sha256,
                    port=port, reauthenticate=reauthenticate)
            elif body.action == "observe":
                result = ehr_reads.observe(*scope, key=body.idempotency_key,
                    connection_id=str(body.connection_id), binding_sha256=body.binding_sha256,
                    starts_at=body.starts_at, ends_at=body.ends_at, port=port, reauthenticate=reauthenticate, provider=body.provider)
            elif body.action == "verify":
                result = ehr_reads.verify(*scope, key=body.idempotency_key,
                    connection_id=str(body.connection_id), binding_sha256=body.binding_sha256,
                    observation_id=str(body.observation_id), observation_sha256=body.observation_sha256,
                    item_handle=str(body.item_handle), item_sha256=body.item_sha256,
                    port=port, reauthenticate=reauthenticate, provider=body.provider, last_name=body.last_name, birth_date=body.birth_date)
            elif body.action == "problems":
                if not configuration().workspace_elation_problems_enabled:
                    raise ws.WorkspaceError("ehr_read_problems_unavailable", 404)
                result = ehr_reads.problems(*scope, key=body.idempotency_key,
                    connection_id=str(body.connection_id), binding_sha256=body.binding_sha256,
                    observation_id=str(body.observation_id), observation_sha256=body.observation_sha256,
                    item_handle=str(body.item_handle), item_sha256=body.item_sha256,
                    port=port, reauthenticate=reauthenticate, provider=body.provider)
            elif body.action == "inspect":
                result = ehr_reads.inspect_observation(*scope, observation_id=str(body.observation_id),
                    port=port, reauthenticate=reauthenticate, provider=body.provider)
            else:
                result = ehr_reads.resolve_observation(*scope, key=body.idempotency_key,
                    port=port, reauthenticate=reauthenticate, provider=body.provider)
            reauthenticate()
            if service(body.provider) is not port:
                raise ws.WorkspaceError("ehr_read_unavailable", 404)
            return result
        return JSONResponse(await run_in_threadpool(execute), headers=HEADERS)

    @routes.post("/workspaces/{workspace_id}/ehr-read/review", dependencies=[Depends(workspace_gate)])
    async def review(workspace_id: UUID, request: Request, identity=Depends(identity_dependency), session=Depends(session_dependency)):
        supported_identity(identity)
        checked(request)
        try:
            body = schema.ReviewEhr.model_validate(await decoded(request))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ws.WorkspaceError("invalid_ehr_read_review", 422) from None
        port = service(body.provider)

        def execute():
            fence(request, session, identity)
            result = ehr_reads.select_review(session, identity.box_id, identity.principal_id, str(workspace_id),
                expected=body.expected_revision, key=body.idempotency_key, observation_id=str(body.observation_id),
                observation_sha256=body.observation_sha256, item_handle=str(body.item_handle), item_sha256=body.item_sha256,
                reviewed_visit=body.reviewed_visit, reviewed_patient_identity=body.reviewed_patient_identity,
                reviewed_exact_snapshot=body.reviewed_exact_snapshot, reviewed_untrusted_source=body.reviewed_untrusted_source,
                port=port, external_identity_id=identity.external_identity_id,
                reauthenticate=lambda: fence(request, session, identity), provider=body.provider)
            result["workspace"] = model_work.project_workspace(session, result["workspace"])
            fence(request, session, identity)
            if service(body.provider) is not port:
                raise ws.WorkspaceError("ehr_read_unavailable", 404)
            return result
        return JSONResponse(await run_in_threadpool(execute), headers=HEADERS)
    return routes
