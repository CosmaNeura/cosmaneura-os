"""Cosmas SaaS adapter. Separate from practice-finance PaymentIntent connectors."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import EnrollmentSettings
from .domain import ADDITIONAL_HUMAN_CENTS, FIRST_HUMAN_CENTS, STRIPE_CONTRACT, EnrollmentError

EVENT_TYPES = {
    "checkout.session.completed", "checkout.session.expired",
    "customer.subscription.created", "customer.subscription.updated",
    "customer.subscription.deleted", "customer.subscription.paused",
    "customer.subscription.resumed", "invoice.paid", "invoice.payment_succeeded",
    "invoice.payment_failed",
}


def hosted_url(value: Any, host: str) -> str:
    p = urlparse(value if isinstance(value, str) else "")
    if p.scheme != "https" or p.hostname != host or p.username or p.password or p.port not in (None, 443):
        raise EnrollmentError("stripe_state_invalid", "Stripe returned an invalid hosted destination.", 503)
    return value


class StripeCommerce:
    def __init__(self, settings: EnrollmentSettings, *, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=httpx.Timeout(20, connect=10), follow_redirects=False)
        self.verified = False

    def _request(self, method: str, path: str, data: dict[str, str] | None = None,
                 key: str | None = None) -> dict[str, Any]:
        if self.settings.billing_errors():
            raise EnrollmentError("billing_not_configured", "Billing configuration is incomplete.", 503)
        headers = {"Authorization": "Bearer " + self.settings.stripe_secret_key.get_secret_value(),
                   "Stripe-Version": self.settings.stripe_api_version}
        if key:
            headers["Idempotency-Key"] = key
        for attempt in range(3):
            try:
                response = self.client.request(method, "https://api.stripe.com/v1" + path,
                                               headers=headers, data=data)
                retry = response.status_code in (429, 500, 502, 503, 504)
                if retry and (method == "GET" or key) and attempt < 2:
                    time.sleep(min(0.5 * 2**attempt, 2))
                    continue
                response.raise_for_status()
                value = response.json()
                if not isinstance(value, dict):
                    raise ValueError("invalid response")
                return value
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                if (method == "GET" or key) and attempt < 2:
                    time.sleep(min(0.5 * 2**attempt, 2))
                    continue
                raise EnrollmentError("stripe_unavailable", "Billing is temporarily unavailable. Your attempt is saved.", 503) from exc
            except (httpx.HTTPStatusError, ValueError) as exc:
                raise EnrollmentError("stripe_unavailable", "Billing could not confirm this request. Your attempt is saved.", 503) from exc
        raise EnrollmentError("stripe_unavailable", "Billing is temporarily unavailable.", 503)

    def _mode(self, value: dict[str, Any]) -> None:
        if value.get("livemode") is not self.settings.stripe_live_mode:
            raise EnrollmentError("stripe_state_invalid", "Stripe environment did not match enrollment.", 503)

    def _portal_configuration(self) -> None:
        config = self._request("GET", "/billing_portal/configurations/" + self.settings.stripe_portal_configuration_id)
        self._mode(config)
        if config.get("id") != self.settings.stripe_portal_configuration_id or config.get("active") is not True:
            raise EnrollmentError("portal_configuration_invalid", "The billing portal configuration is unavailable.", 503)
        features = config.get("features")
        if not isinstance(features, dict) or set(features) - {"customer_update", "invoice_history", "payment_method_update", "subscription_cancel", "subscription_update"}:
            raise EnrollmentError("portal_configuration_invalid", "The billing portal contains unreviewed features.", 503)
        for key in ("subscription_update", "customer_update"):
            if (features.get(key) or {}).get("enabled") is not False:
                raise EnrollmentError("portal_configuration_invalid", "Plan and customer edits must use Cosmas controls.", 503)
        cancel = features.get("subscription_cancel") or {}
        if cancel.get("enabled") is not True or cancel.get("mode") != "at_period_end":
            raise EnrollmentError("portal_configuration_invalid", "Configure cancellation before the next charge.", 503)
        for key in ("invoice_history", "payment_method_update"):
            if (features.get(key) or {}).get("enabled") is not True:
                raise EnrollmentError("portal_configuration_invalid", "Configure invoice and payment-method access.", 503)
        if (config.get("login_page") or {}).get("enabled") is True:
            raise EnrollmentError("portal_configuration_invalid", "Disable the public billing portal login page.", 503)

    def validate_configuration(self) -> None:
        self.verified = False
        account = self._request("GET", "/account")
        if account.get("id") != self.settings.stripe_account_id:
            raise EnrollmentError("stripe_account_invalid", "Stripe merchant account did not match enrollment.", 503)
        for price_id, amount in [(self.settings.stripe_base_price_id, FIRST_HUMAN_CENTS),
                                 (self.settings.stripe_additional_price_id, ADDITIONAL_HUMAN_CENTS)]:
            price = self._request("GET", "/prices/" + price_id)
            self._mode(price)
            recurring = price.get("recurring") or {}
            if (price.get("id") != price_id or price.get("active") is not True
                    or price.get("currency") != "usd" or price.get("unit_amount") != amount
                    or price.get("type") != "recurring" or price.get("billing_scheme") != "per_unit"
                    or recurring.get("interval") != "month" or recurring.get("interval_count") != 1
                    or recurring.get("usage_type") != "licensed"):
                raise EnrollmentError("stripe_price_invalid", "Stripe prices do not match the approved human-seat offer.", 503)
        self._portal_configuration()
        self.verified = True

    def create_checkout(self, request: dict[str, Any], key: str) -> dict[str, Any]:
        if (request.get("base_price_id") != self.settings.stripe_base_price_id
                or request.get("additional_price_id") != self.settings.stripe_additional_price_id
                or request.get("account_id") != self.settings.stripe_account_id
                or request.get("api_version") != self.settings.stripe_api_version
                or request.get("app_origin") != self.settings.public_app_origin.rstrip("/")
                or request.get("live_mode") is not self.settings.stripe_live_mode
                or request.get("trial_days") != 14):
            raise EnrollmentError("checkout_configuration_changed", "Reconcile the saved Checkout terms before changing billing configuration.", 503)
        self.validate_configuration()
        humans = request["human_seats"]
        if isinstance(humans, bool) or not isinstance(humans, int) or not 1 <= humans <= 10:
            raise EnrollmentError("negotiated_quote_required", "Contact us for negotiated pricing above ten humans.")
        data = {
            "mode": "subscription", "payment_method_collection": "always",
            "line_items[0][price]": self.settings.stripe_base_price_id,
            "line_items[0][quantity]": "1",
            "client_reference_id": request["practice_id"],
            "success_url": request["app_origin"] + "/onboarding?checkout=return",
            "cancel_url": request["app_origin"] + "/onboarding?checkout=canceled",
            "subscription_data[trial_period_days]": "14",
            "subscription_data[trial_settings][end_behavior][missing_payment_method]": "pause",
            "automatic_tax[enabled]": "false", "allow_promotion_codes": "false",
        }
        if humans > 1:
            data["line_items[1][price]"] = self.settings.stripe_additional_price_id
            data["line_items[1][quantity]"] = str(humans - 1)
        for name, value in {"practice_id": request["practice_id"], "attempt_id": request["attempt_id"],
                            "contract": STRIPE_CONTRACT, "human_seats": str(humans),
                            "monthly_total_cents": str(FIRST_HUMAN_CENTS + ADDITIONAL_HUMAN_CENTS * (humans - 1)),
                            "trial_days": "14"}.items():
            data[f"metadata[{name}]"] = value
            data[f"subscription_data[metadata][{name}]"] = value
        if request.get("customer_id"):
            data["customer"] = request["customer_id"]
        else:
            data["customer_email"] = request["email"]
        return self._request("POST", "/checkout/sessions", data, key)

    def retrieve_checkout(self, session_id: str) -> dict[str, Any]:
        if not session_id.startswith("cs_") or not session_id.replace("_", "").isalnum():
            raise EnrollmentError("stripe_state_invalid", "Stored Checkout binding is invalid.", 503)
        return self._request("GET", "/checkout/sessions/" + session_id)

    def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        if not subscription_id.startswith("sub_") or not subscription_id.replace("_", "").isalnum():
            raise EnrollmentError("stripe_state_invalid", "Stored subscription binding is invalid.", 503)
        return self._request("GET", "/subscriptions/" + subscription_id)

    def retrieve_invoice(self, invoice_id: str) -> dict[str, Any]:
        if not invoice_id.startswith("in_") or not invoice_id.replace("_", "").isalnum():
            raise EnrollmentError("stripe_state_invalid", "Stored invoice binding is invalid.", 503)
        return self._request("GET", "/invoices/" + invoice_id)

    def create_portal(self, customer_id: str, return_url: str) -> str:
        self.validate_configuration()
        result = self._request("POST", "/billing_portal/sessions", {
            "customer": customer_id, "configuration": self.settings.stripe_portal_configuration_id,
            "return_url": return_url,
        })
        return hosted_url(result.get("url"), "billing.stripe.com")

    def verify_event(self, raw: bytes, signature: str) -> dict[str, Any]:
        if self.settings.billing_errors():
            raise EnrollmentError("billing_not_configured", "Billing webhook is not configured.", 503)
        timestamps, signatures = [], []
        for piece in signature.split(","):
            key, _, value = piece.strip().partition("=")
            if key == "t":
                timestamps.append(value)
            elif key == "v1":
                signatures.append(value)
        try:
            stamp = timestamps[0] if len(timestamps) == 1 else "0"
            timestamp = int(stamp)
        except ValueError:
            stamp = "0"
            timestamp = 0
        expected = hmac.new(self.settings.stripe_webhook_secret.get_secret_value().encode(),
                            stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
        if abs(time.time() - timestamp) > 300 or not any(hmac.compare_digest(expected, s) for s in signatures):
            raise EnrollmentError("invalid_signature", "Invalid billing webhook signature.", 401)
        try:
            event = json.loads(raw)
        except ValueError as exc:
            raise EnrollmentError("invalid_event", "Invalid billing webhook envelope.", 400) from exc
        if (not isinstance(event, dict) or event.get("api_version") != self.settings.stripe_api_version
                or not isinstance(event.get("type"), str)
                or event.get("livemode") is not self.settings.stripe_live_mode
                or event.get("account") not in (None, self.settings.stripe_account_id)
                or not isinstance(event.get("id"), str) or not event["id"].startswith("evt_")
                or not isinstance(event.get("created"), int) or isinstance(event["created"], bool)
                or not 1 <= event["created"] <= int(time.time()) + 300
                or not isinstance((event.get("data") or {}).get("object"), dict)):
            raise EnrollmentError("invalid_event", "Billing event identity or environment did not match.", 400)
        return event
