"""Small closed request; identity and canonical encounter stay server-owned."""

import json
from typing import Literal
from uuid import UUID

from fastapi import Request
from pydantic import ConfigDict, Field, model_validator

from cosmas_os.api.note_schemas import CoreNoteLink
from cosmas_os.api.team_schemas import BotAddress
from cosmas_os.api.workspace_schemas import IdempotencyKey
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.ports.capture_protocol import CaptureOperation
from cosmas_os.ports.core_capture import ConfiguredCaptureSelection, CoreConsentAttestation
from cosmas_os.ports.core_notes import CoreNoteSelection
from cosmas_os.ports.scribe_capture import ProtectedModel


class CaptureBotSelection(ProtectedModel):
    address: BotAddress
    team_revision: int = Field(ge=1, strict=True)


class CaptureAdmissionRequest(ProtectedModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    idempotency_key: IdempotencyKey
    attestation: CoreConsentAttestation | None = None
    configured_capture: ConfiguredCaptureSelection | None = None
    bot: CaptureBotSelection | None = None


class CaptureOperationRequest(ProtectedModel):
    idempotency_key: IdempotencyKey
    session_id: UUID
    operation: CaptureOperation


class EncounterPrepRequest(ProtectedModel):
    idempotency_key: IdempotencyKey
    bot: CaptureBotSelection | None = None
    view: Literal["sources", "brief"] = "sources"

    @model_validator(mode="after")
    def brief_bot_required(self):
        if self.view == "brief" and self.bot is None:
            raise ValueError("session_prep_bot_required")
        return self


class CaptureNoteRequest(ProtectedModel):
    idempotency_key: IdempotencyKey
    session_id: UUID
    note: CoreNoteSelection
    scratchpad_entry_id: UUID | None = None
    bot: CaptureBotSelection | None = None

    @model_validator(mode="after")
    def server_owned_notebook(self):
        if self.note.scratch_notes is not None or self.scratchpad_entry_id is not None and self.note.action not in {"read", "prepare"}:
            raise ValueError("invalid_notebook_selection")
        return self


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


async def read_capture_request[T: ProtectedModel](request: Request, schema: type[T], *, maximum_bytes: int | None = None) -> T:
    try:
        if any(
            len(request.headers.getlist(name)) != 1 for name in ("content-type", "authorization")
        ):
            raise ValueError
        if (
            request.headers["content-type"].split(";", 1)[0].strip().lower() != "application/json"
            or request.query_params
            or request.headers.getlist("content-encoding")
        ):
            raise ValueError
        body = bytearray()
        max_bytes = maximum_bytes if maximum_bytes is not None else 270336 if schema is CaptureNoteRequest else 4_194_304 if schema is CaptureOperationRequest else 1_048_576 if schema is CoreNoteLink else 2048
        async for chunk in request.stream():
            if len(body) + len(chunk) > max_bytes:
                raise ValueError
            body.extend(chunk)
        return schema.model_validate(json.loads(body, object_pairs_hook=_unique_object))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise WorkspaceError("invalid_capture_request", 422) from None


async def read_admission_request(request: Request) -> CaptureAdmissionRequest:
    return await read_capture_request(request, CaptureAdmissionRequest)
