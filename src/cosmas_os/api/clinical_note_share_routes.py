"""Current-human note sharing and exact read-only recovery; no bot invocation."""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from cosmas_os.api.capture_schemas import _unique_object
from cosmas_os.api.clinical_note_share_schemas import ShareSavedNote
from cosmas_os.application import clinical_note_share
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import run_in_threadpool


def router(*, workspace_gate, get_session, identity, fence):
    def contract(request: Request):
        if request.headers.getlist("X-Cosmas-Clinical-Team") != ["1"]:
            raise ws.WorkspaceError("clinical_team_contract_required", 426)
        if request.query_params:
            raise ws.WorkspaceError("clinical_team_request_invalid", 422)

    routes = APIRouter(dependencies=[Depends(workspace_gate), Depends(contract)])

    async def body(request):
        try:
            if (request.headers.getlist("content-encoding") or len(request.headers.getlist("content-type")) != 1
                    or request.headers["content-type"].split(";", 1)[0].strip().lower() != "application/json"):
                raise ValueError
            raw = bytearray()
            async for chunk in request.stream():
                if len(raw) + len(chunk) > 4096:
                    raise ValueError
                raw.extend(chunk)
            return ShareSavedNote.model_validate(json.loads(raw, object_pairs_hook=_unique_object,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError())))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ws.WorkspaceError("clinical_team_request_invalid", 422) from None

    def call(request, session, member, wid, command, *, resolve=False):
        fence(request, session, member)
        if resolve:
            result = clinical_note_share.resolve(session, member.box_id, member.principal_id, wid, command)
        else:
            result = clinical_note_share.share(session, member.box_id, member.principal_id, wid, command,
                fence=lambda: fence(request, session, member))
        fence(request, session, member)
        return result

    @routes.post("/workspaces/{workspace_id}/note/team-source")
    async def share(workspace_id: UUID, request: Request, session: Session = Depends(get_session), member=Depends(identity)):
        return await run_in_threadpool(call, request, session, member, str(workspace_id), await body(request))

    @routes.post("/workspaces/{workspace_id}/note/team-source/resolve")
    async def resolve(workspace_id: UUID, request: Request, session: Session = Depends(get_session), member=Depends(identity)):
        return await run_in_threadpool(call, request, session, member, str(workspace_id), await body(request), resolve=True)

    return routes
