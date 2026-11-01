"""Lookup-only existing-user retention; ordinary local authorization still applies."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmas_os.models import AuditEvent, BoxContext, ExternalIdentity, Principal
from cosmas_os.practice_access_models import PracticeAccessRequest
from cosmas_os.practice_setup_models import PracticeSetupProfile

# edce906 first introduced enrollment admission at this recorded source time.
# This is a fixed policy boundary, never a startup time or customer-controlled flag.
EXISTING_USER_CUTOVER = datetime(2026, 10, 31, 15, 22, 5, tzinfo=UTC)
EXISTING_USER_POLICY = "cosmas-enrollment-existing-user.v1"
_AGREEMENT_EVENT = "cosmaneura.agreement.accepted"
_AGREEMENT_DOC_ID = "CN-BAA-CUST-CW"


def is_existing_user(
    session: Session | None, runtime: object, subject: str, principal_id: str | None = None
) -> bool:
    """Classify saved history for an already verified issuer/subject/Box/Org.

    This does not authenticate a session, reactivate a binding or grant permission.
    Current local human, membership and revocation checks remain mandatory.
    """
    issuer = getattr(runtime, "clerk_issuer", None)
    organization_id = getattr(runtime, "clerk_organization_id", None)
    box_id = getattr(runtime, "beta_box_id", None)
    if session is None or any(
        not isinstance(value, str) or not value or value != value.strip()
        for value in (issuer, organization_id, box_id, subject)
    ):
        return False
    with session.no_autoflush:
        binding = session.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.issuer == issuer,
                ExternalIdentity.subject == subject,
            )
        )
        if binding is not None and principal_id is not None and binding.principal_id != principal_id:
            return False
        person = session.get(Principal, binding.principal_id) if binding else None
        if binding is not None and (
            binding.provider != "clerk" or binding.box_id != box_id
            or binding.organization_id != organization_id or person is None
            or person.box_id != box_id or person.principal_type != "human"
        ):
            return False
        if (principal_id is None or binding is not None) and session.scalar(
            select(PracticeAccessRequest.id).where(
                PracticeAccessRequest.issuer == issuer,
                PracticeAccessRequest.subject == subject,
                PracticeAccessRequest.box_id == box_id,
                PracticeAccessRequest.organization_id == organization_id,
                PracticeAccessRequest.state == "approved",
                PracticeAccessRequest.decided_at < EXISTING_USER_CUTOVER,
                PracticeAccessRequest.decided_by.is_not(None),
            )
        ) is not None:
            return True
        if binding is not None and session.scalar(
            select(ExternalIdentity.id).where(
                ExternalIdentity.id == binding.id,
                ExternalIdentity.created_at < EXISTING_USER_CUTOVER,
            )
        ) is not None:
            return True
        if person is not None:
            if session.scalar(
                select(BoxContext.id).join(Principal, Principal.box_id == BoxContext.id).where(
                    BoxContext.id == box_id,
                    BoxContext.created_at < EXISTING_USER_CUTOVER,
                    Principal.id == person.id,
                    Principal.state == "active",
                    Principal.tombstoned_at.is_(None),
                )
            ) is not None:
                return True
        if person is not None and session.scalar(
            select(PracticeSetupProfile.box_id).where(
                PracticeSetupProfile.box_id == box_id,
                PracticeSetupProfile.owner_id == person.id,
                PracticeSetupProfile.completed_at < EXISTING_USER_CUTOVER,
            )
        ) is not None:
            return True
        agreement_query = select(AuditEvent).where(
            AuditEvent.box_id == box_id,
            AuditEvent.event_type == _AGREEMENT_EVENT,
            AuditEvent.outcome.in_(("accepted", "approved")),
        )
        if person is not None:
            agreement_query = agreement_query.where(AuditEvent.actor_principal_id == person.id)
        if principal_id is not None:
            agreement_query = agreement_query.where(AuditEvent.actor_principal_id == principal_id)
        for event in session.scalars(agreement_query):
            actor = session.get(Principal, event.actor_principal_id) if event.actor_principal_id else None
            detail = event.detail
            if (actor is not None and actor.box_id == box_id and actor.principal_type == "human"
                    and isinstance(detail, dict) and detail.get("issuer") == issuer
                    and detail.get("subject") == subject
                    and detail.get("organization_id") == organization_id
                    and detail.get("doc_id") == _AGREEMENT_DOC_ID
                    and isinstance(detail.get("version"), str) and detail["version"].strip()
                    and detail.get("box_id", box_id) == box_id
                    and detail.get("principal_id", actor.id) == actor.id):
                return True
        # Future retention/legal notices must use a separately reviewed hook;
        # never infer acceptance, import legacy data or rewrite an executed BAA.
        return False
