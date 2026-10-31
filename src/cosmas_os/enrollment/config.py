from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .domain import (
    ADDITIONAL_HUMAN_CENTS,
    BAA_DOC_ID,
    BAA_PDF_URL,
    BAA_SHA256,
    BAA_VERSION,
    CONTRACT,
    FIRST_HUMAN_CENTS,
    MAX_HUMANS,
    SEAT_POLICY,
)


def owned_origin(value: str) -> bool:
    p = urlparse(value)
    return bool(p.scheme == "https" and p.hostname and not p.username and not p.password
                and not p.query and not p.fragment and p.path in ("", "/"))


class EnrollmentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENROLLMENT_", extra="ignore")
    enabled: bool = False
    data_mode: Literal["disabled", "synthetic", "production"] = "disabled"
    database_url: SecretStr = SecretStr("")
    public_app_origin: str = ""
    allowed_origins: list[str] = []
    allowed_workspace_origins: list[str] = []
    clerk_publishable_key: str = ""
    clerk_secret_key: SecretStr = SecretStr("")
    clerk_issuer: str = ""
    clerk_session_policy: Literal["default_session"] = "default_session"
    clerk_authorized_parties: list[str] = []
    # The selected instance must actually have these methods configured by its operator.
    clerk_methods_verified: bool = False
    stripe_integration_enabled: bool = False
    stripe_acquisition_enabled: bool = False
    stripe_secret_key: SecretStr = SecretStr("")
    stripe_account_id: str = ""
    stripe_base_price_id: str = ""
    stripe_additional_price_id: str = ""
    stripe_portal_configuration_id: str = ""
    stripe_webhook_secret: SecretStr = SecretStr("")
    stripe_api_version: str = "2025-09-30.clover"
    stripe_live_mode: bool = False
    commercial_terms_verified: bool = False
    activation_available: bool = False
    production_qualified: bool = False
    provisioning_enabled: bool = False
    invitation_secret: SecretStr = SecretStr("")
    # Central master only. Each Box receives a derived immutable-scope key.
    runtime_admission_secret: SecretStr = SecretStr("")

    def auth_errors(self) -> list[str]:
        errors: list[str] = []
        issuer = urlparse(self.clerk_issuer)
        if (not owned_origin(self.clerk_issuer) or not issuer.hostname
                or not self.clerk_authorized_parties
                or any(not owned_origin(o) for o in self.clerk_authorized_parties)):
            errors.append("Configure the enrollment Clerk issuer and authorized app origins.")
        mode = "live" if self.data_mode == "production" else "test"
        if not self.clerk_publishable_key.startswith(f"pk_{mode}_") or not self.clerk_secret_key.get_secret_value().startswith(f"sk_{mode}_"):
            errors.append("Configure enrollment-specific Clerk keys for the selected environment.")
        if not self.clerk_methods_verified:
            errors.append("Verify Google, Microsoft and email/password in the enrollment Clerk instance.")
        return errors

    def billing_errors(self) -> list[str]:
        errors: list[str] = []
        mode = "live" if self.stripe_live_mode else "test"
        if not self.stripe_integration_enabled:
            errors.append("Stripe integration is disabled.")
        if not self.stripe_secret_key.get_secret_value().startswith((f"sk_{mode}_", f"rk_{mode}_")):
            errors.append("Configure a Stripe key matching the selected mode.")
        for name, value, prefix in [
            ("account", self.stripe_account_id, "acct_"),
            ("base price", self.stripe_base_price_id, "price_"),
            ("additional human price", self.stripe_additional_price_id, "price_"),
            ("portal configuration", self.stripe_portal_configuration_id, "bpc_"),
        ]:
            if not value.startswith(prefix):
                errors.append(f"Configure the Cosmas Stripe {name}.")
        if self.stripe_base_price_id == self.stripe_additional_price_id:
            errors.append("The first and additional human prices must be distinct.")
        if not self.stripe_webhook_secret.get_secret_value().startswith("whsec_"):
            errors.append("Configure the enrollment Stripe webhook signing secret.")
        if self.stripe_api_version != "2025-09-30.clover":
            errors.append("The reviewed Stripe API version is required.")
        if not self.commercial_terms_verified:
            errors.append("Approve tax, cancellation, notification and human-seat commercial terms.")
        if self.data_mode == "production" and not self.stripe_live_mode:
            errors.append("Production cannot grant access from Stripe test-mode state.")
        if self.data_mode != "production" and self.stripe_live_mode:
            errors.append("Synthetic enrollment cannot use Stripe live mode.")
        return errors

    def registration_errors(self) -> list[str]:
        errors = self.auth_errors()
        if not self.enabled or self.data_mode == "disabled":
            errors.append("Customer enrollment is disabled.")
        db = self.database_url.get_secret_value()
        if not db:
            errors.append("Configure the independent durable enrollment database.")
        elif self.data_mode == "production" and not db.startswith("postgresql+psycopg://"):
            errors.append("Production enrollment requires PostgreSQL.")
        if not owned_origin(self.public_app_origin) or self.public_app_origin.rstrip("/") not in self.allowed_origins:
            errors.append("Configure the owned enrollment app origin and explicit CORS origins.")
        if self.data_mode == "production" and not self.production_qualified:
            errors.append("Production enrollment qualification is incomplete.")
        return errors

    def public_config(self, *, database_ready: bool = False, auth_ready: bool = False,
                      stripe_verified: bool = False) -> dict:
        blockers = self.registration_errors()
        if not database_ready:
            blockers.append("Enrollment schema is unavailable; apply its dedicated migration.")
        if not auth_ready:
            blockers.append("Signed enrollment identity verification is unavailable.")
        billing_errors = self.billing_errors()
        billing = not billing_errors and stripe_verified
        return {
            "contract_version": CONTRACT, "enabled": not blockers, "data_mode": self.data_mode,
            "auth_configured": not self.auth_errors() and auth_ready,
            "clerk_publishable_key": self.clerk_publishable_key or None,
            "auth_methods": ["google", "microsoft", "password"],
            "billing_configured": billing, "production_qualified": self.production_qualified,
            "activation_available": bool(self.activation_available and self.provisioning_enabled
                                         and billing and self.stripe_acquisition_enabled and not blockers),
            "blockers": blockers, "billing_blockers": billing_errors + ([] if stripe_verified else ["Stripe catalog and portal have not been verified."]),
            "provisioning_enabled": self.provisioning_enabled,
            "allowed_workspace_origins": self.allowed_workspace_origins,
            "baa": {"doc_id": BAA_DOC_ID, "version": BAA_VERSION, "sha256": BAA_SHA256, "pdf_url": BAA_PDF_URL},
            "pricing": {"currency": "usd", "interval": "month", "first_human_cents": FIRST_HUMAN_CENTS,
                        "additional_human_cents": ADDITIONAL_HUMAN_CENTS, "max_self_serve_humans": MAX_HUMANS,
                        "trial_days": 14, "seat_policy": SEAT_POLICY},
        }
