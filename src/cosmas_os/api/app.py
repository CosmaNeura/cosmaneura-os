from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cosmas_os.application import services as svc
from cosmas_os.config import settings
from cosmas_os.db import make_engine, make_session_factory
from cosmas_os.domain.enums import CapabilityKey, DecisionKind
from cosmas_os.domain.rules import AuthorizationError, DomainError, PolicyDenied

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


app = FastAPI(title="Cosmas OS", version="0.1.0", description="Local synthetic L0 practice computer")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SeedResponse(BaseModel):
    box_id: str
    owner_id: str
    agents: dict[str, str]


class QueueItem(BaseModel):
    id: str
    lane: str
    state: str
    proposed_message: str | None
    revision_id: str | None
    patient_link_id: str | None


class DecideBody(BaseModel):
    kind: DecisionKind
    note: str | None = None
    expected_revision_id: str | None = None


class EditBody(BaseModel):
    body: str = Field(min_length=1)


class AttestBody(BaseModel):
    source_pair_key: str
    label: str


class ImportBody(BaseModel):
    csv_text: str


class UploadBody(BaseModel):
    front_b64: str
    back_b64: str


def _actor(x_actor_principal_id: str = Header(...)) -> str:
    return x_actor_principal_id


def _box(x_box_id: str = Header(...)) -> str:
    return x_box_id


def _map_err(exc: Exception) -> HTTPException:
    if isinstance(exc, AuthorizationError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, PolicyDenied):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, DomainError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="internal error")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.cosmas_env}


@app.post("/synth/seed", response_model=SeedResponse)
def seed(session: Session = Depends(get_session)) -> Any:
    from cosmas_os.application.seed import seed_synth

    return seed_synth(session)


@app.get("/queue", response_model=list[QueueItem])
def queue(
    session: Session = Depends(get_session),
    box_id: str = Depends(_box),
) -> Any:
    c = svc.Container(session)
    return svc.list_queue(c, box_id)


@app.post("/schedule/import")
def schedule_import(
    body: ImportBody,
    session: Session = Depends(get_session),
    box_id: str = Depends(_box),
) -> Any:
    c = svc.Container(session)
    ids = svc.import_schedule(c, box_id, body.csv_text)
    return {"appointment_ids": ids}


@app.post("/patient-links/attest")
def attest(
    body: AttestBody,
    session: Session = Depends(get_session),
    box_id: str = Depends(_box),
    actor: str = Depends(_actor),
) -> Any:
    try:
        c = svc.Container(session)
        link = svc.attest_patient_link(c, box_id, actor, body.source_pair_key, body.label)
        return {"id": link.id, "state": link.state}
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.post("/chase/open")
def open_chase(
    appointment_id: str,
    patient_link_id: str,
    chaser_id: str,
    session: Session = Depends(get_session),
    box_id: str = Depends(_box),
) -> Any:
    try:
        c = svc.Container(session)
        ticket = svc.detect_and_open_chase(c, box_id, chaser_id, appointment_id, patient_link_id)
        return {"ticket_id": ticket.id, "state": ticket.state, "revision_id": ticket.current_revision_id}
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.post("/tickets/{ticket_id}/edit")
def edit_ticket(
    ticket_id: str,
    body: EditBody,
    session: Session = Depends(get_session),
    actor: str = Depends(_actor),
) -> Any:
    try:
        c = svc.Container(session)
        rev = svc.edit_revision(c, ticket_id, actor, body.body)
        return {"revision_id": rev.id, "payload_hash": rev.payload_hash}
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.post("/tickets/{ticket_id}/decide")
def decide_ticket(
    ticket_id: str,
    body: DecideBody,
    session: Session = Depends(get_session),
    actor: str = Depends(_actor),
) -> Any:
    try:
        c = svc.Container(session)
        return svc.decide(
            c,
            ticket_id,
            actor,
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
    actor: str = Depends(_actor),
) -> Any:
    import base64

    try:
        c = svc.Container(session)
        return svc.simulate_upload_and_verify(
            c,
            ticket_id,
            actor,
            base64.b64decode(body.front_b64),
            base64.b64decode(body.back_b64),
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.post("/tickets/{ticket_id}/close")
def close_ticket(
    ticket_id: str,
    session: Session = Depends(get_session),
    actor: str = Depends(_actor),
) -> Any:
    try:
        c = svc.Container(session)
        t = svc.close_ticket(c, ticket_id, actor)
        return {"id": t.id, "state": t.state}
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc


@app.get("/tickets/{ticket_id}/timeline")
def timeline(
    ticket_id: str,
    session: Session = Depends(get_session),
    box_id: str = Depends(_box),
) -> Any:
    c = svc.Container(session)
    return svc.audit_timeline(c, box_id, ticket_id)


@app.post("/retention/purge")
def purge(
    session: Session = Depends(get_session),
    box_id: str = Depends(_box),
) -> Any:
    c = svc.Container(session)
    return {"receipts": svc.purge_due_artifacts(c, box_id)}


@app.post("/capabilities/{key}/invoke")
def invoke_capability(
    key: CapabilityKey,
    session: Session = Depends(get_session),
    box_id: str = Depends(_box),
) -> Any:
    try:
        c = svc.Container(session)
        svc.reject_dark_capability(c, box_id, key)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        raise _map_err(exc) from exc
