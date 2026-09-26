"""Local reference visibility; a private Core reference never becomes a Box catalog."""

from sqlalchemy import and_, exists, or_, select

from cosmas_os.models import CoreCaptureAccount, ExternalIdentity, PatientLink


def patient_visible(owner=None):
    shared = PatientLink.source_owner_id.is_(None)
    if owner is None:
        return shared
    current_account = exists(select(CoreCaptureAccount.id).join(
        ExternalIdentity, ExternalIdentity.id == CoreCaptureAccount.external_identity_id,
    ).where(
        CoreCaptureAccount.id == PatientLink.source_account_id,
        CoreCaptureAccount.revoked_at.is_(None),
        ExternalIdentity.active.is_(True),
        ExternalIdentity.box_id == PatientLink.box_id,
        ExternalIdentity.principal_id == owner,
    ))
    return or_(shared, and_(PatientLink.source_owner_id == owner, current_account))
