"""Invitations enter owner-reviewed access. A link never grants membership."""
from datetime import UTC, timedelta
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, select

from cosmas_os.api.practice_access_schemas import SubmitAccess
from cosmas_os.application import practice_access as access
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import AuditEvent
from cosmas_os.practice_access_models import (
    PracticeInvitation,
    PracticeInviteRevocation,
    PracticeInviteUse,
)


def _view(s, row, now):
    revoked = s.get(PracticeInviteRevocation, row.id)
    return {"invitation_id": row.id, "label": row.label, "created_at": row.created_at.astimezone(UTC).isoformat(),
        "expires_at": row.expires_at.astimezone(UTC).isoformat(),
        "state": "revoked" if revoked else "expired" if row.expires_at <= now else "active",
        "requests": s.scalar(select(func.count()).select_from(PracticeInviteUse).where(PracticeInviteUse.invitation_id == row.id))}


def _audit(s, row, actor, kind):
    s.add(AuditEvent(box_id=row.box_id, aggregate_type="practice_invitation", aggregate_id=row.id,
        event_type="practice_invitation." + kind, actor_principal_id=actor, outcome=kind, detail={}))


def create(s, runtime, member, command, *, fence):
    owner = access._owner(s, runtime, member, fence)
    digest = payload_hash({"contract": "practice-invitation.v1", "label": command.label,
        "token_sha256": sha256(command.token.encode()).hexdigest(), "expires_in_hours": command.expires_in_hours})
    row = s.scalar(select(PracticeInvitation).where(PracticeInvitation.owner_id == owner.id,
        PracticeInvitation.request_key == str(command.idempotency_key)))
    if row and (row.box_id != member.box_id or row.request_sha256 != digest):
        raise access.PracticeAccessError("practice_access_conflict")
    now = access._now(s)
    if row is None:
        if s.scalar(select(PracticeInvitation.id).where(PracticeInvitation.token_sha256 == sha256(command.token.encode()).hexdigest())):
            raise access.PracticeAccessError("practice_access_conflict")
        total = s.scalar(select(func.count()).select_from(PracticeInvitation).where(PracticeInvitation.box_id == member.box_id))
        if total >= 200:
            raise access.PracticeAccessError("practice_access_limit", 429)
        row = PracticeInvitation(id=str(uuid4()), box_id=member.box_id, owner_id=owner.id, issuer=member.issuer,
            organization_id=member.organization_id, label=command.label, request_key=str(command.idempotency_key),
            token_sha256=sha256(command.token.encode()).hexdigest(), request_sha256=digest,
            created_at=now, expires_at=now + timedelta(hours=command.expires_in_hours))
        s.add(row)
        _audit(s, row, owner.id, "created")
        s.flush()
    result = {"contract_version": 1, "invitation": _view(s, row, now)}
    fence()
    s.commit()
    return result


def list_invitations(s, runtime, member, *, fence):
    access._owner(s, runtime, member, fence)
    now = access._now(s)
    rows = s.scalars(select(PracticeInvitation).where(PracticeInvitation.box_id == member.box_id,
        PracticeInvitation.issuer == member.issuer, PracticeInvitation.organization_id == member.organization_id)
        .order_by(PracticeInvitation.created_at.desc()).limit(200)).all()
    result = {"contract_version": 1, "invitations": [_view(s, row, now) for row in rows]}
    fence()
    s.commit()
    return result


def revoke(s, runtime, member, command, *, fence):
    owner = access._owner(s, runtime, member, fence)
    row = s.scalar(select(PracticeInvitation).where(PracticeInvitation.id == str(command.invitation_id),
        PracticeInvitation.box_id == member.box_id, PracticeInvitation.issuer == member.issuer,
        PracticeInvitation.organization_id == member.organization_id))
    if row is None:
        raise access.PracticeAccessError("practice_access_not_found", 404)
    prior = s.scalar(select(PracticeInviteRevocation).where(PracticeInviteRevocation.owner_id == owner.id,
        PracticeInviteRevocation.request_key == str(command.idempotency_key)))
    if prior and prior.invitation_id != row.id:
        raise access.PracticeAccessError("practice_access_conflict")
    if s.get(PracticeInviteRevocation, row.id) is None:
        s.add(PracticeInviteRevocation(invitation_id=row.id, box_id=row.box_id, owner_id=owner.id,
            request_key=str(command.idempotency_key), created_at=access._now(s)))
        _audit(s, row, owner.id, "revoked")
        s.flush()
    result = {"contract_version": 1, "invitation": _view(s, row, access._now(s))}
    fence()
    s.commit()
    return result


def join(s, runtime, member, command, *, fence):
    access._scope(s, runtime, member, fence)
    row = s.scalar(select(PracticeInvitation).where(
        PracticeInvitation.token_sha256 == sha256(command.token.encode()).hexdigest(),
        PracticeInvitation.box_id == member.box_id, PracticeInvitation.issuer == member.issuer,
        PracticeInvitation.organization_id == member.organization_id))
    if row is None or row.expires_at <= access._now(s) or s.get(PracticeInviteRevocation, row.id):
        raise access.PracticeAccessError("practice_invitation_unavailable", 409)
    result = access.submit(s, runtime, member, SubmitAccess(idempotency_key=command.idempotency_key,
        display_name=command.display_name), fence=fence, commit=False)
    request = result["request"]
    if request and s.get(PracticeInviteUse, (row.id, request["request_id"])) is None:
        s.add(PracticeInviteUse(invitation_id=row.id, box_id=row.box_id, request_id=request["request_id"], created_at=access._now(s)))
    fence()
    s.commit()
    return result


def resolve_create(s, runtime, member, command, *, fence):
    owner = access._owner(s, runtime, member, fence)
    digest = payload_hash({"contract": "practice-invitation.v1", "label": command.label,
        "token_sha256": sha256(command.token.encode()).hexdigest(), "expires_in_hours": command.expires_in_hours})
    row = s.scalar(select(PracticeInvitation).where(PracticeInvitation.owner_id == owner.id,
        PracticeInvitation.request_key == str(command.idempotency_key)))
    if row and (row.box_id != member.box_id or row.request_sha256 != digest):
        raise access.PracticeAccessError("practice_access_conflict")
    result = {"contract_version": 1, "outcome": "recorded" if row else "not_found",
        "invitation": _view(s, row, access._now(s)) if row else None}
    fence()
    s.commit()
    return result


def resolve_revoke(s, runtime, member, command, *, fence):
    access._owner(s, runtime, member, fence)
    row = s.scalar(select(PracticeInvitation).where(PracticeInvitation.id == str(command.invitation_id),
        PracticeInvitation.box_id == member.box_id, PracticeInvitation.issuer == member.issuer,
        PracticeInvitation.organization_id == member.organization_id))
    if row is None:
        raise access.PracticeAccessError("practice_access_not_found", 404)
    recorded = s.get(PracticeInviteRevocation, row.id) is not None
    result = {"contract_version": 1, "outcome": "recorded" if recorded else "not_found",
        "invitation": _view(s, row, access._now(s)) if recorded else None}
    fence()
    s.commit()
    return result
