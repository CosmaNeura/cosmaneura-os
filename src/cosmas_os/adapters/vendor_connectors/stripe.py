"""Stripe PaymentIntent create/read only; creation never confirms a payment."""

import hashlib
import hmac
import re

from cosmas_os.ports.vendor_connectors import (
    EventCandidate,
    PaymentObservation,
    StripePaymentIntentIntent,
    VendorError,
)

from .transport import (
    MAX_HEADER_BYTES,
    MAX_RESPONSE_BYTES,
    STRIPE_VERSION,
    WireRequest,
    checked,
    form_bytes,
    parse_json,
    reference,
    require_reference,
    submission,
)


class StripeConnector:
    def __init__(self, runtime):
        self.runtime = runtime

    def prepare(self, command):
        command = checked(command)
        if command.selection.vendor != "stripe" or not isinstance(command.intent, StripePaymentIntentIntent):
            raise VendorError("capability_unavailable")
        intent = command.intent
        body = form_bytes([("amount", str(intent.amount)), ("currency", intent.currency),
            ("customer", intent.customer_id), ("confirm", "false"), ("payment_method_types[]", "card"),
            ("metadata[cosmas_operation_id]", str(command.operation_id))])
        return WireRequest("POST", "/v1/payment_intents", body, "application/x-www-form-urlencoded",
            (("Stripe-Version", STRIPE_VERSION), ("Idempotency-Key", str(command.operation_id))))

    def _payment(self, command, result, ref=None):
        data = result.data
        intent = command.intent
        if (result.status != 200 or data["object"] != "payment_intent" or data["customer"] != intent.customer_id
                or type(data["amount"]) is not int or data["amount"] != intent.amount
                or data["currency"] != intent.currency or data["livemode"] is not (command.selection.environment == "production")
                or ref is not None and data["id"] != ref.value):
            raise ValueError
        ref = ref or reference(command, result, "payment_intent", data["id"])
        value = PaymentObservation(reference=ref, observed_at=result.observed_at, state=data["status"],
            amount=data["amount"], currency=data["currency"], amount_received=data["amount_received"],
            livemode=data["livemode"], response_sha256=result.sha256)
        if value.amount_received > value.amount or value.state == "succeeded" and value.amount_received != value.amount:
            raise ValueError
        return value

    async def submit(self, command, approval):
        command = checked(command)
        if command.selection.vendor != "stripe":
            raise VendorError("capability_unavailable")
        return await self.runtime._submit(command, approval)

    def _parse_submission(self, command, result):
        payment = self._payment(command, result)
        return submission(command, result.observed_at, state="accepted", ref=payment.reference, response_hash=result.sha256)

    def _read_wire(self, command, ref):
        command = checked(command)
        if command.selection.vendor != "stripe" or not isinstance(command.intent, StripePaymentIntentIntent):
            raise VendorError("capability_unavailable")
        ref = require_reference(command, ref, "payment_intent")
        return WireRequest("GET", "/v1/payment_intents/" + ref.value,
            headers=(("Stripe-Version", STRIPE_VERSION),))

    async def observe(self, command, ref):
        command = checked(command)
        ref = require_reference(command, ref, "payment_intent")
        result = await self.runtime._exchange(command, ref=ref)
        try:
            return self._payment(command, result, ref)
        except (ValueError, TypeError, KeyError):
            raise VendorError("reference_unavailable" if result.status == 404 else "response_invalid", attempted=True) from None


def verify_webhook(raw: bytes, signature: str, secret: bytes, selection, now):
    try:
        if (selection.vendor != "stripe" or type(raw) is not bytes or len(raw) > MAX_RESPONSE_BYTES
                or type(signature) is not str or len(signature.encode()) > MAX_HEADER_BYTES
                or type(secret) is not bytes or not 1 <= len(secret) <= MAX_HEADER_BYTES
                or now.utcoffset() is None):
            raise ValueError
        pieces = signature.split(",")
        if len(pieces) > 16:
            raise ValueError
        timestamps, signatures = [], []
        for piece in pieces:
            key, value = piece.strip().split("=", 1)
            if key == "t":
                if not re.fullmatch(r"[0-9]{1,12}", value):
                    raise ValueError
                timestamps.append(value)
            elif key == "v1":
                if not re.fullmatch(r"[0-9a-f]{64}", value):
                    raise ValueError
                signatures.append(value)
        if len(timestamps) != 1 or not 1 <= len(signatures) <= 10 or abs(now.timestamp() - int(timestamps[0])) > 300:
            raise ValueError
        expected = hmac.new(secret, timestamps[0].encode("ascii") + b"." + raw, hashlib.sha256).hexdigest()
        matches = [hmac.compare_digest(expected, candidate) for candidate in signatures]
        if not any(matches):
            raise ValueError
        data = parse_json(raw)
        item = data["data"]["object"]
        if (data["object"] != "event" or data.get("api_version") != STRIPE_VERSION or "account" in data
                or not re.fullmatch(r"payment_intent\.[a-z_]+", data["type"])
                or item["object"] != "payment_intent" or not item["id"].startswith("pi_")
                or not data["id"].startswith("evt_") or data["livemode"] is not (selection.environment == "production")
                or item["livemode"] is not data["livemode"]):
            raise ValueError
        return EventCandidate(vendor="stripe", connection_id=selection.connection_id, observed_at=now,
            authenticity="signature_verified", body_sha256=hashlib.sha256(raw).hexdigest(),
            event_type=data["type"], event_id=data["id"], object_id=item["id"])
    except (ValueError, TypeError, KeyError, AttributeError, VendorError):
        raise VendorError("signature_invalid") from None
