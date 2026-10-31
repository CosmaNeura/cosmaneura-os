from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .config import EnrollmentSettings
from .domain import (
    BAA_DOC_ID,
    BAA_SHA256,
    BAA_VERSION,
    CONTRACT,
    STRIPE_CONTRACT,
    TRIAL,
    CommercePort,
    EnrollmentError,
    HumanIdentity,
    canonical_hash,
    document,
    iso,
    now_utc,
    quote,
    utc,
)
from .models import (
    Acceptance,
    Account,
    CheckoutAttempt,
    Command,
    Invitation,
    Membership,
    Practice,
    StripeInbox,
)
from .stripe import EVENT_TYPES, hosted_url
from .workspace import WorkspaceConfirmationRequest, WorkspaceConfirmer


def identifier() -> str:
    return str(uuid4())


class EnrollmentService:
    def __init__(self, sessions: sessionmaker, settings: EnrollmentSettings, commerce: CommercePort):
        self.sessions, self.settings, self.commerce = sessions, settings, commerce

    def _account(self, session: Session, identity: HumanIdentity) -> Account:
        account = session.scalar(select(Account).where(Account.issuer == identity.issuer,
                                Account.subject == identity.subject).with_for_update())
        if account is None:
            account = Account(id=identifier(), issuer=identity.issuer, subject=identity.subject,
                              email=identity.email, display_name=identity.display_name, title="",
                              revision=0, created_at=now_utc())
            try:
                with session.begin_nested():
                    session.add(account)
                    session.flush()
            except IntegrityError:
                account = session.scalar(select(Account).where(Account.issuer == identity.issuer,
                                         Account.subject == identity.subject).with_for_update())
                assert account
        elif account.email != identity.email:
            account.email = identity.email
        return account

    def _practice(self, session: Session, account: Account, *, owner: bool = False) -> tuple[Practice, Membership]:
        practice = session.scalar(select(Practice).where(Practice.id == account.active_practice_id).with_for_update()) if account.active_practice_id else None
        member = session.scalar(select(Membership).where(Membership.practice_id == account.active_practice_id,
                                Membership.account_id == account.id, Membership.active.is_(True)).with_for_update()) if practice else None
        if practice is None or member is None:
            raise EnrollmentError("practice_required", "Create or join your practice first.")
        if owner and member.role != "owner":
            raise EnrollmentError("owner_required", "Only the practice owner can manage billing or invitations.", 403)
        return practice, member

    def _acceptance(self, session: Session, practice: Practice) -> Acceptance | None:
        return session.scalar(select(Acceptance).where(Acceptance.practice_id == practice.id,
                              Acceptance.doc_id == BAA_DOC_ID, Acceptance.version == BAA_VERSION,
                              Acceptance.sha256 == BAA_SHA256))

    def _entitled(self, practice: Practice) -> bool:
        current = now_utc()
        if not practice.billing_verified_at or utc(practice.billing_verified_at) < current - timedelta(minutes=5):
            return False
        if practice.subscription_status == "trialing":
            return bool(practice.trial_ends_at and utc(practice.trial_ends_at) > current)
        return bool(practice.subscription_status == "active" and practice.paid_period_ends_at
                    and utc(practice.paid_period_ends_at) > current)

    def _view(self, session: Session, account: Account) -> dict[str, Any]:
        result: dict[str, Any] = {"contract_version": CONTRACT, "revision": account.revision,
            "stage": "account", "profile": {"display_name": account.display_name, "title": account.title, "email": account.email},
            "practice": None, "agreement": None, "quote": None,
            "billing": {"status": "none", "trial_ends_at": None, "first_charge_at": None,
                        "cancel_at_period_end": False, "payment_action_required": False},
            "workspace": {"status": "pending", "url": None, "organization_id": None, "box_id": None},
            "action_required": None}
        if not account.active_practice_id:
            if account.display_name and account.revision > 0:
                result["stage"] = "practice"
            return result
        practice, member = self._practice(session, account)
        acceptance = self._acceptance(session, practice)
        result["revision"] += practice.revision
        result["practice"] = {"id": practice.id, "legal_name": practice.legal_name, "display_name": practice.display_name,
                              **practice.address, "administrative_email": practice.administrative_email,
                              "human_seats": practice.human_seats, "role": member.role,
                              "covered_entity": practice.covered_entity, "can_sign": member.can_sign}
        result["agreement"] = {"accepted": acceptance is not None, "doc_id": BAA_DOC_ID, "version": BAA_VERSION,
                               "sha256": BAA_SHA256, "receipt_id": acceptance.id if acceptance else None}
        result["quote"] = quote(practice.human_seats)
        status = practice.subscription_status
        action = status in {"past_due", "unpaid", "paused", "pending_verification", "incomplete"}
        result["billing"] = {"status": status, "trial_ends_at": iso(practice.trial_ends_at),
                             "first_charge_at": iso(practice.trial_ends_at), "cancel_at_period_end": practice.cancel_at_period_end,
                             "payment_action_required": action}
        result["workspace"] = {"status": practice.workspace_status, "url": None,
                               "organization_id": practice.organization_id, "box_id": practice.box_id}
        if not acceptance:
            result["stage"] = "agreement"
            if not practice.covered_entity:
                result["action_required"] = "Contact us for an appropriate agreement for your practice."
        elif practice.human_seats > 10:
            result["stage"] = "negotiated"
            result["action_required"] = "Contact us for negotiated pricing for more than ten humans."
        elif practice.workspace_status != "ready":
            result["stage"] = "activation_pending"
            result["action_required"] = "Your workspace is being prepared. Your trial has not been activated."
        elif status in {"canceled", "incomplete_expired"}:
            result["stage"] = "canceled"
        elif action:
            result["stage"] = "payment_action_required"
        elif ((status == "trialing" and practice.trial_ends_at and utc(practice.trial_ends_at) <= now_utc())
              or (status == "active" and practice.paid_period_ends_at and utc(practice.paid_period_ends_at) <= now_utc())):
            result["stage"] = "payment_action_required"
            result["billing"]["payment_action_required"] = True
            result["action_required"] = "Your billing period ended. Check billing to restore access."
        elif self._entitled(practice) and not member.workspace_ready:
            result["stage"] = "finishing_setup"
            result["action_required"] = "Your practice access is being prepared."
        elif self._entitled(practice):
            result["stage"] = "ready"
            result["workspace"]["url"] = practice.workspace_url
        elif status in {"trialing", "active", "pending"}:
            result["stage"] = "finishing_setup"
            result["action_required"] = "Check your saved billing status to finish setup."
        else:
            result["stage"] = "payment"
        return result

    def status(self, identity: HumanIdentity) -> dict[str, Any]:
        with self.sessions.begin() as session:
            account = self._account(session, identity)
            if account.active_practice_id:
                practice, _ = self._practice(session, account)
                if practice.stripe_subscription_id and (not practice.billing_verified_at
                        or utc(practice.billing_verified_at) <= now_utc() - timedelta(minutes=5)
                        or practice.subscription_status == "trialing" and practice.trial_ends_at and utc(practice.trial_ends_at) <= now_utc()
                        or practice.subscription_status == "active" and practice.paid_period_ends_at and utc(practice.paid_period_ends_at) <= now_utc()):
                    # Any currently authorized human may refresh provider evidence.
                    # This grants no billing controls and performs no Stripe writes.
                    self._refresh_subscription(session, practice)
            return self._view(session, account)

    def _refresh_subscription(self, session: Session, practice: Practice) -> bool:
        if not practice.stripe_subscription_id:
            return False
        attempt = session.scalar(select(CheckoutAttempt).where(CheckoutAttempt.practice_id == practice.id,
                                 CheckoutAttempt.state == "complete").order_by(CheckoutAttempt.created_at.desc()))
        if not attempt:
            practice.billing_verified_at = None
            return False
        try:
            sub = self.commerce.retrieve_subscription(practice.stripe_subscription_id)
            self._confirm_failed_invoice(practice)
            self._apply_subscription(practice, attempt, sub)
            return True
        except Exception:
            practice.billing_verified_at = None
            practice.subscription_status = "pending_verification"
            practice.revision += 1
            return False

    def _confirm_failed_invoice(self, practice: Practice) -> None:
        if not practice.payment_failure_invoice_id:
            return
        invoice = self.commerce.retrieve_invoice(practice.payment_failure_invoice_id)
        parent = invoice.get("parent") or {}
        subscription_id = invoice.get("subscription") or (parent.get("subscription_details") or {}).get("subscription")
        if (invoice.get("id") != practice.payment_failure_invoice_id
                or invoice.get("customer") != practice.stripe_customer_id
                or subscription_id != practice.stripe_subscription_id
                or invoice.get("livemode") is not self.settings.stripe_live_mode):
            raise EnrollmentError("invoice_binding_invalid", "Payment recovery did not match this practice.", 503)
        if invoice.get("paid") is True and invoice.get("status") == "paid":
            practice.payment_failure_invoice_id = None

    def _run(self, identity: HumanIdentity, key: str, operation: str, payload: dict[str, Any],
             action: Callable[[Session, Account], dict[str, Any]]) -> dict[str, Any]:
        if not key or len(key) > 128:
            raise EnrollmentError("idempotency_required", "A stable Idempotency-Key is required.", 422)
        digest = canonical_hash(payload)
        with self.sessions.begin() as session:
            account = self._account(session, identity)
            if account.active_practice_id:
                _, member = self._practice(session, account)
                if operation in {"checkout", "portal", "invite", "practice"} and member.role != "owner":
                    raise EnrollmentError("owner_required", "Only the practice owner can manage this step.", 403)
                if operation == "accept" and not member.can_sign:
                    raise EnrollmentError("signer_required", "Ask an authorized practice representative to accept this agreement.", 403)
            prior = session.scalar(select(Command).where(Command.account_id == account.id, Command.key == key))
            if prior:
                if prior.operation != operation or prior.payload_sha256 != digest:
                    raise EnrollmentError("idempotency_conflict", "This attempt key was used for different information.")
                return prior.response
            if payload.get("expected_revision") != self._view(session, account)["revision"]:
                raise EnrollmentError("revision_conflict", "Your saved progress changed. Check progress and try again.")
            response = action(session, account)
            session.add(Command(id=identifier(), account_id=account.id, key=key, operation=operation,
                                payload_sha256=digest, response=response, created_at=now_utc()))
            return response

    def profile(self, identity: HumanIdentity, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        def action(session, account):
            account.display_name, account.title = payload["display_name"].strip(), payload["title"].strip()
            account.revision += 1
            return self._view(session, account)
        return self._run(identity, key, "profile", payload, action)

    def practices(self, identity: HumanIdentity) -> dict[str, Any]:
        with self.sessions.begin() as session:
            account = self._account(session, identity)
            rows = session.execute(select(Practice, Membership).join(Membership, Membership.practice_id == Practice.id)
                                   .where(Membership.account_id == account.id, Membership.active.is_(True))).all()
            return {"active_practice_id": account.active_practice_id, "practices": [
                {"id": practice.id, "legal_name": practice.legal_name, "display_name": practice.display_name,
                 "role": member.role, "workspace_status": practice.workspace_status} for practice, member in rows]}

    def select_practice(self, identity: HumanIdentity, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        def action(session, account):
            member = session.scalar(select(Membership).where(Membership.account_id == account.id,
                                    Membership.practice_id == payload["practice_id"], Membership.active.is_(True)))
            if not member:
                raise EnrollmentError("practice_access_denied", "This account has no active access to that practice.", 403)
            account.active_practice_id = member.practice_id
            account.revision += 1
            return self._view(session, account)
        return self._run(identity, key, "select_practice", payload, action)

    def practice(self, identity: HumanIdentity, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        def action(session, account):
            if not account.display_name or account.revision < 1:
                raise EnrollmentError("profile_required", "Save your name and role before creating a practice.")
            fields = {k: payload[k] for k in ("address_line1", "address_line2", "city", "region", "postal_code", "country")}
            if account.active_practice_id:
                practice, _ = self._practice(session, account, owner=True)
                used = session.scalar(select(func.count()).select_from(Membership).where(Membership.practice_id == practice.id)) or 0
                reserved = session.scalar(select(func.count()).select_from(Invitation).where(Invitation.practice_id == practice.id,
                                          Invitation.used_by.is_(None), Invitation.expires_at > now_utc())) or 0
                if payload["human_seats"] < used + reserved:
                    raise EnrollmentError("human_seat_limit", "The selected total must include every human and pending invitation.")
                if self._acceptance(session, practice) or session.scalar(select(CheckoutAttempt.id).where(CheckoutAttempt.practice_id == practice.id)):
                    raise EnrollmentError("practice_frozen", "The signed practice and billing terms cannot be rewritten. Contact support.")
                practice.legal_name, practice.display_name, practice.address = payload["legal_name"], payload["display_name"], fields
                practice.administrative_email, practice.human_seats = payload["administrative_email"], payload["human_seats"]
                practice.covered_entity = payload["covered_entity"]
                practice.revision += 1
            else:
                practice = Practice(id=identifier(), owner_id=account.id, legal_name=payload["legal_name"],
                                    display_name=payload["display_name"], address=fields, administrative_email=payload["administrative_email"],
                                    human_seats=payload["human_seats"], covered_entity=payload["covered_entity"], revision=0,
                                    workspace_status="pending", subscription_status="none", cancel_at_period_end=False, created_at=now_utc())
                session.add(practice)
                session.flush()
                session.add(Membership(id=identifier(), practice_id=practice.id, account_id=account.id,
                                       role="owner", can_sign=True, active=True, created_at=now_utc()))
                session.flush()
                account.active_practice_id = practice.id
                account.revision += 1
            return self._view(session, account)
        return self._run(identity, key, "practice", payload, action)

    def accept(self, identity: HumanIdentity, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        def action(session, account):
            practice, member = self._practice(session, account)
            if not member.can_sign:
                raise EnrollmentError("signer_required", "Ask an authorized practice representative to accept this agreement.", 403)
            if not practice.covered_entity:
                raise EnrollmentError("agreement_eligibility", "This practice needs an appropriate agreement before activation.")
            if not payload["accepted"] or not payload["authority_confirmed"]:
                raise EnrollmentError("authority_required", "Confirm that you read the agreement and can bind the practice.", 422)
            if (payload["doc_id"], payload["version"], payload["sha256"]) != (BAA_DOC_ID, BAA_VERSION, BAA_SHA256):
                raise EnrollmentError("document_changed", "Reload and review the exact current agreement.")
            document()  # Never accept text that does not match its pinned digest.
            if self._acceptance(session, practice) is None:
                session.add(Acceptance(id=identifier(), practice_id=practice.id, account_id=account.id,
                    covered_entity_legal_name=practice.legal_name, signer_subject=identity.subject,
                    signer_name=payload["signature_name"].strip(), signer_title=payload["signature_title"].strip(), signer_email=identity.email,
                    authority_statement=f"I am authorized to bind {practice.legal_name} to this agreement.",
                    doc_id=BAA_DOC_ID, version=BAA_VERSION, sha256=BAA_SHA256, accepted_at=now_utc()))
                practice.revision += 1
                session.flush()
            return self._view(session, account)
        return self._run(identity, key, "accept", payload, action)

    def receipt(self, identity: HumanIdentity) -> dict[str, Any]:
        with self.sessions.begin() as session:
            practice, _ = self._practice(session, self._account(session, identity))
            a = self._acceptance(session, practice)
            if not a:
                raise EnrollmentError("agreement_required", "The practice agreement has not been accepted.", 404)
            return {"receipt": {"id": a.id, "practice_id": a.practice_id, "covered_entity_legal_name": a.covered_entity_legal_name,
                    "accepted_by_subject": a.signer_subject, "accepted_by_name": a.signer_name, "accepted_by_title": a.signer_title,
                    "accepted_by_email": a.signer_email, "accepted_at": iso(a.accepted_at), "doc_id": a.doc_id,
                    "version": a.version, "sha256": a.sha256, "authority_statement": a.authority_statement}, "document": document()}

    def _invite_token(self, invitation_id: str) -> str:
        secret = self.settings.invitation_secret.get_secret_value()
        if len(secret) < 32:
            raise EnrollmentError("invitations_not_configured", "Practice invitations are not configured.", 503)
        return invitation_id + "." + hmac.new(secret.encode(), invitation_id.encode(), hashlib.sha256).hexdigest()

    def invite(self, identity: HumanIdentity, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        def action(session, account):
            practice, _ = self._practice(session, account, owner=True)
            existing = session.scalar(select(Invitation).where(Invitation.practice_id == practice.id,
                                      Invitation.email == payload["email"].strip().lower(), Invitation.used_by.is_(None),
                                      Invitation.expires_at > now_utc()))
            if existing:
                return {"id": existing.id, "expires_at": iso(existing.expires_at), "role": existing.role,
                        "can_sign": existing.can_sign, "enrollment": self._view(session, account)}
            used = session.scalar(select(func.count()).select_from(Membership).where(Membership.practice_id == practice.id)) or 0
            reserved = session.scalar(select(func.count()).select_from(Invitation).where(Invitation.practice_id == practice.id,
                                      Invitation.used_by.is_(None), Invitation.expires_at > now_utc())) or 0
            if used + reserved >= practice.human_seats:
                raise EnrollmentError("human_seat_limit", "Every invited human needs a purchased human seat. Contact support to change seats.")
            invitation_id = identifier()
            token = self._invite_token(invitation_id)
            expiry = now_utc() + timedelta(days=7)
            session.add(Invitation(id=invitation_id, practice_id=practice.id, email=payload["email"].strip().lower(),
                                  role=payload["role"], can_sign=payload["can_sign"], token_sha256=hashlib.sha256(token.encode()).hexdigest(), expires_at=expiry))
            practice.revision += 1
            return {"id": invitation_id, "expires_at": iso(expiry), "role": payload["role"], "can_sign": payload["can_sign"], "enrollment": self._view(session, account)}
        response = self._run(identity, key, "invite", payload, action)
        return {**response, "token": self._invite_token(response["id"])}

    def join(self, identity: HumanIdentity, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        def action(session, account):
            token = payload["token"]
            invitation = session.scalar(select(Invitation).where(Invitation.token_sha256 == hashlib.sha256(token.encode()).hexdigest()).with_for_update())
            if not invitation or utc(invitation.expires_at) <= now_utc() or invitation.email != identity.email or invitation.used_by not in (None, account.id):
                raise EnrollmentError("invitation_invalid", "This invitation is expired or belongs to another verified account.", 403)
            practice = session.scalar(select(Practice).where(Practice.id == invitation.practice_id).with_for_update())
            assert practice
            member = session.scalar(select(Membership).where(Membership.practice_id == practice.id, Membership.account_id == account.id))
            if not member:
                used = session.scalar(select(func.count()).select_from(Membership).where(Membership.practice_id == practice.id)) or 0
                if used >= practice.human_seats:
                    raise EnrollmentError("human_seat_limit", "The practice has no available human seat. Ask the owner to update the plan.")
                session.add(Membership(id=identifier(), practice_id=practice.id, account_id=account.id,
                                       role=invitation.role, can_sign=invitation.can_sign, active=True, created_at=now_utc()))
                practice.revision += 1
                session.flush()
            elif not member.active:
                raise EnrollmentError("access_removed", "Your practice access was removed. Ask the owner to restore it.", 403)
            invitation.used_by = account.id
            account.active_practice_id = practice.id
            account.revision += 1
            return self._view(session, account)
        return self._run(identity, key, "join", payload, action)

    def record_workspace(self, practice_id: str, *, box_id: str, organization_id: str,
                         url: str, proof_sha256: str, status: str = "ready",
                         workspace_api_origin: str | None = None, source_commit: str | None = None,
                         image_sha256: str | None = None) -> None:
        """Private provisioner hook. Never exposed through the enrollment HTTP API.

        The caller must provision owner/Clerk membership and qualify the independent
        Box, then provide its immutable proof. A ready record does not grant billing.
        """
        origin = urlparse(url)
        try:
            UUID(box_id)
        except ValueError as exc:
            raise EnrollmentError("workspace_proof_invalid", "Workspace Box identity is invalid.") from exc
        if (status not in {"provisioning", "ready", "failed"} or not organization_id.startswith("org_")
                or len(proof_sha256) != 64 or any(c not in "0123456789abcdef" for c in proof_sha256)
                or origin.scheme != "https" or origin.username or origin.password or origin.fragment
                or f"https://{origin.netloc}" not in self.settings.allowed_workspace_origins):
            raise EnrollmentError("workspace_proof_invalid", "Workspace qualification evidence is invalid.")
        with self.sessions.begin() as session:
            practice = session.scalar(select(Practice).where(Practice.id == practice_id).with_for_update())
            if not practice:
                raise EnrollmentError("practice_missing", "Practice not found.", 404)
            if practice.box_id and (practice.box_id != box_id or practice.organization_id != organization_id):
                raise EnrollmentError("workspace_binding_immutable", "The practice workspace identity cannot be replaced.")
            if status == "ready" and not self._acceptance(session, practice):
                raise EnrollmentError("agreement_required", "Accept the agreement before workspace qualification.")
            practice.box_id, practice.organization_id, practice.workspace_url = box_id, organization_id, url
            if workspace_api_origin is not None:
                api = urlparse(workspace_api_origin)
                if api.scheme != "https" or not api.hostname or api.username or api.password or api.path not in ("", "/") or api.query or api.fragment:
                    raise EnrollmentError("workspace_proof_invalid", "Workspace API origin is invalid.")
                practice.workspace_api_origin = workspace_api_origin.rstrip("/")
            if source_commit is not None:
                if len(source_commit) not in (40, 64) or any(c not in "0123456789abcdef" for c in source_commit):
                    raise EnrollmentError("workspace_proof_invalid", "Workspace source identity is invalid.")
                practice.source_commit = source_commit
            if image_sha256 is not None:
                digest = image_sha256.removeprefix("sha256:")
                if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise EnrollmentError("workspace_proof_invalid", "Workspace image identity is invalid.")
                practice.image_sha256 = digest
            practice.workspace_proof_sha256, practice.workspace_status = proof_sha256, status
            owner = session.scalar(select(Membership).where(Membership.practice_id == practice.id,
                                   Membership.account_id == practice.owner_id))
            if owner:
                owner.workspace_ready = status == "ready"
                owner.workspace_proof_sha256 = proof_sha256 if status == "ready" else None
            practice.revision += 1

    def confirm_workspace(self, identity: HumanIdentity, key: str, expected_revision: int,
                          workspace_token: str, confirmer: WorkspaceConfirmer) -> dict[str, Any]:
        payload = {"expected_revision": expected_revision,
                   "workspace_token_sha256": hashlib.sha256(workspace_token.encode()).hexdigest()}
        def prepare(session, account):
            practice, member = self._practice(session, account)
            if not self._acceptance(session, practice):
                raise EnrollmentError("agreement_required", "Accept the practice agreement before confirming access.")
            if not all([practice.box_id, practice.organization_id, practice.workspace_url, practice.workspace_api_origin,
                        practice.source_commit, practice.image_sha256]):
                raise EnrollmentError("workspace_preparation_pending", "Your workspace is being prepared. Check progress shortly.")
            scope = WorkspaceConfirmationRequest(practice_id=practice.id, box_id=practice.box_id or "",
                organization_id=practice.organization_id or "", workspace_api_origin=practice.workspace_api_origin or "",
                workspace_url=practice.workspace_url or "", source_commit=practice.source_commit or "", image_sha256=practice.image_sha256 or "",
                issuer=identity.issuer, subject=identity.subject, email=identity.email, display_name=account.display_name, role=member.role)
            return {"scope": asdict(scope), "completed": False}
        prepared = self._run(identity, key, "workspace_confirm", payload, prepare)
        if prepared.get("completed"):
            return self.status(identity)
        request = WorkspaceConfirmationRequest(**prepared["scope"])
        # The root port may create only registry-authorized Clerk membership and
        # measure real runtime scope. It receives the token in memory, never DB.
        result = confirmer.confirm(request, workspace_token)
        if result.proof_sha256 is not None and (len(result.proof_sha256) != 64 or any(c not in "0123456789abcdef" for c in result.proof_sha256)):
            raise EnrollmentError("workspace_proof_invalid", "Workspace confirmation evidence is invalid.", 503)
        with self.sessions.begin() as session:
            account = self._account(session, identity)
            practice, member = self._practice(session, account)
            if (practice.id, practice.box_id, practice.organization_id, practice.workspace_api_origin,
                    practice.workspace_url, practice.source_commit, practice.image_sha256, member.role) != (
                    request.practice_id, request.box_id, request.organization_id, request.workspace_api_origin,
                    request.workspace_url, request.source_commit, request.image_sha256, request.role):
                raise EnrollmentError("workspace_binding_changed", "Your selected workspace changed. Check progress and reconfirm.")
            if result.proof_sha256:
                if member.role == "owner":
                    practice.workspace_status, practice.workspace_proof_sha256 = "ready", result.proof_sha256
                elif practice.workspace_status != "ready":
                    raise EnrollmentError("workspace_preparation_pending", "The practice owner must finish workspace setup first.")
                member.workspace_ready, member.workspace_proof_sha256 = True, result.proof_sha256
                practice.revision += 1
            command = session.scalar(select(Command).where(Command.account_id == account.id, Command.key == key).with_for_update())
            assert command
            command.response = {**prepared, "completed": result.proof_sha256 is not None}
            state = self._view(session, account)
            if result.proof_sha256 is None:
                state["action_required"] = "Your practice membership is prepared. Refresh your account, select the practice and confirm again."
            return state

    def pending_human_memberships(self, practice_id: str) -> list[dict[str, Any]]:
        """Private provisioner inventory; never exposed in the customer API."""
        with self.sessions.begin() as session:
            members = session.execute(select(Membership, Account).join(Account, Membership.account_id == Account.id)
                                      .where(Membership.practice_id == practice_id, Membership.active.is_(True),
                                             Membership.workspace_ready.is_(False))).all()
            return [{"membership_id": member.id, "issuer": account.issuer, "subject": account.subject,
                     "email": account.email, "display_name": account.display_name, "role": member.role}
                    for member, account in members]

    def record_membership_ready(self, practice_id: str, *, issuer: str, subject: str,
                                organization_id: str, proof_sha256: str) -> None:
        """Private root hook after Clerk Org AND runtime human membership synchronization."""
        if len(proof_sha256) != 64 or any(c not in "0123456789abcdef" for c in proof_sha256):
            raise EnrollmentError("membership_proof_invalid", "Human membership proof is invalid.")
        with self.sessions.begin() as session:
            practice = session.scalar(select(Practice).where(Practice.id == practice_id).with_for_update())
            account = session.scalar(select(Account).where(Account.issuer == issuer, Account.subject == subject))
            member = session.scalar(select(Membership).where(Membership.practice_id == practice_id,
                                    Membership.account_id == account.id, Membership.active.is_(True))) if account else None
            if not practice or practice.organization_id != organization_id or practice.workspace_status != "ready" or not member:
                raise EnrollmentError("membership_proof_invalid", "Human membership is not bound to this ready practice.")
            member.workspace_ready, member.workspace_proof_sha256 = True, proof_sha256
            practice.revision += 1

    def _checkout_guard(self, session: Session, practice: Practice) -> None:
        if not self._acceptance(session, practice):
            raise EnrollmentError("agreement_required", "Accept the practice agreement before payment setup.")
        if practice.human_seats > 10:
            raise EnrollmentError("negotiated_quote_required", "Contact us for negotiated pricing above ten humans.")
        if practice.workspace_status != "ready" or not practice.workspace_proof_sha256:
            raise EnrollmentError("activation_pending", "Your trial starts only when your workspace is ready.")
        if not self.settings.activation_available or not self.settings.provisioning_enabled:
            raise EnrollmentError("activation_pending", "Workspace activation is not available yet.")

    def checkout(self, identity: HumanIdentity, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        # Freeze before crossing the provider boundary. Lost replies retain one
        # exact command/key; concurrent callers replay it instead of creating sales.
        def prepare(session, account):
            practice, _ = self._practice(session, account, owner=True)
            self._checkout_guard(session, practice)
            attempt = session.scalar(select(CheckoutAttempt).where(CheckoutAttempt.practice_id == practice.id,
                                     CheckoutAttempt.state.in_(["pending", "open", "reconciliation_required"])) )
            if not attempt:
                if practice.stripe_subscription_id or practice.trial_started_at:
                    raise EnrollmentError("trial_already_received", "Manage your saved subscription. A second trial requires support.")
                if not self.settings.stripe_acquisition_enabled:
                    raise EnrollmentError("billing_acquisition_disabled", "New trial checkout is currently unavailable.", 503)
                attempt_id = identifier()
                request = {"attempt_id": attempt_id, "practice_id": practice.id, "human_seats": practice.human_seats,
                           "email": identity.email, "customer_id": practice.stripe_customer_id,
                           "base_price_id": self.settings.stripe_base_price_id, "additional_price_id": self.settings.stripe_additional_price_id,
                           "account_id": self.settings.stripe_account_id, "live_mode": self.settings.stripe_live_mode,
                           "api_version": self.settings.stripe_api_version, "trial_days": 14,
                           "app_origin": self.settings.public_app_origin.rstrip("/")}
                attempt = CheckoutAttempt(id=attempt_id, practice_id=practice.id, request=request,
                                          request_sha256=canonical_hash(request), state="pending", created_at=now_utc())
                session.add(attempt)
                practice.subscription_status = "pending"
                practice.revision += 1
                session.flush()
            return {"attempt_id": attempt.id}
        response = self._run(identity, key, "checkout", payload, prepare)
        return self._resolve_checkout(identity, response["attempt_id"])

    def _session_binding(self, attempt: CheckoutAttempt, result: dict[str, Any]) -> None:
        request = attempt.request
        metadata = result.get("metadata") or {}
        if (result.get("livemode") is not request["live_mode"] or result.get("mode") != "subscription"
                or result.get("client_reference_id") != attempt.practice_id
                or metadata.get("practice_id") != attempt.practice_id or metadata.get("attempt_id") != attempt.id
                or metadata.get("contract") != STRIPE_CONTRACT or metadata.get("human_seats") != str(request["human_seats"])
                or result.get("payment_method_collection") != "always"
                or result.get("amount_total") not in (0, None)
                or result.get("status") == "complete" and result.get("amount_total") != 0
                or (attempt.stripe_session_id and result.get("id") != attempt.stripe_session_id)):
            raise EnrollmentError("stripe_binding_invalid", "Checkout is not bound to this practice and offer.", 503)

    def _apply_subscription(self, practice: Practice, attempt: CheckoutAttempt, sub: dict[str, Any]) -> None:
        metadata = sub.get("metadata") or {}
        request = attempt.request
        statuses = {"trialing", "active", "past_due", "unpaid", "paused", "canceled", "incomplete", "incomplete_expired"}
        items = (sub.get("items") or {}).get("data")
        quantities = {request["base_price_id"]: 1}
        if request["human_seats"] > 1:
            quantities[request["additional_price_id"]] = request["human_seats"] - 1
        if (not isinstance(items, list) or len(items) != len(quantities)
                or sub.get("livemode") is not request["live_mode"] or sub.get("status") not in statuses
                or metadata.get("practice_id") != practice.id or metadata.get("attempt_id") != attempt.id
                or metadata.get("contract") != STRIPE_CONTRACT or metadata.get("trial_days") != "14"
                or metadata.get("human_seats") != str(practice.human_seats)
                or metadata.get("monthly_total_cents") != str(30000 + 10000 * (practice.human_seats - 1))
                or not isinstance(sub.get("customer"), str) or not sub["customer"].startswith("cus_")
                or not isinstance(sub.get("id"), str) or not sub["id"].startswith("sub_")
                or (practice.stripe_customer_id and practice.stripe_customer_id != sub["customer"])
                or (practice.stripe_subscription_id and practice.stripe_subscription_id != sub["id"])):
            raise EnrollmentError("stripe_binding_invalid", "Subscription is not bound to this practice and offer.", 503)
        if sub.get("discounts") or sub.get("default_tax_rates") or (sub.get("automatic_tax") or {}).get("enabled") is True:
            raise EnrollmentError("stripe_price_invalid", "Subscription contains unapproved taxes or discounts.", 503)
        for item in items:
            price = item.get("price") or {}
            expected_amount = 30000 if price.get("id") == request["base_price_id"] else 10000
            recurring = price.get("recurring") or {}
            if (price.get("id") not in quantities or item.get("quantity") != quantities.pop(price["id"])
                    or isinstance(item.get("quantity"), bool) or price.get("unit_amount") != expected_amount
                    or price.get("currency") != "usd" or recurring.get("interval") != "month"
                    or recurring.get("interval_count") != 1 or recurring.get("usage_type") != "licensed"):
                raise EnrollmentError("stripe_price_invalid", "Subscription charges do not match the approved human-seat total.", 503)
        start, end = sub.get("trial_start"), sub.get("trial_end")
        if (not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool)
                or end - start != int(TRIAL.total_seconds())):
            raise EnrollmentError("trial_clock_invalid", "Stripe did not confirm the exact fourteen-day trial.", 503)
        trial_start, trial_end = datetime.fromtimestamp(start, UTC), datetime.fromtimestamp(end, UTC)
        if practice.trial_started_at and (not practice.trial_ends_at or utc(practice.trial_started_at) != trial_start or utc(practice.trial_ends_at) != trial_end):
            raise EnrollmentError("trial_clock_changed", "The original trial clock cannot be restarted.", 503)
        cancel = sub.get("cancel_at_period_end")
        if not isinstance(cancel, bool):
            raise EnrollmentError("stripe_state_invalid", "Subscription cancellation state is invalid.", 503)
        period = sub.get("current_period_end") or min((i.get("current_period_end", 0) for i in items), default=0)
        practice.stripe_customer_id, practice.stripe_subscription_id = sub["customer"], sub["id"]
        practice.trial_started_at, practice.trial_ends_at = trial_start, trial_end
        practice.subscription_status = ("pending_verification" if practice.payment_failure_invoice_id
                                        else sub["status"] if sub.get("pause_collection") is None else "paused")
        practice.cancel_at_period_end = cancel
        practice.billing_verified_at = now_utc()
        practice.paid_period_ends_at = datetime.fromtimestamp(period, UTC) if isinstance(period, int) and not isinstance(period, bool) and period > 0 else None
        practice.revision += 1

    def _resolve_checkout(self, identity: HumanIdentity, attempt_id: str) -> dict[str, Any]:
        with self.sessions.begin() as session:
            account = self._account(session, identity)
            practice, _ = self._practice(session, account, owner=True)
            attempt = session.get(CheckoutAttempt, attempt_id)
            if not attempt or attempt.practice_id != practice.id:
                raise EnrollmentError("checkout_missing", "This saved checkout is unavailable.")
            self._checkout_guard(session, practice)
            request, session_id, state = dict(attempt.request), attempt.stripe_session_id, attempt.state
            if canonical_hash(request) != attempt.request_sha256:
                raise EnrollmentError("checkout_integrity", "Saved Checkout terms failed integrity verification.", 503)
            if state == "reconciliation_required" or (not session_id and utc(attempt.created_at) <= now_utc() - timedelta(hours=23, minutes=55)):
                attempt.state = "reconciliation_required"
                # Commit the durable boundary before returning the recovery action.
                response = {"url": None, "status": "pending", "enrollment": self._view(session, account), "action_required": "Contact support to reconcile the saved Checkout attempt."}
                return response
        result = self.commerce.retrieve_checkout(session_id) if session_id else self.commerce.create_checkout(request, "cosmas-enrollment:" + attempt_id)
        subscription_id = result.get("subscription")
        if isinstance(subscription_id, dict):
            subscription_id = subscription_id.get("id")
        subscription = self.commerce.retrieve_subscription(subscription_id) if result.get("status") == "complete" and isinstance(subscription_id, str) else None
        with self.sessions.begin() as session:
            account = self._account(session, identity)
            practice, _ = self._practice(session, account, owner=True)
            attempt = session.scalar(select(CheckoutAttempt).where(CheckoutAttempt.id == attempt_id).with_for_update())
            assert attempt
            if attempt.practice_id != practice.id:
                raise EnrollmentError("checkout_binding_changed", "Your selected practice changed. Check progress before resuming Checkout.")
            self._session_binding(attempt, result)
            session_id = result.get("id")
            if not isinstance(session_id, str) or not session_id.startswith("cs_"):
                raise EnrollmentError("stripe_state_invalid", "Stripe Checkout identity is invalid.", 503)
            attempt.stripe_session_id = session_id
            if result.get("status") == "complete":
                if not subscription:
                    raise EnrollmentError("checkout_confirmation_pending", "Payment setup is still being confirmed.", 503)
                if result.get("customer") != subscription.get("customer"):
                    raise EnrollmentError("stripe_binding_invalid", "Checkout customer did not match its subscription.", 503)
                self._apply_subscription(practice, attempt, subscription)
                attempt.state, attempt.hosted_url = "complete", None
                return {"url": None, "status": "complete", "enrollment": self._view(session, account)}
            if result.get("status") == "expired":
                if subscription_id:
                    raise EnrollmentError("checkout_reconciliation_required", "Expired Checkout has a subscription; support must reconcile it.")
                attempt.state, attempt.hosted_url = "expired", None
                practice.subscription_status = "none"
                practice.revision += 1
                return {"url": None, "status": "expired", "enrollment": self._view(session, account)}
            expiry = result.get("expires_at")
            if result.get("status") != "open" or not isinstance(expiry, int) or isinstance(expiry, bool) or expiry <= now_utc().timestamp():
                raise EnrollmentError("stripe_state_invalid", "Checkout expiration state is invalid.", 503)
            attempt.state, attempt.expires_at = "open", datetime.fromtimestamp(expiry, UTC)
            attempt.hosted_url = hosted_url(result.get("url"), "checkout.stripe.com")
            return {"url": attempt.hosted_url, "status": "open", "enrollment": self._view(session, account)}

    def recover(self, identity: HumanIdentity, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        def prepare(session, account):
            practice, _ = self._practice(session, account)
            attempt = session.scalar(select(CheckoutAttempt).where(CheckoutAttempt.practice_id == practice.id).order_by(CheckoutAttempt.created_at.desc()))
            return {"practice_id": practice.id, "attempt_id": attempt.id if attempt else None, "subscription_id": practice.stripe_subscription_id}
        prepared = self._run(identity, key, "recover", payload, prepare)
        if prepared["subscription_id"]:
            subscription = self.commerce.retrieve_subscription(prepared["subscription_id"])
            with self.sessions.begin() as session:
                account = self._account(session, identity)
                practice, _ = self._practice(session, account)
                attempt = session.get(CheckoutAttempt, prepared["attempt_id"])
                assert attempt
                self._confirm_failed_invoice(practice)
                self._apply_subscription(practice, attempt, subscription)
                return self._view(session, account)
        if prepared["attempt_id"]:
            return self._resolve_checkout(identity, prepared["attempt_id"])["enrollment"]
        return self.status(identity)

    def portal(self, identity: HumanIdentity, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        def action(session, account):
            practice, _ = self._practice(session, account, owner=True)
            if not practice.stripe_customer_id:
                raise EnrollmentError("billing_account_required", "Complete payment setup before managing billing.")
            url = self.commerce.create_portal(practice.stripe_customer_id,
                                            self.settings.public_app_origin.rstrip("/") + "/onboarding")
            return {"url": hosted_url(url, "billing.stripe.com")}
        return self._run(identity, key, "portal", payload, action)

    def ingest(self, raw: bytes, signature: str) -> bool:
        event = self.commerce.verify_event(raw, signature)
        if event["type"] not in EVENT_TYPES:
            return False
        obj = event["data"]["object"]
        raw_parent = obj.get("parent")
        parent = raw_parent if isinstance(raw_parent, dict) else {}
        raw_details = parent.get("subscription_details")
        details = raw_details if isinstance(raw_details, dict) else {}
        raw_metadata = obj.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        def reference(value):
            candidate = value.get("id") if isinstance(value, dict) else value
            return candidate if isinstance(candidate, str) else None
        # No full invoice/customer payload, email, address or payment details retained.
        minimal = {"id": event["id"], "type": event["type"], "created": event["created"],
                   "object_id": reference(obj.get("id")), "subscription": reference(obj.get("subscription") or details.get("subscription")),
                   "metadata": {k: metadata.get(k) if isinstance(metadata.get(k), str) else None for k in ("practice_id", "attempt_id", "contract")},
                   "customer": reference(obj.get("customer"))}
        digest = canonical_hash(minimal)
        try:
            with self.sessions.begin() as session:
                prior = session.get(StripeInbox, event["id"])
                if prior:
                    if prior.payload_sha256 != digest:
                        raise EnrollmentError("event_conflict", "Repeated billing event changed its identity.", 400)
                    return True
                session.add(StripeInbox(id=event["id"], event_type=event["type"], payload=minimal, payload_sha256=digest,
                                        state="pending", attempts=0, created_at=now_utc()))
                if event["type"] == "invoice.payment_failed":
                    practice = session.scalar(select(Practice).where(Practice.stripe_subscription_id == minimal["subscription"]).with_for_update())
                    event_at = datetime.fromtimestamp(event["created"], UTC)
                    if practice and (not practice.last_event_at or utc(practice.last_event_at) <= event_at):
                        invoice_id = minimal["object_id"]
                        if not isinstance(invoice_id, str) or not invoice_id.startswith("in_"):
                            raise EnrollmentError("invalid_event", "Payment failure invoice identity is invalid.", 400)
                        practice.payment_failure_invoice_id = invoice_id
                        practice.subscription_status = "pending_verification"
                        practice.billing_verified_at = None
                        practice.revision += 1
        except IntegrityError:
            with self.sessions.begin() as session:
                prior = session.get(StripeInbox, event["id"])
                if not prior or prior.payload_sha256 != digest:
                    raise EnrollmentError("event_conflict", "Repeated billing event changed its identity.", 400) from None
        return True

    def reconcile(self, event_id: str) -> bool:
        with self.sessions.begin() as session:
            inbox = session.get(StripeInbox, event_id)
            if not inbox or inbox.state == "processed":
                return True
            payload = dict(inbox.payload)
        try:
            metadata = payload["metadata"]
            with self.sessions.begin() as session:
                if payload["type"].startswith("checkout."):
                    attempt = session.scalar(select(CheckoutAttempt).where(CheckoutAttempt.stripe_session_id == payload["object_id"]))
                    if not attempt and metadata.get("contract") == STRIPE_CONTRACT:
                        attempt = session.get(CheckoutAttempt, metadata.get("attempt_id"))
                    practice = session.get(Practice, attempt.practice_id) if attempt else None
                else:
                    subscription_id = payload["object_id"] if payload["type"].startswith("customer.subscription.") else payload["subscription"]
                    practice = session.scalar(select(Practice).where(Practice.stripe_subscription_id == subscription_id)) if subscription_id else None
                    attempt = session.scalar(select(CheckoutAttempt).where(CheckoutAttempt.practice_id == practice.id).order_by(CheckoutAttempt.created_at.desc())) if practice else None
                if not practice or not attempt:
                    raise EnrollmentError("event_binding_pending", "The saved billing binding has not been confirmed.")
                practice_id, attempt_id = practice.id, attempt.id
                session_id, subscription_id = attempt.stripe_session_id, practice.stripe_subscription_id
            checkout = self.commerce.retrieve_checkout(session_id or payload["object_id"]) if payload["type"].startswith("checkout.") else None
            if checkout:
                subscription_id = checkout.get("subscription")
            sub = self.commerce.retrieve_subscription(subscription_id) if isinstance(subscription_id, str) else None
            with self.sessions.begin() as session:
                practice = session.scalar(select(Practice).where(Practice.id == practice_id).with_for_update())
                attempt = session.get(CheckoutAttempt, attempt_id)
                inbox = session.scalar(select(StripeInbox).where(StripeInbox.id == event_id).with_for_update())
                assert practice and attempt and inbox
                if inbox.state == "processed":
                    return True
                event_at = datetime.fromtimestamp(payload["created"], UTC)
                if not practice.last_event_at or utc(practice.last_event_at) <= event_at:
                    if checkout:
                        self._session_binding(attempt, checkout)
                    if sub:
                        if checkout and checkout.get("customer") != sub.get("customer"):
                            raise EnrollmentError("stripe_binding_invalid", "Checkout customer did not match its subscription.", 503)
                        self._confirm_failed_invoice(practice)
                        self._apply_subscription(practice, attempt, sub)
                        attempt.state = "complete"
                        attempt.stripe_session_id = checkout["id"] if checkout else attempt.stripe_session_id
                    elif checkout and checkout.get("status") == "expired" and not checkout.get("subscription"):
                        attempt.state, practice.subscription_status = "expired", "none"
                        practice.revision += 1
                    else:
                        raise EnrollmentError("event_binding_pending", "Billing confirmation is still pending.")
                    practice.last_event_at = event_at
                inbox.state, inbox.error_code, inbox.payload = "processed", None, {}
                inbox.attempts += 1
            return True
        except Exception as exc:
            with self.sessions.begin() as session:
                inbox = session.scalar(select(StripeInbox).where(StripeInbox.id == event_id).with_for_update())
                if inbox and inbox.state != "processed":
                    inbox.attempts += 1
                    inbox.error_code = exc.code if isinstance(exc, EnrollmentError) else "billing_unavailable"
                    inbox.next_attempt_at = now_utc() + timedelta(seconds=min(2**min(inbox.attempts, 10), 300))
            return False

    def reconcile_pending(self) -> dict[str, int]:
        with self.sessions.begin() as session:
            ids = list(session.scalars(select(StripeInbox.id).where(StripeInbox.state == "pending",
                                       (StripeInbox.next_attempt_at.is_(None)) | (StripeInbox.next_attempt_at <= now_utc())).limit(100)))
        processed = sum(self.reconcile(event_id) for event_id in ids)
        return {"processed": processed, "pending": len(ids) - processed}

    def reconcile_subscriptions(self) -> dict[str, int]:
        """Periodic freshness repair, even when Stripe delivers no new event."""
        with self.sessions.begin() as session:
            ids = list(session.scalars(select(Practice.id).where(Practice.stripe_subscription_id.is_not(None),
                                       Practice.subscription_status.not_in(["canceled", "incomplete_expired"]))
                                       .order_by(Practice.billing_verified_at.asc().nulls_first()).limit(100)))
        succeeded = 0
        for practice_id in ids:
            with self.sessions.begin() as session:
                practice = session.scalar(select(Practice).where(Practice.id == practice_id).with_for_update())
                if practice:
                    succeeded += self._refresh_subscription(session, practice)
        return {"verified": succeeded, "pending": len(ids) - succeeded}
