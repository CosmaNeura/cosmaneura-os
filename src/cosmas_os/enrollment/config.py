from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .domain import (
    BAA_DOC_ID,
    BAA_PDF_URL,
    BAA_SHA256,
    BAA_VERSION,
    CONTRACT,
    MAX_HUMANS,
    SEAT_CENTS,
    SEAT_POLICY,
)
from .environments import hosting_environment_for_data_mode


def owned_origin(value: str) -> bool:
    p = urlparse(value)
    return bool(p.scheme == "https" and p.hostname and not p.username and not p.password
                and not p.query and not p.fragment and p.path in ("", "/"))


def owned_https_url(value: str) -> bool:
    """HTTPS URL with an optional path for operator webhooks / download links."""
    p = urlparse(value)
    return bool(p.scheme == "https" and p.hostname and not p.username and not p.password
                and not p.query and not p.fragment and (p.path == "" or p.path.startswith("/")))


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
    # Blank preserves the no-audience default. A configured value is exact,
    # never an alternative audience or a replacement for session/party checks.
    clerk_audience: str = Field(default="", strict=True, max_length=255)
    clerk_authorized_parties: list[str] = []
    # Explicit native account path only. Browser session verification is unchanged.
    native_account_enabled: bool = False
    native_authorized_origins: list[str] = []
    # Private operator input containing measured native transports, never a token.
    native_workspace_proof_file: str = ""
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
    workspace_allocation_enabled: bool = False
    invitation_secret: SecretStr = SecretStr("")
    # Central master only. Each Box receives a derived immutable-scope key.
    runtime_admission_secret: SecretStr = SecretStr("")
    # Invitation email stays dark until the operator webhook is configured.
    # New / staging flags default OFF. Production never enables this path.
    invitation_mail_enabled: bool = False
    invitation_mail_webhook_url: str = ""
    invitation_mail_webhook_secret: SecretStr = SecretStr("")
    # Exact synthetic team test inboxes (in addition to *@example.invalid).
    # Empty by default; operators set exact addresses only — never secrets.
    invitation_mail_allowed_recipients: list[str] = []
    # Public Mac / iPhone distribution URLs. Empty means "not published yet".
    mac_download_url: str = ""
    iphone_download_url: str = ""
    google_callback_broker_enabled: bool = False
    google_callback_broker_origin: str = ""
    google_callback_client_id: str = ""

    def google_broker_errors(self) -> list[str]:
        if not self.google_callback_broker_enabled:
            return []
        env = hosting_environment_for_data_mode(self.data_mode)
        if (not self.enabled or env is None or not self.workspace_allocation_enabled
                or self.google_callback_broker_origin != env.api_origin
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com", self.google_callback_client_id)
                or len(self.runtime_admission_secret.get_secret_value()) < 32):
            return ["Google callback routing requires this environment's isolated broker and per-Box custody."]
        return []

    def native_origin_enabled(self, origin: str) -> bool:
        values = self.native_authorized_origins
        return bool(self.native_account_enabled and values and len(set(values)) == len(values)
                    and all(v in {"capacitor://localhost", "app://cosmas"} for v in values)
                    and origin in values)

    def registered_workspace_origin(self, origin: str, practice_id: str) -> bool:
        """Validate a stored practice destination, never arbitrary browser input.

        The additional practice-UUID namespace (staging or production) is enabled
        only with the private allocation workflow. Existing reviewed destinations
        remain exact.
        """
        if origin in self.allowed_workspace_origins:
            return True
        env = hosting_environment_for_data_mode(self.data_mode)
        if not self.workspace_allocation_enabled or env is None:
            return False
        try:
            if str(UUID(practice_id)) != practice_id:
                return False
        except (ValueError, TypeError):
            return False
        return origin == env.workspace_origin(practice_id)

    def workspace_origin_policy(self) -> str:
        if self.workspace_allocation_enabled and self.data_mode == "synthetic":
            return "synthetic-practice-uuid-staging-v1"
        if self.workspace_allocation_enabled and self.data_mode == "production":
            return "practice-uuid-production-v1"
        return "exact"

    def auth_errors(self) -> list[str]:
        errors: list[str] = []
        if any(ord(c) < 33 or ord(c) > 126 for c in self.clerk_audience):
            errors.append("Configure one exact printable Clerk session audience or leave it blank.")
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
            ("per-seat price", self.stripe_base_price_id, "price_"),
            ("portal configuration", self.stripe_portal_configuration_id, "bpc_"),
        ]:
            if not value.startswith(prefix):
                errors.append(f"Configure the Cosmas Stripe {name}.")
        # Legacy additional-price env may still be present; flat $300/seat uses only the base price.
        if self.stripe_additional_price_id and not self.stripe_additional_price_id.startswith("price_"):
            errors.append("Clear or repair the unused legacy additional Stripe price reference.")
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
        if self.workspace_allocation_enabled and not self.provisioning_enabled:
            errors.append("Workspace allocation requires the configured private provisioner.")
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

    def invitation_mail_configured(self) -> bool:
        # Synthetic staging only. Production and disabled modes stay fail-closed.
        return bool(self.data_mode == "synthetic"
                    and self.invitation_mail_enabled
                    and owned_https_url(self.invitation_mail_webhook_url)
                    and len(self.invitation_mail_webhook_secret.get_secret_value()) >= 32)

    def _download_url(self, value: str) -> str | None:
        if not value:
            return None
        return value if owned_https_url(value) else None

    def synthetic_staging_host(self) -> bool:
        """True only for the owned synthetic staging account host, never lab fixtures."""
        env = hosting_environment_for_data_mode(self.data_mode)
        return bool(
            self.data_mode == "synthetic"
            and env is not None
            and env.synthetic_only
            and self.public_app_origin.rstrip("/") == env.app_origin
        )

    def synthetic_staging_self_serve_ready(
        self,
        *,
        billing: bool,
        registration_blockers: list[str],
        workspace_confirmation_configured: bool = True,
    ) -> bool:
        """Admit synthetic staging trial finish without production acquisition flags.

        Hosted staging already uses data_mode=synthetic with practice-UUID workspace
        allocation. When provisioning, Stripe TEST billing, and workspace confirmation
        are ready, self-serve Checkout must not stick on activation_available=false.
        Lab fixtures and production never use this path.
        """
        return bool(
            self.synthetic_staging_host()
            and self.workspace_allocation_enabled
            and self.provisioning_enabled
            and billing
            and not registration_blockers
            and workspace_confirmation_configured
            and self.stripe_integration_enabled
            and self.commercial_terms_verified
            and not self.stripe_live_mode
        )

    def activation_blockers(self, *, billing: bool, registration_blockers: list[str],
                            workspace_confirmation_configured: bool = True) -> list[str]:
        """Explain why public activation remains closed without granting access."""
        if self.synthetic_staging_self_serve_ready(
            billing=billing,
            registration_blockers=registration_blockers,
            workspace_confirmation_configured=workspace_confirmation_configured,
        ):
            return []
        reasons: list[str] = []
        if registration_blockers:
            reasons.append("Registration admission is incomplete.")
        if not self.activation_available and not self.synthetic_staging_host():
            reasons.append("ENROLLMENT_ACTIVATION_AVAILABLE is false until the staged journey receipt admits trial activation.")
        if not self.provisioning_enabled:
            reasons.append("Workspace provisioning is not enabled.")
        if not self.stripe_acquisition_enabled and not self.synthetic_staging_host():
            reasons.append("Stripe acquisition remains closed.")
        if self.synthetic_staging_host() and not self.workspace_allocation_enabled:
            reasons.append("Synthetic staging self-serve trial needs practice workspace allocation.")
        if not billing:
            reasons.append("Stripe TEST catalog, portal, and webhook are not verified.")
        if not workspace_confirmation_configured:
            reasons.append("Workspace confirmation is not configured.")
        return reasons

    def public_config(self, *, database_ready: bool = False, auth_ready: bool = False,
                      stripe_verified: bool = False,
                      workspace_confirmation_configured: bool = True) -> dict:
        blockers = self.registration_errors()
        if not database_ready:
            blockers.append("Enrollment schema is unavailable; apply its dedicated migration.")
        if not auth_ready:
            blockers.append("Signed enrollment identity verification is unavailable.")
        billing_errors = self.billing_errors()
        billing = not billing_errors and stripe_verified
        synthetic_ready = self.synthetic_staging_self_serve_ready(
            billing=billing,
            registration_blockers=blockers,
            workspace_confirmation_configured=workspace_confirmation_configured,
        )
        checkout_ready = bool(
            (self.activation_available or synthetic_ready)
            and self.provisioning_enabled
            and billing
            and not blockers
            and workspace_confirmation_configured
        )
        activation = checkout_ready and (self.stripe_acquisition_enabled or synthetic_ready)
        return {
            "contract_version": CONTRACT, "enabled": not blockers, "data_mode": self.data_mode,
            "auth_configured": not self.auth_errors() and auth_ready,
            "clerk_publishable_key": self.clerk_publishable_key or None,
            "auth_methods": ["google", "microsoft", "password"],
            "billing_configured": billing, "production_qualified": self.production_qualified,
            "activation_available": activation,
            # Existing frozen attempts retain recovery while new acquisition is closed.
            "checkout_recovery_available": checkout_ready,
            "blockers": blockers, "billing_blockers": billing_errors + ([] if stripe_verified else ["Stripe catalog and portal have not been verified."]),
            "activation_blockers": ([] if activation else self.activation_blockers(
                billing=billing, registration_blockers=blockers,
                workspace_confirmation_configured=workspace_confirmation_configured)),
            "provisioning_enabled": self.provisioning_enabled,
            "allowed_workspace_origins": self.allowed_workspace_origins,
            "workspace_origin_policy": self.workspace_origin_policy(),
            "invitation_email_configured": self.invitation_mail_configured(),
            "client_install": {
                "mac_download_url": self._download_url(self.mac_download_url),
                "iphone_download_url": self._download_url(self.iphone_download_url),
                "open_chief_is_not_install": True,
            },
            "baa": {"doc_id": BAA_DOC_ID, "version": BAA_VERSION, "sha256": BAA_SHA256, "pdf_url": BAA_PDF_URL},
            "pricing": {"currency": "usd", "interval": "month", "seat_cents": SEAT_CENTS,
                        "max_self_serve_humans": MAX_HUMANS, "trial_days": 14, "seat_policy": SEAT_POLICY},
        }
