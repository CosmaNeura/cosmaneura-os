"""Dormant first-party consent/session client. Not selected by the runtime.

Wire fields/routes follow Scribe 1e48c124 and Core's dormant workflow client.
No source credentials, environment configuration or service startup is inherited.
"""

import json
import re
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scribe_capture import (
    ConsentAttestation,
    ScribeConsentReceipt,
    ScribeEncounterBinding,
    ScribeSessionReceipt,
)

MAX_RECEIPT_BYTES = 65536
_KEY = re.compile(r"^[A-Za-z0-9:_-]{8,100}$")


def _scope(binding: ScribeEncounterBinding) -> dict:
    return {
        name: getattr(binding, name) for name in ("appointment_id", "practitioner_id", "patient_id")
    }


def _matches(binding, receipt):
    return all(getattr(receipt, key) == value for key, value in _scope(binding).items())


class HttpScribeAdmission:
    def __init__(self, origin: str, token_provider: Callable[[], str], *, transport=None):
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or any(c.isspace() for c in origin)
        ):
            raise ValueError("Scribe requires a configured HTTPS origin")
        self._origin = origin.rstrip("/")
        self._token_provider = token_provider
        self._client = httpx.Client(
            transport=transport, timeout=10, follow_redirects=False, trust_env=False
        )

    def close(self):
        self._client.close()

    def _post(self, binding, path, body, key):
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ConnectorUnavailable("scribe_invalid_idempotency_key")
        try:
            token = self._token_provider()
            if not isinstance(token, str) or not token or any(c.isspace() for c in token):
                raise ConnectorUnavailable("scribe_identity_unavailable")
            with self._client.stream(
                "POST",
                self._origin + path,
                json=body,
                headers={
                    "Authorization": "Bearer " + token,
                    "X-Tenant-ID": str(binding.tenant_id),
                    "Idempotency-Key": key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            ) as response:
                if response.status_code not in (200, 201):
                    code = (
                        "scribe_request_unconfirmed"
                        if response.status_code >= 500
                        else "scribe_request_rejected"
                    )
                    raise ConnectorUnavailable(code)
                if (
                    response.headers.get("content-type", "").split(";", 1)[0].strip()
                    != "application/json"
                ):
                    raise ConnectorUnavailable("scribe_receipt_invalid")
                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > MAX_RECEIPT_BYTES:
                        raise ConnectorUnavailable("scribe_receipt_invalid")
                    data.extend(chunk)
                return json.loads(data)
        except ConnectorUnavailable:
            raise
        except (httpx.HTTPError, ValueError, TypeError):
            raise ConnectorUnavailable("scribe_request_unconfirmed") from None
        except Exception:
            # Credential-provider errors must not expose identity/configuration.
            raise ConnectorUnavailable("scribe_identity_unavailable") from None

    def record_consent(
        self, binding: ScribeEncounterBinding, attestation: ConsentAttestation, idempotency_key: str
    ) -> ScribeConsentReceipt:
        body = {
            **_scope(binding),
            **attestation.model_dump(mode="json"),
            "evidence_object_id": None,
        }
        raw = self._post(binding, "/v1/consents", body, idempotency_key)
        try:
            receipt = ScribeConsentReceipt.model_validate(raw)
        except ValidationError:
            raise ConnectorUnavailable("scribe_receipt_invalid") from None
        if (
            not _matches(binding, receipt)
            or receipt.revoked_at is not None
            or receipt.model_dump(include=set(ConsentAttestation.model_fields))
            != attestation.model_dump()
            or receipt.evidence_object_id is not None
        ):
            raise ConnectorUnavailable("scribe_receipt_scope_conflict")
        return receipt

    def create_session(
        self, binding: ScribeEncounterBinding, consent: ScribeConsentReceipt, idempotency_key: str
    ) -> ScribeSessionReceipt:
        if not _matches(binding, consent) or consent.revoked_at is not None:
            raise ConnectorUnavailable("scribe_consent_scope_conflict")
        body = {
            **_scope(binding),
            "consent_record_id": str(consent.id),
            "modality": consent.modality,
        }
        raw = self._post(binding, "/v1/sessions", body, idempotency_key)
        try:
            receipt = ScribeSessionReceipt.model_validate(raw)
        except ValidationError:
            raise ConnectorUnavailable("scribe_receipt_invalid") from None
        if (
            not _matches(binding, receipt)
            or receipt.consent_record_id != consent.id
            or receipt.modality != consent.modality
        ):
            raise ConnectorUnavailable("scribe_receipt_scope_conflict")
        return receipt
