from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cosmas_os.config import Settings
from cosmas_os.domain.enums import PrincipalState, PrincipalType
from cosmas_os.domain.rules import AuthorizationError, DomainError
from cosmas_os.models import AuditEvent, BoxContext, ExternalIdentity, Principal


class BetaIdentityAdminError(DomainError):
    """An authenticated beta identity change cannot safely proceed."""


@dataclass(frozen=True, slots=True)
class BetaIdentitySummary:
    """Privacy-minimized owner roster entry for the configured beta Box."""

    clerk_subject: str
    display_name: str
    active: bool
    principal_state: str
    is_owner: bool


def _validate_text(value: str, *, label: str, maximum: int) -> str:
    if not value or value != value.strip() or len(value) > maximum:
        raise BetaIdentityAdminError(f"invalid {label}")
    return value


def _validate_subject(value: str) -> str:
    value = _validate_text(value, label="Clerk subject", maximum=255)
    if not value.startswith("user_"):
        raise BetaIdentityAdminError("invalid Clerk subject")
    return value


def _runtime_boundary(runtime: Settings) -> tuple[str, str, str]:
    runtime.validate_runtime_configuration()
    if runtime.cosmas_env != "early_adopter_beta" or runtime.auth_mode != "clerk_jwt":
        raise AuthorizationError("beta identity administration is unavailable")
    if not runtime.beta_box_id or not runtime.clerk_issuer or not runtime.clerk_organization_id:
        raise BetaIdentityAdminError("reviewed beta identity boundary is unavailable")
    return runtime.beta_box_id, runtime.clerk_issuer, runtime.clerk_organization_id


