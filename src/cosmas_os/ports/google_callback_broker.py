"""Closed, domain-separated Google control-plane messages; no token custody."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

BROKER_HEADER = "X-Cosmas-Google-Broker-Signature"
REGISTER_PATH = "/enrollment/v1/google/attempts"
RELAY_PATH = "/connections/google/relay"
CALLBACK_PATH = "/connections/google/callback"


class GoogleBrokerError(Exception):
    """Only a fixed public reason crosses a request boundary."""


class Scope(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    practice_id: str
    box_id: str
    organization_id: str = Field(pattern=r"^org_[A-Za-z0-9]+$", max_length=255)
    issuer: str = Field(min_length=8, max_length=255)
    subject: str = Field(pattern=r"^user_[A-Za-z0-9_]+$", max_length=255)
    attempt_id: str
    state_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    binding_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    pkce_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    image_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    client_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com$")
    callback_uri: str = Field(min_length=8, max_length=255)
    grant: Literal["metadata-calendar", "full-mail-read"]
    native_origin: Literal["capacitor://localhost", "app://cosmas"] | None = None
    expires_at: int

    @field_validator("practice_id", "box_id", "attempt_id")
    @classmethod
    def canonical_uuid(cls, value: str):
        if str(UUID(value)) != value:
            raise ValueError("canonical UUID required")
        return value


class Registration(Scope):
    contract_version: Literal["cosmas-google-register.v1"] = "cosmas-google-register.v1"
    nonce: str
    issued_at: int
    token_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("nonce")
    @classmethod
    def nonce_uuid(cls, value: str):
        return Scope.canonical_uuid(value)


class Receipt(Scope):
    contract_version: Literal["cosmas-google-registration.v1"] = "cosmas-google-registration.v1"
    broker_id: str
    session_id: str = Field(pattern=r"^sess_[A-Za-z0-9_]+$", max_length=255)

    @field_validator("broker_id")
    @classmethod
    def broker_uuid(cls, value: str):
        return Scope.canonical_uuid(value)


class Relay(Receipt):
    contract_version: Literal["cosmas-google-relay.v1"] = "cosmas-google-relay.v1"
    nonce: str
    issued_at: int
    state: SecretStr = Field(min_length=43, max_length=43)
    code: SecretStr | None = Field(default=None, min_length=1, max_length=4096)
    denied: bool

    @field_validator("nonce")
    @classmethod
    def nonce_uuid(cls, value: str):
        return Scope.canonical_uuid(value)

    @model_validator(mode="after")
    def exactly_one_result(self):
        if self.denied == (self.code is not None):
            raise ValueError("one callback result required")
        return self


class Cancellation(Receipt):
    contract_version: Literal["cosmas-google-cancel.v1"] = "cosmas-google-cancel.v1"
    nonce: str
    issued_at: int

    @field_validator("nonce")
    @classmethod
    def nonce_uuid(cls, value: str):
        return Scope.canonical_uuid(value)


class ReceiptCheck(Cancellation):
    contract_version: Literal["cosmas-google-check.v1"] = "cosmas-google-check.v1"


class Outcome(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    contract_version: Literal["cosmas-google-outcome.v1"] = "cosmas-google-outcome.v1"
    broker_id: str
    nonce: str
    callback_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: Literal["complete", "declined", "failed", "pending"]


def encoded(value: BaseModel | dict) -> bytes:
    data = value.model_dump() if isinstance(value, BaseModel) else value
    if isinstance(value, Relay):
        data["state"] = value.state.get_secret_value()
        data["code"] = value.code.get_secret_value() if value.code else None
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def broker_key(box_key: str) -> str:
    if len(box_key) < 32:
        raise GoogleBrokerError("google_broker_unavailable")
    return hmac.new(box_key.encode(), b"cosmas-google-callback-key.v1\x00", hashlib.sha256).hexdigest()


def signed(key: str, raw: bytes, purpose: str, nonce: str) -> str:
    return hmac.new(key.encode(), b"cosmas-google-broker.v1\x00" + purpose.encode() + b"\x00" + nonce.encode() + b"\x00" + raw,
                    hashlib.sha256).hexdigest()


def decoded[T: BaseModel](raw: bytes, model: type[T]) -> T:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result
    try:
        if len(raw) > 8192:
            raise ValueError
        return model.model_validate(json.loads(raw, object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError())))
    except (ValueError, TypeError):
        raise GoogleBrokerError("invalid_google_broker_request") from None


def authenticate(key: str, raw: bytes, purpose: str, nonce: str, supplied: str, issued_at: int):
    if abs(int(time.time()) - issued_at) > 30 or not hmac.compare_digest(signed(key, raw, purpose, nonce), supplied):
        raise GoogleBrokerError("invalid_google_broker_signature")


def callback_digest(state: str, code: str | None, denied: bool) -> str:
    return hashlib.sha256(encoded({"state_sha256": hashlib.sha256(state.encode()).hexdigest(),
        "code_sha256": hashlib.sha256((code or "").encode()).hexdigest(), "denied": denied})).hexdigest()


class GoogleRegistrationPort(Protocol):
    def register(self, request: Registration, token: str) -> Receipt: ...
    def cancel(self, receipt: Receipt) -> None: ...
    def check(self, receipt: Receipt) -> None: ...
    def close(self) -> None: ...


class GoogleRelayPort(Protocol):
    def relay(self, api_origin: str, request: Relay, key: str) -> Outcome: ...
