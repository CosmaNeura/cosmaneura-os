from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cosmas_os.api.auth import AccessDenied, authenticate_request
from cosmas_os.config import Settings
from cosmas_os.domain.enums import PrincipalState, PrincipalType
from cosmas_os.models import AuditEvent, ExternalIdentity, Principal

OFFBOARDING_ACCEPTANCE_CONTRACT = "cosmas-os-d3-offboarding-acceptance-v1"
OFFBOARDING_REQUEST_CONTRACT = "cosmas-os-d3-offboarding-request-v1"
_STATE_LIFETIME = timedelta(hours=4)
_HANDLE_PATTERN = r"^[0-9a-f]{64}$"


class OffboardingAcceptanceError(RuntimeError):
    """A live offboarding assertion failed without exposing identity details."""


class OffboardingTargetRequest(BaseModel):
    """Private, owner-reviewed target binding; never emit this model."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    contract: Literal["cosmas-os-d3-offboarding-request-v1"]
    box_id: str
    clerk_issuer: str
    clerk_organization_id: str
    clerk_subject: str
    principal_id: str
    approved_at: str
    reviewer_reference: str


class OffboardingBaselineState(BaseModel):
    """Sanitized, integrity-protected state passed through the human handoff."""

    model_config = ConfigDict(extra="forbid", strict=True)

    contract: Literal["cosmas-os-d3-offboarding-acceptance-v1"]
    stage: Literal["baseline"]
    status: Literal["ready_for_owner"]
    issued_at: str
    expires_at: str
    target_handle: str = Field(pattern=_HANDLE_PATTERN)
    confirmation_challenge: str = Field(pattern=_HANDLE_PATTERN)
    required_deactivation_evidence_ref: str
    deactivation_audit_count: int = Field(ge=0)
    request_sha256: str = Field(pattern=_HANDLE_PATTERN)
    reviewer_reference_sha256: str = Field(pattern=_HANDLE_PATTERN)
    state_mac: str = Field(pattern=_HANDLE_PATTERN)
    evidence_sha256: str = Field(pattern=_HANDLE_PATTERN)

    def sanitized_json(self) -> str:
        return json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))


class OffboardingOwnerConfirmation(BaseModel):
    """Private human/browser evidence bound to one unpredictable baseline."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    owner_assertion: Literal[
        "I CONFIRM D3 CLERK OFFBOARDING AND LIVE ACCESS DENIAL"
    ]
    challenge: str = Field(pattern=_HANDLE_PATTERN)
    baseline_evidence_sha256: str = Field(pattern=_HANDLE_PATTERN)
    confirmed_at: str
    confirmation_reference: str
    clerk_organization_membership_removed: Literal[True]
    clerk_sessions_revoked: Literal[True]
    live_access_denied: Literal[True]


class OffboardingVerificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    prior_state: OffboardingBaselineState
    owner_confirmation: OffboardingOwnerConfirmation


@dataclass(frozen=True, slots=True)
class OffboardingAcceptanceEvidence:
    contract: str
    stage: str
    status: str
    completed_at: str
    state_bound: bool
    target_binding_inactive: bool
    target_principal_disabled: bool
    deactivation_audit_delta: int
    owner_authorized_deactivation_observed: bool
    application_inactive_binding_denied: bool
    clerk_org_membership_removal_human_attested: bool
    clerk_sessions_revoked_human_attested: bool
    live_access_denial_human_attested: bool
    confirmation_reference_sha256: str

    def sanitized_json(self) -> str:
        values = asdict(self)
        values["evidence_sha256"] = hashlib.sha256(
            _canonical_json(values).encode("utf-8")
        ).hexdigest()
        return _canonical_json(values)


