from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.requests import Request

from cosmas_os.adapters.core_capture_admission import HttpCoreCaptureAdmission
from cosmas_os.adapters.core_record_connection import record_connection as core_record_connection
from cosmas_os.adapters.core_session_prep_connection import session_prep_connection
from cosmas_os.adapters.google_connection_runtime import google_connection_lifespan
from cosmas_os.adapters.managed_services import managed_services, managed_services_lifespan
from cosmas_os.adapters.microsoft_connection_runtime import microsoft_connection_lifespan
from cosmas_os.adapters.portal_services import portal_services, portal_services_lifespan
from cosmas_os.adapters.scheduling_login_runtime import scheduling_login_lifespan
from cosmas_os.adapters.scheduling_runtime import scheduling_lifespan, scheduling_runtime
from cosmas_os.api.auth import (
    AccessDenied,
    AuthenticationFailed,
    ClerkTokenVerifier,
    RequestIdentity,
    authenticate_request,
    native_clerk_origin,
)
from cosmas_os.api.capture_schemas import (
    CaptureAdmissionRequest,
    CaptureNoteRequest,
    CaptureOperationRequest,
    EncounterPrepRequest,
    ExistingCaptureRequest,
    ScribeSourcePacketRequest,
    read_capture_request,
)
from cosmas_os.api.core_connection_routes import (
    install_boundary as install_core_connection_boundary,
)
from cosmas_os.api.core_connection_routes import router as core_connection_router
from cosmas_os.api.core_record_routes import install_record_boundary
from cosmas_os.api.core_record_routes import router as core_record_router
from cosmas_os.api.follow_up_schemas import FollowUpComplete, FollowUpDecision, FollowUpPropose
from cosmas_os.api.google_connection_routes import GoogleConnectionBoundary
from cosmas_os.api.google_connection_routes import router as google_connection_router
from cosmas_os.api.microsoft_connection_routes import MicrosoftConnectionBoundary
from cosmas_os.api.microsoft_connection_routes import router as microsoft_connection_router
from cosmas_os.api.note_schemas import CoreNoteLink, NoteReview, NoteSave
from cosmas_os.api.prep_work_schemas import PrepWorkDecision, PrepWorkPropose, PrepWorkVerify
from cosmas_os.api.scheduling_login_routes import SchedulingCallbackBoundary
from cosmas_os.api.scheduling_login_routes import router as scheduling_login_router
from cosmas_os.api.shared_work_schemas import WorkHandoffCommand
from cosmas_os.api.team_schemas import (
    BotAddress,
    ConversationRequest,
    HandoffRetry,
    TeamRehearsalRequest,
    TeamSave,
)
from cosmas_os.api.team_setup_schemas import contract_header, read_team_request
from cosmas_os.api.workspace_schemas import WorkspaceAppend, WorkspaceCreate, WorkspaceWorkLink
from cosmas_os.application import (
    conversation,
    core_note_review,
    follow_up,
    handoffs,
    note_review,
    prep_work,
    provider_team,
    routines,
    shared_work,
    team_setup,
    workspace_capture,
)
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import (
    check_capture_deadline,
    current_budget,
    new_capture_session,
)
from cosmas_os.application.worker_progress import (
    HANDOFF_MAX_AGE_SECONDS,
    ROUTINE_MAX_AGE_SECONDS,
    WorkerProgress,
    workspace_workers_ready,
)
from cosmas_os.config import settings
from cosmas_os.db import make_engine, make_session_factory
from cosmas_os.domain.enums import CapabilityKey, DecisionKind
from cosmas_os.domain.rules import AuthorizationError, DomainError, PolicyDenied
from cosmas_os.ports.core_capture import CoreCaptureAdmissionPort, CoreCaptureAdmissionSnapshot
from cosmas_os.ports.core_notes import CoreDraftReceipt, CoreDraftReference, CoreNoteSelection
from cosmas_os.ports.encounter_prep import CorePrepReceipt
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION

engine = make_engine()
SessionLocal = make_session_factory(engine)


def get_session() -> Iterator[Session]:
    session = new_capture_session(SessionLocal)
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = new_capture_session(SessionLocal)
    try:
        yield session
    finally:
        session.close()


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings.validate_runtime_configuration()
    async with portal_services_lifespan(application, settings, lambda: new_capture_session(SessionLocal)):
        with google_connection_lifespan(application, settings, lambda: new_capture_session(SessionLocal)), microsoft_connection_lifespan(application, settings, lambda: new_capture_session(SessionLocal)), scheduling_login_lifespan(application, settings, lambda: new_capture_session(SessionLocal)), scheduling_lifespan(application, settings), managed_services_lifespan(
                application, settings, lambda: new_capture_session(SessionLocal)):
            stop = asyncio.Event()
            workers = []
            progress = {}
            application.state.workspace_worker_progress = progress
            try:
                if settings.workspace_llm_available:
                    progress["handoffs"] = WorkerProgress(HANDOFF_MAX_AGE_SECONDS)
                    workers.append(asyncio.create_task(handoffs.run_worker(
                        SessionLocal, stop, progress=progress["handoffs"])))
                if settings.workspace_available and settings.workspace_routines_enabled:
                    progress["routines"] = WorkerProgress(ROUTINE_MAX_AGE_SECONDS)
                    workers.append(asyncio.create_task(routines.run_worker(
                        SessionLocal, stop, incoming_sources=_routine_sources(),
                        progress=progress["routines"])))
                yield
            finally:
                for state in progress.values():
                    state.stopped()
                stop.set()
                results = await asyncio.gather(*workers, return_exceptions=True)
                for result in results:
                    if isinstance(result, BaseException):
                        raise result


app = FastAPI(
    title="Cosmas OS",
    version="0.2.0",
    description="Box-scoped practice work queue",
    lifespan=lifespan,
)


class SeedResponse(BaseModel):
    box_id: str
    owner_id: str
    agents: dict[str, str]


class DemoSeedResponse(SeedResponse):
    ticket_id: str


class QueueItem(BaseModel):
    id: str
    lane: str
    state: str
    proposed_message: str | None
    revision_id: str | None
    patient_link_id: str | None
    execution_status: str | None = None


class DecideBody(BaseModel):
    kind: DecisionKind
    note: str | None = Field(default=None, max_length=2000)
    expected_revision_id: str | None = None


class EditBody(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class AttestBody(BaseModel):
    source_pair_key: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=200)


class ImportBody(BaseModel):
    csv_text: str = Field(min_length=1, max_length=1_000_000)


class UploadBody(BaseModel):
    front_b64: str = Field(min_length=1, max_length=11_200_000)
    back_b64: str = Field(min_length=1, max_length=11_200_000)


class IdentityBindBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clerk_subject: str = Field(min_length=6, max_length=255, pattern=r"^user_[A-Za-z0-9]+$")
    display_name: str = Field(min_length=1, max_length=200)
    evidence_ref: str = Field(min_length=1, max_length=255)


class IdentityChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clerk_subject: str = Field(min_length=6, max_length=255, pattern=r"^user_[A-Za-z0-9]+$")
    evidence_ref: str = Field(min_length=1, max_length=255)


class IdentitySummaryResponse(BaseModel):
    clerk_subject: str
    display_name: str
    active: bool
    principal_state: str
    is_owner: bool


@lru_cache(maxsize=3)
def _clerk_verifier(native_origin: str | None = None) -> ClerkTokenVerifier:
    return ClerkTokenVerifier(settings, native_origin=native_origin)


def _request_clerk_verifier(origins: list[str]) -> ClerkTokenVerifier:
    native_origin = native_clerk_origin(settings, origins)
    return _clerk_verifier(native_origin) if native_origin else _clerk_verifier()


def _identity(
    request: Request,
    session: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
    x_box_id: str | None = Header(default=None),
    x_actor_principal_id: str | None = Header(default=None),
) -> RequestIdentity:
    try:
        check_capture_deadline()
        verifier = _request_clerk_verifier(request.headers.getlist("origin")) if settings.auth_mode == "clerk_jwt" else None
        check_capture_deadline()
        result = authenticate_request(
            session,
            settings,
            authorization=authorization,
            box_header=x_box_id,
            actor_header=x_actor_principal_id,
            verifier=verifier,
        )
        check_capture_deadline()
        return result
    except AuthenticationFailed as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        ) from exc
    except AccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc), headers={"Cache-Control": "no-store"}) from exc


def _map_err(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, AuthorizationError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, PolicyDenied):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, DomainError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="internal error")


def _require_data_entry_authorized() -> None:
    if settings.cosmas_env == "early_adopter_beta" and settings.data_mode != "authorized_beta":
        raise HTTPException(
            status_code=403,
            detail="data entry is disabled until separate PHI authorization",
        )


def _workspace_gate(response: Response, request: Request) -> None:
    if not settings.workspace_available:
        raise HTTPException(404, "not found", headers={"Cache-Control": "no-store"})
    if settings.workspace_draft_recovery_required and request.headers.get("X-Cosmas-Draft-Recovery") != "2":
        raise HTTPException(426, "workspace_client_update_required", headers={"Cache-Control": "no-store"})
    response.headers["Cache-Control"] = "no-store"


@app.exception_handler(ws.WorkspaceError)
async def workspace_error(_: Request, exc: ws.WorkspaceError):
    return JSONResponse(status_code=exc.status, content={"detail": exc.code},
                        headers={"Cache-Control": "no-store"})


@app.exception_handler(RequestValidationError)
async def safe_workspace_validation(request: Request, exc: RequestValidationError):
    if request.url.path in {"/workspaces", "/provider-team", "/practice-work"} or request.url.path.startswith(("/workspaces/", "/practice-work/", "/provider-team/")):
        return JSONResponse(status_code=422, content={"detail": "invalid_workspace_request"},
                            headers={"Cache-Control": "no-store"})
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(SQLAlchemyError)
async def safe_workspace_storage_error(request: Request, exc: SQLAlchemyError):
    if request.url.path in {"/workspaces", "/provider-team", "/practice-work"} or request.url.path.startswith(("/workspaces/", "/practice-work/", "/provider-team/")):
        return JSONResponse(status_code=503, content={"detail": "workspace_storage_unavailable"},
                            headers={"Cache-Control": "no-store"})
    raise exc


@app.get("/workspaces", dependencies=[Depends(_workspace_gate)])
def workspace_catalog(session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity)):
    return ws.catalog(session, identity.box_id, identity.principal_id)


