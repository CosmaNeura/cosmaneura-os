"""Bounded inbox reads and human read markers; no model or vendor dispatch."""

import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from cosmas_os.api.capture_schemas import _unique_object
from cosmas_os.api.team_schemas import BotAddress, BotRole
from cosmas_os.application import conversation_inbox as inbox
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import run_in_threadpool


class MarkerCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    watermark: str | None = Field(default=None, min_length=115, max_length=115, pattern=r'^r1[0-9a-f]{16}[a-z][0-9a-f]{96}$')
    manual_unread: bool | None = Field(default=None, strict=True)
    expected_version: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode='after')
    def manual_change_version(self):
        if (self.manual_unread is None) != (self.expected_version is None):
            raise ValueError('Manual unread changes require an observed marker version')
        if self.manual_unread is False and self.watermark is None:
            raise ValueError('Mark read requires the observed activity watermark')
        return self


class InboxBot(BaseModel):
    model_config = ConfigDict(extra='forbid')
    address: BotAddress
    role: BotRole
    name: str = Field(min_length=1, max_length=40)
    available: bool


class InboxRow(BaseModel):
    model_config = ConfigDict(extra='forbid')
    workspace_id: UUID
    appointment_id: UUID | None
    context_label: str = Field(min_length=1, max_length=200)
    bot: InboxBot
    preview: str = Field(max_length=180)
    preview_withheld: bool
    attention: Literal['idle', 'working', 'needs_review', 'needs_check']
    last_activity_at: str
    watermark: str
    unread: bool
    manual_unread: bool
    marker_version: int = Field(ge=0)


class InboxResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    contract_version: Literal[1]
    as_of: str
    rows: list[InboxRow] = Field(max_length=20)
    next_cursor: str | None


def router(*, workspace_gate, get_session, identity, fence):
    def contract(request: Request):
        if request.headers.getlist('X-Cosmas-Conversations') != ['1']:
            raise ws.WorkspaceError('conversation_contract_required', 426)
        if request.query_params:
            raise ws.WorkspaceError('invalid_conversation_request', 422)

    routes = APIRouter(dependencies=[Depends(workspace_gate), Depends(contract)])

    @routes.get('/workspaces/conversations', response_model=InboxResponse)
    @routes.get('/workspaces/conversations/pages/{cursor}', response_model=InboxResponse)
    async def read(request: Request, cursor: str | None = None, session: Session = Depends(get_session), member=Depends(identity)):
        if request.headers.getlist('content-encoding') or request.headers.getlist('transfer-encoding') or request.headers.getlist('content-length') not in ([], ['0']):
            raise ws.WorkspaceError('invalid_conversation_request', 422)
        value = await run_in_threadpool(inbox.read, session, member.box_id, member.principal_id, cursor=cursor,
            fence=lambda: fence(request, session, member))
        response = InboxResponse.model_validate(value)
        return JSONResponse(response.model_dump(mode='json'), headers={'Cache-Control': 'no-store'})

    @routes.post('/workspaces/{workspace_id}/conversations/{bot}/read', openapi_extra={'requestBody': {'required': True, 'content': {'application/json': {'schema': MarkerCommand.model_json_schema()}}}})
    async def mark(workspace_id: UUID, bot: BotAddress, request: Request, session: Session = Depends(get_session), member=Depends(identity)):
        try:
            if request.headers.getlist('content-encoding') or len(request.headers.getlist('content-type')) != 1 or request.headers['content-type'].split(';', 1)[0].strip().lower() != 'application/json':
                raise ValueError()
            raw = bytearray()
            async for chunk in request.stream():
                if len(raw) + len(chunk) > 4096:
                    raise ValueError()
                raw.extend(chunk)
            command = MarkerCommand.model_validate(json.loads(raw, object_pairs_hook=_unique_object,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError())))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ws.WorkspaceError('invalid_conversation_request', 422) from None
        value = await run_in_threadpool(inbox.update_marker, session, member.box_id, member.principal_id, str(workspace_id), bot,
            **command.model_dump(), fence=lambda: fence(request, session, member))
        return JSONResponse(value, headers={'Cache-Control': 'no-store'})

    return routes
