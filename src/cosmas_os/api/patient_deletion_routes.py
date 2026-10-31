"""Admin route for deleting one patient's live records."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from cosmas_os.api.auth import RequestIdentity
from cosmas_os.application.patient_deletion import delete_patient_records, storage_roots
from cosmas_os.application.services import Container
from cosmas_os.domain.rules import AuthorizationError, DomainError


class PatientDeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False


def router(*, get_session, identity):
    routes = APIRouter()

    @routes.post("/admin/patients/{patient_link_id}/records")
    def delete_records(
        patient_link_id: str,
        body: PatientDeletionRequest,
        response: Response,
        session: Session = Depends(get_session),
        actor: RequestIdentity = Depends(identity),
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "no-store"
        # This route uses the application runtime database role. That role cannot
        # call the deletion function, so confirmation is refused here as well.
        if body.confirm:
            raise HTTPException(
                status_code=403,
                detail="patient record deletion is only available to the admin command",
            )
        container = Container(session)
        try:
            return delete_patient_records(
                session,
                actor_principal_id=actor.principal_id,
                patient_link_id=patient_link_id,
                confirm=False,
                blob=container.blob,
                file_roots=storage_roots(container.blob),
            )
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except DomainError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except (SQLAlchemyError, OSError):
            raise HTTPException(status_code=500, detail="internal error") from None

    return routes
