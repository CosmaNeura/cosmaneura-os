"""Additional SaaS condition after existing immutable human approval checks."""
from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy import select

from cosmas_os.adapters.enrollment_admission import (
    ACCESS_REQUIRED,
    EnrollmentAdmissionAdapter,
    RuntimeAdmissionError,
)
from cosmas_os.enrollment.domain import canonical_hash
from cosmas_os.models import AuditEvent, BoxContext, ExternalIdentity, Principal
from cosmas_os.practice_setup_models import PracticeSetupProfile


def prepare_registered_member(s, runtime, member, checked, *, fence):
    """Create only a non-owner local human from measured capped registry authority."""
    if not runtime.workspace_enrollment_managed or checked is None:
        return
    if (checked.get("enforced") is not True or checked.get("purpose") != "qualification"
            or checked.get("practice_id") != runtime.workspace_enrollment_practice_id):
        raise RuntimeAdmissionError(ACCESS_REQUIRED, 403)
    s.scalar(select(BoxContext).where(BoxContext.id == member.box_id).with_for_update())
    binding = s.scalar(select(ExternalIdentity).where(ExternalIdentity.issuer == member.issuer,
        ExternalIdentity.subject == member.subject).with_for_update())
    if binding is not None:
        # Existing access._binding rejects revocation/remapping. Never repair it
        # here or turn registry signer/admin authority into local owner authority.
        return
    if checked.get("member_role") == "owner":
        return  # Owner uses the existing reserved-owner setup completion.
    profile = s.get(PracticeSetupProfile, member.box_id)
    owner = s.get(Principal, profile.owner_id) if profile else None
    name = checked.get("display_name")
    if (checked.get("member_role") not in {"admin", "staff"} or profile is None or owner is None
            or owner.box_id != member.box_id or not owner.is_owner or owner.state != "active"
            or not isinstance(name, str) or not 2 <= len(name) <= 120 or name != name.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise RuntimeAdmissionError(ACCESS_REQUIRED, 403)
    fence()
    principal = Principal(id=str(uuid4()), box_id=member.box_id, principal_type="human", state="active", is_owner=False, display_name=name)
    s.add(principal)
    s.flush()
    evidence = "cosmas-enrollment-runtime-binding.v1:" + canonical_hash({**checked, "issuer": member.issuer,
        "subject": member.subject, "box_id": member.box_id, "organization_id": member.organization_id})
    binding = ExternalIdentity(box_id=member.box_id, principal_id=principal.id, provider="clerk", issuer=member.issuer,
        organization_id=member.organization_id, subject=member.subject, active=True,
        reviewed_by="Enrollment registry", evidence_ref=evidence)
    s.add(binding)
    s.flush()
    s.add(AuditEvent(box_id=member.box_id, aggregate_type="external_identity", aggregate_id=binding.id,
        event_type="external_identity.bound", actor_principal_id=principal.id, initiated_by_principal_id=principal.id,
        approved_by_principal_id=owner.id, outcome="approved", detail={"evidence_ref": evidence, "authority": "capped-enrollment-registry"}))
    fence()


def require_worker_admission(s, runtime, *, box, owner, operation_id, approval_sha256,
                             external_identity_id=None, adapter=None):
    if not runtime.workspace_enrollment_managed:
        return
    if box != runtime.beta_box_id or not re.fullmatch(r"[a-f0-9]{64}", approval_sha256 or ""):
        raise RuntimeAdmissionError(ACCESS_REQUIRED, 403)
    person = s.scalar(select(Principal).where(Principal.id == owner, Principal.box_id == box,
        Principal.principal_type == "human", Principal.state == "active", Principal.tombstoned_at.is_(None)))
    bindings = list(s.scalars(select(ExternalIdentity).where(ExternalIdentity.principal_id == owner,
        ExternalIdentity.box_id == box, ExternalIdentity.provider == "clerk", ExternalIdentity.issuer == runtime.clerk_issuer,
        ExternalIdentity.organization_id == runtime.clerk_organization_id, ExternalIdentity.active.is_(True))))
    if (person is None or len(bindings) != 1 or external_identity_id is not None and bindings[0].id != external_identity_id):
        raise RuntimeAdmissionError(ACCESS_REQUIRED, 403)
    # No bearer is persisted or replayed. This service purpose grants no approval.
    (adapter or EnrollmentAdmissionAdapter(runtime)).authorize("", bindings[0].subject, purpose="worker",
        operation_id=str(operation_id), approval_sha256=approval_sha256)