def offboarding_failure_json() -> str:
    return _canonical_json(
        {"contract": OFFBOARDING_ACCEPTANCE_CONTRACT, "status": "failed"}
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise OffboardingAcceptanceError("offboarding acceptance failed") from None
    return parsed


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _database_now(session: Session) -> datetime:
    observed = session.scalar(select(func.now()))
    if not isinstance(observed, datetime):
        raise OffboardingAcceptanceError("offboarding acceptance failed")
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed.astimezone(UTC)


def _require_hmac_key(key: bytes) -> None:
    if len(key) != 32:
        raise OffboardingAcceptanceError("offboarding acceptance failed")


def decode_offboarding_hmac_key(value: str | None) -> bytes:
    try:
        decoded = bytes.fromhex(value or "")
    except ValueError:
        raise OffboardingAcceptanceError("offboarding acceptance failed") from None
    _require_hmac_key(decoded)
    return decoded


def _canonical_uuid(value: str) -> str:
    try:
        canonical = str(UUID(value))
    except ValueError:
        raise OffboardingAcceptanceError("offboarding acceptance failed") from None
    if canonical != value:
        raise OffboardingAcceptanceError("offboarding acceptance failed")
    return canonical


def _bounded_reference(value: str) -> str:
    if (
        not value
        or value != value.strip()
        or len(value) > 512
        or "@" in value
        or any(character in value for character in "\r\n\x00")
    ):
        raise OffboardingAcceptanceError("offboarding acceptance failed")
    return value


def _runtime_boundary(runtime: Settings) -> tuple[str, str, str]:
    try:
        runtime.validate_runtime_configuration()
        box_id = _canonical_uuid(runtime.beta_box_id or "")
    except Exception:
        raise OffboardingAcceptanceError("offboarding acceptance failed") from None
    issuer = runtime.clerk_issuer or ""
    organization_id = runtime.clerk_organization_id or ""
    parsed_issuer = urlparse(issuer)
    if (
        runtime.cosmas_env != "early_adopter_beta"
        or runtime.data_mode != "synthetic"
        or runtime.auth_mode != "clerk_jwt"
        or runtime.sync_worker
        or parsed_issuer.scheme != "https"
        or not parsed_issuer.hostname
        or parsed_issuer.username is not None
        or parsed_issuer.password is not None
        or parsed_issuer.query
        or parsed_issuer.fragment
        or not organization_id.startswith("org_")
    ):
        raise OffboardingAcceptanceError("offboarding acceptance failed")
    return box_id, issuer, organization_id


def _validate_target_request(
    serialized: str,
    runtime: Settings,
    now: datetime,
) -> OffboardingTargetRequest:
    try:
        request = OffboardingTargetRequest.model_validate_json(serialized)
    except (ValidationError, ValueError):
        raise OffboardingAcceptanceError("offboarding acceptance failed") from None
    box_id, issuer, organization_id = _runtime_boundary(runtime)
    if (
        request.box_id != box_id
        or request.clerk_issuer != issuer
        or request.clerk_organization_id != organization_id
        or not request.clerk_subject.startswith("user_")
        or len(request.clerk_subject) > 255
        or request.clerk_subject != request.clerk_subject.strip()
        or _canonical_uuid(request.principal_id) != request.principal_id
    ):
        raise OffboardingAcceptanceError("offboarding acceptance failed")
    _bounded_reference(request.reviewer_reference)
    approved_at = _timestamp(request.approved_at)
    if approved_at > now + timedelta(minutes=5) or approved_at < now - _STATE_LIFETIME:
        raise OffboardingAcceptanceError("offboarding acceptance failed")
    return request


def _target_handle(key: bytes, binding: ExternalIdentity) -> str:
    material = "\0".join(
        (
            "offboarding-target",
            binding.box_id,
            binding.issuer,
            binding.organization_id,
            binding.subject,
            binding.principal_id,
            binding.id,
        )
    ).encode()
    return hmac.new(key, material, hashlib.sha256).hexdigest()


def _signed_baseline(payload: dict[str, Any], key: bytes) -> OffboardingBaselineState:
    state_mac = hmac.new(
        key,
        _canonical_json(payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    with_mac = {**payload, "state_mac": state_mac}
    return OffboardingBaselineState.model_validate(
        {
            **with_mac,
            "evidence_sha256": hashlib.sha256(
                _canonical_json(with_mac).encode("utf-8")
            ).hexdigest(),
        }
    )


def _validate_baseline(
    state: OffboardingBaselineState,
    key: bytes,
    now: datetime,
) -> None:
    values = state.model_dump()
    evidence_hash = values.pop("evidence_sha256")
    if not hmac.compare_digest(
        evidence_hash,
        hashlib.sha256(_canonical_json(values).encode("utf-8")).hexdigest(),
    ):
        raise OffboardingAcceptanceError("offboarding acceptance failed")
    state_mac = values.pop("state_mac")
    if not hmac.compare_digest(
        state_mac,
        hmac.new(key, _canonical_json(values).encode("utf-8"), hashlib.sha256).hexdigest(),
    ):
        raise OffboardingAcceptanceError("offboarding acceptance failed")
    issued_at = _timestamp(state.issued_at)
    expires_at = _timestamp(state.expires_at)
    if expires_at - issued_at != _STATE_LIFETIME or now < issued_at or now > expires_at:
        raise OffboardingAcceptanceError("offboarding acceptance failed")


def _deactivation_audits(session: Session, binding: ExternalIdentity) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent).where(
                AuditEvent.box_id == binding.box_id,
                AuditEvent.aggregate_type == "external_identity",
                AuditEvent.aggregate_id == binding.id,
                AuditEvent.event_type == "external_identity.deactivated",
            ).order_by(AuditEvent.created_at, AuditEvent.id)
        ).all()
    )