def _capture_gate() -> None:
    if not settings.workspace_capture_available:
        raise HTTPException(404, "not found", headers={"Cache-Control": "no-store"})


def _capture_note_gate() -> None:
    _capture_gate()
    if not settings.workspace_capture_notes_enabled:
        raise HTTPException(404, "not found", headers={"Cache-Control": "no-store"})


def _prep_gate() -> None:
    _capture_gate()
    if not settings.workspace_prep_enabled:
        raise HTTPException(404, "not found", headers={"Cache-Control": "no-store"})


def _scheduling_gate() -> None:
    if not settings.workspace_scheduling_available:
        raise HTTPException(404, "not found", headers={"Cache-Control": "no-store"})


def _scheduling_connection(request: Request):
    from cosmas_os.ports.scheduling import build_scheduling_availability
    runtime = scheduling_runtime(request.app)
    return runtime.availability if runtime is not None else build_scheduling_availability()


def _appointment_gate() -> None:
    _scheduling_gate()
    if not settings.workspace_appointments_enabled:
        raise HTTPException(404, "not found", headers={"Cache-Control": "no-store"})


def _appointment_connection(request: Request):
    from cosmas_os.ports.scheduling_actions import build_scheduling_appointments
    runtime = scheduling_runtime(request.app)
    return runtime.appointments if runtime is not None else build_scheduling_appointments()


