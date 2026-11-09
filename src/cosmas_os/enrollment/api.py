"""Independent /enrollment/v1 API. No public provisioner-ready route exists."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path
from threading import Lock
from typing import Literal, cast
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import ClientDisconnect

from cosmas_os.ports.google_callback_broker import GoogleRelayPort

from .admission import (
    ADMISSION_HEADER,
    AdmissionRequest,
    derive_runtime_admission_key,
    encode,
    signature,
    verify_request,
)
from .allocation import WorkspaceAllocationScheduler
from .auth import ClerkEnrollmentVerifier
from .config import EnrollmentSettings
from .domain import (
    CONTRACT,
    CommercePort,
    EnrollmentError,
    HumanIdentity,
    IdentityVerifier,
    document,
)
from .mail import DisabledInvitationNotifier, build_invitation_notifier
from .migration import schema_ready
from .service import EnrollmentService
from .stripe import StripeCommerce
from .workspace import (
    NativeOrigin,
    NativeWorkspaceAuthority,
    NativeWorkspaceProofRegistry,
    NativeWorkspaceRecordedAuthority,
    ProductionNativeWorkspaceAuthority,
    ProductionWorkspaceConfirmer,
    WorkspaceConfirmer,
)

ADMISSION_BODY_TIMEOUT_SECONDS = 5


def _unique_json(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate field")
        value[key] = item
    return value


class RevisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0)


class ProfileBody(RevisionBody):
    display_name: str = Field(min_length=2, max_length=120)
    title: str = Field(default="", max_length=120)

    @field_validator("display_name")
    @classmethod
    def meaningful(cls, value: str) -> str:
        if len(value.strip()) < 2 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Enter your name and role.")
        return value.strip()


class PracticeBody(RevisionBody):
    legal_name: str = Field(min_length=3, max_length=160)
    display_name: str = Field(min_length=2, max_length=120)
    address_line1: str = Field(min_length=3, max_length=200)
    address_line2: str = Field(default="", max_length=200)
    city: str = Field(min_length=2, max_length=100)
    region: str = Field(min_length=2, max_length=80)
    postal_code: str = Field(min_length=3, max_length=20)
    country: Literal["US"] = "US"
    administrative_email: str = Field(min_length=3, max_length=320)
    human_seats: int = Field(ge=1, le=1000)
    covered_entity: bool

    @field_validator("display_name")
    @classmethod
    def practice_display_name(cls, value: str) -> str:
        return ProfileBody.meaningful(value)

    @field_validator("administrative_email")
    @classmethod
    def email(cls, value: str) -> str:
        if "@" not in value or any(c.isspace() for c in value):
            raise ValueError("Enter an administrative contact email.")
        return value.strip().lower()


class AcceptanceBody(RevisionBody):
    doc_id: str = Field(max_length=64)
    version: str = Field(max_length=16)
    sha256: str = Field(min_length=64, max_length=64)
    signature_name: str = Field(min_length=2, max_length=160)
    signature_title: str = Field(min_length=2, max_length=120)
    authority_confirmed: bool
    accepted: bool

    @field_validator("signature_name", "signature_title")
    @classmethod
    def meaningful(cls, value: str) -> str:
        if len(value.strip()) < 2:
            raise ValueError("Enter the representative's name and title.")
        return value.strip()


class InvitationBody(RevisionBody):
    email: str = Field(min_length=3, max_length=320)
    role: Literal["admin", "staff"]
    can_sign: bool = False

    @field_validator("email")
    @classmethod
    def email_valid(cls, value: str) -> str:
        return PracticeBody.email(value)


class JoinBody(RevisionBody):
    token: str = Field(min_length=80, max_length=128)


class SelectPracticeBody(RevisionBody):
    practice_id: str = Field(min_length=36, max_length=36)


class WorkspaceConfirmationBody(RevisionBody):
    workspace_token: SecretStr = Field(min_length=1, max_length=8192)


class NativeProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    client: Literal["apple", "desktop"]
    nonce: str
    expected_revision: int | None = Field(default=None, ge=0)

    @field_validator("nonce")
    @classmethod
    def canonical_nonce(cls, value: str) -> str:
        if str(UUID(value)) != value:
            raise ValueError("canonical UUID required")
        return value


def create_app(settings: EnrollmentSettings | None = None, *, engine=None,
               verifier: IdentityVerifier | None = None, commerce: CommercePort | None = None,
               workspace_confirmer: WorkspaceConfirmer | None = None,
               native_workspace_authority: NativeWorkspaceAuthority | None = None,
               google_relay_port: GoogleRelayPort | None = None) -> FastAPI:
    settings = settings or EnrollmentSettings()
    if settings.data_mode == "production" and (
            (verifier is not None and not isinstance(verifier, ClerkEnrollmentVerifier))
            or (commerce is not None and not isinstance(commerce, StripeCommerce))):
        raise RuntimeError("Production enrollment requires real Clerk and Stripe adapters")
    if (settings.data_mode == "production" and native_workspace_authority is not None
            and not isinstance(native_workspace_authority, ProductionNativeWorkspaceAuthority)):
        raise RuntimeError("Production native enrollment requires a root-owned native qualification authority")
    if (native_workspace_authority is None and settings.native_account_enabled
            and settings.native_workspace_proof_file):
        try:
            native_workspace_authority = NativeWorkspaceProofRegistry.from_path(Path(settings.native_workspace_proof_file))
        except EnrollmentError:
            # Native proof failure must not disable existing browser enrollment.
            native_workspace_authority = None
    if engine is None and settings.database_url.get_secret_value():
        engine = create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    db_ready = bool(engine is not None and schema_ready(engine))
    if db_ready and settings.native_account_enabled:
        imported = native_workspace_authority if isinstance(native_workspace_authority, ProductionNativeWorkspaceAuthority) else None
        if native_workspace_authority is None or imported is not None:
            native_workspace_authority = NativeWorkspaceRecordedAuthority(sessionmaker(engine, expire_on_commit=False), imported)
    if verifier is None and not settings.auth_errors():
        try:
            verifier = ClerkEnrollmentVerifier(settings)
        except EnrollmentError:
            verifier = None
    commerce = commerce or StripeCommerce(settings)
    stripe_verified = False
    if not settings.billing_errors():
        try:
            commerce.validate_configuration()
            stripe_verified = True
        except EnrollmentError:
            pass
    try:
        invitation_notifier = (build_invitation_notifier(
            enabled=settings.invitation_mail_enabled,
            webhook_url=settings.invitation_mail_webhook_url,
            webhook_secret=settings.invitation_mail_webhook_secret.get_secret_value(),
            allowed_recipients=settings.invitation_mail_allowed_recipients,
        ) if settings.invitation_mail_configured() else DisabledInvitationNotifier())
    except ValueError:
        invitation_notifier = DisabledInvitationNotifier()
    service = EnrollmentService(sessionmaker(engine, expire_on_commit=False), settings, commerce,
        native_workspace_authority=native_workspace_authority,
        invitation_notifier=invitation_notifier) if db_ready else None
    if service is not None and settings.workspace_allocation_enabled:
        # Queue intent only. Hosting allocation remains a separately installed
        # private worker; this API never executes a customer deployment.
        service.workspace_allocation_scheduler = WorkspaceAllocationScheduler(service)
    if workspace_confirmer is None and service and settings.provisioning_enabled:
        try:
            factory = import_module("cosmas_os.enrollment.provisioning").create_workspace_confirmer
            workspace_confirmer = factory(settings, service)
        except (ImportError, AttributeError, EnrollmentError):
            workspace_confirmer = None
    if settings.data_mode == "production" and workspace_confirmer is not None and not isinstance(workspace_confirmer, ProductionWorkspaceConfirmer):
        raise RuntimeError("Production enrollment requires the real workspace confirmation port")

    google_transport = None
    @asynccontextmanager
    async def lifespan(_app):
        yield
        if google_transport is not None:
            google_transport.close()
        if engine is not None:
            engine.dispose()

    app = FastAPI(title="Cosmas Enrollment", version="1", lifespan=lifespan)
    if settings.google_callback_broker_enabled:
        from cosmas_os.adapters.google_callback_broker import HttpGoogleRelayPort

        from .google_callback_routes import install as install_google_callback_broker
        relay = google_relay_port or HttpGoogleRelayPort()
        if settings.data_mode != "synthetic" and not isinstance(relay, HttpGoogleRelayPort):
            raise RuntimeError("Google callback routing requires the real relay adapter")
        app.state.google_callback_broker = install_google_callback_broker(app, settings, service, verifier, relay)
        if isinstance(relay, HttpGoogleRelayPort):
            google_transport = relay
    app.state.enrollment_service = service
    app.state.enrollment_settings = settings
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
                       allow_methods=["GET", "PUT", "POST"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Cosmas-Enrollment-Contract"])

    @app.middleware("http")
    async def response_contract(request: Request, call_next):
        supplied = request.headers.get("x-cosmas-enrollment-contract")
        if supplied is not None and supplied != CONTRACT:
            response = JSONResponse({"detail": {"code": "enrollment_contract_mismatch", "message": "Reload to use the current enrollment contract."}}, status_code=409)
        else:
            try:
                response = await call_next(request)
            except Exception:
                response = JSONResponse({"detail": {"code": "enrollment_temporarily_unavailable", "message": "Your saved enrollment is temporarily unavailable. Try again shortly."}}, status_code=503)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(EnrollmentError)
    async def enrollment_error(_request, exc: EnrollmentError):
        code = exc.code if exc.code.startswith("enrollment_") else "enrollment_" + exc.code
        return JSONResponse({"detail": {"code": code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, exc: RequestValidationError):
        # Do not echo a workspace token or account/form input in validation errors.
        return JSONResponse({"detail": {"code": "enrollment_invalid_request", "message": "Check the required fields and try again."},
                             "errors": [{"field": ".".join(str(p) for p in error["loc"]), "type": error["type"]} for error in exc.errors()]}, status_code=422)

    def identity(authorization: str | None = Header(default=None)) -> HumanIdentity:
        config = settings.public_config(database_ready=bool(db_ready and schema_ready(engine)),
                                        auth_ready=bool(verifier and getattr(verifier, "ready", True)), stripe_verified=stripe_verified)
        if not config["enabled"] or service is None or verifier is None:
            raise EnrollmentError("registration_unavailable", "Customer enrollment is not available in this environment.", 503)
        if not authorization or not authorization.startswith("Bearer "):
            raise EnrollmentError("invalid_identity", "Sign in to continue.", 401)
        return verifier.verify(authorization[7:])

    def native_identity(request: Request) -> tuple[HumanIdentity, NativeOrigin]:
        origins = request.headers.getlist("origin")
        if len(origins) != 1 or not settings.native_origin_enabled(origins[0]):
            raise EnrollmentError("native_identity_unavailable", "Native account sign-in is unavailable.", 503)
        if (request.scope.get("query_string") or len(request.headers.getlist("authorization")) != 1
                or request.headers.getlist("x-box-id") or request.headers.getlist("x-actor-principal-id")
                or request.headers.getlist("content-encoding") or request.headers.getlist("transfer-encoding")):
            raise EnrollmentError("invalid_native_identity", "Start a new native account sign-in.", 422)
        config = current_config()
        if not config["enabled"] or service is None or verifier is None:
            raise EnrollmentError("registration_unavailable", "Customer enrollment is not available in this environment.", 503)
        authorization = request.headers["authorization"]
        if not authorization.startswith("Bearer "):
            raise EnrollmentError("invalid_identity", "Sign in to continue.", 401)
        verify = getattr(verifier, "verify_native", None)
        if verify is None:
            raise EnrollmentError("native_identity_unavailable", "Native account sign-in is unavailable.", 503)
        origin = cast(NativeOrigin, origins[0])
        return verify(authorization[7:], native_origin=origin), origin

    @app.get("/health")
    def health():
        return {"status": "ok", "component": "enrollment", "data_mode": settings.data_mode}

    @app.get("/operational-ready")
    def operational_ready():
        # Keep closed enrollment reachable for configuration/recovery messages.
        # Registration, billing and workspace admission remain separate gates.
        available = bool(db_ready and schema_ready(engine))
        return JSONResponse({"component": "enrollment", "operational_ready": available},
                            status_code=200 if available else 503)

    @app.get("/ready")
    def ready():
        config = current_config()
        return JSONResponse({"component": "enrollment", "registration_ready": config["enabled"],
                             "billing_ready": config["billing_configured"], "activation_available": config["activation_available"],
                             "blockers": config["blockers"]}, status_code=200 if config["enabled"] else 503)

    @app.get("/enrollment/v1/config")
    def config():
        return current_config()

    @app.get("/enrollment/v1/native/config")
    def native_config(request: Request):
        origins = request.headers.getlist("origin")
        if len(origins) != 1 or not settings.native_origin_enabled(origins[0]) or request.scope.get("query_string"):
            raise EnrollmentError("native_identity_unavailable", "Native account sign-in is unavailable.", 503)
        value = current_config()
        native_ready = bool(workspace_confirmer and
            getattr(workspace_confirmer, "native_origin_supported", False) is True and native_workspace_authority is not None)
        value["workspace_confirmation_configured"] = native_ready
        value["activation_available"] = bool(value["activation_available"] and native_ready)
        value["checkout_recovery_available"] = bool(value["checkout_recovery_available"] and native_ready)
        if not value["activation_available"]:
            value["activation_blockers"] = settings.activation_blockers(
                billing=bool(value["billing_configured"]),
                registration_blockers=list(value["blockers"]),
                workspace_confirmation_configured=native_ready,
            )
        return {**value, "native_account": {"issuer": settings.clerk_issuer, "audience": settings.clerk_audience,
                "session_policy": settings.clerk_session_policy, "native_origin": origins[0]}}

    def current_config():
        confirmation_ready = workspace_confirmer is not None
        value = settings.public_config(
            database_ready=bool(db_ready and schema_ready(engine)),
            auth_ready=bool(verifier and getattr(verifier, "ready", True)),
            stripe_verified=stripe_verified,
            workspace_confirmation_configured=confirmation_ready,
        )
        value["workspace_confirmation_configured"] = confirmation_ready
        return value

    @app.get("/enrollment/v1/status")
    def status(human: HumanIdentity = Depends(identity)):
        assert service
        return service.status(human)

    @app.get("/enrollment/v1/native/status")
    def native_status(request: Request, verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity)):
        if request.headers.get("content-length") not in (None, "0"):
            raise EnrollmentError("invalid_native_identity", "Start a new native account sign-in.", 422)
        assert service
        return service.status(verified[0])

    @app.post("/enrollment/v1/native/workspace-profile")
    async def native_profile(request: Request, verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity)):
        if (request.headers.getlist("content-type") != ["application/json"]
                or len(request.headers.getlist("content-length")) > 1):
            raise EnrollmentError("invalid_native_profile", "Start a new native practice connection.", 422)
        raw = bytearray()
        try:
            async with asyncio.timeout(ADMISSION_BODY_TIMEOUT_SECONDS):
                async for chunk in request.stream():
                    if len(raw) + len(chunk) > 4096:
                        raise EnrollmentError("invalid_native_profile", "Native connection request is too large.", 413)
                    raw.extend(chunk)
            body = NativeProfileBody.model_validate(json.loads(raw, object_pairs_hook=_unique_json))
        except (ValueError, TypeError):
            raise EnrollmentError("invalid_native_profile", "Start a new native practice connection.", 422) from None
        except (TimeoutError, ClientDisconnect):
            raise EnrollmentError("native_profile_interrupted", "Native connection was interrupted. Retry safely.", 408) from None
        human, origin = verified
        assert service and verifier
        verify_registered_member = verifier.verify_registered_member
        return service.native_workspace_profile(human, native_origin=origin, client=body.client,
            nonce=body.nonce, expected_revision=body.expected_revision,
            verify_membership=lambda org: verify_registered_member(human.subject, org))

    # Separate native routes reuse the exact form validators and business gates.
    # Their native JWT dependency never becomes a browser fallback or beta gate.
    @app.put("/enrollment/v1/native/profile")
    def native_save_profile(body: ProfileBody, verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity),
                            idempotency_key: str = Header(default="")):
        assert service
        return service.profile(verified[0], idempotency_key, body.model_dump())

    @app.put("/enrollment/v1/native/practice")
    def native_save_practice(body: PracticeBody, verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity),
                             idempotency_key: str = Header(default="")):
        assert service
        return service.practice(verified[0], idempotency_key, body.model_dump())

    @app.get("/enrollment/v1/native/practices")
    def native_practices(verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity)):
        assert service
        return service.practices(verified[0])

    @app.post("/enrollment/v1/native/select-practice")
    def native_select_practice(body: SelectPracticeBody, verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity),
                              idempotency_key: str = Header(default="")):
        assert service
        return service.select_practice(verified[0], idempotency_key, body.model_dump())

    @app.get("/enrollment/v1/native/baa/current")
    def native_document(_verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity)):
        return document()

    @app.post("/enrollment/v1/native/baa/accept")
    def native_accept(body: AcceptanceBody, verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity),
                      idempotency_key: str = Header(default="")):
        assert service
        return service.accept(verified[0], idempotency_key, body.model_dump())

    @app.get("/enrollment/v1/native/baa/receipt")
    def native_receipt(verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity)):
        assert service
        return service.receipt(verified[0])

    @app.get("/enrollment/v1/native/quote")
    def native_quote(verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity)):
        assert service
        return service.status(verified[0])["quote"]

    @app.post("/enrollment/v1/native/invitations")
    def native_invite(body: InvitationBody, verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity),
                      idempotency_key: str = Header(default="")):
        assert service
        return service.invite(verified[0], idempotency_key, body.model_dump())

    @app.post("/enrollment/v1/native/join")
    def native_join(body: JoinBody, verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity),
                    idempotency_key: str = Header(default="")):
        assert service
        return service.join(verified[0], idempotency_key, body.model_dump())

    @app.post("/enrollment/v1/native/checkout")
    def native_checkout(body: RevisionBody, verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity),
                        idempotency_key: str = Header(default="")):
        assert service
        service.require_native_workspace(verified[0], verified[1])
        return service.checkout(verified[0], idempotency_key, body.model_dump())

    @app.post("/enrollment/v1/native/recover")
    def native_recover(body: RevisionBody, verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity),
                       idempotency_key: str = Header(default="")):
        assert service
        return service.recover(verified[0], idempotency_key, body.model_dump())

    @app.post("/enrollment/v1/native/portal")
    def native_portal(body: RevisionBody, verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity),
                      idempotency_key: str = Header(default="")):
        assert service
        return service.portal(verified[0], idempotency_key, body.model_dump())

    @app.post("/enrollment/v1/native/workspace/confirm")
    def native_confirm(body: WorkspaceConfirmationBody, verified: tuple[HumanIdentity, NativeOrigin] = Depends(native_identity),
                       idempotency_key: str = Header(default="")):
        assert service and verifier
        if workspace_confirmer is None or getattr(workspace_confirmer, "native_origin_supported", False) is not True:
            raise EnrollmentError("native_workspace_confirmation_unavailable", "Native practice confirmation is unavailable.", 503)
        human, origin = verified
        verify = getattr(verifier, "verify_native", None)
        if verify is None:
            raise EnrollmentError("native_identity_unavailable", "Native account sign-in is unavailable.", 503)
        workspace_human = verify(body.workspace_token.get_secret_value(), native_origin=origin)
        if (workspace_human.issuer, workspace_human.subject, workspace_human.session_id) != (
                human.issuer, human.subject, human.session_id):
            raise EnrollmentError("runtime_scope_denied", "Refresh the selected native account before confirming.", 403)
        return service.confirm_workspace(human, idempotency_key, body.expected_revision,
            body.workspace_token.get_secret_value(), workspace_confirmer, native_origin=origin)

    @app.put("/enrollment/v1/profile")
    def profile(body: ProfileBody, human: HumanIdentity = Depends(identity), idempotency_key: str = Header(default="")):
        assert service
        return service.profile(human, idempotency_key, body.model_dump())

    @app.put("/enrollment/v1/practice")
    def practice(body: PracticeBody, human: HumanIdentity = Depends(identity), idempotency_key: str = Header(default="")):
        assert service
        return service.practice(human, idempotency_key, body.model_dump())

    @app.get("/enrollment/v1/practices")
    def practices(human: HumanIdentity = Depends(identity)):
        assert service
        return service.practices(human)

    @app.post("/enrollment/v1/select-practice")
    def select_practice(body: SelectPracticeBody, human: HumanIdentity = Depends(identity), idempotency_key: str = Header(default="")):
        assert service
        return service.select_practice(human, idempotency_key, body.model_dump())

    @app.get("/enrollment/v1/baa/current")
    def baa_current(_human: HumanIdentity = Depends(identity)):
        return document()

    @app.post("/enrollment/v1/baa/accept")
    def baa_accept(body: AcceptanceBody, human: HumanIdentity = Depends(identity), idempotency_key: str = Header(default="")):
        assert service
        return service.accept(human, idempotency_key, body.model_dump())

    @app.get("/enrollment/v1/baa/receipt")
    def baa_receipt(human: HumanIdentity = Depends(identity)):
        assert service
        return service.receipt(human)

    @app.get("/enrollment/v1/quote")
    def price_quote(human: HumanIdentity = Depends(identity)):
        assert service
        return service.status(human)["quote"]

    @app.post("/enrollment/v1/invitations")
    def invite(body: InvitationBody, human: HumanIdentity = Depends(identity), idempotency_key: str = Header(default="")):
        assert service
        return service.invite(human, idempotency_key, body.model_dump())

    @app.post("/enrollment/v1/join")
    def join(body: JoinBody, human: HumanIdentity = Depends(identity), idempotency_key: str = Header(default="")):
        assert service
        return service.join(human, idempotency_key, body.model_dump())

    @app.post("/enrollment/v1/checkout")
    def checkout(body: RevisionBody, human: HumanIdentity = Depends(identity), idempotency_key: str = Header(default="")):
        assert service
        return service.checkout(human, idempotency_key, body.model_dump())

    @app.post("/enrollment/v1/recover")
    def recover(body: RevisionBody, human: HumanIdentity = Depends(identity), idempotency_key: str = Header(default="")):
        assert service
        return service.recover(human, idempotency_key, body.model_dump())

    @app.post("/enrollment/v1/portal")
    def portal(body: RevisionBody, human: HumanIdentity = Depends(identity), idempotency_key: str = Header(default="")):
        assert service
        return service.portal(human, idempotency_key, body.model_dump())

    @app.post("/enrollment/v1/workspace/confirm")
    def workspace_confirm(body: WorkspaceConfirmationBody, human: HumanIdentity = Depends(identity), idempotency_key: str = Header(default="")):
        assert service
        if workspace_confirmer is None:
            raise EnrollmentError("workspace_confirmation_not_configured", "Practice account confirmation is not available yet.", 503)
        return service.confirm_workspace(human, idempotency_key, body.expected_revision,
                                         body.workspace_token.get_secret_value(), workspace_confirmer)

    @app.post("/enrollment/v1/runtime/admission")
    async def runtime_admission(request: Request):
        config = current_config()
        if not config["enabled"] or service is None or verifier is None:
            raise EnrollmentError("runtime_admission_unavailable", "Runtime admission is unavailable.", 503)
        if (request.headers.getlist("content-type") != ["application/json"]
                or request.headers.getlist("content-encoding") or request.scope.get("query_string")
                or request.headers.getlist("transfer-encoding")
                or len(request.headers.getlist("content-length")) > 1
                or len(request.headers.getlist("authorization")) != 1
                or len(request.headers.getlist(ADMISSION_HEADER)) != 1):
            raise EnrollmentError("invalid_runtime_admission", "Runtime admission request is invalid.", 422)
        raw = bytearray()
        try:
            async with asyncio.timeout(ADMISSION_BODY_TIMEOUT_SECONDS):
                async for chunk in request.stream():
                    if len(raw) + len(chunk) > 4096:
                        raise EnrollmentError("invalid_runtime_admission", "Runtime admission request is invalid.", 413)
                    raw.extend(chunk)
        except (TimeoutError, ClientDisconnect):
            raise EnrollmentError("runtime_admission_interrupted", "Runtime admission was interrupted. Retry safely.", 408) from None
        try:
            body = AdmissionRequest.model_validate(json.loads(raw, object_pairs_hook=_unique_json))
        except (ValueError, TypeError):
            raise EnrollmentError("invalid_runtime_admission", "Runtime admission request is invalid.", 422) from None
        authorization = request.headers["authorization"]
        token = authorization[7:] if authorization.startswith("Bearer ") else ""
        if body.purpose == "worker" and authorization != "Cosmas-Worker":
            raise EnrollmentError("invalid_runtime_admission", "Runtime admission request is invalid.", 422)
        key = derive_runtime_admission_key(settings.runtime_admission_secret.get_secret_value(),
                                          body.practice_id, body.box_id, body.organization_id)
        verify_request(key, body, bytes(raw), token, request.headers[ADMISSION_HEADER])
        try:
            parties = service.runtime_authorized_parties(body)
            if body.native_origin is not None:
                verify = getattr(verifier, "verify_native_scoped", None)
                if verify is None or not settings.native_origin_enabled(body.native_origin):
                    raise EnrollmentError("native_identity_unavailable", "Native account sign-in is unavailable.", 503)
                human = verify(token, body.organization_id, native_origin=body.native_origin)
            else:
                human = (verifier.verify_registered_member(body.subject, body.organization_id) if body.purpose == "worker"
                         else verifier.verify_scoped(token, body.organization_id, authorized_parties=parties))
            result = service.runtime_admission(human, body)
        except EnrollmentError as exc:
            if exc.status not in (401, 403):
                raise
            now = int(time.time())
            result = {**body.model_dump(exclude={"token_sha256", "issued_at"}), "request_issued_at": body.issued_at,
                      "decision": "deny", "reason": "identity_required", "member_role": None, "display_name": None,
                      "issued_at": now, "expires_at": now + 30}
        result["request_sha256"] = hashlib.sha256(raw).hexdigest()
        encoded = encode(result)
        return Response(encoded, media_type="application/json", headers={"Cache-Control": "no-store",
                        ADMISSION_HEADER: signature(key, encoded, direction="response", nonce=body.nonce)})

    @app.post("/enrollment/v1/webhooks/stripe")
    async def webhook(request: Request):
        if service is None:
            raise EnrollmentError("database_unavailable", "Billing inbox is unavailable.", 503)
        raw = await request.body()
        if len(raw) > 128_000:
            raise EnrollmentError("event_too_large", "Billing event exceeds the accepted size.", 413)
        # Commit before acknowledgement. The separate reconcile command retries
        # durable pending rows; HTTP transport is never the authoritative inbox.
        accepted = service.ingest(raw, request.headers.get("stripe-signature", ""))
        return {"accepted": accepted}

    return app


# Plain factory imports must not inspect ambient settings or contact services.
# The documented ASGI target initializes only when its `app` is requested.
app: FastAPI
_default_app_lock = Lock()


def _default_application() -> FastAPI:
    with _default_app_lock:
        if "app" not in globals():
            globals()["app"] = create_app()
        return globals()["app"]


def __getattr__(name: str):
    if name == "app":
        return _default_application()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Serve the independent enrollment API.")
    parser.add_argument("--host", choices=("0.0.0.0", "127.0.0.1"), default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    uvicorn.run(_default_application(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