def _request_digest(
    *,
    box_id: str,
    issuer: str,
    organization_id: str,
    subject: str,
    evidence_ref: str,
) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "box_id": box_id,
                "evidence_ref": evidence_ref,
                "issuer": issuer,
                "operation": "deactivate",
                "organization_id": organization_id,
                "subject": subject,
            }
        ).encode()
    ).hexdigest()


def baseline_beta_offboarding_acceptance(
    session: Session,
    runtime: Settings,
    request_json: str,
    hmac_key: bytes,
) -> OffboardingBaselineState:
    """Bind one reviewed active non-owner target to opaque handoff state."""

    try:
        _require_hmac_key(hmac_key)
        now = _database_now(session)
        request = _validate_target_request(request_json, runtime, now)
        binding = session.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == "clerk",
                ExternalIdentity.issuer == request.clerk_issuer,
                ExternalIdentity.subject == request.clerk_subject,
                ExternalIdentity.organization_id == request.clerk_organization_id,
                ExternalIdentity.box_id == request.box_id,
                ExternalIdentity.principal_id == request.principal_id,
            )
        )
        principal = session.get(Principal, request.principal_id)
        if (
            binding is None
            or principal is None
            or not binding.active
            or principal.box_id != request.box_id
            or principal.principal_type != PrincipalType.HUMAN.value
            or principal.state != PrincipalState.ACTIVE.value
            or principal.is_owner
        ):
            raise OffboardingAcceptanceError("offboarding acceptance failed")
        audits = _deactivation_audits(session, binding)
        challenge = hashlib.sha256(
            hmac.new(
                hmac_key,
                f"offboarding-challenge\0{binding.id}\0{now.isoformat()}".encode(),
                hashlib.sha256,
            ).digest()
        ).hexdigest()
        required_ref = f"d3-offboarding:{challenge}"
        request_sha256 = hashlib.sha256(
            _canonical_json(request.model_dump()).encode("utf-8")
        ).hexdigest()
        payload = {
            "contract": OFFBOARDING_ACCEPTANCE_CONTRACT,
            "stage": "baseline",
            "status": "ready_for_owner",
            "issued_at": _utc_timestamp(now),
            "expires_at": _utc_timestamp(now + _STATE_LIFETIME),
            "target_handle": _target_handle(hmac_key, binding),
            "confirmation_challenge": challenge,
            "required_deactivation_evidence_ref": required_ref,
            "deactivation_audit_count": len(audits),
            "request_sha256": request_sha256,
            "reviewer_reference_sha256": hashlib.sha256(
                request.reviewer_reference.encode()
            ).hexdigest(),
        }
        return _signed_baseline(payload, hmac_key)
    except OffboardingAcceptanceError:
        raise
    except Exception:
        raise OffboardingAcceptanceError("offboarding acceptance failed") from None


class _FixedClaimsVerifier:
    def __init__(self, *, subject: str, organization_id: str) -> None:
        self._claims = {"sub": subject, "org_id": organization_id}

    def verify(self, token: str) -> dict[str, Any]:
        del token
        return dict(self._claims)


