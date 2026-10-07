"""Owner-only notebooks before a patient is selected; linking performs no upstream I/O."""

import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from cosmas_os.api.capture_schemas import _unique_object
from cosmas_os.api.workspace_schemas import IdempotencyKey
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import run_in_threadpool


class PrivateDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    idempotency_key: IdempotencyKey


class PrivateDraftLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    idempotency_key: IdempotencyKey
    appointment_id: UUID
    appointment_link_confirmed: Literal[True]

    @field_validator("appointment_link_confirmed", mode="before")
    @classmethod
    def human_confirmation(cls, value):
        if value is not True:
            raise ValueError("human appointment confirmation required")
        return value


def router(*, workspace_gate, get_session, identity, fence):
    def contract(request: Request):
        values = request.headers.getlist("X-Cosmas-Private-Draft")
        if values != ["1"]:
            raise ws.WorkspaceError("private_draft_contract_required", 426)
        if request.query_params:
            raise ws.WorkspaceError("invalid_private_draft_request", 422)

    routes = APIRouter(dependencies=[Depends(workspace_gate), Depends(contract)])

    async def body(request, model):
        try:
            if (request.headers.getlist("content-encoding") or len(request.headers.getlist("content-type")) != 1
                    or request.headers["content-type"].split(";", 1)[0].strip().lower() != "application/json"):
                raise ValueError
            raw = bytearray()
            async for chunk in request.stream():
                if len(raw) + len(chunk) > 4096:
                    raise ValueError
                raw.extend(chunk)
            return model.model_validate(json.loads(raw, object_pairs_hook=_unique_object,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError())))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ws.WorkspaceError("invalid_private_draft_request", 422) from None

    def observe(session, member, request, call):
        fence(request, session, member)
        result = call()
        fence(request, session, member)
        return result

    @routes.get("/workspaces/private-drafts")
    async def list_drafts(request: Request, session: Session = Depends(get_session), member=Depends(identity)):
        return await run_in_threadpool(observe, session, member, request,
            lambda: ws.private_drafts(session, member.box_id, member.principal_id))

    @routes.post("/workspaces/private-drafts")
    async def create_draft(request: Request, session: Session = Depends(get_session), member=Depends(identity)):
        command = await body(request, PrivateDraftCreate)
        return await run_in_threadpool(observe, session, member, request,
            lambda: ws.create_private_draft(session, member.box_id, member.principal_id, command.title,
                command.idempotency_key, fence=lambda: fence(request, session, member)))

    @routes.post("/workspaces/private-drafts/resolve")
    async def resolve_draft(request: Request, session: Session = Depends(get_session), member=Depends(identity)):
        command = await body(request, PrivateDraftCreate)
        return await run_in_threadpool(observe, session, member, request,
            lambda: ws.resolve_private_draft(session, member.box_id, member.principal_id, command.title, command.idempotency_key))

    @routes.post("/workspaces/{workspace_id}/appointment-link")
    async def link_draft(workspace_id: UUID, request: Request,
                   session: Session = Depends(get_session), member=Depends(identity)):
        command = await body(request, PrivateDraftLink)
        return await run_in_threadpool(observe, session, member, request,
            lambda: ws.link_appointment(session, member.box_id, member.principal_id, str(workspace_id),
                expected=command.expected_revision, key=command.idempotency_key,
                appointment=str(command.appointment_id), confirmed=command.appointment_link_confirmed,
                fence=lambda: fence(request, session, member)))

    @routes.post("/workspaces/{workspace_id}/appointment-link/resolve")
    async def resolve_link(workspace_id: UUID, request: Request,
                     session: Session = Depends(get_session), member=Depends(identity)):
        command = await body(request, PrivateDraftLink)
        return await run_in_threadpool(observe, session, member, request,
            lambda: ws.resolve_appointment_link(session, member.box_id, member.principal_id, str(workspace_id),
                expected=command.expected_revision, key=command.idempotency_key,
                appointment=str(command.appointment_id), confirmed=command.appointment_link_confirmed))

    return routes