@app.get("/workspaces/{workspace_id}/appointments", dependencies=[Depends(_workspace_gate), Depends(_appointment_gate)])
@app.get("/workspaces/{workspace_id}/appointments/pages/{cursor}", dependencies=[Depends(_workspace_gate), Depends(_appointment_gate)])
def workspace_appointment_catalog(workspace_id: UUID, cursor: UUID | None = None,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.application import appointment_work
    return appointment_work.catalog(session, identity.box_id, identity.principal_id,
                                    str(workspace_id), cursor=str(cursor) if cursor else None)


async def _prepare_workspace_appointment(request, workspace_id, session, identity, availability_port, appointment_port, *, current=False):
    from cosmas_os.api.scheduling_schemas import AppointmentPrepare, CurrentAppointmentRequest
    from cosmas_os.application import workspace_appointments
    from cosmas_os.application.capture_deadline import run_in_threadpool

    if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
        raise ws.WorkspaceError("scheduling_access_unavailable", 403)
    body = await read_capture_request(request, CurrentAppointmentRequest if current else AppointmentPrepare)
    def reauthenticate():
        _appointment_gate()
        if _identity(request=request, session=session, authorization=request.headers.get("authorization"),
                     x_box_id=None, x_actor_principal_id=None) != identity:
            raise ws.WorkspaceError("scheduling_access_unavailable", 403)
    context = dict(box=identity.box_id, owner=identity.principal_id, workspace_id=str(workspace_id),
                   external_identity_id=identity.external_identity_id, reauthenticate=reauthenticate)
    if current:
        return await run_in_threadpool(workspace_appointments.read_current, session,
                                       **context, bot=body.bot, port=appointment_port)
    return await run_in_threadpool(workspace_appointments.prepare, session,
                                  **context, body=body, availability_port=availability_port,
                                  appointment_port=appointment_port)


@app.post("/workspaces/{workspace_id}/appointments/current", dependencies=[Depends(_workspace_gate), Depends(_appointment_gate)])
async def current_workspace_appointment(request: Request, workspace_id: UUID,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
    port=Depends(_appointment_connection)):
    return await _prepare_workspace_appointment(request, workspace_id, session, identity, None, port, current=True)


@app.post("/workspaces/{workspace_id}/appointments", dependencies=[Depends(_workspace_gate), Depends(_appointment_gate)])
async def prepare_workspace_appointment(request: Request, workspace_id: UUID,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
    availability_port=Depends(_scheduling_connection), appointment_port=Depends(_appointment_connection)):
    return await _prepare_workspace_appointment(request, workspace_id, session, identity, availability_port, appointment_port)


@app.get("/workspaces/{workspace_id}/appointments/{ticket_id}", dependencies=[Depends(_workspace_gate), Depends(_appointment_gate)])
def read_workspace_appointment(workspace_id: UUID, ticket_id: UUID,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.application import appointment_work

    if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
        raise ws.WorkspaceError("scheduling_access_unavailable", 403)
    return appointment_work.read(session, identity.box_id, identity.principal_id, str(workspace_id), str(ticket_id))


@app.post("/workspaces/{workspace_id}/appointments/{ticket_id}/decide", dependencies=[Depends(_workspace_gate), Depends(_appointment_gate)])
async def decide_workspace_appointment(request: Request, workspace_id: UUID, ticket_id: UUID,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.api.scheduling_schemas import AppointmentDecision
    from cosmas_os.application import appointment_work
    from cosmas_os.application.capture_deadline import run_in_threadpool

    if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
        raise ws.WorkspaceError("scheduling_access_unavailable", 403)
    body = await read_capture_request(request, AppointmentDecision)
    def decide():
        # A slow request body must not extend the lifetime of its signed session.
        _appointment_gate()
        if _identity(request=request, session=session, authorization=request.headers.get("authorization"),
                     x_box_id=None, x_actor_principal_id=None) != identity:
            raise ws.WorkspaceError("scheduling_access_unavailable", 403)
        return appointment_work.decide(session, identity.box_id, identity.principal_id,
            str(workspace_id), str(ticket_id), external_identity_id=identity.external_identity_id,
            revision_id=str(body.revision_id), digest=body.payload_hash, choice=body.choice)
    return await run_in_threadpool(decide)


@app.post("/workspaces/{workspace_id}/appointments/{ticket_id}/execute", dependencies=[Depends(_workspace_gate), Depends(_appointment_gate)])
async def execute_workspace_appointment(request: Request, workspace_id: UUID, ticket_id: UUID,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
    port=Depends(_appointment_connection)):
    from cosmas_os.api.scheduling_schemas import AppointmentExecutionRequest
    from cosmas_os.application import appointment_execution
    from cosmas_os.application.capture_deadline import run_in_threadpool

    if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
        raise ws.WorkspaceError("scheduling_access_unavailable", 403)
    body = await read_capture_request(request, AppointmentExecutionRequest, maximum_bytes=2048)
    def reauthenticate():
        _appointment_gate()
        session.expire_all()
        if _identity(request=request, session=session, authorization=request.headers.get("authorization"),
                     x_box_id=None, x_actor_principal_id=None) != identity:
            raise ws.WorkspaceError("scheduling_access_unavailable", 403)
    return await run_in_threadpool(appointment_execution.run, session,
        identity.box_id, identity.principal_id, str(workspace_id), str(ticket_id),
        external_identity_id=identity.external_identity_id, reauthenticate=reauthenticate,
        port=port, operation_id=str(body.operation_id), revision_id=str(body.revision_id),
        digest=body.payload_hash, mode=body.mode)


@app.post("/workspaces/{workspace_id}/scheduling/availability", dependencies=[Depends(_workspace_gate), Depends(_scheduling_gate)])
async def read_workspace_scheduling(request: Request, workspace_id: UUID,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
    port=Depends(_scheduling_connection)):
    from cosmas_os.api.scheduling_schemas import WorkspaceAvailabilityRequest
    from cosmas_os.application import workspace_scheduling
    from cosmas_os.application.capture_deadline import run_in_threadpool

    if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
        raise ws.WorkspaceError("scheduling_access_unavailable", 403)
    body = await read_capture_request(request, WorkspaceAvailabilityRequest)
    authorization = request.headers["authorization"]

    def reauthenticate():
        if _identity(request=request, session=session, authorization=authorization, x_box_id=None,
                     x_actor_principal_id=None) != identity:
            raise ws.WorkspaceError("scheduling_access_unavailable", 403)

    result = await run_in_threadpool(workspace_scheduling.read_availability, session,
        box=identity.box_id, owner=identity.principal_id, external_identity_id=identity.external_identity_id,
        workspace_id=str(workspace_id), bot=body.bot, window=body.window,
        port=port, reauthenticate=reauthenticate)
    return JSONResponse(content=result, headers={"Cache-Control": "no-store"})


def _capture_connection() -> Iterator[CoreCaptureAdmissionPort | None]:
    # Shared note routes also serve manual notes when capture is disabled.
    # Constructing the client performs no token exchange or network request.
    if not settings.workspace_capture_available:
        yield None
        return
    budget = current_budget()
    if budget is not None:
        from cosmas_os.adapters.core_capture_connection import capture_connection
        with capture_connection(settings, budget) as connection:
            yield connection
        return
    from azure.identity import ManagedIdentityCredential
    credential = ManagedIdentityCredential(client_id=settings.core_capture_managed_identity_client_id)
    connection = HttpCoreCaptureAdmission(settings.core_capture_origin,
        lambda: credential.get_token(settings.core_capture_scope).token)
    try:
        yield connection
    finally:
        connection.close()
        credential.close()


app.include_router(core_record_router(settings=lambda: settings, session_factory=lambda: SessionLocal(),
    identity_dependency=_identity, workspace_gate=_workspace_gate,
    connection_factory=lambda configuration, budget: core_record_connection(configuration, budget)))


async def _execute_workspace_capture(request: Request, workspace_id: UUID, session: Session,
    identity: RequestIdentity, port: CoreCaptureAdmissionPort | None,
    body: CaptureAdmissionRequest | CaptureOperationRequest | CaptureNoteRequest | EncounterPrepRequest | ExistingCaptureRequest,
    finalize_note: Callable[[BaseModel], Any] | None = None,
    *, finalize_prep: Callable[[BaseModel], Any] | None = None,
    finalize_existing: Callable[[BaseModel], Any] | None = None):
    if port is None:
        raise ws.WorkspaceError("capture_connection_required", 409)
    if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
        raise ws.WorkspaceError("capture_access_unavailable", 403)
    raw_authorization = request.headers["authorization"]
    bearer = SecretStr(raw_authorization.partition(" ")[2])

    def reauthenticate():
        if isinstance(body, ExistingCaptureRequest):
            _capture_gate()
        if isinstance(body, EncounterPrepRequest):
            _prep_gate()
            if finalize_prep is not None:
                _prep_work_gate()
        current = _identity(request=request, session=session, authorization=raw_authorization, x_box_id=None,
                            x_actor_principal_id=None)
        if current != identity:
            raise ws.WorkspaceError("capture_access_unavailable", 403)

    # Sync transport runs off the event loop. This request owns the session;
    # it is never used concurrently by another task or callback.
    from cosmas_os.application.capture_deadline import run_in_threadpool
    def require_qualified_source(receipt):
        if (isinstance(receipt, CoreDraftReceipt) and receipt.capture_gap_review is not None
            and not (settings.workspace_capture_source_enabled and settings.workspace_capture_corrections_enabled)):
            raise ws.WorkspaceError("capture_source_unavailable", 503)

    checked_finalize = finalize_note
    if finalize_note is not None:
        def finalize_checked_note(receipt: BaseModel):
            require_qualified_source(receipt)
            return finalize_note(receipt)
        checked_finalize = finalize_checked_note
    result = await run_in_threadpool(workspace_capture.admit, session,
        box=identity.box_id, actor=identity.principal_id,
        external_identity_id=identity.external_identity_id, workspace_id=str(workspace_id),
        bearer=bearer, reauthenticate=reauthenticate, port=port,
        attestation=body.attestation if isinstance(body, CaptureAdmissionRequest) else None,
        idempotency_key=body.idempotency_key,
        configured_capture=body.configured_capture if isinstance(body, CaptureAdmissionRequest) else None,
        operation=body.operation if isinstance(body, CaptureOperationRequest) else None,
        expected_session_id=body.session_id if isinstance(body, (CaptureOperationRequest, CaptureNoteRequest)) else None,
        note_selection=body.note if isinstance(body, CaptureNoteRequest) else None,
        scratchpad_entry_id=body.scratchpad_entry_id if isinstance(body, CaptureNoteRequest) else None,
        bot_selection=body.bot if isinstance(body, (CaptureAdmissionRequest, CaptureNoteRequest, EncounterPrepRequest)) else None,
        prep=isinstance(body, EncounterPrepRequest),
        existing_recording=isinstance(body, ExistingCaptureRequest),
        finalize_existing=finalize_existing,
        finalize_note=checked_finalize, finalize_prep=finalize_prep)
    require_qualified_source(result)
    return result


@app.post("/workspaces/{workspace_id}/capture/existing", dependencies=[Depends(_workspace_gate), Depends(_capture_gate)])
async def read_existing_scribe_recording(request: Request, workspace_id: UUID,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
    port: CoreCaptureAdmissionPort | None = Depends(_capture_connection)):
    from cosmas_os.application.scribe_source import selection
    body = await read_capture_request(request, ExistingCaptureRequest)
    result = await _execute_workspace_capture(request, workspace_id, session, identity, port, body)
    selected = selection(result.review) if result.review is not None else None
    return JSONResponse({"contract_version": 1, "workspace_id": str(workspace_id),
        "status": result.status, "review": result.review.model_dump(mode="json") if result.review else None,
        "selection": selected.model_dump(mode="json") if selected else None}, headers={"Cache-Control": "no-store"})


@app.post("/workspaces/{workspace_id}/capture/source-packets", dependencies=[Depends(_workspace_gate), Depends(_capture_gate)])
async def save_scribe_source_packet(request: Request, workspace_id: UUID,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
    port: CoreCaptureAdmissionPort | None = Depends(_capture_connection)):
    from cosmas_os.application.capture_deadline import run_in_threadpool
    from cosmas_os.application.scribe_source import save_snapshot, saved_snapshot
    body = await read_capture_request(request, ScribeSourcePacketRequest)

    def recover():
        if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
            raise ws.WorkspaceError("capture_access_unavailable", 403)
        _refresh_team_identity(request, session, identity)
        return saved_snapshot(session, box=identity.box_id, owner=identity.principal_id,
            workspace_id=str(workspace_id), expected=body.expected_revision, key=body.idempotency_key,
            selected=body.selection)

    prior = await run_in_threadpool(recover)
    if prior is not None:
        return JSONResponse(prior, headers={"Cache-Control": "no-store"})

    def publish(checked):
        return save_snapshot(session, box=identity.box_id, owner=identity.principal_id,
            workspace_id=str(workspace_id), expected=body.expected_revision, key=body.idempotency_key,
            selected=body.selection, checked=checked)

    value = await _execute_workspace_capture(request, workspace_id, session, identity, port, body,
                                              finalize_existing=publish)
    return JSONResponse(value, headers={"Cache-Control": "no-store"})


@app.post("/workspaces/{workspace_id}/capture/prep", dependencies=[Depends(_workspace_gate), Depends(_prep_gate)])
async def read_workspace_prep(request: Request, workspace_id: UUID,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
    port: CoreCaptureAdmissionPort | None = Depends(_capture_connection)):
    body = await read_capture_request(request, EncounterPrepRequest)
    if body.view == "brief":
        from cosmas_os.application import session_prep
        from cosmas_os.application.capture_deadline import run_in_threadpool

        authorization = request.headers["authorization"]

        def reauthenticate():
            _prep_gate()
            if not settings.workspace_session_prep_available:
                raise ws.WorkspaceError("session_prep_unavailable", 404)
            if (identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None
                or _identity(request=request, session=session, authorization=authorization,
                    x_box_id=None, x_actor_principal_id=None) != identity):
                raise ws.WorkspaceError("session_prep_access_unavailable", 403)

        def read_brief():
            reauthenticate()
            with session_prep_connection(settings, current_budget()) as brief_port:
                return session_prep.read(session, box=identity.box_id, owner=identity.principal_id,
                    external_identity_id=identity.external_identity_id, workspace_id=str(workspace_id),
                    bot=body.bot, bearer=SecretStr(authorization.partition(" ")[2]),
                    idempotency_key=body.idempotency_key,
                    reauthenticate=reauthenticate, port=brief_port)

        result = await run_in_threadpool(read_brief)
        return JSONResponse(content=result, headers={"Cache-Control": "no-store"})
    result = await _execute_workspace_capture(request, workspace_id, session, identity, port, body)
    if not isinstance(result, CorePrepReceipt):
        raise ws.WorkspaceError("capture_request_unconfirmed", 503)
    return JSONResponse(content={"workspace_id": str(workspace_id), "receipt": prep_work.public_prep_receipt(result)},
        headers={"Cache-Control": "no-store"})


def _prep_work_gate():
    prep_work.available()


def _refresh_prep_work_identity(request, session, identity):
    # A streamed request body must not extend a signed session, including when
    # recovering a committed command or withdrawing without a Core connection.
    _prep_work_gate()
    session.expire_all()
    if (identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None
        or _identity(request=request, session=session, authorization=request.headers.get("authorization"),
            x_box_id=None, x_actor_principal_id=None) != identity):
        raise ws.WorkspaceError("capture_access_unavailable", 403)


@app.get("/workspaces/{workspace_id}/prep-work", dependencies=[Depends(_workspace_gate), Depends(_prep_work_gate)])
def list_preparation_work(workspace_id: UUID, session: Session = Depends(get_session),
                          identity: RequestIdentity = Depends(_identity)):
    return prep_work.catalog(session, identity.box_id, identity.principal_id, str(workspace_id))


@app.get("/workspaces/{workspace_id}/prep-work/{ticket_id}", dependencies=[Depends(_workspace_gate), Depends(_prep_work_gate)])
def read_preparation_work(workspace_id: UUID, ticket_id: UUID, session: Session = Depends(get_session),
                          identity: RequestIdentity = Depends(_identity)):
    return prep_work.detail(session, identity.box_id, identity.principal_id, str(workspace_id), str(ticket_id))


@app.post("/workspaces/{workspace_id}/prep-work", dependencies=[Depends(_workspace_gate), Depends(_prep_work_gate)])
async def propose_preparation_work(request: Request, workspace_id: UUID, session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity), port: CoreCaptureAdmissionPort | None = Depends(_capture_connection)):
    from cosmas_os.application.capture_deadline import run_in_threadpool
    body = await read_capture_request(request, PrepWorkPropose, maximum_bytes=32768)
    await run_in_threadpool(_refresh_prep_work_identity, request, session, identity)
    command = body.model_dump(mode="json", exclude_none=True)
    recovered = await run_in_threadpool(prep_work.recover_proposal, session,
        identity.box_id, identity.principal_id, str(workspace_id), command)
    if recovered is not None:
        return recovered
    _prep_gate()
    return await _execute_workspace_capture(request, workspace_id, session, identity, port,
        EncounterPrepRequest(idempotency_key=body.idempotency_key, bot=body.bot),
        finalize_prep=lambda checked: prep_work.propose(session, identity.box_id, identity.principal_id,
            str(workspace_id), command, checked))


@app.post("/workspaces/{workspace_id}/prep-work/{ticket_id}/decide", dependencies=[Depends(_workspace_gate), Depends(_prep_work_gate)])
async def decide_preparation_work(request: Request, workspace_id: UUID, ticket_id: UUID,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
    port: CoreCaptureAdmissionPort | None = Depends(_capture_connection)):
    from cosmas_os.application.capture_deadline import run_in_threadpool
    body = await read_capture_request(request, PrepWorkDecision)
    await run_in_threadpool(_refresh_prep_work_identity, request, session, identity)
    command = body.model_dump(mode="json", exclude_none=True)
    args = (session, identity.box_id, identity.principal_id, str(workspace_id), str(ticket_id), command)
    recovered = await run_in_threadpool(prep_work.recover_decision, *args)
    if recovered is not None:
        return recovered
    if body.choice == "reject":
        return await run_in_threadpool(prep_work.decide, *args)
    _prep_gate()
    return await _execute_workspace_capture(request, workspace_id, session, identity, port,
        EncounterPrepRequest(idempotency_key="prep-work-approval", bot=body.bot),
        finalize_prep=lambda checked: prep_work.decide(*args, checked))


@app.post("/workspaces/{workspace_id}/prep-work/{ticket_id}/verify", dependencies=[Depends(_workspace_gate), Depends(_prep_work_gate)])
async def verify_preparation_work(request: Request, workspace_id: UUID, ticket_id: UUID,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
    port: CoreCaptureAdmissionPort | None = Depends(_capture_connection)):
    from cosmas_os.application.capture_deadline import run_in_threadpool
    body = await read_capture_request(request, PrepWorkVerify)
    await run_in_threadpool(_refresh_prep_work_identity, request, session, identity)
    command = body.model_dump(mode="json", exclude_none=True)
    args = (session, identity.box_id, identity.principal_id, str(workspace_id), str(ticket_id), command)
    recovered = await run_in_threadpool(prep_work.recover_verification, *args)
    if recovered is not None:
        return recovered
    _prep_gate()
    return await _execute_workspace_capture(request, workspace_id, session, identity, port,
        EncounterPrepRequest(idempotency_key=body.idempotency_key, bot=body.bot),
        finalize_prep=lambda checked: prep_work.verify(*args, checked))


async def _with_current_core_note(request: Request, workspace_id: UUID, session: Session,
    identity: RequestIdentity, port: CoreCaptureAdmissionPort | None,
    apply: Callable[[CoreDraftReceipt | None], Any], *, selected: CoreDraftReference | None = None,
    note_id: str | None = None, ticket_id: str | None = None):
    from cosmas_os.application.capture_deadline import run_in_threadpool
    if selected is None:
        selected = await run_in_threadpool(core_note_review.selected_source, session,
            identity.box_id, identity.principal_id, str(workspace_id), note_id=note_id, ticket_id=ticket_id)
    if selected is None:
        return await run_in_threadpool(apply, None)
    _capture_note_gate()

    def finalize(receipt: BaseModel):
        if not isinstance(receipt, CoreDraftReceipt):
            raise ws.WorkspaceError("capture_request_unconfirmed", 503)
        core_note_review.compare(selected, receipt)
        return apply(receipt)

    return await _execute_workspace_capture(request, workspace_id, session, identity, port,
        CaptureNoteRequest(idempotency_key="verify-core-note", session_id=selected.session_id,
            note=CoreNoteSelection(action="read", schema_ref=selected.schema_ref)), finalize)


@app.post("/workspaces/{workspace_id}/capture/note-links", dependencies=[Depends(_workspace_gate), Depends(_capture_note_gate)])
async def link_core_note(request: Request, workspace_id: UUID,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
    port: CoreCaptureAdmissionPort | None = Depends(_capture_connection)):
    body = await read_capture_request(request, CoreNoteLink)
    return await _with_current_core_note(request, workspace_id, session, identity, port,
        lambda checked: core_note_review.import_saved(session, identity.box_id, identity.principal_id,
            str(workspace_id), expected=body.expected_revision, key=body.idempotency_key,
            base_note_id=str(body.base_note_id) if body.base_note_id else None,
            selected=body.source, checked=checked), selected=body.source)


@app.post("/workspaces/{workspace_id}/capture/admission", dependencies=[Depends(_workspace_gate), Depends(_capture_gate)])
async def admit_workspace_capture(request: Request, workspace_id: UUID,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
    port: CoreCaptureAdmissionPort = Depends(_capture_connection)):
    body = await read_capture_request(request, CaptureAdmissionRequest)
    if body.configured_capture is not None:
        _capture_note_gate()
    receipt = await _execute_workspace_capture(request, workspace_id, session, identity, port, body)
    if not isinstance(receipt, CoreCaptureAdmissionSnapshot):
        raise ws.WorkspaceError("capture_request_unconfirmed", 503)
    return JSONResponse(content={"status": "prepared", "session_id": str(receipt.session_id),
        "consent_record_id": str(receipt.consent_record_id), "workspace_id": str(receipt.workspace_id),
        **({"configured_capture": receipt.configured_capture.model_dump(mode="json")} if receipt.configured_capture is not None else {})},
        headers={"Cache-Control": "no-store"})


@app.post("/workspaces/{workspace_id}/capture/operations", dependencies=[Depends(_workspace_gate), Depends(_capture_gate)])
async def perform_workspace_capture(request: Request, workspace_id: UUID,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
    port: CoreCaptureAdmissionPort = Depends(_capture_connection)):
    body = await read_capture_request(request, CaptureOperationRequest)
    if body.operation.kind in {"creator_review", "decide_translation", "source_start", "source_extend"}:
        _capture_note_gate()
    if body.operation.kind in {"select_capture_profile", "source_extend"} and not settings.workspace_capture_long_visits_enabled:
        raise HTTPException(404, "not found", headers={"Cache-Control": "no-store"})
    if body.operation.kind in {"capture_source", "correct_capture_source"} and not (
        settings.workspace_capture_source_enabled and settings.workspace_capture_notes_enabled
        and settings.workspace_capture_corrections_enabled
    ):
        raise HTTPException(404, "not found", headers={"Cache-Control": "no-store"})
    if body.operation.kind in {"recover_capture", "capture_recovery_state"} and not (
        settings.workspace_capture_recovery_enabled
    ):
        raise HTTPException(404, "not found", headers={"Cache-Control": "no-store"})
    if body.operation.kind in {"working_transcript", "correct_transcript"} and not (
        settings.workspace_capture_notes_enabled and settings.workspace_capture_corrections_enabled
    ):
        raise HTTPException(404, "not found", headers={"Cache-Control": "no-store"})
    receipt = await _execute_workspace_capture(request, workspace_id, session, identity, port, body)
    return JSONResponse(content={"session_id": str(body.session_id), "workspace_id": str(workspace_id),
        "operation": body.operation.kind, "receipt": receipt.model_dump(mode="json")},
        headers={"Cache-Control": "no-store"})


@app.post("/workspaces/{workspace_id}/capture/notes", dependencies=[Depends(_workspace_gate), Depends(_capture_note_gate)])
async def workspace_capture_note(request: Request, workspace_id: UUID,
    session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
    port: CoreCaptureAdmissionPort = Depends(_capture_connection)):
    body = await read_capture_request(request, CaptureNoteRequest)
    receipt = await _execute_workspace_capture(request, workspace_id, session, identity, port, body)
    return JSONResponse(content={"session_id": str(body.session_id), "workspace_id": str(workspace_id),
        "action": body.note.action, "receipt": receipt.model_dump(mode="json")},
        headers={"Cache-Control": "no-store"})


@app.get("/provider-team", dependencies=[Depends(_workspace_gate)])
def read_provider_team(request: Request, session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity)):
    compatible = contract_header(request)
    value = provider_team.read(session, identity.box_id, identity.principal_id)
    team_setup.require_compatible(compatible, value["configuration"])
    return _team_recovery_scope(value, identity)


@app.get("/provider-team/setup", dependencies=[Depends(_workspace_gate)])
def read_provider_team_setup(request: Request, session: Session = Depends(get_session),
                             identity: RequestIdentity = Depends(_identity)):
    compatible = contract_header(request, required=True)
    if request.query_params:
        raise ws.WorkspaceError("invalid_team_setup_request", 422)
    value = team_setup.setup(session, identity.box_id, identity.principal_id, identity.external_identity_id, contract=compatible)
    value["team"] = _team_recovery_scope(value["team"], identity)
    return value


@app.get("/provider-team/resources", dependencies=[Depends(_workspace_gate)])
def read_team_resources(request: Request, session: Session = Depends(get_session),
                        identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.application import team_resources
    if contract_header(request, required=True) < 2:
        raise ws.WorkspaceError("team_contract_required", 426)
    if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
        raise ws.WorkspaceError("workspace_access_denied", 403)
    if request.query_params:
        raise ws.WorkspaceError("invalid_team_setup_request", 422)
    return team_resources.inventory(session, identity.box_id, identity.principal_id, identity.external_identity_id)


@app.get("/provider-team/usage", dependencies=[Depends(_workspace_gate)])
def read_team_usage(request: Request, session: Session = Depends(get_session),
                    identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.application import model_work
    if contract_header(request, required=True) < 2:
        raise ws.WorkspaceError("team_contract_required", 426)
    if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
        raise ws.WorkspaceError("workspace_access_denied", 403)
    if request.query_params:
        raise ws.WorkspaceError("invalid_team_setup_request", 422)
    ws._human(session, identity.box_id, identity.principal_id)
    return model_work.usage(session, identity.box_id, identity.principal_id)


def _refresh_team_identity(request, session, identity):
    _workspace_gate(Response(), request)
    session.expire_all()
    if _identity(request=request, session=session, authorization=request.headers.get("authorization"),
        x_box_id=request.headers.get("x-box-id"), x_actor_principal_id=request.headers.get("x-actor-principal-id")) != identity:
        raise ws.WorkspaceError("workspace_access_denied", 403)


@app.post("/provider-team/rehearsal", dependencies=[Depends(_workspace_gate)])
async def rehearse_provider_team(request: Request, session: Session = Depends(get_session),
                                identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.application.capture_deadline import run_in_threadpool
    compatible = contract_header(request, required=True)
    body = await read_team_request(request, TeamRehearsalRequest)
    if body.scenario_id != ('team_policy_setup.v1' if compatible >= 2 else 'preset_setup.v1'):
        raise ws.WorkspaceError('invalid_team_setup_request', 422)
    def evaluate():
        _refresh_team_identity(request, session, identity)
        return team_setup.rehearsal(session, identity.box_id, identity.principal_id,
            identity.external_identity_id, expected=body.expected_revision,
            configuration=body.configuration.model_dump(mode="json"), contract=compatible)
    return await run_in_threadpool(evaluate)


def _team_recovery_scope(value, identity: RequestIdentity):
    # An opaque local-storage namespace, not a credential or an access grant.
    # Emit it only after the current signed identity and human team access pass.
    if identity.auth_mode == "clerk_jwt" and identity.external_identity_id is not None:
        from cosmas_os.domain.hashing import payload_hash

        return {**value, "recovery_scope": payload_hash({"contract": "cosmas-private-drafts-v1",
            "box_id": identity.box_id, "owner_id": identity.principal_id})}
    return value


@app.middleware("http")
async def routine_contract_boundary(request: Request, call_next):
    import re

    values = request.headers.getlist("x-cosmas-routine-contract")
    if values:
        ident = r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"
        path = rf"/provider-team/routines/(?:chief|scribe|visit_prep|follow_up|{ident})/runs/{ident}"
        if request.method != "GET" or not re.fullmatch(path, request.url.path) or values != ["2"]:
            return JSONResponse({"detail": "routine_contract_required"}, status_code=426,
                headers={"Cache-Control": "no-store"})
    return await call_next(request)


def _routine_gate():
    if not settings.workspace_routines_enabled:
        raise HTTPException(404, "not found", headers={"Cache-Control": "no-store"})


@app.get("/provider-team/routines/{bot}", dependencies=[Depends(_workspace_gate), Depends(_routine_gate)])
def read_routine(bot: BotAddress, session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity)):
    return routines.read(session, identity.box_id, identity.principal_id, bot)


@app.get("/provider-team/routines/{bot}/runs/{run_id}", dependencies=[Depends(_workspace_gate), Depends(_routine_gate)])
def read_routine_run(request: Request, bot: BotAddress, run_id: UUID, session: Session = Depends(get_session),
                     identity: RequestIdentity = Depends(_identity)):
    values = request.headers.getlist("x-cosmas-routine-contract")
    if len(values) > 1 or values and values != ["2"]:
        raise ws.WorkspaceError("routine_contract_required", 426)
    if request.url.query or "content-encoding" in request.headers or "transfer-encoding" in request.headers or request.headers.get("content-length", "0") != "0":
        raise ws.WorkspaceError("invalid_routine_read", 422)
    contract = 2 if values else 1
    if contract == 2:
        if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
            raise ws.WorkspaceError("routine_access_unavailable", 403)
        def check():
            _refresh_team_identity(request, session, identity)
        session.info["routine_final_authority"] = check
        session.info["inbox_handoff_final_authority"] = check
    try:
        return routines.read_run(session, identity.box_id, identity.principal_id, bot, str(run_id),
            contract=contract, incoming_sources=_routine_sources())
    finally:
        session.info.pop("routine_final_authority", None)
        session.info.pop("inbox_handoff_final_authority", None)


@app.post("/provider-team/routines/{bot}", dependencies=[Depends(_workspace_gate), Depends(_routine_gate)])
async def save_routine(request: Request, bot: BotAddress, session: Session = Depends(get_session),
                       identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.api.routine_schemas import RoutineSave
    from cosmas_os.application.capture_deadline import run_in_threadpool
    # Require signed identity, bounded duplicate-free JSON, then recheck the
    # identity and switches after the body arrives.
    if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
        raise ws.WorkspaceError("routine_access_unavailable", 403)
    body = await read_capture_request(request, RoutineSave)
    def save_current():
        _routine_gate()
        if _identity(request=request, session=session, authorization=request.headers.get("authorization"),
                     x_box_id=None, x_actor_principal_id=None) != identity:
            raise ws.WorkspaceError("routine_access_unavailable", 403)
        return routines.save(session, identity.box_id, identity.principal_id, bot,
            expected=body.expected_revision, team_revision=body.team_revision,
            key=body.idempotency_key, configuration=body.configuration.model_dump(mode="json"))
    return await run_in_threadpool(save_current)


@app.post("/provider-team", dependencies=[Depends(_workspace_gate)])
async def save_provider_team(request: Request, session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.application.capture_deadline import run_in_threadpool
    compatible = contract_header(request)
    body = await read_team_request(request, TeamSave)
    def save_current():
        _refresh_team_identity(request, session, identity)
        return _team_recovery_scope(provider_team.save(session, identity.box_id, identity.principal_id,
            expected=body.expected_revision, key=body.idempotency_key, configuration=body.configuration.model_dump(mode="json"),
            setup_review=body.setup_review.model_dump(mode="json") if body.setup_review else None,
            external_identity_id=identity.external_identity_id, team_contract=compatible), identity)
    return await run_in_threadpool(save_current)


def _refresh_model_identity(request, session, identity):
    try:
        _refresh_team_identity(request, session, identity)
    except HTTPException as error:
        # Admission settlement must retain observed usage even when the signed
        # identity expires or is revoked while the provider is responding.
        raise ws.WorkspaceError("workspace_access_denied", error.status_code) from None


def _session_prep_analysis_sources(request, session, identity, workspace_id, body):
    from uuid import uuid5

    from cosmas_os.api.capture_schemas import CaptureBotSelection
    from cosmas_os.application import session_prep, session_prep_analysis

    def current():
        _refresh_model_identity(request, session, identity)
        if not settings.workspace_session_prep_available:
            raise ws.WorkspaceError("session_prep_analysis_unavailable", 503)
        if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
            raise ws.WorkspaceError("session_prep_access_unavailable", 403)

    def read(phase):
        current()
        budget = current_budget()
        if budget is None:
            raise ws.WorkspaceError("session_prep_analysis_unavailable", 503)
        with session_prep_connection(settings, budget) as port:
            return session_prep.read(
                session, box=identity.box_id, owner=identity.principal_id,
                external_identity_id=identity.external_identity_id, workspace_id=str(workspace_id),
                bot=CaptureBotSelection(address=body.role, team_revision=body.team_revision),
                bearer=SecretStr(request.headers["authorization"].partition(" ")[2]),
                idempotency_key=str(uuid5(workspace_id, f"prep-chat:{body.idempotency_key}:{phase}")),
                reauthenticate=current, port=port,
            )["receipt"]

    return session_prep_analysis.Sources(
        str(workspace_id), identity.box_id, identity.principal_id, body.role,
        body.team_revision, body.session_prep_analysis.model_dump(mode="json"), read,
    )


@app.post("/workspaces/{workspace_id}/conversation", dependencies=[Depends(_workspace_gate)])
async def converse(request: Request, workspace_id: UUID, session: Session = Depends(get_session),
                   identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.api.model_work_schemas import contract_header as model_header
    from cosmas_os.api.model_work_schemas import read_model_request
    from cosmas_os.application.capture_deadline import run_in_threadpool
    negotiated = model_header(request)
    body = await read_model_request(request, ConversationRequest)
    def submit():
        if body.inbox_analysis:
            session.info["inbox_analysis_sources"] = _inbox_analysis_sources()
        if body.session_prep_analysis:
            session.info["session_prep_analysis_sources"] = _session_prep_analysis_sources(
                request, session, identity, workspace_id, body
            )
        value = conversation.ask(session, identity.box_id, identity.principal_id, str(workspace_id),
            expected=body.expected_revision, team_revision=body.team_revision, key=body.idempotency_key,
            role=body.role, content=body.content, model_contract=negotiated,
            research_analysis=body.research_analysis.model_dump(mode="json") if body.research_analysis else None,
            inbox_analysis=body.inbox_analysis.model_dump(mode="json") if body.inbox_analysis else None,
            membership_analysis=body.membership_analysis.model_dump(mode="json") if body.membership_analysis else None,
            session_prep_analysis=body.session_prep_analysis.model_dump(mode="json") if body.session_prep_analysis else None,
            external_identity_id=identity.external_identity_id,
            reauthenticate=lambda: _refresh_model_identity(request, session, identity))
        return JSONResponse(value, status_code=409 if negotiated and value["outcome"] != "saved" else 200,
                            headers={"Cache-Control": "no-store"})
    return await run_in_threadpool(submit)


@app.post("/workspaces/{workspace_id}/conversation/resolve", dependencies=[Depends(_workspace_gate)])
async def resolve_conversation(request: Request, workspace_id: UUID, session: Session = Depends(get_session),
                               identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.api.model_work_schemas import contract_header as model_header
    from cosmas_os.api.model_work_schemas import read_model_request
    from cosmas_os.application import model_work
    from cosmas_os.application.capture_deadline import run_in_threadpool
    model_header(request, required=True)
    body = await read_model_request(request, ConversationRequest)
    def observe():
        session.rollback()
        session.execute(text("SET TRANSACTION READ ONLY"))
        value = model_work.resolve_conversation(session, identity.box_id, identity.principal_id, str(workspace_id),
            expected=body.expected_revision, team_revision=body.team_revision, key=body.idempotency_key,
            role=body.role, content=body.content, external_identity_id=identity.external_identity_id,
            research_analysis=body.research_analysis.model_dump(mode="json") if body.research_analysis else None,
            inbox_analysis=body.inbox_analysis.model_dump(mode="json") if body.inbox_analysis else None,
            membership_analysis=body.membership_analysis.model_dump(mode="json") if body.membership_analysis else None,
            session_prep_analysis=body.session_prep_analysis.model_dump(mode="json") if body.session_prep_analysis else None,
            reauthenticate=lambda: _refresh_model_identity(request, session, identity))
        return JSONResponse(value, headers={"Cache-Control": "no-store"})
    return await run_in_threadpool(observe)


@app.post("/workspaces", dependencies=[Depends(_workspace_gate)])
def create_workspace(body: WorkspaceCreate, session: Session = Depends(get_session),
                     identity: RequestIdentity = Depends(_identity)):
    return ws.create(session, identity.box_id, identity.principal_id,
                     str(body.appointment_id), body.idempotency_key,
                     initial_synthetic_source=settings.cosmas_env == "synth_os")


@app.post("/workspaces/{workspace_id}/handoffs/{handoff_id}/retry", dependencies=[Depends(_workspace_gate)])
async def retry_handoff(request: Request, workspace_id: UUID, handoff_id: UUID,
                        session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.api.model_work_schemas import contract_header as model_header
    from cosmas_os.api.model_work_schemas import read_model_request
    from cosmas_os.application.capture_deadline import run_in_threadpool
    model_header(request, required=True)
    body = await read_model_request(request, HandoffRetry)
    def submit():
        value = handoffs.retry(session, identity.box_id, identity.principal_id, str(workspace_id), str(handoff_id),
            expected=body.expected_revision, previous_attempt=str(body.previous_attempt_id), key=body.idempotency_key,
            external_identity_id=identity.external_identity_id,
            reauthenticate=lambda: _refresh_model_identity(request, session, identity))
        return JSONResponse(value, headers={"Cache-Control": "no-store"})
    return await run_in_threadpool(submit)


@app.post("/workspaces/{workspace_id}/handoffs/{handoff_id}/retry/resolve", dependencies=[Depends(_workspace_gate)])
async def resolve_handoff_retry(request: Request, workspace_id: UUID, handoff_id: UUID,
                                session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.api.model_work_schemas import contract_header as model_header
    from cosmas_os.api.model_work_schemas import read_model_request
    from cosmas_os.application import model_work
    from cosmas_os.application.capture_deadline import run_in_threadpool
    model_header(request, required=True)
    body = await read_model_request(request, HandoffRetry)
    def observe():
        session.rollback()
        session.execute(text("SET TRANSACTION READ ONLY"))
        value = model_work.resolve_retry(session, identity.box_id, identity.principal_id, str(workspace_id), str(handoff_id),
            expected=body.expected_revision, previous_attempt=str(body.previous_attempt_id), key=body.idempotency_key,
            external_identity_id=identity.external_identity_id,
            reauthenticate=lambda: _refresh_model_identity(request, session, identity))
        return JSONResponse(value, headers={"Cache-Control": "no-store"})
    return await run_in_threadpool(observe)


@app.get("/workspaces/{workspace_id}", dependencies=[Depends(_workspace_gate)])
def read_workspace(request: Request, workspace_id: UUID, session: Session = Depends(get_session),
                   identity: RequestIdentity = Depends(_identity)):
    from sqlalchemy import select

    from cosmas_os.api.model_work_schemas import contract_header as model_header
    from cosmas_os.application import model_work
    from cosmas_os.models import ModelWorkAdmission
    negotiated = model_header(request)
    if request.query_params:
        raise ws.WorkspaceError("invalid_model_request", 422)
    value = ws.read(session, identity.box_id, identity.principal_id, str(workspace_id))
    if negotiated:
        value = model_work.project_workspace(session, value)
    elif session.scalar(select(ModelWorkAdmission.id).where(ModelWorkAdmission.workspace_id == str(workspace_id)).limit(1)):
        raise ws.WorkspaceError("model_contract_required", 426)
    return value


@app.post("/workspaces/{workspace_id}/notes", dependencies=[Depends(_workspace_gate)])
def save_private_note(workspace_id: UUID, body: NoteSave, session: Session = Depends(get_session),
                      identity: RequestIdentity = Depends(_identity)):
    return note_review.save(session, identity.box_id, identity.principal_id, str(workspace_id),
        expected=body.expected_revision, key=body.idempotency_key,
        base_note_id=str(body.base_note_id) if body.base_note_id else None,
        source_reply_id=str(body.source_reply_id) if body.source_reply_id else None,
        content=body.content, sources_reconciled=body.sources_reconciled)


@app.post("/workspaces/{workspace_id}/notes/{note_id}/review", dependencies=[Depends(_workspace_gate)])
async def review_private_note(request: Request, workspace_id: UUID, note_id: UUID, body: NoteReview,
                        session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
                        port: CoreCaptureAdmissionPort | None = Depends(_capture_connection)):
    return await _with_current_core_note(request, workspace_id, session, identity, port,
        lambda checked: note_review.review(session, identity.box_id, identity.principal_id, str(workspace_id),
        str(note_id), expected=body.expected_revision, key=body.idempotency_key,
        content_hash=body.content_hash, source_hash=body.source_fingerprint, core_checked=checked,
        gap_acknowledgment=body.gap_acknowledgment), note_id=str(note_id))


@app.post("/workspaces/{workspace_id}/follow-ups", dependencies=[Depends(_workspace_gate)])
async def propose_follow_up(request: Request, workspace_id: UUID, body: FollowUpPropose,
                      session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
                      port: CoreCaptureAdmissionPort | None = Depends(_capture_connection)):
    return await _with_current_core_note(request, workspace_id, session, identity, port,
        lambda checked: follow_up.propose(session, identity.box_id, identity.principal_id, str(workspace_id),
        expected=body.expected_revision, key=body.idempotency_key, note_id=str(body.note_id),
        body=body.body, due_date=body.due_date, expected_outcome=body.expected_outcome, share=body.share,
        core_checked=checked), note_id=str(body.note_id))


@app.post("/workspaces/{workspace_id}/follow-ups/{ticket_id}/decide", dependencies=[Depends(_workspace_gate)])
async def decide_follow_up(request: Request, workspace_id: UUID, ticket_id: UUID, body: FollowUpDecision,
                     session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity),
                     port: CoreCaptureAdmissionPort | None = Depends(_capture_connection)):
    from cosmas_os.application.capture_deadline import run_in_threadpool
    def decide(checked):
        return follow_up.decide(session, identity.box_id, identity.principal_id, str(workspace_id), str(ticket_id),
            revision_id=str(body.revision_id), digest=body.payload_hash, choice=body.choice,
            core_checked=checked, defer_delivery=checked is not None)
    # Withdrawal of an unexecuted approval stays available if Core is unavailable.
    if body.choice == "reject":
        return await run_in_threadpool(decide, None)
    result = await _with_current_core_note(request, workspace_id, session, identity, port,
        decide, ticket_id=str(ticket_id))
    item = next(item for item in result["workspace"]["follow_ups"] if item["ticket_id"] == str(ticket_id))
    if item["operation_status"] != "pending":
        return result
    return await _with_current_core_note(request, workspace_id, session, identity, port,
        lambda checked: follow_up.deliver(session, identity.box_id, identity.principal_id,
            str(workspace_id), str(ticket_id), revision_id=str(body.revision_id), digest=body.payload_hash,
            core_checked=checked), ticket_id=str(ticket_id))


@app.post("/workspaces/{workspace_id}/follow-ups/{ticket_id}/complete", dependencies=[Depends(_workspace_gate)])
def complete_follow_up(workspace_id: UUID, ticket_id: UUID, body: FollowUpComplete,
                       session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity)):
    return follow_up.complete(session, identity.box_id, identity.principal_id, str(workspace_id), str(ticket_id),
        revision_id=str(body.revision_id), digest=body.payload_hash, key=body.idempotency_key, evidence=body.evidence)


@app.get("/practice-work", dependencies=[Depends(_workspace_gate)])
def list_practice_work(request: Request, session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.api.vendor_routes import negotiated
    return shared_work.catalog(session, identity.box_id, identity.principal_id, vendor=negotiated(request))


@app.get("/practice-work/pages/{cursor}", dependencies=[Depends(_workspace_gate)])
def page_practice_work(request: Request, cursor: UUID, session: Session = Depends(get_session),
                       identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.api.vendor_routes import negotiated
    return shared_work.catalog(session, identity.box_id, identity.principal_id, after=str(cursor), vendor=negotiated(request))


@app.get("/practice-work/{ticket_id}", dependencies=[Depends(_workspace_gate)])
def read_practice_work(request: Request, ticket_id: UUID, session: Session = Depends(get_session),
                       identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.api.vendor_routes import negotiated
    return shared_work.read(session, identity.box_id, identity.principal_id, str(ticket_id), vendor=negotiated(request))


@app.post("/practice-work/{ticket_id}/handoffs", dependencies=[Depends(_workspace_gate)])
async def handoff_practice_work(request: Request, ticket_id: UUID,
                          session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity)):
    from cosmas_os.api import vendor_work_schemas as vendor_schema
    from cosmas_os.api.vendor_routes import command, negotiated
    from cosmas_os.application import vendor_shared
    if negotiated(request):
        async def apply():
            body = await command(request, vendor_schema.VendorHandoff)
            return await app.state.vendor_run(request, session, identity, lambda: vendor_shared.handoff(
                session, identity.box_id, identity.principal_id, str(ticket_id), body))
        return await app.state.vendor_protected(apply)
    # Preserve the exact existing shape and validation for non-vendor work.
    try:
        body = WorkHandoffCommand.model_validate(await request.json())
    except (ValueError, TypeError):
        raise ws.WorkspaceError("invalid_workspace_request", 422) from None
    return shared_work.act(session, identity.box_id, identity.principal_id, str(ticket_id),
        expected=body.expected_version, revision_id=str(body.revision_id), digest=body.payload_hash,
        key=body.idempotency_key, kind=body.kind,
        recipient=str(body.recipient_id) if body.recipient_id else None,
        offer_id=str(body.offer_id) if body.offer_id else None)


@app.post("/practice-work/{ticket_id}/complete", dependencies=[Depends(_workspace_gate)])
def complete_practice_work(ticket_id: UUID, body: FollowUpComplete,
                           session: Session = Depends(get_session), identity: RequestIdentity = Depends(_identity)):
    return shared_work.complete(session, identity.box_id, identity.principal_id, str(ticket_id),
        revision_id=str(body.revision_id), digest=body.payload_hash, key=body.idempotency_key,
        evidence=body.evidence, expected=body.expected_version)


@app.post("/workspaces/{workspace_id}/entries", dependencies=[Depends(_workspace_gate)])
def append_workspace(workspace_id: UUID, body: WorkspaceAppend, session: Session = Depends(get_session),
                     identity: RequestIdentity = Depends(_identity)):
    return ws.append(session, identity.box_id, identity.principal_id, str(workspace_id),
        expected=body.expected_revision, key=body.idempotency_key, kind=body.kind,
        content=body.content, source_label=body.source_label)


@app.post("/workspaces/{workspace_id}/work-links", dependencies=[Depends(_workspace_gate)])
def link_workspace_work(workspace_id: UUID, body: WorkspaceWorkLink, session: Session = Depends(get_session),
                        identity: RequestIdentity = Depends(_identity)):
    return ws.append(session, identity.box_id, identity.principal_id, str(workspace_id),
        expected=body.expected_revision, key=body.idempotency_key, kind="work_link",
        ticket_id=str(body.ticket_id))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.cosmas_env}


@app.get("/ready")
def ready(request: Request, session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        settings.validate_runtime_configuration()
        if not workspace_workers_ready(request.app, settings):
            raise RuntimeError("workspace workers are not progressing")
        session.execute(text("SELECT 1"))
        revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != EXPECTED_SCHEMA_REVISION:
            raise RuntimeError("database schema is not current")
        if settings.execution_backend == "postgres_local":
            from cosmas_os.compact.schema import worker_is_ready

            if not worker_is_ready(session):
                raise RuntimeError("compact worker is not progressing")
    except Exception as exc:  # noqa: BLE001 — readiness must fail closed
        raise HTTPException(status_code=503, detail="runtime is not ready") from exc
    return {"status": "ready", "env": settings.cosmas_env}


@app.post("/synth/seed", response_model=SeedResponse)
def seed(session: Session = Depends(get_session)) -> Any:
    if settings.cosmas_env != "synth_os" or not settings.synth_seed or settings.auth_mode != "synth_headers":
        raise HTTPException(status_code=404, detail="not found")
    from cosmas_os.application.seed import seed_synth

    return seed_synth(session)


@app.post("/synth/demo-queue", response_model=DemoSeedResponse)
def seed_demo_queue(session: Session = Depends(get_session)) -> Any:
    if settings.cosmas_env != "synth_os" or not settings.synth_seed or settings.auth_mode != "synth_headers":
        raise HTTPException(status_code=404, detail="not found")
    from cosmas_os.application.seed import seed_synth_work_queue

    return seed_synth_work_queue(session)


@app.get("/queue", response_model=list[QueueItem])
def queue(
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> Any:
    c = svc.Container(session)
    items = svc.list_queue(c, identity.box_id)
    if settings.execution_backend == "postgres_local":
        from sqlalchemy import select

        from cosmas_os.models import Operation

        statuses = {ticket_id: status for ticket_id, status in session.execute(
            select(Operation.ticket_id, Operation.status).where(Operation.box_id == identity.box_id)
        )}
        for item in items:
            item["execution_status"] = statuses.get(item["id"])
    return items


@app.post("/schedule/import")
def schedule_import(
    body: ImportBody,
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> Any:
    _require_data_entry_authorized()
    c = svc.Container(session)
    ids = svc.import_schedule(c, identity.box_id, body.csv_text)
    return {"appointment_ids": ids}


@app.post("/patient-links/attest")
def attest(
    body: AttestBody,
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> Any:
    try:
        _require_data_entry_authorized()
        c = svc.Container(session)
        link = svc.attest_patient_link(
            c,
            identity.box_id,
            identity.principal_id,
            body.source_pair_key,
            body.label,
        )
        return {"id": link.id, "state": link.state}
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.post("/chase/open")
def open_chase(
    appointment_id: str,
    patient_link_id: str,
    chaser_id: str,
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> Any:
    try:
        _require_data_entry_authorized()
        c = svc.Container(session)
        ticket = svc.detect_and_open_chase(
            c,
            identity.box_id,
            chaser_id,
            appointment_id,
            patient_link_id,
        )
        return {"ticket_id": ticket.id, "state": ticket.state, "revision_id": ticket.current_revision_id}
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.post("/tickets/{ticket_id}/edit")
def edit_ticket(
    ticket_id: str,
    body: EditBody,
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> Any:
    try:
        # The synthetic Beta Lab is seeded with invented work specifically so
        # testers can exercise the human edit/approval loop. New schedules,
        # patient links, chases, and uploads remain blocked in synthetic mode.
        c = svc.Container(session)
        rev = svc.edit_revision(c, ticket_id, identity.principal_id, body.body)
        return {"revision_id": rev.id, "payload_hash": rev.payload_hash}
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.post("/tickets/{ticket_id}/decide")
def decide_ticket(
    ticket_id: str,
    body: DecideBody,
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> Any:
    try:
        if body.note:
            _require_data_entry_authorized()
        c = svc.Container(session)
        return svc.decide(
            c,
            ticket_id,
            identity.principal_id,
            body.kind,
            expected_revision_id=body.expected_revision_id,
            note=body.note,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.post("/tickets/{ticket_id}/upload-verify")
def upload_verify(
    ticket_id: str,
    body: UploadBody,
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> Any:
    import base64
    import binascii

    try:
        _require_data_entry_authorized()
        try:
            front = base64.b64decode(body.front_b64, validate=True)
            back = base64.b64decode(body.back_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid image encoding") from exc
        if any(len(image) > 8_000_000 or not image.startswith(b"\x89PNG\r\n\x1a\n") for image in (front, back)):
            raise HTTPException(status_code=400, detail="only bounded PNG images are accepted")
        c = svc.Container(session)
        return svc.simulate_upload_and_verify(
            c,
            ticket_id,
            identity.principal_id,
            front,
            back,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.post("/tickets/{ticket_id}/close")
def close_ticket(
    ticket_id: str,
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> Any:
    try:
        c = svc.Container(session)
        t = svc.close_ticket(c, ticket_id, identity.principal_id)
        return {"id": t.id, "state": t.state}
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.get("/tickets/{ticket_id}/timeline")
def timeline(
    ticket_id: str,
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> Any:
    try:
        c = svc.Container(session)
        return svc.audit_timeline(c, identity.box_id, ticket_id)
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.post("/retention/purge")
def purge(
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> Any:
    try:
        c = svc.Container(session)
        return {
            "receipts": svc.purge_due_artifacts(
                c,
                identity.box_id,
                identity.principal_id,
            )
        }
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.post("/admin/identities/bind")
def bind_identity(
    body: IdentityBindBody,
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> dict[str, str]:
    from cosmas_os.application.beta_identity_admin import bind_beta_identity

    try:
        bind_beta_identity(
            session,
            settings,
            actor_principal_id=identity.principal_id,
            clerk_subject=body.clerk_subject,
            display_name=body.display_name,
            evidence_ref=body.evidence_ref,
        )
        return {"status": "bound"}
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.get("/admin/identities", response_model=list[IdentitySummaryResponse])
def list_identities(
    response: Response,
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> list[IdentitySummaryResponse]:
    from cosmas_os.application.beta_identity_admin import list_beta_identities

    try:
        response.headers["Cache-Control"] = "no-store"
        return [
            IdentitySummaryResponse.model_validate(entry, from_attributes=True)
            for entry in list_beta_identities(
                session,
                settings,
                actor_principal_id=identity.principal_id,
            )
        ]
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.post("/admin/identities/deactivate")
def deactivate_identity(
    body: IdentityChangeBody,
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> dict[str, str]:
    from cosmas_os.application.beta_identity_admin import deactivate_beta_identity

    try:
        deactivate_beta_identity(
            session,
            settings,
            actor_principal_id=identity.principal_id,
            clerk_subject=body.clerk_subject,
            evidence_ref=body.evidence_ref,
        )
        return {"status": "deactivated"}
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.post("/admin/identities/reactivate")
def reactivate_identity(
    body: IdentityChangeBody,
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> dict[str, str]:
    from cosmas_os.application.beta_identity_admin import reactivate_beta_identity

    try:
        reactivate_beta_identity(
            session,
            settings,
            actor_principal_id=identity.principal_id,
            clerk_subject=body.clerk_subject,
            evidence_ref=body.evidence_ref,
        )
        return {"status": "reactivated"}
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.post("/admin/owner/transfer")
def transfer_owner(
    body: IdentityChangeBody,
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> dict[str, str]:
    from cosmas_os.application.beta_identity_admin import transfer_beta_ownership

    try:
        transfer_beta_ownership(
            session,
            settings,
            actor_principal_id=identity.principal_id,
            successor_clerk_subject=body.clerk_subject,
            evidence_ref=body.evidence_ref,
        )
        return {"status": "transferred"}
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.post("/capabilities/{key}/invoke")
def invoke_capability(
    key: CapabilityKey,
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> Any:
    try:
        c = svc.Container(session)
        svc.reject_dark_capability(c, identity.box_id, key)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


def _vendor_execution_factory(request: Request):
    """Explicit service wiring only; no credential or account discovery."""
    runtime = managed_services(request.app)
    return runtime.vendor_execution if runtime is not None and runtime.has_credentials else None


def _vendor_installed_catalog(request: Request):
    from cosmas_os.application.vendor_settings import EMPTY_CATALOG

    runtime = managed_services(request.app)
    return runtime.vendor_catalog if runtime is not None else EMPTY_CATALOG


def _vendor_setup_policy():
    from cosmas_os.application.vendor_settings import VendorSetupPolicy

    return VendorSetupPolicy(enabled=settings.workspace_available and settings.vendor_setup_enabled)


def _vendor_artifact_store(request: Request):
    runtime = managed_services(request.app)
    return runtime.artifact_store if runtime is not None else None


def _vendor_readiness_configuration(request: Request):
    from cosmas_os.application.vendor_readiness import FaxReadinessConfiguration

    runtime = managed_services(request.app)
    return FaxReadinessConfiguration(
        work_enabled=settings.workspace_available and settings.vendor_work_enabled,
        delivery_enabled=settings.workspace_available and settings.vendor_io_enabled,
        credential_access_configured=runtime is not None and runtime.has_credentials,
        document_storage_configured=runtime is not None and runtime.artifact_store is not None,
    )


def _vendor_event_routes(request: Request):
    """Explicit server-only lookup; renderer input cannot select an account."""
    runtime = managed_services(request.app)
    return runtime.vendor_event if runtime is not None and runtime.events is not None else None


def _vendor_reauthenticate(request, session, identity):
    current = _identity(request=request, session=session, authorization=request.headers.get("authorization"),
        x_box_id=request.headers.get("x-box-id"), x_actor_principal_id=request.headers.get("x-actor-principal-id"))
    if current != identity:
        raise ws.WorkspaceError("vendor_work_unavailable", 403)


from cosmas_os.api.vendor_routes import install as install_vendor_routes  # noqa: E402

install_vendor_routes(app, get_session=get_session, identity_dependency=_identity,
    core_connection=_capture_connection, current_core_note=_with_current_core_note,
    execution_factory_dependency=_vendor_execution_factory, artifact_store_dependency=_vendor_artifact_store,
    event_route_dependency=_vendor_event_routes,
    installed_catalog_dependency=_vendor_installed_catalog,
    reauthenticate=_vendor_reauthenticate, session_factory=lambda: new_capture_session(SessionLocal))

from cosmas_os.api.vendor_setup_routes import register as register_vendor_setup  # noqa: E402

register_vendor_setup(app, get_session, _identity, reauthenticate=_vendor_reauthenticate,
    policy_dependency=_vendor_setup_policy, catalog_dependency=_vendor_installed_catalog,
    readiness_dependency=_vendor_readiness_configuration)

from cosmas_os.api.portal_setup_routes import register as register_portal_setup  # noqa: E402


def _portal_installed_catalog(request: Request):
    from cosmas_os.application.portal_setup import EMPTY_CATALOG

    runtime = portal_services(request.app)
    return runtime.catalog if runtime is not None else EMPTY_CATALOG


register_portal_setup(app, get_session, _identity, catalog_dependency=_portal_installed_catalog)


def _portal_work_policy():
    from cosmas_os.application.portal_work import PortalWorkPolicy

    return PortalWorkPolicy(
        enabled=settings.workspace_available and settings.portal_work_enabled,
        io_enabled=settings.workspace_available and settings.portal_io_enabled,
    )


def _portal_work_execution(request: Request):
    """Return the installed factory; each invocation gets fresh request authority."""
    runtime = portal_services(request.app)
    return runtime.execution if runtime is not None and runtime.has_execution else None


from cosmas_os.api.portal_work_routes import register as register_portal_work  # noqa: E402

register_portal_work(app, get_session, _identity,
    policy_dependency=_portal_work_policy, execution_factory_dependency=_portal_work_execution,
    catalog_dependency=_portal_installed_catalog, session_factory=lambda: new_capture_session(SessionLocal),
    core_connection=_capture_connection, current_core_note=_with_current_core_note)


def _finance_policy():
    from cosmas_os.application.finance_work import FinancePolicy

    return FinancePolicy(
        enabled=settings.workspace_available and settings.finance_work_enabled,
        io_enabled=settings.workspace_available and settings.finance_io_enabled,
        events_enabled=settings.workspace_available and settings.finance_events_enabled,
    )


def _finance_execution_factory(request: Request):
    """Exact service wiring is required; no implicit account or credential lookup."""
    runtime = managed_services(request.app)
    return runtime.finance_execution if runtime is not None and runtime.has_credentials else None


def _finance_event_routes(request: Request):
    runtime = managed_services(request.app)
    return runtime.finance_event if runtime is not None and runtime.events is not None else None


def _finance_reauthenticate(request, session, identity):
    current = _identity(request=request, session=session, authorization=request.headers.get("authorization"),
        x_box_id=request.headers.get("x-box-id"), x_actor_principal_id=request.headers.get("x-actor-principal-id"))
    if current != identity:
        raise ws.WorkspaceError("finance_work_unavailable", 403)


from cosmas_os.api.finance_routes import install as install_finance_routes  # noqa: E402

install_finance_routes(app, get_session=get_session, identity_dependency=_identity,
    policy_dependency=_finance_policy, execution_factory_dependency=_finance_execution_factory,
    event_route_dependency=_finance_event_routes, core_connection=_capture_connection,
    current_core_note=_with_current_core_note, reauthenticate=_finance_reauthenticate,
    session_factory=lambda: new_capture_session(SessionLocal))


def _finance_setup_policy():
    from cosmas_os.application.finance_settings import FinanceSetupPolicy

    return FinanceSetupPolicy(enabled=settings.workspace_available and settings.finance_setup_enabled)


from cosmas_os.api.finance_setup_routes import register as register_finance_setup  # noqa: E402

register_finance_setup(app, get_session, _identity,
    policy_dependency=_finance_setup_policy, reauthenticate=_finance_reauthenticate)


def _membership_policy():
    from cosmas_os.application.membership_work import MembershipPolicy

    return MembershipPolicy(
        enabled=settings.workspace_available and settings.membership_work_enabled,
        private_selectors_ready=True,  # Central private-lane selectors qualified before exposure.
    )


def _membership_reauthenticate(request, session, identity):
    current = _identity(request=request, session=session, authorization=request.headers.get("authorization"),
        x_box_id=request.headers.get("x-box-id"), x_actor_principal_id=request.headers.get("x-actor-principal-id"))
    if current != identity:
        raise ws.WorkspaceError("membership_work_unavailable", 403)


from cosmas_os.api.membership_work_routes import register as register_membership_work  # noqa: E402

register_membership_work(app, get_session, _identity,
    policy_dependency=_membership_policy, reauthenticate=_membership_reauthenticate,
    core_connection_dependency=_capture_connection, current_core_note=_with_current_core_note)


def _inbox_policy():
    from cosmas_os.application.inbox_work import InboxPolicy

    return InboxPolicy(enabled=settings.workspace_available and settings.inbox_work_enabled)


def _inbox_registry():
    # Fresh server-installed read authority is separate from outgoing permissions.
    from cosmas_os.application.inbox_work import no_registry

    return no_registry


def _inbox_analysis_sources():
    from cosmas_os.application.inbox_analysis import Sources

    def registry():
        return app.dependency_overrides.get(_inbox_registry, _inbox_registry)()()
    def policy():
        return app.dependency_overrides.get(_inbox_policy, _inbox_policy)()
    return Sources(registry=registry, policy=policy)


def _routine_sources():
    from cosmas_os.application.routine_inbox import Sources

    # The worker and signed reads resolve the same current server configuration.
    # Trusted dependency overrides are fixture/integration configuration only;
    # the product's unconfigured supplier remains the empty reviewed registry.
    def registry():
        return app.dependency_overrides.get(_inbox_registry, _inbox_registry)()()
    def policy():
        return app.dependency_overrides.get(_inbox_handoff_policy, _inbox_handoff_policy)()
    return Sources(registry=registry, policy=policy)


def _inbox_reauthenticate(request, session, identity):
    current = _identity(request=request, session=session, authorization=request.headers.get("authorization"),
        x_box_id=request.headers.get("x-box-id"), x_actor_principal_id=request.headers.get("x-actor-principal-id"))
    if current != identity:
        raise ws.WorkspaceError("inbox_unavailable", 403)


from cosmas_os.api.inbox_work_routes import register as register_inbox_work  # noqa: E402

register_inbox_work(app, get_session, _identity,
    policy_dependency=_inbox_policy, registry_dependency=_inbox_registry,
    reauthenticate=_inbox_reauthenticate)


from cosmas_os.api import inbox_review_routes as _inbox_review_routes  # noqa: E402

_inbox_review_routes.register(app, get_session, _identity,
    policy_dependency=_inbox_policy, registry_dependency=_inbox_registry,
    reauthenticate=_inbox_reauthenticate)



def _inbox_handoff_policy():
    from cosmas_os.application.inbox_handoff import Policy

    return Policy(enabled=settings.workspace_available and settings.inbox_work_enabled
        and settings.inbox_handoff_enabled)


from cosmas_os.api.inbox_handoff_routes import register as register_inbox_handoff  # noqa: E402

register_inbox_handoff(app, get_session, _identity,
    policy_dependency=_inbox_handoff_policy, registry_dependency=_inbox_registry,
    reauthenticate=_inbox_reauthenticate)


from cosmas_os.api import provider_identity_routes  # noqa: E402

provider_identity_routes.register(app, get_session, _identity, gate=_workspace_gate,
    reauthenticate=_refresh_team_identity, recovery_scope=_team_recovery_scope)


from cosmas_os.api import model_activity_routes  # noqa: E402

model_activity_routes.register(app, get_session, _identity, gate=_workspace_gate,
    reauthenticate=_refresh_team_identity,
    enabled=lambda: settings.workspace_ai_activity_enabled)

from cosmas_os.adapters.public_research import PublicResearch  # noqa: E402
from cosmas_os.api.research_routes import install_research_boundary  # noqa: E402
from cosmas_os.api.research_routes import router as research_router  # noqa: E402

app.include_router(research_router(settings=lambda: settings, session_factory=lambda: SessionLocal(),
    identity_dependency=_identity, workspace_gate=_workspace_gate, port_factory=PublicResearch))


if settings.compact_web_root:
    from cosmas_os.compact.web import install_compact_web

    install_compact_web(app, settings)


# Register last so origin policy also wraps connector-boundary error responses.
from cosmas_os.api.practice_access_routes import register as register_practice_access  # noqa: E402

register_practice_access(app, runtime=lambda: settings, verifier=_request_clerk_verifier,
                        session_factory=lambda: new_capture_session(SessionLocal))

allowed_headers = ["X-Cosmas-Practice-Access-Contract", "Authorization", "Content-Type", "X-Cosmas-Draft-Recovery", "X-Cosmas-Team-Contract", "X-Cosmas-Model-Contract", "X-Cosmas-Vendor-Contract", "X-Cosmas-Vendor-Setup-Contract", "X-Cosmas-Artifact-Write-Key", "X-Cosmas-Portal-Contract", "X-Cosmas-Portal-Work-Contract", "X-Cosmas-Finance-Contract", "X-Cosmas-Finance-Setup-Contract", "X-Cosmas-Membership-Contract", "X-Cosmas-Inbox-Contract", "X-Cosmas-Inbox-Handoff-Contract", "X-Cosmas-Routine-Contract"]
allowed_headers.extend(["X-Cosmas-Research-Contract", "X-Cosmas-Scheduling-Login", "X-Cosmas-Microsoft-Connection", "X-Cosmas-Google-Connection"])
allowed_headers.extend(["X-Cosmas-Record-Contract", "X-Cosmas-Connection-Contract", "X-Cosmas-Activity-Contract"])
if settings.cosmas_env == "synth_os" and settings.auth_mode == "synth_headers":
    allowed_headers.extend(["X-Box-Id", "X-Actor-Principal-Id"])



from cosmas_os.api.capture_deadline import install_capture_boundaries  # noqa: E402

install_capture_boundaries(app, _capture_connection)

app.include_router(core_connection_router(settings=lambda: settings, session_factory=lambda: SessionLocal(),
    identity_dependency=_identity, workspace_gate=_workspace_gate))
from cosmas_os.api.connection_catalog import router as connection_catalog_router  # noqa: E402

app.include_router(connection_catalog_router(settings=lambda: settings, runtime=lambda: app.state,
    identity_dependency=_identity, workspace_gate=_workspace_gate))
install_record_boundary(app)
install_core_connection_boundary(app)

install_research_boundary(app)

from cosmas_os.api.conversation_deadline import install_conversation_boundary  # noqa: E402

install_conversation_boundary(app)


app.include_router(scheduling_login_router(
    runtime=lambda: getattr(app.state, "scheduling_google_login", None),
    identity_dependency=_identity, workspace_gate=_workspace_gate, scheduling_gate=_scheduling_gate))
app.add_middleware(SchedulingCallbackBoundary)
app.include_router(google_connection_router(
    runtime=lambda: getattr(app.state, "google_connection", None),
    identity_dependency=_identity, workspace_gate=_workspace_gate))
app.include_router(microsoft_connection_router(
    runtime=lambda: getattr(app.state, "microsoft_connection", None),
    identity_dependency=_identity, workspace_gate=_workspace_gate))
app.add_middleware(GoogleConnectionBoundary)
app.add_middleware(MicrosoftConnectionBoundary)


from cosmas_os.api.workspace_protocol import WorkspaceProtocolBoundary  # noqa: E402

app.add_middleware(WorkspaceProtocolBoundary, runtime=lambda: settings)
allowed_headers.append("X-Cosmas-Workspace-Protocol")
# Origin policy covers compatibility failures before any inner handler runs.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=allowed_headers,
    expose_headers=["X-Cosmas-Workspace-Protocol"],
)
