"""Private synthetic provider-clock composition; never imported by deployed API.

StripeCommerce performs the real catalog/Checkout/read/webhook validation.
Only its HTTP transport is an invented provider. This does not qualify Stripe
TEST-clock compatibility or hosted TLS/runtime behavior.
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import parse_qs

import httpx

from cosmas_os.enrollment.domain import TRIAL, EnrollmentError
from cosmas_os.enrollment.service import EnrollmentService
from cosmas_os.enrollment.stripe import StripeCommerce


class ProviderDouble:
    """Invented provider behavior, separate from the authoritative registry."""

    def __init__(self, settings):
        self.settings = settings
        self.clock = {"id": "clock_syntheticm3", "livemode": False, "status": "ready", "frozen_time": int(time.time())}
        self.customer = {"id": "cus_syntheticm3", "livemode": False, "test_clock": self.clock["id"]}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self.invoices: dict[str, dict[str, Any]] = {}
        self.keys: dict[str, str] = {}
        self.checkout_count = self.charge_count = 0
        self.fail_reads = False
        self.transition: Literal["lagging", "failure", "paid"] = "lagging"

    def _price(self, price_id, amount):
        return {"id": price_id, "livemode": False, "active": True, "unit_amount": amount, "currency": "usd",
            "type": "recurring", "billing_scheme": "per_unit", "recurring": {
                "interval": "month", "interval_count": 1, "usage_type": "licensed"}}

    def request(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.stripe.com"
        assert request.headers["authorization"] == "Bearer sk_test_synthetic"
        path = request.url.path.removeprefix("/v1")
        data = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if self.fail_reads and request.method == "GET":
            raise httpx.ReadTimeout("invented provider outage")
        if path == "/account":
            result = {"id": self.settings.stripe_account_id}
        elif path.startswith("/prices/"):
            price = path.rsplit("/", 1)[-1]
            result = self._price(price, 30000 if price == self.settings.stripe_base_price_id else 10000)
        elif path.startswith("/billing_portal/configurations/"):
            result = {"id": self.settings.stripe_portal_configuration_id, "livemode": False, "active": True,
                "features": {"subscription_update": {"enabled": False}, "customer_update": {"enabled": False},
                    "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
                    "invoice_history": {"enabled": True}, "payment_method_update": {"enabled": True}},
                "login_page": {"enabled": False}}
        elif path == "/test_helpers/test_clocks" and request.method == "POST":
            assert int(data["frozen_time"]) == self.clock["frozen_time"]
            result = self.clock
        elif path == "/customers" and request.method == "POST":
            assert data == {"test_clock": self.clock["id"]}
            result = self.customer
        elif path == "/customers/" + self.customer["id"]:
            result = self.customer
        elif path == "/test_helpers/test_clocks/" + self.clock["id"] + "/advance":
            stamp = int(data["frozen_time"])
            assert stamp >= self.clock["frozen_time"]
            self.clock.update(frozen_time=stamp, status="ready")
            self._period_transition()
            result = self.clock
        elif path == "/test_helpers/test_clocks/" + self.clock["id"]:
            result = self.clock
        elif path == "/checkout/sessions" and request.method == "POST":
            assert data["customer"] == self.customer["id"] and "customer_email" not in data
            assert data["subscription_data[trial_period_days]"] == "14"
            key = request.headers["idempotency-key"]
            if key not in self.keys:
                self.checkout_count += 1
                session_id = "cs_syntheticm3" + str(self.checkout_count)
                metadata = {k[9:-1]: v for k, v in data.items() if k.startswith("metadata[")}
                self.sessions[session_id] = {"id": session_id, "livemode": False, "mode": "subscription", "status": "open",
                    "client_reference_id": data["client_reference_id"], "metadata": metadata, "payment_method_collection": "always",
                    "amount_total": 0, "expires_at": int(time.time()) + 86400,
                    "url": "https://checkout.stripe.com/c/syntheticm3", "customer": self.customer["id"], "subscription": None}
                self.keys[key] = session_id
            result = self.sessions[self.keys[key]]
        elif path.startswith("/checkout/sessions/"):
            result = self.sessions[path.rsplit("/", 1)[-1]]
        elif path.startswith("/subscriptions/"):
            result = self.subscriptions[path.rsplit("/", 1)[-1]]
        elif path.startswith("/invoices/"):
            result = self.invoices[path.rsplit("/", 1)[-1]]
        else:
            raise AssertionError("Unexpected private synthetic provider operation")
        return httpx.Response(200, json=result)

    def complete(self, session_id: str) -> None:
        checkout = self.sessions[session_id]
        if checkout["status"] == "complete":
            return
        start = self.clock["frozen_time"]
        humans = int(checkout["metadata"]["human_seats"])
        items = [{"quantity": qty, "current_period_end": start + int(TRIAL.total_seconds()),
            "price": self._price(price, amount)} for price, qty, amount in [
                (self.settings.stripe_base_price_id, 1, 30000),
                (self.settings.stripe_additional_price_id, humans - 1, 10000)] if qty]
        sub_id = "sub_syntheticm3"
        self.subscriptions[sub_id] = {"id": sub_id, "customer": self.customer["id"], "livemode": False, "status": "trialing",
            "metadata": checkout["metadata"], "trial_start": start, "trial_end": start + int(TRIAL.total_seconds()),
            "cancel_at_period_end": False, "items": {"data": items}, "pause_collection": None}
        checkout.update(status="complete", subscription=sub_id)

    def _period_transition(self) -> None:
        for sub in self.subscriptions.values():
            if self.clock["frozen_time"] < sub["trial_end"]:
                continue
            if sub["cancel_at_period_end"]:
                sub["status"] = "canceled"
            elif self.transition != "lagging":
                self.invoices.setdefault("in_syntheticm3", {"id": "in_syntheticm3", "customer": self.customer["id"],
                    "subscription": sub["id"], "livemode": False, "paid": False, "status": "open"})
                sub["status"] = "past_due"
                if self.transition == "paid":
                    self.pay_same_invoice()

    def pay_same_invoice(self) -> None:
        invoice = self.invoices["in_syntheticm3"]
        if not invoice["paid"]:
            self.charge_count += 1
        invoice.update(paid=True, status="paid")
        for sub in self.subscriptions.values():
            sub.update(status="active", current_period_end=sub["trial_end"] + 30 * 86400)


class ClockBoundStripeCommerce(StripeCommerce):
    """TEST-clock/customer binding is private composition, never request input."""

    def __init__(self, settings, provider: ProviderDouble):
        if settings.data_mode != "synthetic" or settings.stripe_live_mode or settings.stripe_secret_key.get_secret_value() != "sk_test_synthetic":
            raise ValueError("This source harness accepts only invented credentials and synthetic transport")
        super().__init__(settings, client=httpx.Client(transport=httpx.MockTransport(provider.request)))
        self.provider = provider
        self.practice_id: str | None = None
        self._stamp: int | None = None
        self._last_qualified_stamp: int | None = None
        self._trial: tuple[int, int] | None = None
        self.validate_configuration()
        self.clock_id = self._request("POST", "/test_helpers/test_clocks", {"frozen_time": str(provider.clock["frozen_time"])}, "synthetic-clock")["id"]
        self.customer_id = self._request("POST", "/customers", {"test_clock": self.clock_id}, "synthetic-customer")["id"]
        self.refresh_clock()

    def refresh_clock(self) -> None:
        previous = self._last_qualified_stamp
        self._stamp = None  # An interrupted/unready read cannot reuse virtual time.
        clock = self._request("GET", "/test_helpers/test_clocks/" + self.clock_id)
        customer = self._request("GET", "/customers/" + self.customer_id)
        if (clock.get("id") != self.clock_id or clock.get("livemode") is not False or clock.get("status") != "ready"
                or type(clock.get("frozen_time")) is not int or customer.get("id") != self.customer_id
                or customer.get("livemode") is not False or customer.get("test_clock") != self.clock_id
                or previous is not None and clock["frozen_time"] < previous):
            raise EnrollmentError("clock_unqualified", "Private provider clock is not qualified.", 503)
        self._stamp = self._last_qualified_stamp = clock["frozen_time"]

    def now(self) -> datetime:
        if self._stamp is None:
            raise EnrollmentError("clock_unqualified", "Private provider clock is not qualified.", 503)
        return datetime.fromtimestamp(self._stamp, UTC)

    def install(self, service: EnrollmentService) -> None:
        if service.settings.data_mode != "synthetic" or service.commerce is not self:
            raise ValueError("Period time requires this private synthetic composition")
        service._period_time = self

    def create_checkout(self, request, key):
        if (self.practice_id is not None and self.practice_id != request["practice_id"]
                or request.get("customer_id") not in (None, self.customer_id)):
            raise EnrollmentError("clock_binding_invalid", "Private clock binding changed.", 503)
        self.practice_id = request["practice_id"]
        return super().create_checkout({**request, "customer_id": self.customer_id}, key)

    def retrieve_checkout(self, session_id):
        value = super().retrieve_checkout(session_id)
        if value.get("customer") != self.customer_id or value.get("client_reference_id") != self.practice_id:
            raise EnrollmentError("clock_binding_invalid", "Private clock binding changed.", 503)
        return value

    def retrieve_subscription(self, subscription_id):
        value = super().retrieve_subscription(subscription_id)
        if value.get("customer") != self.customer_id or (value.get("metadata") or {}).get("practice_id") != self.practice_id:
            raise EnrollmentError("clock_binding_invalid", "Private clock binding changed.", 503)
        start, end = value.get("trial_start"), value.get("trial_end")
        if (type(start) is not int or type(end) is not int or end - start != int(TRIAL.total_seconds())
                or self._trial is not None and self._trial != (start, end)):
            raise EnrollmentError("clock_binding_invalid", "Private original trial binding changed.", 503)
        self._trial = (start, end)
        return value

    def advance(self, point: Literal["before", "expiry", "after"]) -> None:
        # Targets derive exclusively from the original provider trial, never CLI
        # dates or edits to the saved registry period.
        if self._trial is None:
            raise ValueError("Exact original fourteen-day trial required")
        end = self._trial[1]
        target = end + {"before": -1, "expiry": 0, "after": 1}[point]
        if self._stamp is None or target < self._stamp:
            raise ValueError("A private clock cannot rewind")
        self._stamp = None
        self._request("POST", "/test_helpers/test_clocks/" + self.clock_id + "/advance",
                      {"frozen_time": str(target)}, "synthetic-advance-" + point)
        self.refresh_clock()
        if self._stamp != target:
            self._stamp = None
            raise EnrollmentError("clock_unqualified", "Private provider clock did not reach the bound target.", 503)


def signed_event(commerce, event_type, obj, event_id):
    import hashlib
    import hmac
    raw = json.dumps({"id": event_id, "type": event_type, "created": int(time.time()),
        "api_version": commerce.settings.stripe_api_version, "livemode": False, "data": {"object": obj}}).encode()
    stamp = str(int(time.time()))
    digest = hmac.new(commerce.settings.stripe_webhook_secret.get_secret_value().encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return raw, "t=" + stamp + ",v1=" + digest
