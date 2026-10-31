from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

CONTRACT = "enrollment.v1"
STRIPE_CONTRACT = "cosmas-enrollment.v1"
BAA_DOC_ID = "CN-BAA-CUST-CW"
BAA_VERSION = "2.3"
BAA_SHA256 = "9bdc110b6b2ffcc9f5e7aee653af499357d2f35dccf43c57d8bbcf70094ed34e"
BAA_PDF_URL = "https://cosmaneura.com/baa-v2-3.pdf"
TRIAL = timedelta(days=14)
FIRST_HUMAN_CENTS = 30_000
ADDITIONAL_HUMAN_CENTS = 10_000
MAX_HUMANS = 10
SEAT_POLICY = (
    "All human seats, including owners/admin/staff. Pending invites reserve a purchased "
    "seat; paused humans retain their seat until explicitly removed. Agents are not seats."
)


class EnrollmentError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class HumanIdentity:
    issuer: str
    subject: str
    session_id: str
    email: str
    display_name: str


class IdentityVerifier(Protocol):
    def verify(self, token: str) -> HumanIdentity: ...
    def verify_scoped(self, token: str, organization_id: str, *, authorized_parties: list[str] | None = None) -> HumanIdentity: ...
    def verify_registered_member(self, subject: str, organization_id: str) -> HumanIdentity: ...


class CommercePort(Protocol):
    def validate_configuration(self) -> None: ...
    def create_checkout(self, request: dict[str, Any], key: str) -> dict[str, Any]: ...
    def retrieve_checkout(self, session_id: str) -> dict[str, Any]: ...
    def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]: ...
    def retrieve_invoice(self, invoice_id: str) -> dict[str, Any]: ...
    def create_portal(self, customer_id: str, return_url: str) -> str: ...
    def verify_event(self, raw: bytes, signature: str) -> dict[str, Any]: ...


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def now_utc() -> datetime:
    return datetime.now(UTC)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def iso(value: datetime | None) -> str | None:
    return utc(value).isoformat() if value else None


def document() -> dict[str, str]:
    raw = (Path(__file__).parent / "assets" / "baa_v2.3.html").read_bytes()
    if hashlib.sha256(raw).hexdigest() != BAA_SHA256:
        raise EnrollmentError("agreement_integrity", "Agreement integrity check failed.", 503)
    return {"doc_id": BAA_DOC_ID, "version": BAA_VERSION, "sha256": BAA_SHA256,
            "html": raw.decode(), "pdf_url": BAA_PDF_URL}


def quote(humans: int) -> dict[str, Any]:
    if isinstance(humans, bool) or not isinstance(humans, int) or not 1 <= humans <= 1_000:
        raise EnrollmentError("invalid_human_seats", "Choose at least one human seat.", 422)
    return {"currency": "usd", "interval": "month", "human_seats": humans,
            "monthly_total_cents": FIRST_HUMAN_CENTS + ADDITIONAL_HUMAN_CENTS * (humans - 1)
            if humans <= MAX_HUMANS else None,
            "due_today_cents": 0, "trial_days": 14, "self_serve": humans <= MAX_HUMANS,
            "seat_policy": SEAT_POLICY, "tax_treatment": "No additional tax in this checkout."}