def _lock_box_and_require_owner(
    session: Session,
    *,
    box_id: str,
    actor_principal_id: str,
) -> Principal:
    # Serialize identity changes for this Box so concurrent retries cannot race
    # the uniqueness and last-owner checks.
    box = session.scalar(
        select(BoxContext).where(BoxContext.id == box_id).with_for_update()
    )
    box_count = session.scalar(select(func.count()).select_from(BoxContext)) or 0
    # authenticate_request may already have loaded this Principal. Force a
    # database refresh after the Box lock so an ownership transfer committed by
    # another request cannot leave stale owner authority in the identity map.
    actor = session.scalar(
        select(Principal)
        .where(Principal.id == actor_principal_id, Principal.box_id == box_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if box_count != 1 or box is None:
        raise BetaIdentityAdminError("reviewed dedicated beta Box is unavailable")
    if (
        actor is None
        or actor.box_id != box_id
        or actor.principal_type != PrincipalType.HUMAN.value
        or actor.state != PrincipalState.ACTIVE.value
        or not actor.is_owner
    ):
        raise AuthorizationError("active Box owner authority is required")
    return actor


def _request_digest(
    *,
    operation: str,
    box_id: str,
    issuer: str,
    organization_id: str,
    subject: str,
    evidence_ref: str,
) -> str:
    canonical = json.dumps(
        {
            "box_id": box_id,
            "evidence_ref": evidence_ref,
            "issuer": issuer,
            "operation": operation,
            "organization_id": organization_id,
            "subject": subject,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _audit_identity_change(
    session: Session,
    *,
    box_id: str,
    binding: ExternalIdentity,
    actor_principal_id: str,
    event_type: str,
    evidence_ref: str,
    request_digest: str,
) -> None:
    session.add(
        AuditEvent(
            box_id=box_id,
            aggregate_type="external_identity",
            aggregate_id=binding.id,
            event_type=event_type,
            actor_principal_id=actor_principal_id,
            initiated_by_principal_id=actor_principal_id,
            approved_by_principal_id=actor_principal_id,
            correlation_id=str(uuid4()),
            outcome="approved",
            detail={
                "provider": "clerk",
                "evidence_ref": evidence_ref,
                "request_digest": request_digest,
            },
        )
    )


def _binding_and_human(
    session: Session,
    *,
    box_id: str,
    issuer: str,
    organization_id: str,
    subject: str,
) -> tuple[ExternalIdentity, Principal]:
    binding = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == "clerk",
            ExternalIdentity.issuer == issuer,
            ExternalIdentity.subject == subject,
            ExternalIdentity.organization_id == organization_id,
            ExternalIdentity.box_id == box_id,
        )
    )
    if binding is None:
        raise BetaIdentityAdminError("Clerk subject is not bound in this Box")
    principal = session.get(Principal, binding.principal_id)
    if (
        principal is None
        or principal.box_id != box_id
        or principal.principal_type != PrincipalType.HUMAN.value
    ):
        raise BetaIdentityAdminError("binding does not resolve to a Box human")
    return binding, principal


def _list_beta_identities(
    session: Session,
    runtime: Settings,
    *,
    actor_principal_id: str,
) -> list[BetaIdentitySummary]:
    """Return only reviewed Clerk bindings after a serialized owner check."""

    box_id, issuer, organization_id = _runtime_boundary(runtime)
    _lock_box_and_require_owner(
        session, box_id=box_id, actor_principal_id=actor_principal_id
    )
    rows = session.execute(
        select(ExternalIdentity, Principal)
        .join(
            Principal,
            (Principal.id == ExternalIdentity.principal_id)
            & (Principal.box_id == ExternalIdentity.box_id),
        )
        .where(
            ExternalIdentity.provider == "clerk",
            ExternalIdentity.issuer == issuer,
            ExternalIdentity.organization_id == organization_id,
            ExternalIdentity.box_id == box_id,
            Principal.principal_type == PrincipalType.HUMAN.value,
        )
        .order_by(
            Principal.is_owner.desc(),
            Principal.display_name,
            ExternalIdentity.subject,
        )
    ).all()
    roster = [
        BetaIdentitySummary(
            clerk_subject=binding.subject,
            display_name=principal.display_name,
            active=binding.active,
            principal_state=principal.state,
            is_owner=principal.is_owner,
        )
        for binding, principal in rows
    ]
    session.commit()
    return roster


def _bind_beta_identity(
    session: Session,
    runtime: Settings,
    *,
    actor_principal_id: str,
    clerk_subject: str,
    display_name: str,
    evidence_ref: str,
) -> None:
    """Bind one non-owner human after an authenticated owner request."""

    box_id, issuer, organization_id = _runtime_boundary(runtime)
    subject = _validate_subject(clerk_subject)
    display_name = _validate_text(display_name, label="display name", maximum=200)
    evidence_ref = _validate_text(evidence_ref, label="evidence reference", maximum=255)
    actor = _lock_box_and_require_owner(
        session, box_id=box_id, actor_principal_id=actor_principal_id
    )
    digest = _request_digest(
        operation="bind",
        box_id=box_id,
        issuer=issuer,
        organization_id=organization_id,
        subject=subject,
        evidence_ref=evidence_ref,
    )

    existing = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.issuer == issuer,
            ExternalIdentity.subject == subject,
        )
    )
    if existing is not None:
        principal = session.get(Principal, existing.principal_id)
        if (
            existing.provider == "clerk"
            and existing.box_id == box_id
            and existing.organization_id == organization_id
            and existing.active
            and existing.evidence_ref == evidence_ref
            and principal is not None
            and principal.box_id == box_id
            and principal.principal_type == PrincipalType.HUMAN.value
            and principal.state == PrincipalState.ACTIVE.value
            and not principal.is_owner
            and principal.display_name == display_name
        ):
            session.commit()
            return
        if not existing.active:
            raise BetaIdentityAdminError("Clerk subject is inactive; use explicit reactivation")
        raise BetaIdentityAdminError("Clerk subject is already bound differently")

    try:
        principal = Principal(
            box_id=box_id,
            principal_type=PrincipalType.HUMAN.value,
            display_name=display_name,
            is_owner=False,
            state=PrincipalState.ACTIVE.value,
        )
        session.add(principal)
        session.flush()
        binding = ExternalIdentity(
            box_id=box_id,
            principal_id=principal.id,
            provider="clerk",
            issuer=issuer,
            subject=subject,
            organization_id=organization_id,
            active=True,
            reviewed_by=actor.display_name,
            evidence_ref=evidence_ref,
        )
        session.add(binding)
        session.flush()
        _audit_identity_change(
            session,
            box_id=box_id,
            binding=binding,
            actor_principal_id=actor.id,
            event_type="external_identity.bound",
            evidence_ref=evidence_ref,
            request_digest=digest,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise


def _deactivate_beta_identity(
    session: Session,
    runtime: Settings,
    *,
    actor_principal_id: str,
    clerk_subject: str,
    evidence_ref: str,
) -> None:
    """Deactivate a non-owner binding after an authenticated owner request."""

    box_id, issuer, organization_id = _runtime_boundary(runtime)
    subject = _validate_subject(clerk_subject)
    evidence_ref = _validate_text(evidence_ref, label="evidence reference", maximum=255)
    actor = _lock_box_and_require_owner(
        session, box_id=box_id, actor_principal_id=actor_principal_id
    )
    binding, principal = _binding_and_human(
        session,
        box_id=box_id,
        issuer=issuer,
        organization_id=organization_id,
        subject=subject,
    )
    if principal.is_owner:
        raise BetaIdentityAdminError("transfer ownership before deactivating this identity")
    if not binding.active:
        session.commit()
        return

    try:
        binding.active = False
        other_active = session.scalar(
            select(func.count()).select_from(ExternalIdentity).where(
                ExternalIdentity.principal_id == principal.id,
                ExternalIdentity.active.is_(True),
                ExternalIdentity.id != binding.id,
            )
        )
        if not other_active:
            principal.state = PrincipalState.DISABLED.value
        digest = _request_digest(
            operation="deactivate",
            box_id=box_id,
            issuer=issuer,
            organization_id=organization_id,
            subject=subject,
            evidence_ref=evidence_ref,
        )
        _audit_identity_change(
            session,
            box_id=box_id,
            binding=binding,
            actor_principal_id=actor.id,
            event_type="external_identity.deactivated",
            evidence_ref=evidence_ref,
            request_digest=digest,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise


def _reactivate_beta_identity(
    session: Session,
    runtime: Settings,
    *,
    actor_principal_id: str,
    clerk_subject: str,
    evidence_ref: str,
) -> None:
    """Reactivate an unchanged non-owner binding after owner authentication."""

    box_id, issuer, organization_id = _runtime_boundary(runtime)
    subject = _validate_subject(clerk_subject)
    evidence_ref = _validate_text(evidence_ref, label="evidence reference", maximum=255)
    actor = _lock_box_and_require_owner(
        session, box_id=box_id, actor_principal_id=actor_principal_id
    )
    binding, principal = _binding_and_human(
        session,
        box_id=box_id,
        issuer=issuer,
        organization_id=organization_id,
        subject=subject,
    )
    if principal.is_owner:
        raise BetaIdentityAdminError("owner identity cannot use member reactivation")
    if binding.active and principal.state == PrincipalState.ACTIVE.value:
        session.commit()
        return
    if principal.state == PrincipalState.TOMBSTONED.value:
        raise BetaIdentityAdminError("tombstoned principals cannot be reactivated")

    try:
        binding.active = True
        binding.reviewed_by = actor.display_name
        binding.evidence_ref = evidence_ref
        principal.state = PrincipalState.ACTIVE.value
        digest = _request_digest(
            operation="reactivate",
            box_id=box_id,
            issuer=issuer,
            organization_id=organization_id,
            subject=subject,
            evidence_ref=evidence_ref,
        )
        _audit_identity_change(
            session,
            box_id=box_id,
            binding=binding,
            actor_principal_id=actor.id,
            event_type="external_identity.reactivated",
            evidence_ref=evidence_ref,
            request_digest=digest,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise


def _transfer_beta_ownership(
    session: Session,
    runtime: Settings,
    *,
    actor_principal_id: str,
    successor_clerk_subject: str,
    evidence_ref: str,
) -> None:
    """Atomically transfer Box ownership to an active bound human."""

    box_id, issuer, organization_id = _runtime_boundary(runtime)
    subject = _validate_subject(successor_clerk_subject)
    evidence_ref = _validate_text(evidence_ref, label="evidence reference", maximum=255)
    actor = _lock_box_and_require_owner(
        session, box_id=box_id, actor_principal_id=actor_principal_id
    )
    binding, successor = _binding_and_human(
        session,
        box_id=box_id,
        issuer=issuer,
        organization_id=organization_id,
        subject=subject,
    )
    if not binding.active or successor.state != PrincipalState.ACTIVE.value:
        raise BetaIdentityAdminError("successor identity must be active")
    if successor.id == actor.id:
        session.commit()
        return
    if successor.is_owner:
        raise BetaIdentityAdminError("successor is already an owner")

    try:
        actor.is_owner = False
        successor.is_owner = True
        digest = _request_digest(
            operation="transfer_owner",
            box_id=box_id,
            issuer=issuer,
            organization_id=organization_id,
            subject=subject,
            evidence_ref=evidence_ref,
        )
        _audit_identity_change(
            session,
            box_id=box_id,
            binding=binding,
            actor_principal_id=actor.id,
            event_type="owner.transferred",
            evidence_ref=evidence_ref,
            request_digest=digest,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise


def bind_beta_identity(
    session: Session,
    runtime: Settings,
    *,
    actor_principal_id: str,
    clerk_subject: str,
    display_name: str,
    evidence_ref: str,
) -> None:
    try:
        _bind_beta_identity(
            session,
            runtime,
            actor_principal_id=actor_principal_id,
            clerk_subject=clerk_subject,
            display_name=display_name,
            evidence_ref=evidence_ref,
        )
    except Exception:
        session.rollback()
        raise


def list_beta_identities(
    session: Session,
    runtime: Settings,
    *,
    actor_principal_id: str,
) -> list[BetaIdentitySummary]:
    try:
        return _list_beta_identities(
            session,
            runtime,
            actor_principal_id=actor_principal_id,
        )
    except Exception:
        session.rollback()
        raise


def deactivate_beta_identity(
    session: Session,
    runtime: Settings,
    *,
    actor_principal_id: str,
    clerk_subject: str,
    evidence_ref: str,
) -> None:
    try:
        _deactivate_beta_identity(
            session,
            runtime,
            actor_principal_id=actor_principal_id,
            clerk_subject=clerk_subject,
            evidence_ref=evidence_ref,
        )
    except Exception:
        session.rollback()
        raise


def reactivate_beta_identity(
    session: Session,
    runtime: Settings,
    *,
    actor_principal_id: str,
    clerk_subject: str,
    evidence_ref: str,
) -> None:
    try:
        _reactivate_beta_identity(
            session,
            runtime,
            actor_principal_id=actor_principal_id,
            clerk_subject=clerk_subject,
            evidence_ref=evidence_ref,
        )
    except Exception:
        session.rollback()
        raise


def transfer_beta_ownership(
    session: Session,
    runtime: Settings,
    *,
    actor_principal_id: str,
    successor_clerk_subject: str,
    evidence_ref: str,
) -> None:
    try:
        _transfer_beta_ownership(
            session,
            runtime,
            actor_principal_id=actor_principal_id,
            successor_clerk_subject=successor_clerk_subject,
            evidence_ref=evidence_ref,
        )
    except Exception:
        session.rollback()
        raise
