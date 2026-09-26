"""Verified member requests, exact owner review and existing human identity binding."""

from dataclasses import dataclass
from datetime import UTC, timedelta
from uuid import uuid4

from sqlalchemy import func, select

from cosmas_os.application import beta_identity_admin as admin
from cosmas_os.domain.enums import PrincipalState, PrincipalType
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import AuditEvent, BoxContext, ExternalIdentity, Principal
from cosmas_os.practice_access_models import PracticeAccessRequest


class PracticeAccessError(Exception):
    def __init__(self, code="practice_access_unavailable", status=409):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class VerifiedMember:
    box_id: str
    issuer: str
    organization_id: str
    subject: str


def _scope(s, runtime, member, fence):
    runtime.validate_runtime_configuration()
    if (not runtime.workspace_hosted_enabled or not runtime.workspace_available
            or runtime.auth_mode != "clerk_jwt" or runtime.cosmas_env != "early_adopter_beta"
            or member.box_id != runtime.beta_box_id or member.issuer != runtime.clerk_issuer
            or member.organization_id != runtime.clerk_organization_id):
        raise PracticeAccessError("practice_access_denied", 403)
    fence()
    box = s.scalar(select(BoxContext).where(BoxContext.id == member.box_id).with_for_update()
                   .execution_options(populate_existing=True))
    if box is None or s.scalar(select(func.count()).select_from(BoxContext)) != 1:
        raise PracticeAccessError("practice_access_unavailable", 503)


def _binding(s, member):
    binding = s.scalar(select(ExternalIdentity).where(
        ExternalIdentity.issuer == member.issuer, ExternalIdentity.subject == member.subject
    ).with_for_update().execution_options(populate_existing=True))
    if binding is None:
        return None
    principal = s.scalar(select(Principal).where(Principal.id == binding.principal_id)
                         .with_for_update().execution_options(populate_existing=True))
    if (not binding.active or binding.provider != "clerk"
            or binding.box_id != member.box_id or binding.organization_id != member.organization_id
            or principal is None or principal.box_id != member.box_id
            or principal.principal_type != PrincipalType.HUMAN.value
            or principal.state != PrincipalState.ACTIVE.value):
        # A new request cannot bypass an earlier revocation or scope change.
        raise PracticeAccessError("practice_access_denied", 403)
    return principal


def _now(s):
    return s.scalar(select(func.clock_timestamp()))


def _request_hash(row):
    return payload_hash({"contract": "practice-access-v1", "id": row.id, "box": row.box_id,
        "issuer": row.issuer, "organization": row.organization_id, "subject": row.subject,
        "display_name": row.display_name, "created_at": row.created_at.astimezone(UTC).isoformat(),
        "expires_at": row.expires_at.astimezone(UTC).isoformat()})


def _view(row, now):
    if row.review_sha256 != _request_hash(row):
        raise PracticeAccessError("practice_access_unavailable", 503)
    return {"request_id": row.id, "display_name": row.display_name,
            "review_sha256": row.review_sha256,
            "state": "expired" if row.state == "pending" and row.expires_at <= now else row.state,
            "created_at": row.created_at.astimezone(UTC).isoformat(),
            "expires_at": row.expires_at.astimezone(UTC).isoformat()}


def _latest(s, member):
    return s.scalar(select(PracticeAccessRequest).where(
        PracticeAccessRequest.box_id == member.box_id,
        PracticeAccessRequest.issuer == member.issuer,
        PracticeAccessRequest.organization_id == member.organization_id,
        PracticeAccessRequest.subject == member.subject,
    ).order_by(PracticeAccessRequest.created_at.desc(), PracticeAccessRequest.id.desc()).limit(1))


def _self(s, member, principal):
    row = None if principal is not None else _latest(s, member)
    request = _view(row, _now(s)) if row is not None else None
    return {"contract_version": 1,
            "state": "connected" if principal is not None else request["state"] if request else "request_required",
            "role": "owner" if principal is not None and principal.is_owner else "member" if principal is not None else None,
            "request": request}


def _audit(s, row, state, actor=None):
    s.add(AuditEvent(box_id=row.box_id, aggregate_type="practice_access", aggregate_id=row.id,
        event_type="practice_access." + state, actor_principal_id=actor,
        initiated_by_principal_id=actor, approved_by_principal_id=actor,
        outcome=state, detail={"review_sha256": row.review_sha256}))


def status(s, runtime, member, *, fence):
    _scope(s, runtime, member, fence)
    result = _self(s, member, _binding(s, member))
    fence()
    s.commit()
    return result


