"""Explicit loopback-only synthetic journey server; never imported by production API.

Run: python -m cosmas_os.enrollment.synthetic --port 8041
The lab routes issue invented sessions and drive fake Stripe/workspace state only.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
from dataclasses import asdict
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from pydantic import BaseModel, SecretStr
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from .api import create_app
from .config import EnrollmentSettings
from .domain import STRIPE_CONTRACT, TRIAL, EnrollmentError, HumanIdentity
from .migration import upgrade
from .models import EnrollmentBase
from .stripe import StripeCommerce
from .workspace import WorkspaceConfirmationRequest, WorkspaceConfirmationResult


def synthetic_settings() -> EnrollmentSettings:
    return EnrollmentSettings(enabled=True, data_mode="synthetic", database_url=SecretStr("sqlite://"),
        public_app_origin="https://app.example.invalid", allowed_origins=["https://app.example.invalid", "http://localhost:5173"],
        allowed_workspace_origins=["https://app.example.invalid"], clerk_publishable_key="pk_test_synthetic",
        clerk_secret_key=SecretStr("sk_test_synthetic"), clerk_issuer="https://enrollment.example.invalid",
        clerk_authorized_parties=["https://app.example.invalid"], clerk_methods_verified=True,
        stripe_integration_enabled=True, stripe_acquisition_enabled=True, stripe_secret_key=SecretStr("sk_test_synthetic"),
        stripe_account_id="acct_synthetic", stripe_base_price_id="price_syntheticbase", stripe_additional_price_id="price_syntheticadditional",
        stripe_portal_configuration_id="bpc_synthetic", stripe_webhook_secret=SecretStr("whsec_synthetic"),
        commercial_terms_verified=True, activation_available=True, provisioning_enabled=True,
        invitation_secret=SecretStr("synthetic-invitation-key-never-production"),
        runtime_admission_secret=SecretStr("synthetic-control-admission-master-never-production"))


class SyntheticIdentities:
    ready = True

    def __init__(self, settings: EnrollmentSettings):
        self.settings = settings
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.blocked_users: set[str] = set()
        self.removed_memberships: set[tuple[str, str]] = set()
        self.users = {"owner-a": ("owner-a@example.invalid", "Alex Example"),
                      "owner-b": ("owner-b@example.invalid", "Blair Example"),
                      "staff-a": ("staff-a@example.invalid", "Casey Example"),
                      "signer-a": ("signer-a@example.invalid", "Drew Example")}

    def token(self, user: str, organization_id: str | None = None) -> str:
        if user not in self.users:
            raise EnrollmentError("synthetic_identity_missing", "Choose an invented lab identity.", 404)
        now = int(time.time())
        claims = {"iss": self.settings.clerk_issuer, "sub": "user_synthetic_" + user,
                           "sid": "sess_synthetic_" + user, "azp": self.settings.public_app_origin,
                           "iat": now, "nbf": now, "exp": now + 3600}
        if organization_id:
            claims["org_id"] = organization_id
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "synthetic"})

    def verify(self, token: str) -> HumanIdentity:
        try:
            claims = jwt.decode(token, self.key.public_key(), algorithms=["RS256"], issuer=self.settings.clerk_issuer,
                                options={"require": ["iss", "sub", "sid", "azp", "iat", "nbf", "exp"]})
            user = claims["sub"].removeprefix("user_synthetic_")
            if "aud" in claims or claims["azp"] != self.settings.public_app_origin or user not in self.users:
                raise ValueError("invalid fixture identity")
            email, name = self.users[user]
            return HumanIdentity(self.settings.clerk_issuer, claims["sub"], claims["sid"], email, name)
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise EnrollmentError("invalid_identity", "Invalid synthetic session.", 401) from exc

    def verify_scoped(self, token: str, organization_id: str, *, authorized_parties: list[str] | None = None) -> HumanIdentity:
        claims = jwt.decode(token, self.key.public_key(), algorithms=["RS256"], issuer=self.settings.clerk_issuer)
        user = claims["sub"].removeprefix("user_synthetic_")
        if "aud" in claims or claims.get("azp") not in (authorized_parties or [self.settings.public_app_origin]) or user not in self.users:
            raise EnrollmentError("invalid_identity", "Invalid synthetic session.", 401)
        email, name = self.users[user]
        human = HumanIdentity(self.settings.clerk_issuer, claims["sub"], claims["sid"], email, name)
        compact = claims.get("o")
        values = [v for v in (claims.get("org_id"), compact.get("id") if isinstance(compact, dict) else None)
                  if isinstance(v, str) and v]
        if not values or len(set(values)) != 1 or values[0] != organization_id:
            raise EnrollmentError("runtime_scope_denied", "Select this synthetic practice.", 403)
        self.verify_registered_member(human.subject, organization_id)
        return human

    def verify_registered_member(self, subject: str, organization_id: str) -> HumanIdentity:
        user = subject.removeprefix("user_synthetic_")
        if user not in self.users or subject in self.blocked_users or (subject, organization_id) in self.removed_memberships:
            raise EnrollmentError("runtime_scope_denied", "Synthetic member is unavailable.", 403)
        email, name = self.users[user]
        return HumanIdentity(self.settings.clerk_issuer, subject, "", email, name)


class SyntheticCommerce:
    def __init__(self, settings: EnrollmentSettings):
        self.settings = settings
        self.sessions: dict[str, dict[str, Any]] = {}
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self.invoices: dict[str, dict[str, Any]] = {}
        self.keys: dict[str, str] = {}
        self.create_count = 0
        self.lose_next_reply = False
        self.fail_reads = False

    def validate_configuration(self) -> None:
        if self.settings.data_mode != "synthetic":
            raise RuntimeError("Fake commerce is synthetic-only")

    def create_checkout(self, request: dict[str, Any], key: str) -> dict[str, Any]:
        self.validate_configuration()
        if key not in self.keys:
            self.create_count += 1
            session_id = "cs_synthetic" + str(self.create_count)
            metadata = {"practice_id": request["practice_id"], "attempt_id": request["attempt_id"], "contract": STRIPE_CONTRACT,
                        "human_seats": str(request["human_seats"]), "monthly_total_cents": str(30000 + 10000 * (request["human_seats"] - 1)), "trial_days": "14"}
            self.sessions[session_id] = {"id": session_id, "livemode": False, "mode": "subscription", "status": "open",
                "client_reference_id": request["practice_id"], "metadata": metadata, "payment_method_collection": "always",
                "amount_total": 0,
                "expires_at": int(time.time()) + 86400, "url": "https://checkout.stripe.com/c/synthetic" + str(self.create_count),
                "customer": None, "subscription": None, "request": request}
            self.keys[key] = session_id
        if self.lose_next_reply:
            self.lose_next_reply = False
            raise EnrollmentError("stripe_unavailable", "Synthetic provider reply was lost.", 503)
        return dict(self.sessions[self.keys[key]])

    def retrieve_checkout(self, session_id: str) -> dict[str, Any]:
        if self.fail_reads:
            raise EnrollmentError("stripe_unavailable", "Synthetic provider is unavailable.", 503)
        return dict(self.sessions[session_id])

    def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        if self.fail_reads:
            raise EnrollmentError("stripe_unavailable", "Synthetic provider is unavailable.", 503)
        return self.subscriptions[subscription_id]

    def retrieve_invoice(self, invoice_id: str) -> dict[str, Any]:
        if self.fail_reads:
            raise EnrollmentError("stripe_unavailable", "Synthetic provider is unavailable.", 503)
        return self.invoices[invoice_id]

    def complete(self, session_id: str) -> None:
        checkout = self.sessions[session_id]
        if checkout["status"] == "complete":
            return
        request = checkout["request"]
        start = int(time.time())
        sub_id = "sub_synthetic" + session_id.removeprefix("cs_synthetic")
        customer = "cus_synthetic" + session_id.removeprefix("cs_synthetic")
        items = []
        for price, qty, amount in [(request["base_price_id"], 1, 30000), (request["additional_price_id"], request["human_seats"] - 1, 10000)]:
            if qty:
                items.append({"quantity": qty, "current_period_end": start + int(TRIAL.total_seconds()),
                              "price": {"id": price, "unit_amount": amount, "currency": "usd",
                                        "recurring": {"interval": "month", "interval_count": 1, "usage_type": "licensed"}}})
        self.subscriptions[sub_id] = {"id": sub_id, "customer": customer, "livemode": False, "status": "trialing",
            "metadata": dict(checkout["metadata"]), "trial_start": start, "trial_end": start + int(TRIAL.total_seconds()),
            "cancel_at_period_end": False, "items": {"data": items}, "pause_collection": None}
        checkout.update(status="complete", customer=customer, subscription=sub_id)

    def create_portal(self, customer_id: str, return_url: str) -> str:
        return "https://billing.stripe.com/p/session/synthetic"

    def verify_event(self, raw: bytes, signature: str) -> dict[str, Any]:
        return StripeCommerce(self.settings).verify_event(raw, signature)

    def signed_event(self, event_type: str, obj: dict[str, Any], event_id: str, created: int | None = None) -> tuple[bytes, str]:
        if event_type.startswith("invoice."):
            self.invoices[obj["id"]] = {**obj, "livemode": False,
                "paid": event_type != "invoice.payment_failed", "status": "open" if event_type == "invoice.payment_failed" else "paid"}
        raw = json.dumps({"id": event_id, "type": event_type, "created": created or int(time.time()),
                          "api_version": self.settings.stripe_api_version, "livemode": False, "data": {"object": obj}}).encode()
        stamp = str(int(time.time()))
        digest = hmac.new(self.settings.stripe_webhook_secret.get_secret_value().encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
        return raw, "t=" + stamp + ",v1=" + digest


class LabSessionBody(BaseModel):
    user: str
    organization_id: str | None = None


class LabPracticeBody(BaseModel):
    practice_id: str


class LabCheckoutBody(BaseModel):
    session_id: str


class LabMemberBody(LabPracticeBody):
    user: str


class SyntheticWorkspaceConfirmer:
    def __init__(self, identities: SyntheticIdentities):
        self.identities = identities

    def confirm(self, request: WorkspaceConfirmationRequest, workspace_token: str) -> WorkspaceConfirmationResult:
        identity = self.identities.verify(workspace_token)
        if (identity.issuer, identity.subject) != (request.issuer, request.subject):
            raise EnrollmentError("workspace_identity_mismatch", "The workspace session belongs to another human.", 403)
        claims = jwt.decode(workspace_token, self.identities.key.public_key(), algorithms=["RS256"], issuer=request.issuer)
        if not claims.get("org_id"):
            return WorkspaceConfirmationResult(None)
        if claims["org_id"] != request.organization_id:
            raise EnrollmentError("workspace_scope_mismatch", "Select this practice account before confirming.", 403)
        return WorkspaceConfirmationResult(hashlib.sha256(json.dumps(asdict(request), sort_keys=True).encode()).hexdigest())


def create_synthetic_app(*, engine=None) -> FastAPI:
    settings = synthetic_settings()
    if engine is None:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    upgrade(engine)
    identities, commerce = SyntheticIdentities(settings), SyntheticCommerce(settings)
    app = create_app(settings, engine=engine, verifier=identities, commerce=commerce,
                     workspace_confirmer=SyntheticWorkspaceConfirmer(identities))
    app.state.synthetic_identities, app.state.synthetic_commerce = identities, commerce

    @app.post("/lab/session")
    def lab_session(body: LabSessionBody):
        email, name = identities.users.get(body.user, ("", ""))
        return {"token": identities.token(body.user, body.organization_id), "email": email, "display_name": name, "data_mode": "synthetic"}

    @app.post("/lab/qualify")
    def qualify(body: LabPracticeBody):
        app.state.enrollment_service.record_workspace(body.practice_id,
            box_id=str(uuid5(NAMESPACE_URL, body.practice_id)), organization_id="org_synthetic" + body.practice_id.replace("-", ""),
            url="https://app.example.invalid/chief", proof_sha256="a" * 64,
            workspace_api_origin="https://api.example.invalid", source_commit="a" * 40, image_sha256="b" * 64)
        return {"qualified": True, "data_mode": "synthetic"}

    @app.post("/lab/checkout/complete")
    def complete(body: LabCheckoutBody):
        commerce.complete(body.session_id)
        raw, signature = commerce.signed_event("checkout.session.completed", commerce.sessions[body.session_id], "evt_synthetic_" + body.session_id)
        service = app.state.enrollment_service
        service.ingest(raw, signature)
        service.reconcile_pending()
        return {"completed": True, "data_mode": "synthetic"}

    @app.post("/lab/memberships/qualify")
    def qualify_member(body: LabMemberBody):
        identities.token(body.user)  # Require one of the explicitly invented humans.
        app.state.enrollment_service.record_membership_ready(body.practice_id,
            issuer=settings.clerk_issuer, subject="user_synthetic_" + body.user,
            organization_id="org_synthetic" + body.practice_id.replace("-", ""), proof_sha256="b" * 64)
        return {"qualified": True, "data_mode": "synthetic"}

    @app.post("/lab/checkout/expire")
    def expire(body: LabCheckoutBody):
        commerce.sessions[body.session_id]["status"] = "expired"
        return {"expired": True, "data_mode": "synthetic"}

    @app.post("/lab/reset")
    def reset():
        # The only caller-controlled reset exists in this synthetic entrypoint.
        EnrollmentBase.metadata.drop_all(engine)
        upgrade(engine)
        commerce.sessions.clear()
        commerce.subscriptions.clear()
        commerce.invoices.clear()
        commerce.keys.clear()
        commerce.create_count = 0
        commerce.fail_reads = commerce.lose_next_reply = False
        return {"reset": True, "data_mode": "synthetic"}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Loopback-only synthetic enrollment journey")
    parser.add_argument("--port", type=int, default=8041)
    args = parser.parse_args()
    uvicorn.run(create_synthetic_app(), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
