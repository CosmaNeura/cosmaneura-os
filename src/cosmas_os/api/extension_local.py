"""Explicit local factory, never mounted by cosmas_os.api.app or hosted profiles."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from cosmas_os.adapters.extension_observation_store import PostgresObservationStore
from cosmas_os.api.auth import (
    AccessDenied,
    AuthenticationFailed,
    ClerkTokenVerifier,
    RequestIdentity,
    TokenVerifier,
    authenticate_request,
)
from cosmas_os.application.extension_screen_observations import observe
from cosmas_os.db import make_session_factory
from cosmas_os.extension_local_profile import EXTENSION_ORIGIN, LocalExtensionProfile


class ScreenRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    appointment: str = Field(min_length=1, max_length=200)
    person: str = Field(min_length=1, max_length=200)
    time: str = Field(min_length=1, max_length=200)


class ScreenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[ScreenRow] = Field(min_length=1, max_length=50)


def create_app(profile: LocalExtensionProfile, session_factory: Callable[[], Session],
               verifier: TokenVerifier | None = None) -> FastAPI:
    runtime = profile.auth_settings()
    selected_verifier = verifier or ClerkTokenVerifier(runtime)
    app = FastAPI(title="CosmaBot local extension proof", docs_url=None, redoc_url=None,
                  openapi_url=None)

    app.add_middleware(CORSMiddleware, allow_origins=[EXTENSION_ORIGIN],
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def local_fence(request: Request, call_next):
        if not profile.admits_request(request.client.host if request.client else None,
                                     request.headers.getlist("origin"), request.headers.getlist("host")):
            return JSONResponse({"detail": "request_refused"}, status_code=403,
                                headers={"Cache-Control": "no-store"})
        # Bound bodies before validation. No exception includes caller payloads.
        try:
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 40_000:
                    return JSONResponse({"detail": "invalid_request"}, status_code=422,
                                        headers={"Cache-Control": "no-store"})
                chunks.append(chunk)
            # _CachedRequest forwards this bounded body to the route exactly once.
            request._body = b"".join(chunks)
        except Exception:
            return JSONResponse({"detail": "invalid_request"}, status_code=422,
                                headers={"Cache-Control": "no-store"})
        try:
            response = await call_next(request)
        except Exception:
            response = JSONResponse({"detail": "local_box_unavailable"}, status_code=503)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        return JSONResponse({"detail": "invalid_request"}, status_code=422)

    def get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def identity(request: Request, session: Session) -> RequestIdentity:
        try:
            return authenticate_request(session, runtime,
                authorization=request.headers.get("authorization"),
                box_header=request.headers.get("x-box-id"),
                actor_header=request.headers.get("x-actor-principal-id"), verifier=selected_verifier)
        except AuthenticationFailed:
            raise HTTPException(401, "sign_in_required") from None
        except AccessDenied:
            raise HTTPException(403, "access_refused") from None

    @app.get("/workspace/extension-session")
    def signed_session(request: Request, session: Session = Depends(get_session)):
        actor = identity(request, session)
        return {"signed_in": True, "synthetic": True, "box_id": actor.box_id}

    @app.post("/workspace/screen-observations")
    def screen_observations(request: Request, body: ScreenBody,
                            session: Session = Depends(get_session)):
        actor = identity(request, session)
        def recheck() -> None:
            identity(request, session)

        return observe(PostgresObservationStore(session), actor.box_id, actor.principal_id,
                       [row.model_dump() for row in body.rows], recheck)

    return app


def local_app() -> FastAPI:
    profile = LocalExtensionProfile.from_env()
    # Do not enable SQL statement/parameter logging on the local evidence path.
    from sqlalchemy import create_engine

    engine = create_engine(profile.database_url, echo=False, hide_parameters=True, pool_pre_ping=True)
    return create_app(profile, make_session_factory(engine))