def verify_beta_offboarding_acceptance(
    session: Session,
    runtime: Settings,
    verification_json: str,
    hmac_key: bytes,
) -> OffboardingAcceptanceEvidence:
    """Verify app deactivation plus the separate human Clerk/browser handoff."""

    try:
        _require_hmac_key(hmac_key)
        now = _database_now(session)
        try:
            verification = OffboardingVerificationInput.model_validate_json(verification_json)
        except (ValidationError, ValueError):
            raise OffboardingAcceptanceError("offboarding acceptance failed") from None
        state = verification.prior_state
        confirmation = verification.owner_confirmation
        _validate_baseline(state, hmac_key, now)
        if (
            not hmac.compare_digest(confirmation.challenge, state.confirmation_challenge)
            or not hmac.compare_digest(
                confirmation.baseline_evidence_sha256,
                state.evidence_sha256,
            )
        ):
            raise OffboardingAcceptanceError("offboarding acceptance failed")
        confirmed_at = _timestamp(confirmation.confirmed_at)
        if not (_timestamp(state.issued_at) <= confirmed_at <= now + timedelta(minutes=5)):
            raise OffboardingAcceptanceError("offboarding acceptance failed")
        _bounded_reference(confirmation.confirmation_reference)

        box_id, issuer, organization_id = _runtime_boundary(runtime)
        candidates = session.scalars(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == "clerk",
                ExternalIdentity.issuer == issuer,
                ExternalIdentity.organization_id == organization_id,
                ExternalIdentity.box_id == box_id,
            )
        ).all()
        matches = [
            binding
            for binding in candidates
            if hmac.compare_digest(_target_handle(hmac_key, binding), state.target_handle)
        ]
        if len(matches) != 1:
            raise OffboardingAcceptanceError("offboarding acceptance failed")
        binding = matches[0]
        principal = session.get(Principal, binding.principal_id)
        audits = _deactivation_audits(session, binding)
        if len(audits) - state.deactivation_audit_count != 1:
            raise OffboardingAcceptanceError("offboarding acceptance failed")
        audit = audits[-1]
        actor = (
            session.get(Principal, audit.actor_principal_id)
            if audit.actor_principal_id is not None
            else None
        )
        expected_request_digest = _request_digest(
            box_id=box_id,
            issuer=issuer,
            organization_id=organization_id,
            subject=binding.subject,
            evidence_ref=state.required_deactivation_evidence_ref,
        )
        audit_created_at = audit.created_at
        if audit_created_at.tzinfo is None:
            audit_created_at = audit_created_at.replace(tzinfo=UTC)
        if (
            binding.active
            or principal is None
            or principal.box_id != box_id
            or principal.principal_type != PrincipalType.HUMAN.value
            or principal.state != PrincipalState.DISABLED.value
            or principal.is_owner
            or audit.outcome != "approved"
            or audit.actor_principal_id is None
            or audit.actor_principal_id != audit.initiated_by_principal_id
            or audit.actor_principal_id != audit.approved_by_principal_id
            or audit.detail
            != {
                "provider": "clerk",
                "evidence_ref": state.required_deactivation_evidence_ref,
                "request_digest": expected_request_digest,
            }
            or actor is None
            or actor.box_id != box_id
            or actor.principal_type != PrincipalType.HUMAN.value
            or actor.state != PrincipalState.ACTIVE.value
            or not actor.is_owner
            # The reviewed handoff timestamp is intentionally whole-second UTC,
            # while PostgreSQL records sub-second audit precision.
            or confirmed_at < audit_created_at.astimezone(UTC).replace(microsecond=0)
        ):
            raise OffboardingAcceptanceError("offboarding acceptance failed")

        denied = False
        try:
            authenticate_request(
                session,
                runtime,
                authorization="Bearer offboarding-inactive-binding-proof",
                box_header=None,
                actor_header=None,
                verifier=_FixedClaimsVerifier(
                    subject=binding.subject,
                    organization_id=binding.organization_id,
                ),
            )
        except AccessDenied:
            denied = True
        if not denied:
            raise OffboardingAcceptanceError("offboarding acceptance failed")

        return OffboardingAcceptanceEvidence(
            contract=OFFBOARDING_ACCEPTANCE_CONTRACT,
            stage="post_browser",
            status="verified",
            completed_at=_utc_timestamp(now),
            state_bound=True,
            target_binding_inactive=True,
            target_principal_disabled=True,
            deactivation_audit_delta=1,
            owner_authorized_deactivation_observed=True,
            application_inactive_binding_denied=True,
            clerk_org_membership_removal_human_attested=True,
            clerk_sessions_revoked_human_attested=True,
            live_access_denial_human_attested=True,
            confirmation_reference_sha256=hashlib.sha256(
                confirmation.confirmation_reference.encode()
            ).hexdigest(),
        )
    except OffboardingAcceptanceError:
        raise
    except Exception:
        raise OffboardingAcceptanceError("offboarding acceptance failed") from None