def submit(s, runtime, member, command, *, fence):
    _scope(s, runtime, member, fence)
    principal = _binding(s, member)
    if principal is not None:
        result = _self(s, member, principal)
        fence()
        s.commit()
        return result
    existing = s.scalar(select(PracticeAccessRequest).where(
        PracticeAccessRequest.issuer == member.issuer,
        PracticeAccessRequest.subject == member.subject,
        PracticeAccessRequest.request_key == str(command.idempotency_key)))
    if existing is not None:
        if (existing.box_id != member.box_id or existing.organization_id != member.organization_id
                or existing.display_name != command.display_name):
            raise PracticeAccessError("practice_access_conflict")
    else:
        now = _now(s)
        latest = _latest(s, member)
        if latest is not None and latest.state == "pending" and latest.expires_at > now:
            if latest.display_name != command.display_name:
                raise PracticeAccessError("practice_access_conflict")
        else:
            recent = s.scalar(select(func.count()).select_from(PracticeAccessRequest).where(
                PracticeAccessRequest.issuer == member.issuer, PracticeAccessRequest.subject == member.subject,
                PracticeAccessRequest.created_at > now - timedelta(days=1)))
            pending = s.scalar(select(func.count()).select_from(PracticeAccessRequest).where(
                PracticeAccessRequest.box_id == member.box_id, PracticeAccessRequest.state == "pending",
                PracticeAccessRequest.expires_at > now))
            if recent >= 5 or pending >= 100:
                raise PracticeAccessError("practice_access_limit", 429)
            row = PracticeAccessRequest(id=str(uuid4()), box_id=member.box_id, issuer=member.issuer,
                organization_id=member.organization_id, subject=member.subject,
                request_key=str(command.idempotency_key), display_name=command.display_name,
                state="pending", created_at=now, expires_at=now + timedelta(days=7))
            row.review_sha256 = _request_hash(row)
            s.add(row)
            _audit(s, row, "requested")
            s.flush()
    result = _self(s, member, None)
    fence()
    s.commit()
    return result


def _selected(s, member, command):
    row = s.scalar(select(PracticeAccessRequest).where(
        PracticeAccessRequest.id == str(command.request_id),
        PracticeAccessRequest.box_id == member.box_id,
        PracticeAccessRequest.issuer == member.issuer,
        PracticeAccessRequest.organization_id == member.organization_id,
    ).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise PracticeAccessError("practice_access_not_found", 404)
    if command.review_sha256 != row.review_sha256 or row.review_sha256 != _request_hash(row):
        raise PracticeAccessError("practice_access_conflict")
    return row


def cancel(s, runtime, member, command, *, fence):
    _scope(s, runtime, member, fence)
    principal = _binding(s, member)
    row = _selected(s, member, command)
    if row.subject != member.subject:
        raise PracticeAccessError("practice_access_not_found", 404)
    if row.state not in {"pending", "cancelled"}:
        raise PracticeAccessError("practice_access_conflict")
    if row.state == "pending":
        row.state, row.decided_at = "cancelled", _now(s)
        _audit(s, row, "cancelled")
        s.flush()
    result = _self(s, member, principal)
    fence()
    s.commit()
    return result


def _owner(s, runtime, member, fence):
    _scope(s, runtime, member, fence)
    principal = _binding(s, member)
    if principal is None or not principal.is_owner:
        raise PracticeAccessError("practice_access_denied", 403)
    return admin._lock_box_and_require_owner(s, box_id=member.box_id, actor_principal_id=principal.id)


def pending(s, runtime, member, *, fence):
    _owner(s, runtime, member, fence)
    now = _now(s)
    rows = s.scalars(select(PracticeAccessRequest).where(
        PracticeAccessRequest.box_id == member.box_id,
        PracticeAccessRequest.issuer == member.issuer,
        PracticeAccessRequest.organization_id == member.organization_id,
        PracticeAccessRequest.state == "pending", PracticeAccessRequest.expires_at > now,
    ).order_by(PracticeAccessRequest.created_at, PracticeAccessRequest.id).limit(100)).all()
    result = {"contract_version": 1, "requests": [_view(row, now) for row in rows]}
    fence()
    s.commit()
    return result


def decide(s, runtime, member, command, *, fence):
    owner = _owner(s, runtime, member, fence)
    row = _selected(s, member, command)
    target = "approved" if command.decision == "approve" else "declined"
    now = _now(s)
    if row.state == target:
        result = {"contract_version": 1, "request": _view(row, now)}
        fence()
        s.commit()
        return result
    if row.state != "pending" or row.expires_at <= now:
        raise PracticeAccessError("practice_access_conflict")
    row.state, row.decided_by, row.decided_at = target, owner.id, now
    _audit(s, row, target, owner.id)
    fence()
    if target == "approved":
        # Its existing commit covers BOTH this request decision and the binding.
        # The existing writer rejects revocation, remapping and owner grants.
        admin.bind_beta_identity(s, runtime, actor_principal_id=owner.id,
            clerk_subject=row.subject, display_name=row.display_name,
            evidence_ref=f"practice-access:v1:{row.id}:{row.review_sha256}")
    else:
        s.commit()
    return {"contract_version": 1, "request": _view(row, now)}
