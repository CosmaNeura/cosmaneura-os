"""Short first-use setup; ownership is verified before the user can claim it."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from cosmas_os.application import practice_access as access
from cosmas_os.application.beta_bootstrap import BetaBootstrapError, _matches_runtime
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import AuditEvent, BoxContext, ExternalIdentity, Principal
from cosmas_os.practice_setup_models import PracticeOwnerReservation, PracticeSetupProfile


def reserve_first_owner(s, runtime, manifest):
    """Host-only, protected reviewed manifest; no HTTP route can reserve a seat."""
    runtime.validate_runtime_configuration()
    if (not runtime.workspace_hosted_enabled or not _matches_runtime(manifest, runtime)
            or runtime.cosmas_env != "early_adopter_beta"):
        raise BetaBootstrapError("owner reservation does not match the reviewed runtime")
    # A transaction advisory lock also serializes an initially empty database.
    s.execute(select(func.pg_advisory_xact_lock(187463921)))
    digest = payload_hash(manifest.model_dump(mode="json"))
    existing = s.get(PracticeOwnerReservation, str(manifest.box_id))
    if existing is not None:
        if existing.manifest_sha256 != digest:
            raise BetaBootstrapError("owner reservation differs from reviewed state")
        s.commit()
        return
    if (s.scalar(select(func.count()).select_from(BoxContext))
            or s.scalar(select(func.count()).select_from(Principal))
            or s.scalar(select(func.count()).select_from(ExternalIdentity))):
        raise BetaBootstrapError("first owner reservation requires an empty dedicated practice")
    s.add(BoxContext(id=str(manifest.box_id), display_name=manifest.clinic_display_name))
    s.flush()
    s.add(PracticeOwnerReservation(box_id=str(manifest.box_id), issuer=manifest.clerk_issuer,
        organization_id=manifest.clerk_organization_id, subject=manifest.clerk_subject,
        reviewed_by=manifest.reviewed_by, evidence_ref=manifest.evidence_ref,
        manifest_sha256=digest, expires_at=access._now(s) + timedelta(days=7)))
    s.commit()


def _reservation(s, member):
    row = s.scalar(select(PracticeOwnerReservation).where(
        PracticeOwnerReservation.box_id == member.box_id,
        PracticeOwnerReservation.issuer == member.issuer,
        PracticeOwnerReservation.organization_id == member.organization_id,
        PracticeOwnerReservation.subject == member.subject,
    ).with_for_update().execution_options(populate_existing=True))
    return row


def _view(s, member, principal):
    profile = s.get(PracticeSetupProfile, member.box_id)
    if principal is not None:
        box = s.get(BoxContext, member.box_id)
        return {"contract_version": 1,
            "state": "owner_ready" if principal.is_owner and profile else "owner_setup" if principal.is_owner else "member_ready",
            "practice": {"display_name": profile.display_name if profile else box.display_name,
                         "specialty": profile.specialty if profile else None},
            "display_name": profile.owner_display_name if principal.is_owner and profile else principal.display_name,
            "can_start_practice": False}
    reservation = _reservation(s, member)
    allowed = bool(reservation and reservation.consumed_at is None
                   and reservation.expires_at > access._now(s)
                   and not s.scalar(select(func.count()).select_from(Principal).where(Principal.box_id == member.box_id)))
    return {"contract_version": 1, "state": "solo_setup_available" if allowed else "join_existing", "display_name": None,
            "practice": None, "can_start_practice": allowed}


def status(s, runtime, member, *, fence):
    access._scope(s, runtime, member, fence)
    principal = access._binding(s, member)
    result = _view(s, member, principal)
    fence()
    s.commit()
    return result


def complete(s, runtime, member, command, *, fence):
    access._scope(s, runtime, member, fence)
    principal = access._binding(s, member)
    request = command.model_dump(mode="json")
    digest = payload_hash({"contract": "practice-setup-v1", "request": request,
                          "box": member.box_id, "subject": member.subject})
    profile = s.get(PracticeSetupProfile, member.box_id)
    if profile is not None:
        if (principal is None or not principal.is_owner or principal.id != profile.owner_id
                or profile.request_key != str(command.idempotency_key) or profile.request_sha256 != digest):
            raise access.PracticeAccessError("practice_access_conflict")
    else:
        if principal is not None and not principal.is_owner:
            raise access.PracticeAccessError("practice_access_denied", 403)
        if principal is None:
            reservation = _reservation(s, member)
            if (reservation is None or reservation.consumed_at is not None
                    or reservation.expires_at <= access._now(s)
                    or s.scalar(select(func.count()).select_from(Principal).where(Principal.box_id == member.box_id))):
                raise access.PracticeAccessError("practice_access_denied", 403)
            principal = Principal(id=str(uuid4()), box_id=member.box_id, principal_type="human",
                display_name=command.display_name, state="active", is_owner=True)
            s.add(principal)
            s.flush()
            s.add(ExternalIdentity(box_id=member.box_id, principal_id=principal.id, provider="clerk",
                issuer=member.issuer, organization_id=member.organization_id, subject=member.subject,
                active=True, reviewed_by=reservation.reviewed_by, evidence_ref=reservation.evidence_ref))
            reservation.consumed_at = access._now(s)
        s.add(PracticeSetupProfile(box_id=member.box_id, owner_id=principal.id,
            display_name=command.practice_name, owner_display_name=command.display_name, specialty=command.specialty,
            request_key=str(command.idempotency_key), request_sha256=digest))
        s.add(AuditEvent(box_id=member.box_id, aggregate_type="practice_setup", aggregate_id=member.box_id,
            event_type="practice_setup.completed", actor_principal_id=principal.id,
            initiated_by_principal_id=principal.id, approved_by_principal_id=principal.id,
            outcome="completed", detail={"request_sha256": digest}))
        s.flush()
    result = _view(s, member, principal)
    fence()
    s.commit()
    return result
