"""Proof-backed first connection, with explicit review and durable result receipts."""

import base64
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import select

from cosmas_os.adapters.scheduling_google_login import (
    AUTHORIZATION_URL,
    SchedulingGoogleLogin,
    digest,
)
from cosmas_os.application import workspace as ws
from cosmas_os.models import AuditEvent, BoxContext, ExternalIdentity, SchedulingAccount
from cosmas_os.ports.scheduling_enrollment import (
    EnrollmentCommand,
    catalog_digest,
    enrollment_command_digest,
)
from cosmas_os.scheduling_enrollment_models import SchedulingEnrollment
from cosmas_os.scheduling_login_models import SchedulingLoginCredential


def changed():
    return ws.WorkspaceError("scheduling_account_review_required", 409)


class SchedulingEnrollmentService:
    def __init__(self, login):
        self.login = login
        self.practice_id = UUID(login.settings.scheduling_enrollment_practice_id)
        self.config_digest = catalog_digest([login.config_digest, str(self.practice_id)])

    def enabled(self):
        self.login._enabled()
        if (
            not self.login.settings.workspace_scheduling_enrollment_enabled
            or self.login.settings.scheduling_enrollment_practice_id != str(self.practice_id)
        ):
            raise changed()

    def owner(self, session, identity=None, external_id=None):
        self.enabled()
        if identity is not None:
            if identity.auth_mode != "clerk_jwt" or not identity.external_identity_id:
                raise ws.WorkspaceError("scheduling_sign_in_unavailable", 403)
            external_id = identity.external_identity_id
        hint = session.get(ExternalIdentity, external_id)
        if hint is None:
            raise ws.WorkspaceError("scheduling_sign_in_unavailable", 403)
        hinted_box, hinted_owner = hint.box_id, hint.principal_id
        # Serialize enrollment with existing owner administration within this Box.
        box = session.scalar(
            select(BoxContext).where(BoxContext.id == hint.box_id).with_for_update()
        )
        # Patient setup and staff login lock the human before identity/account.
        # Preserve Box serialization while avoiding the reverse identity order.
        ws._human(session, hinted_box, hinted_owner, creating=True)
        session.expire(hint)
        external = session.scalar(
            select(ExternalIdentity)
            .where(ExternalIdentity.id == external_id, ExternalIdentity.active.is_(True))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            box is None
            or external is None
            or external.box_id != hinted_box
            or external.principal_id != hinted_owner
            or identity is not None
            and (
                external.box_id != identity.box_id or external.principal_id != identity.principal_id
            )
        ):
            raise ws.WorkspaceError("scheduling_sign_in_unavailable", 403)
        binding = catalog_digest(
            [
                self.config_digest,
                external.id,
                external.box_id,
                external.principal_id,
                external.issuer,
                external.subject,
                external.organization_id,
            ]
        )
        return external, binding

    def accounts(self, session, external):
        return list(
            session.scalars(
                select(SchedulingAccount).where(
                    SchedulingAccount.external_identity_id == external.id
                )
            )
        )

    def latest(self, session, external):
        return session.scalar(
            select(SchedulingEnrollment)
            .where(SchedulingEnrollment.external_identity_id == external.id)
            .order_by(SchedulingEnrollment.created_at.desc(), SchedulingEnrollment.id.desc())
            .limit(1)
            .with_for_update()
        )

    def attempt(self, session, external, binding, identifier):
        row = session.scalar(
            select(SchedulingEnrollment)
            .where(
                SchedulingEnrollment.id == str(identifier),
                SchedulingEnrollment.external_identity_id == external.id,
            )
            .with_for_update()
        )
        if row is None or row.binding_digest != binding:
            raise changed()
        return row

    def audit(self, session, external, row, event, outcome):
        session.add(
            AuditEvent(
                box_id=external.box_id,
                aggregate_type="scheduling_enrollment",
                aggregate_id=row.id,
                actor_principal_id=external.principal_id,
                event_type="workspace.scheduling_enrollment_" + event,
                outcome=outcome,
                detail={},
            )
        )

    def pack(self, row, binding, private):
        return self.login._seal(private, "enrollment", row.external_identity_id, binding, row.id)

    def unpack(self, row, binding):
        return self.login._open(row.sealed, "enrollment", row.external_identity_id, binding, row.id)

    def current_review(self, session, identity, command):
        external, binding = self.owner(session, identity)
        if self.accounts(session, external):
            raise changed()  # Includes administrative revocations, never self-reversed.
        row = self.attempt(session, external, binding, command.attempt_ref)
        if row.status != "review" or row.expires_at <= self.login.now():
            raise changed()
        private = self.unpack(row, binding)
        if datetime.fromisoformat(private["expires_at"]) <= self.login.now() + timedelta(
            seconds=60
        ):
            raise changed()
        return external, binding, row, private

    def catalog(self, private):
        self.enabled()
        result = self.login._verifier.catalog(self.practice_id, SecretStr(private["token"]))
        if str(result.actor_id) != private["actor_id"]:
            raise changed()
        self.enabled()
        return result

    def execute(self, identity, command: EnrollmentCommand):
        self.enabled()
        return getattr(self, command.action.removeprefix("enrollment_"))(identity, command)

    def status(self, identity, _command):
        with self.login._session() as session:
            external, binding = self.owner(session, identity)
            accounts = self.accounts(session, external)
            row = self.latest(session, external)
            active = [a for a in accounts if a.revoked_at is None]
            if accounts:
                return {
                    "state": "connected" if len(active) == 1 else "review_required",
                    "label": active[0].label if len(active) == 1 else None,
                    "attempt_ref": row.id if row else None,
                    "catalog": None,
                    "expires_at": None,
                }
            if (
                row is None
                or row.binding_digest != binding
                or row.status in {"failed", "confirmed"}
                or row.expires_at <= self.login.now()
            ):
                return {
                    "state": "not_connected",
                    "label": None,
                    "attempt_ref": None,
                    "catalog": None,
                    "expires_at": None,
                }
            base = {
                "label": None,
                "attempt_ref": row.id,
                "catalog": None,
                "expires_at": row.expires_at.astimezone(UTC).isoformat(),
            }
            if row.status != "review":
                return {
                    **base,
                    "state": "sign_in_pending" if row.status == "pending" else "completing_sign_in",
                }
            private = self.unpack(row, binding)
            if datetime.fromisoformat(private["expires_at"]) <= self.login.now() + timedelta(
                seconds=60
            ):
                raise changed()
            identifier = row.id
            session.commit()
        catalog = self.catalog(private)
        with self.login._session() as session:
            external, current = self.owner(session, identity)
            row = self.attempt(session, external, current, identifier)
            if (
                current != binding
                or row.status != "review"
                or row.expires_at <= self.login.now()
                or self.accounts(session, external)
            ):
                raise changed()
            state = (
                "choose_schedule"
                if catalog.practitioner and catalog.locations and catalog.appointment_types
                else "setup_required"
            )
            return {**base, "state": state, "catalog": catalog.model_dump(mode="json")}

    def start(self, identity, _command):
        with self.login._session() as session:
            external, binding = self.owner(session, identity)
            if self.accounts(session, external):
                raise changed()
            row = self.latest(session, external)
            now = self.login.now()
            if (
                row
                and row.status in {"pending", "exchanging", "review"}
                and (row.expires_at <= now or row.binding_digest != binding)
            ):
                row.status, row.sealed = "failed", None
                session.flush()
            if row and row.status in {"exchanging", "review"}:
                raise changed()
            if row is None or row.status != "pending":
                private = {
                    "state": secrets.token_urlsafe(32),
                    "nonce": secrets.token_urlsafe(32),
                    "verifier": secrets.token_urlsafe(48),
                }
                row = SchedulingEnrollment(
                    id=str(uuid4()),
                    external_identity_id=external.id,
                    state_digest=digest(private["state"]),
                    binding_digest=binding,
                    status="pending",
                    created_at=now,
                    expires_at=now + timedelta(minutes=10),
                )
                row.sealed = self.pack(row, binding, private)
                session.add(row)
                self.audit(session, external, row, "started", "pending")
            else:
                private = self.unpack(row, binding)
            url = (
                AUTHORIZATION_URL
                + "?"
                + urlencode(
                    {
                        "client_id": self.login.client_id,
                        "redirect_uri": self.login.callback_uri,
                        "response_type": "code",
                        "scope": "openid email",
                        "state": private["state"],
                        "nonce": private["nonce"],
                        "access_type": "offline",
                        "prompt": "consent select_account",
                        "code_challenge_method": "S256",
                        "code_challenge": base64.urlsafe_b64encode(
                            hashlib.sha256(private["verifier"].encode()).digest()
                        )
                        .rstrip(b"=")
                        .decode(),
                    }
                )
            )
            expiry = row.expires_at.astimezone(UTC).isoformat()
            session.commit()
            return {"authorization_url": url, "expires_at": expiry}

    def cancel(self, identity, _command):
        with self.login._session() as session:
            external, _ = self.owner(session, identity)
            row = self.latest(session, external)
            if row and row.status in {"pending", "exchanging", "review"}:
                row.status, row.sealed = "failed", None
                self.audit(session, external, row, "cancelled", "cancelled")
                session.commit()
            return {"state": "cancelled"}

    def recognizes(self, state):
        if not isinstance(state, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", state):
            return False
        self.enabled()
        with self.login._session() as session:
            return (
                session.scalar(
                    select(SchedulingEnrollment.id).where(
                        SchedulingEnrollment.state_digest == digest(state)
                    )
                )
                is not None
            )

    def callback(self, state, code=None, denied=False):
        identifier = None
        try:
            with self.login._session() as session:
                discovered = session.scalar(
                    select(SchedulingEnrollment).where(
                        SchedulingEnrollment.state_digest == digest(state)
                    )
                )
                if discovered is None:
                    return False
                external, binding = self.owner(session, external_id=discovered.external_identity_id)
                row = self.attempt(session, external, binding, discovered.id)
                if (
                    row.status != "pending"
                    or row.expires_at <= self.login.now()
                    or self.accounts(session, external)
                ):
                    raise changed()
                identifier, external_id = row.id, external.id
                private = self.unpack(row, binding)
                if not hmac.compare_digest(private["state"], state):
                    raise changed()
                if denied:
                    row.status, row.sealed = "failed", None
                    self.audit(session, external, row, "finished", "declined")
                    session.commit()
                    return False
                if (
                    not isinstance(code, str)
                    or not 1 <= len(code) <= 4096
                    or any(ord(c) < 33 or ord(c) > 126 for c in code)
                ):
                    raise changed()
                row.status = "exchanging"
                session.commit()
            value = self.login._exchange(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.login.callback_uri,
                    "code_verifier": private["verifier"],
                }
            )
            with self.login._session() as session:
                external, current = self.owner(session, external_id=external_id)
                row = self.attempt(session, external, current, identifier)
                if current != binding or row.status != "exchanging" or row.expires_at <= self.login.now() or self.accounts(session, external):
                    raise changed()
                session.commit()
            self.enabled()
            # This receiver verifies the Google signature and current membership.
            catalog = self.login._verifier.catalog(self.practice_id, SecretStr(value["id_token"]))
            credential, expiry = self.login._verified_claims(value, nonce=private["nonce"])
            with self.login._session() as session:
                external, current = self.owner(session, external_id=external_id)
                row = self.attempt(session, external, current, identifier)
                if (
                    current != binding
                    or row.status != "exchanging"
                    or row.expires_at <= self.login.now()
                    or self.accounts(session, external)
                ):
                    raise changed()
                row.sealed = self.pack(
                    row,
                    binding,
                    {
                        **credential,
                        "expires_at": expiry.isoformat(),
                        "actor_id": str(catalog.actor_id),
                    },
                )
                row.status = "review"
                self.audit(session, external, row, "authenticated", "review_required")
                session.commit()
            return True
        except Exception:
            if identifier:
                self.fail(identifier)
            return False

    def fail(self, identifier):
        try:
            with self.login._session() as session:
                row = session.scalar(
                    select(SchedulingEnrollment)
                    .where(SchedulingEnrollment.id == identifier)
                    .with_for_update()
                )
                if row and row.status in {"pending", "exchanging"}:
                    row.status, row.sealed = "failed", None
                    session.commit()
        except Exception:
            pass  # A durable exchanging claim blocks another code exchange.

    def plan(self, command, binding, catalog):
        if catalog.catalog_sha256 != command.catalog_sha256 or catalog.practitioner is None:
            raise changed()
        locations = [v for v in catalog.locations if v.id == command.location_id]
        kinds = [v for v in catalog.appointment_types if v.id == command.appointment_type_id]
        if len(locations) != 1 or len(kinds) != 1:
            raise changed()
        return catalog_digest(
            {
                "binding": binding,
                "attempt_ref": str(command.attempt_ref),
                "catalog_sha256": catalog.catalog_sha256,
                "location_id": str(command.location_id),
                "appointment_type_id": str(command.appointment_type_id),
                "command_key": str(command.command_key),
            }
        )

    def review(self, identity, command):
        with self.login._session() as session:
            _, binding, row, private = self.current_review(session, identity, command)
            expiry = row.expires_at.astimezone(UTC).isoformat()
            session.commit()
        catalog = self.catalog(private)
        plan = self.plan(command, binding, catalog)
        with self.login._session() as session:
            _, current, _, again = self.current_review(session, identity, command)
            if current != binding or again != private:
                raise changed()
            write = command.model_copy(
                update={"action": "enrollment_confirm", "plan_sha256": plan, "confirmed": True}
            )
            return {
                "state": "ready",
                "attempt_ref": str(command.attempt_ref),
                "catalog": catalog.model_dump(mode="json"),
                "location_id": str(command.location_id),
                "appointment_type_id": str(command.appointment_type_id),
                "plan_sha256": plan,
                "command_key": str(command.command_key),
                "command_sha256": enrollment_command_digest(write),
                "expires_at": expiry,
            }

    def receipt(self, session, row, command):
        expected = (
            command.command_sha256
            if command.action == "enrollment_result"
            else enrollment_command_digest(command)
        )
        if row.status != "confirmed":
            return {
                "state": "not_found",
                "attempt_ref": row.id,
                "command_key": str(command.command_key),
                "command_sha256": expected,
                "applied": False,
                "label": None,
            }
        if row.command_key != str(command.command_key) or row.command_sha256 != expected:
            raise changed()
        account = session.get(SchedulingAccount, row.account_id)
        if account is None or account.external_identity_id != row.external_identity_id:
            raise changed()
        return {
            "state": "connected" if account.revoked_at is None else "review_required",
            "attempt_ref": row.id,
            "command_key": row.command_key,
            "command_sha256": row.command_sha256,
            "applied": True,
            "label": account.label if account.revoked_at is None else None,
        }

    def result(self, identity, command):
        with self.login._session() as session:
            external, binding = self.owner(session, identity)
            row = self.attempt(session, external, binding, command.attempt_ref)
            return self.receipt(session, row, command)

    def confirm(self, identity, command):
        with self.login._session() as session:
            external, binding = self.owner(session, identity)
            row = self.attempt(session, external, binding, command.attempt_ref)
            if row.status == "confirmed":
                return self.receipt(session, row, command)
            _, binding, row, private = self.current_review(session, identity, command)
            session.commit()
        catalog = self.catalog(private)
        plan = self.plan(command, binding, catalog)
        if command.plan_sha256 != plan:
            raise changed()
        with self.login._session() as session:
            external, current, row, again = self.current_review(session, identity, command)
            if current != binding or again != private:
                raise changed()
            # A different OS human cannot silently take an already connected receiver actor.
            if session.scalar(
                select(SchedulingAccount.id)
                .where(
                    SchedulingAccount.practice_id == str(self.practice_id),
                    SchedulingAccount.actor_id == str(catalog.actor_id),
                    SchedulingAccount.revoked_at.is_(None),
                )
                .limit(1)
            ):
                raise changed()
            account = SchedulingAccount(
                external_identity_id=external.id,
                practice_id=str(self.practice_id),
                actor_id=str(catalog.actor_id),
                practitioner_id=str(catalog.practitioner.id),
                location_id=str(command.location_id),
                appointment_type_id=str(command.appointment_type_id),
                label=(catalog.practice.label + " · " + catalog.practitioner.label)[:120],
                reviewed_by="Provider confirmed verified Scheduling membership",
                evidence_ref="scheduling-enrollment:" + row.id + ":" + plan,
                reviewed_at=self.login.now(),
            )
            session.add(account)
            session.flush()
            _, selected, credential_binding = self.login._account(session, identity=identity)
            secret = {key: private[key] for key in ("token", "refresh", "subject")}
            session.add(
                SchedulingLoginCredential(
                    account_id=account.id,
                    binding_digest=credential_binding,
                    status="ready",
                    sealed=self.login._seal(secret, "credential", account.id, credential_binding),
                    connected_at=self.login.now(),
                    expires_at=datetime.fromisoformat(private["expires_at"]),
                )
            )
            row.status, row.sealed, row.account_id = "confirmed", None, account.id
            row.command_key, row.command_sha256 = (
                str(command.command_key),
                enrollment_command_digest(command),
            )
            self.audit(session, external, row, "confirmed", "connected")
            self.enabled()
            session.commit()
            return self.receipt(session, row, command)


class SchedulingEnrollmentLogin(SchedulingGoogleLogin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.enrollment = (
                SchedulingEnrollmentService(self)
                if self.settings.workspace_scheduling_enrollment_enabled
                else None
            )
        except BaseException:
            self.close()
            raise

    def callback(self, state, code=None, denied=False):
        if self.enrollment and self.enrollment.recognizes(state):
            return self.enrollment.callback(state, code, denied)
        return super().callback(state, code, denied)
