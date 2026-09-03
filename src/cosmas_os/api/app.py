from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from cosmas_os.api.auth import (
    AccessDenied,
    AuthenticationFailed,
    ClerkTokenVerifier,
    RequestIdentity,
    authenticate_request,
)
from cosmas_os.application import services as svc
from cosmas_os.config import settings
from cosmas_os.db import make_engine, make_session_factory
from cosmas_os.domain.enums import CapabilityKey, DecisionKind
from cosmas_os.domain.rules import AuthorizationError, DomainError, PolicyDenied
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION

engine = make_engine()
SessionLocal = make_session_factory(engine)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_runtime_configuration()
    yield


app = FastAPI(
    title="Cosmas OS",
    version="0.2.0",
    description="Box-scoped practice work queue",
    lifespan=lifespan,
)
allowed_headers = ["Authorization", "Content-Type"]
if settings.cosmas_env == "synth_os":
    allowed_headers.extend(["X-Box-Id", "X-Actor-Principal-Id"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=allowed_headers,
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


@lru_cache(maxsize=1)
def _clerk_verifier() -> ClerkTokenVerifier:
    return ClerkTokenVerifier(settings)


def _identity(
    session: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
    x_box_id: str | None = Header(default=None),
    x_actor_principal_id: str | None = Header(default=None),
) -> RequestIdentity:
    try:
        verifier = _clerk_verifier() if settings.auth_mode == "clerk_jwt" else None
        return authenticate_request(
            session,
            settings,
            authorization=authorization,
            box_header=x_box_id,
            actor_header=x_actor_principal_id,
            verifier=verifier,
        )
    except AuthenticationFailed as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.cosmas_env}


@app.get("/ready")
def ready(session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        settings.validate_runtime_configuration()
        session.execute(text("SELECT 1"))
        revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != EXPECTED_SCHEMA_REVISION:
            raise RuntimeError("database schema is not current")
    except Exception as exc:  # noqa: BLE001 — readiness must fail closed
        raise HTTPException(status_code=503, detail="runtime is not ready") from exc
    return {"status": "ready", "env": settings.cosmas_env}


@app.post("/synth/seed", response_model=SeedResponse)
def seed(session: Session = Depends(get_session)) -> Any:
    if settings.cosmas_env != "synth_os" or not settings.synth_seed:
        raise HTTPException(status_code=404, detail="not found")
    from cosmas_os.application.seed import seed_synth

    return seed_synth(session)


@app.post("/synth/demo-queue", response_model=DemoSeedResponse)
def seed_demo_queue(session: Session = Depends(get_session)) -> Any:
    if settings.cosmas_env != "synth_os" or not settings.synth_seed:
        raise HTTPException(status_code=404, detail="not found")
    from cosmas_os.application.seed import seed_synth_work_queue

    return seed_synth_work_queue(session)


@app.get("/queue", response_model=list[QueueItem])
def queue(
    session: Session = Depends(get_session),
    identity: RequestIdentity = Depends(_identity),
) -> Any:
    c = svc.Container(session)
    return svc.list_queue(c, identity.box_id)


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
