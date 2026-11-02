"""Real bounded first-party broker transport; imports perform no network I/O."""
from __future__ import annotations

import hmac
import time
from uuid import uuid4

import httpx

from cosmas_os.ports.google_callback_broker import (
    BROKER_HEADER,
    REGISTER_PATH,
    RELAY_PATH,
    Cancellation,
    GoogleBrokerError,
    Outcome,
    Receipt,
    ReceiptCheck,
    Registration,
    Relay,
    broker_key,
    decoded,
    encoded,
    signed,
)


def exchange(client: httpx.Client, url: str, value, key: str, purpose: str, *, token: str | None = None) -> tuple[bytes, str]:
    raw = encoded(value)
    headers = {"Content-Type": "application/json", BROKER_HEADER: signed(key, raw, purpose, value.nonce)}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with client.stream("POST", url, content=raw, headers=headers) as response:
            response.raise_for_status()
            if (response.status_code != 200 or response.headers.get("cache-control") != "no-store"
                    or response.headers.get("content-type", "").split(";", 1)[0] != "application/json"
                    or response.headers.get_list("content-encoding") or len(response.headers.get_list(BROKER_HEADER)) != 1):
                raise ValueError
            result = bytearray()
            for chunk in response.iter_bytes():
                if len(result) + len(chunk) > 8192:
                    raise ValueError
                result.extend(chunk)
            signature = response.headers.get(BROKER_HEADER, "")
        if not hmac.compare_digest(signature, signed(key, bytes(result), purpose + "-result", value.nonce)):
            raise ValueError
        return bytes(result), signature
    except Exception:
        raise GoogleBrokerError("google_broker_transport_unavailable") from None


class HttpGoogleRegistrationPort:
    def __init__(self, settings, *, client: httpx.Client | None = None):
        self.origin = settings.google_connection_broker_origin
        if (self.origin != "https://enrollment-api.staging.cosmas.ai" or not settings.google_connection_broker_enabled
                or not settings.workspace_enrollment_managed or not settings.workspace_enrollment_admission_secret):
            raise GoogleBrokerError("google_broker_unavailable")
        self.key = broker_key(settings.workspace_enrollment_admission_secret.get_secret_value())
        self.client = client or httpx.Client(timeout=httpx.Timeout(30, connect=5), follow_redirects=False, trust_env=False)

    def register(self, request: Registration, token: str) -> Receipt:
        # The bearer is a transient transport argument, never a model field.
        raw, _ = exchange(self.client, self.origin + REGISTER_PATH, request, self.key, "registration", token=token)
        receipt = decoded(raw, Receipt)
        if any(getattr(receipt, field) != getattr(request, field) for field in Receipt.model_fields
               if field not in {"contract_version", "broker_id", "session_id"}):
            raise GoogleBrokerError("google_broker_reply_changed")
        return receipt

    def cancel(self, receipt: Receipt):
        data = receipt.model_dump(exclude={"contract_version"})
        request = Cancellation(**data, nonce=str(uuid4()), issued_at=int(time.time()))
        exchange(self.client, self.origin + REGISTER_PATH + "/cancel", request, self.key, "cancellation")

    def check(self, receipt: Receipt):
        request = ReceiptCheck(**receipt.model_dump(exclude={"contract_version"}),
            nonce=str(uuid4()),issued_at=int(time.time()))
        raw, _ = exchange(self.client,self.origin + REGISTER_PATH + "/check",request,self.key,"check")
        if decoded(raw,Receipt) != receipt:
            raise GoogleBrokerError("google_broker_reply_changed")

    def close(self):
        self.client.close()


class HttpGoogleRelayPort:
    def __init__(self, *, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=httpx.Timeout(40, connect=5), follow_redirects=False, trust_env=False)

    def relay(self, api_origin: str, request: Relay, key: str) -> Outcome:
        if api_origin != "https://api." + request.practice_id + ".staging.cosmas.ai":
            raise GoogleBrokerError("google_broker_scope_changed")
        raw, _ = exchange(self.client, api_origin + RELAY_PATH, request, key, "relay")
        return decoded(raw, Outcome)

    def close(self):
        self.client.close()
