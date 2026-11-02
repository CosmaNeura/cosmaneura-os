"""Self-serve account deletion for Apple App Review 5.1.1(v).

Deletes only the signed-in human's login binding and personal connection
secrets. Practice-shared Box data and every other principal stay untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cosmas_os.domain.enums import PrincipalState, PrincipalType
from cosmas_os.domain.rules import AuthorizationError, DomainError
from cosmas_os.google_connection_models import GoogleConnectionAttempt, GoogleConnectionCredential
from cosmas_os.microsoft_connection_models import (
    MicrosoftConnectionAttempt,
    MicrosoftConnectionCredential,
)
from cosmas_os.models import (
    AuditEvent,
    BoxContext,
    CoreCaptureAccount,
    ExternalIdentity,
    Principal,
    SchedulingAccount,
)

CONFIRM_PHRASE = "delete_my_account"


class AccountDeletionError(DomainError):
    """The signed-in user cannot complete account deletion safely."""


class ClerkUserDeletionPort(Protocol):
    def delete_user(self, subject: str) -> None: ...


def _now() -> datetime:
    return datetime.now(UTC)


def _wipe_personal_connection(session: Session, account_id: str) -> None:
    credential = session.get(GoogleConnectionCredential, account_id)
    if credential is not None and credential.status != "disconnected":
        credential.status = "disconnected"
        credential.sealed = None
        credential.refresh_id = None
    for attempt in session.scalars(
        select(GoogleConnectionAttempt).where(
            GoogleConnectionAttempt.account_id == account_id,
            GoogleConnectionAttempt.status.in_(("pending", "exchanging")),
        )
    ):
        attempt.status = "failed"
        attempt.sealed = None

    ms_credential = session.get(MicrosoftConnectionCredential, account_id)
    if ms_credential is not None and ms_credential.status != "disconnected":
        ms_credential.status = "disconnected"
        ms_credential.sealed = None
        ms_credential.refresh_id = None
    for attempt in session.scalars(
        select(MicrosoftConnectionAttempt).where(
            MicrosoftConnectionAttempt.account_id == account_id,
            MicrosoftConnectionAttempt.status.in_(("pending", "exchanging")),
        )
    ):
        attempt.status = "failed"
        attempt.sealed = None

    for capture in session.scalars(
        select(CoreCaptureAccount).where(
            CoreCaptureAccount.external_identity_id == account_id,
            CoreCaptureAccount.revoked_at.is_(None),
        )
    ):
        capture.revoked_at = _now()
    for scheduling in session.scalars(
        select(SchedulingAccount).where(
            SchedulingAccount.external_identity_id == account_id,
            SchedulingAccount.revoked_at.is_(None),
        )
    ):
        scheduling.revoked_at = _now()


def delete_own_account(
    session: Session,
    *,
    box_id: str,
    principal_id: str,
    external_identity_id: str | None,
    confirm: str,
    clerk: ClerkUserDeletionPort | None,
) -> dict[str, str]:
    """Delete the caller's CosmaBot account data and Clerk login.

    Requires an explicit confirm phrase. Never deletes another principal or
    practice-shared records (patients, tickets, appointments, other users).
    """

    if confirm != CONFIRM_PHRASE:
        raise AccountDeletionError("account deletion requires explicit confirmation")

    box = session.scalar(select(BoxContext).where(BoxContext.id == box_id).with_for_update())
    actor = session.scalar(
        select(Principal)
        .where(Principal.id == principal_id, Principal.box_id == box_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if box is None or actor is None:
        raise AuthorizationError("account deletion is unavailable")
    if (
        actor.principal_type != PrincipalType.HUMAN.value
        or actor.state != PrincipalState.ACTIVE.value
        or actor.tombstoned_at is not None
    ):
        raise AuthorizationError("account deletion is unavailable")

    bindings = list(
        session.scalars(
            select(ExternalIdentity)
            .where(
                ExternalIdentity.principal_id == actor.id,
                ExternalIdentity.box_id == box_id,
            )
            .with_for_update()
        )
    )
    if not bindings:
        raise AuthorizationError("account deletion is unavailable")
    if external_identity_id is not None and not any(b.id == external_identity_id for b in bindings):
        raise AuthorizationError("account deletion is unavailable")

    active_bindings = [b for b in bindings if b.active]
    if not active_bindings:
        raise AuthorizationError("account deletion is unavailable")

    if actor.is_owner:
        other_active_humans = session.scalar(
            select(func.count())
            .select_from(Principal)
            .where(
                Principal.box_id == box_id,
                Principal.id != actor.id,
                Principal.principal_type == PrincipalType.HUMAN.value,
                Principal.state == PrincipalState.ACTIVE.value,
                Principal.tombstoned_at.is_(None),
            )
        ) or 0
        if other_active_humans > 0:
            raise AccountDeletionError(
                "transfer ownership before deleting this owner account"
            )

    clerk_subjects = sorted({b.subject for b in active_bindings if b.provider == "clerk"})
    if clerk is None and clerk_subjects:
        raise AccountDeletionError("account deletion is temporarily unavailable")

    try:
        for binding in bindings:
            _wipe_personal_connection(session, binding.id)
            binding.active = False

        actor.state = PrincipalState.TOMBSTONED.value
        actor.tombstoned_at = _now()
        actor.display_name = "Deleted account"
        actor.is_owner = False

        session.add(
            AuditEvent(
                box_id=box_id,
                aggregate_type="principal",
                aggregate_id=actor.id,
                event_type="account.deleted",
                actor_principal_id=actor.id,
                approved_by_principal_id=actor.id,
                correlation_id=str(uuid4()),
                outcome="deleted",
                detail={
                    "provider": "clerk",
                    "subjects": clerk_subjects,
                    "external_identity_ids": [b.id for b in bindings],
                },
            )
        )
        session.flush()

        if clerk is not None:
            for subject in clerk_subjects:
                clerk.delete_user(subject)

        session.commit()
    except Exception:
        session.rollback()
        raise

    return {"status": "deleted"}
