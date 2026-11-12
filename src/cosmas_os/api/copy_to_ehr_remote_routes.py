"""Authenticated Copy to EHR phone-remote routes.

Computer creates a session. Phone posts highlight-only messages. Computer
polls for highlights. No note text crosses this relay.
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from cosmas_os.api.capture_schemas import _unique_object
from cosmas_os.api.copy_to_ehr_remote_schemas import (
    CreateRemoteSession,
    EndRemoteSession,
    HighlightRemoteSection,
)
from cosmas_os.application import copy_to_ehr_remote as remote
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import run_in_threadpool

HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
MAX_BODY = 4096
CONTRACT_HEADER = "x-cosmas-copy-to-ehr"


def remote_enabled(configuration) -> bool:
    """Track A owns copy_to_ehr_remote_enabled; consume it without defining it."""
    settings = configuration()
    return bool(getattr(settings, "copy_to_ehr_remote_enabled", False))


def router(*, configuration, identity_dependency, session_dependency, workspace_gate, fence, store=None):
    sessions = store if store is not None else remote.STORE
    routes = APIRouter(prefix="/api/copy-to-ehr")

    def available():
        if not remote_enabled(configuration):
            raise ws.WorkspaceError("copy_to_ehr_remote_unavailable", 404)

    def supported(identity):
        if getattr(identity, "auth_mode", None) != "clerk_jwt" or getattr(identity, "external_identity_id", None) is None:
            raise ws.WorkspaceError("copy_to_ehr_remote_unavailable", 404)

    def checked(request: Request, *, require_json: bool):
        params = request.query_params
        if params and not (len(params) == 1 and "after" in params):
            raise ws.WorkspaceError("invalid_copy_to_ehr_remote_request", 422)
        if request.headers.getlist(CONTRACT_HEADER) != ["1"]:
            raise ws.WorkspaceError("invalid_copy_to_ehr_remote_request", 422)
        if len(request.headers.getlist("authorization")) != 1:
            raise ws.WorkspaceError("invalid_copy_to_ehr_remote_request", 422)
        if require_json and (
            request.headers.getlist("content-encoding")
            or len(request.headers.getlist("content-type")) != 1
            or request.headers["content-type"].split(";", 1)[0].strip().lower() != "application/json"
        ):
            raise ws.WorkspaceError("invalid_copy_to_ehr_remote_request", 422)

    async def decoded(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_BODY:
                raise ValueError
            raw.extend(chunk)
        if not raw:
            raise ValueError
        return json.loads(raw, object_pairs_hook=_unique_object)

    def json_ok(payload: dict, status_code: int = 200):
        return JSONResponse(payload, status_code=status_code, headers=HEADERS)

    @routes.post("/sessions", dependencies=[Depends(workspace_gate)])
    async def create_session(
        request: Request,
        identity=Depends(identity_dependency),
        session: Session = Depends(session_dependency),
    ):
        available()
        supported(identity)
        checked(request, require_json=True)
        try:
            body = CreateRemoteSession.model_validate(await decoded(request))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ws.WorkspaceError("invalid_copy_to_ehr_remote_request", 422) from None

        def execute():
            fence(request, session, identity)
            created = sessions.create(
                box_id=identity.box_id,
                principal_id=identity.principal_id,
                draft_id=str(body.draft_id),
                draft_revision=body.draft_revision,
                section_keys=list(body.section_keys),
                visit_key=body.visit_key,
            )
            fence(request, session, identity)
            return remote.public_session(created)

        return json_ok(await run_in_threadpool(execute), status_code=201)

    @routes.get("/sessions/current", dependencies=[Depends(workspace_gate)])
    async def current_session(
        request: Request,
        identity=Depends(identity_dependency),
        session: Session = Depends(session_dependency),
    ):
        available()
        supported(identity)
        checked(request, require_json=False)

        def execute():
            fence(request, session, identity)
            current = sessions.current(box_id=identity.box_id, principal_id=identity.principal_id)
            fence(request, session, identity)
            if current is None:
                raise ws.WorkspaceError("copy_to_ehr_remote_session_unavailable", 404)
            return remote.public_session(current)

        return json_ok(await run_in_threadpool(execute))

    @routes.post("/sessions/{session_id}/highlight", dependencies=[Depends(workspace_gate)])
    async def highlight(
        session_id: UUID,
        request: Request,
        identity=Depends(identity_dependency),
        session: Session = Depends(session_dependency),
    ):
        available()
        supported(identity)
        checked(request, require_json=True)
        try:
            body = HighlightRemoteSection.model_validate(await decoded(request))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ws.WorkspaceError("invalid_copy_to_ehr_remote_request", 422) from None

        def execute():
            fence(request, session, identity)
            event = sessions.highlight(
                session_id=str(session_id),
                box_id=identity.box_id,
                principal_id=identity.principal_id,
                draft_revision=body.draft_revision,
                section_key=body.section_key,
            )
            fence(request, session, identity)
            return remote.public_event(event)

        return json_ok(await run_in_threadpool(execute))

    @routes.get("/sessions/{session_id}/events", dependencies=[Depends(workspace_gate)])
    async def events(
        session_id: UUID,
        request: Request,
        identity=Depends(identity_dependency),
        session: Session = Depends(session_dependency),
    ):
        available()
        supported(identity)
        checked(request, require_json=False)
        after_raw = request.query_params.get("after", "0")
        if not after_raw.isdigit():
            raise ws.WorkspaceError("invalid_copy_to_ehr_remote_request", 422)
        after = int(after_raw)

        def execute():
            fence(request, session, identity)
            current, items = sessions.events_after(
                session_id=str(session_id),
                box_id=identity.box_id,
                principal_id=identity.principal_id,
                after=after,
            )
            fence(request, session, identity)
            payload = remote.public_session(current)
            payload["events"] = [remote.public_event(item) for item in items]
            payload["next_after"] = items[-1].seq if items else after
            return payload

        return json_ok(await run_in_threadpool(execute))

    @routes.post("/sessions/{session_id}/end", dependencies=[Depends(workspace_gate)])
    async def end_session(
        session_id: UUID,
        request: Request,
        identity=Depends(identity_dependency),
        session: Session = Depends(session_dependency),
    ):
        available()
        supported(identity)
        checked(request, require_json=True)
        try:
            body = EndRemoteSession.model_validate(await decoded(request))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ws.WorkspaceError("invalid_copy_to_ehr_remote_request", 422) from None

        def execute():
            fence(request, session, identity)
            ended = sessions.end(
                session_id=str(session_id),
                box_id=identity.box_id,
                principal_id=identity.principal_id,
                reason=body.reason,
            )
            fence(request, session, identity)
            return remote.public_session(ended)

        return json_ok(await run_in_threadpool(execute))

    return routes
