"""Owner member lifecycle using existing bindings, writers and immutable audits."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import String, cast, event, func, or_, select

from cosmas_os.application import beta_identity_admin as admin
from cosmas_os.application import practice_access as access
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import AuditEvent, ExternalIdentity, Principal

REVIEW_LIFETIME = timedelta(minutes=10)
RECORDED = "external_identity.member_change_recorded"


def _stamp(value):
    return value.astimezone(UTC).isoformat()


def _identity(binding, principal):
    return {"id": binding.id, "box": binding.box_id, "provider": binding.provider,
            "issuer": binding.issuer, "organization": binding.organization_id,
            "subject": binding.subject, "principal": principal.id,
            "principal_box": principal.box_id, "principal_type": principal.principal_type,
            "binding_created": _stamp(binding.created_at),
            "principal_created": _stamp(principal.created_at)}


def _context(s, principals):
    """Batch related bindings and audit revisions, avoiding a scan per roster row."""
    related = s.scalars(select(ExternalIdentity).where(
        ExternalIdentity.principal_id.in_(principals)).order_by(ExternalIdentity.id)
        .execution_options(populate_existing=True)).all()
    ids = [row.id for row in related]
    revisions = s.execute(select(AuditEvent.aggregate_type, AuditEvent.aggregate_id,
        func.count(AuditEvent.id), func.max(cast(AuditEvent.id, String))).where(or_(
            (AuditEvent.aggregate_type == "external_identity") & AuditEvent.aggregate_id.in_(ids),
            (AuditEvent.aggregate_type == "principal") & AuditEvent.aggregate_id.in_(principals),
        )).group_by(AuditEvent.aggregate_type, AuditEvent.aggregate_id)).all()
    return related, {(kind, key): [count, latest] for kind, key, count, latest in revisions}


def _view(binding, principal, reviewed_at, context):
    if principal.state == "active" and binding.active:
        state, action = "active", "deactivate"
    elif principal.state in {"active", "disabled"} and not binding.active:
        state, action = "inactive", "reactivate"
    else:
        state, action = "unavailable", None
    if principal.is_owner or principal.tombstoned_at is not None:
        action = None
    if principal.tombstoned_at is not None:
        state = "unavailable"
    related, revisions = context
    rows = [row for row in related if row.principal_id == principal.id]
    snapshot = {"contract": "practice-members-v1", "identity": _identity(binding, principal),
        "display_name": principal.display_name, "principal_state": principal.state,
        "owner": principal.is_owner, "tombstoned_at": _stamp(principal.tombstoned_at) if principal.tombstoned_at else None,
        "reviewed_at": _stamp(reviewed_at), "bindings": [{
            "id": row.id, "box": row.box_id, "provider": row.provider,
            "issuer": row.issuer, "subject": row.subject, "organization": row.organization_id,
            "active": row.active, "reviewed_by": row.reviewed_by, "evidence": row.evidence_ref,
            "created_at": _stamp(row.created_at), "audit_revision": revisions.get(("external_identity", row.id), [0, None]),
        } for row in rows], "principal_audit_revision": revisions.get(("principal", principal.id), [0, None])}
    return {"member_id": binding.id, "display_name": principal.display_name,
        "role": "owner" if principal.is_owner else "member", "state": state, "action": action,
        "reviewed_at": _stamp(reviewed_at), "expires_at": _stamp(reviewed_at + REVIEW_LIFETIME),
        "review_sha256": payload_hash(snapshot)}


def members(s, runtime, member, command, *, fence):
    access._owner(s, runtime, member, fence)
    query = select(ExternalIdentity, Principal).join(Principal,
        (Principal.id == ExternalIdentity.principal_id) & (Principal.box_id == ExternalIdentity.box_id)).where(
        ExternalIdentity.box_id == member.box_id, ExternalIdentity.provider == "clerk",
        ExternalIdentity.issuer == member.issuer, ExternalIdentity.organization_id == member.organization_id,
        Principal.principal_type == "human")
    if command.after_id is not None:
        query = query.where(ExternalIdentity.id > str(command.after_id))
    rows = s.execute(query.order_by(ExternalIdentity.id).limit(101)
                     .execution_options(populate_existing=True)).all()
    selected = rows[:100]
    now = access._now(s)
    context = _context(s, [principal.id for _, principal in selected]) if selected else ([], {})
    result = {"contract_version": 1, "members": [_view(binding, principal, now, context) for binding, principal in selected],
              "next_after_id": selected[-1][0].id if len(rows) > 100 else None}
    fence()
    s.commit()
    return result


def _target(s, member, member_id):
    binding = s.scalar(select(ExternalIdentity).where(ExternalIdentity.id == member_id,
        ExternalIdentity.box_id == member.box_id, ExternalIdentity.provider == "clerk",
        ExternalIdentity.issuer == member.issuer, ExternalIdentity.organization_id == member.organization_id)
        .with_for_update().execution_options(populate_existing=True))
    if binding is None:
        raise access.PracticeAccessError("practice_access_not_found", 404)
    principal = s.scalar(select(Principal).where(Principal.id == binding.principal_id,
        Principal.box_id == member.box_id, Principal.principal_type == "human")
        .with_for_update().execution_options(populate_existing=True))
    if principal is None:
        raise access.PracticeAccessError("practice_access_not_found", 404)
    return binding, principal


def _recorded(row, member, owner, binding, principal, command):
    detail = row.detail
    if (row.box_id != member.box_id or row.aggregate_type != "external_identity"
            or row.aggregate_id != binding.id or row.event_type != RECORDED
            or row.actor_principal_id != owner.id or row.initiated_by_principal_id != owner.id
            or row.approved_by_principal_id != owner.id or not isinstance(detail, dict)
            or set(detail) != {"contract_version", "command", "identity_sha256", "receipt"}
            or detail["contract_version"] != 1 or detail["command"] != command.model_dump(mode="json")
            or detail["identity_sha256"] != payload_hash(_identity(binding, principal))):
        raise access.PracticeAccessError("practice_access_conflict")
    expected = {"receipt_id": row.id, "member_id": binding.id, "action": command.action,
        "recorded_state": "inactive" if command.action == "deactivate" else "active",
        "review_sha256": command.review_sha256, "recorded_at": _stamp(row.created_at)}
    if row.payload_hash != payload_hash(detail) or detail["receipt"] != expected or row.outcome != expected["recorded_state"]:
        raise access.PracticeAccessError("practice_access_unavailable", 503)
    return expected


def change(s, runtime, member, command, *, fence):
    owner = access._owner(s, runtime, member, fence)
    binding, principal = _target(s, member, str(command.member_id))
    previous = s.scalar(select(AuditEvent).where(AuditEvent.id == str(command.idempotency_key))
                        .with_for_update().execution_options(populate_existing=True))
    if previous is not None:
        # A later access change, or the passage of the review deadline, does not
        # replay an old write. Return its immutable historical receipt only.
        receipt = _recorded(previous, member, owner, binding, principal, command)
        fence()
        s.commit()
        return {"contract_version": 1, "receipt": receipt, "replayed": True}
    now = access._now(s)
    reviewed_at = datetime.fromisoformat(command.reviewed_at)
    if not reviewed_at <= now < reviewed_at + REVIEW_LIFETIME:
        raise access.PracticeAccessError("practice_access_conflict")
    view = _view(binding, principal, reviewed_at, _context(s, [principal.id]))
    if (principal.id == owner.id or principal.is_owner or view["action"] != command.action
            or view["review_sha256"] != command.review_sha256):
        raise access.PracticeAccessError("practice_access_conflict")
    receipt = {"receipt_id": str(command.idempotency_key), "member_id": binding.id,
        "action": command.action, "recorded_state": "inactive" if command.action == "deactivate" else "active",
        "review_sha256": command.review_sha256, "recorded_at": _stamp(now)}
    detail = {"contract_version": 1, "command": command.model_dump(mode="json"),
              "identity_sha256": payload_hash(_identity(binding, principal)), "receipt": receipt}
    s.add(AuditEvent(id=str(command.idempotency_key), box_id=member.box_id,
        aggregate_type="external_identity", aggregate_id=binding.id, event_type=RECORDED,
        actor_principal_id=owner.id, initiated_by_principal_id=owner.id, approved_by_principal_id=owner.id,
        outcome=receipt["recorded_state"], created_at=now, detail=detail, payload_hash=payload_hash(detail)))

    def commit_fence(session):
        # The existing writer owns commit. Its state/audit and this receipt must
        # remain one transaction, with a final cancellation/JWT fence after SQL.
        session.flush()
        fence()

    event.listen(s, "before_commit", commit_fence)
    try:
        fence()
        writer = admin.deactivate_beta_identity if command.action == "deactivate" else admin.reactivate_beta_identity
        writer(s, runtime, actor_principal_id=owner.id, clerk_subject=binding.subject,
               evidence_ref=f"practice-member:v1:{command.idempotency_key}:{command.review_sha256}")
    except BaseException:
        s.rollback()
        raise
    finally:
        event.remove(s, "before_commit", commit_fence)
    fence()
    return {"contract_version": 1, "receipt": receipt, "replayed": False}
