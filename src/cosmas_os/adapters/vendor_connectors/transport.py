"""Fixed-origin private HTTP. Nothing is dispatched by construction/import."""

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, quote, urlencode

import httpx
from pydantic import SecretStr

from cosmas_os.ports.scribe_capture import ProtectedModel
from cosmas_os.ports.vendor_connectors import (
    ApprovalBinding,
    ConnectionSelection,
    MediaUploadIntent,
    PortalIntent,
    ProviderReference,
    SpruceMessageIntent,
    SubmissionObservation,
    VendorCommand,
    VendorError,
)

MAX_REQUEST_BYTES = 16_777_216
MAX_RESPONSE_BYTES = 1_048_576
MAX_HEADER_BYTES = 8192
STRIPE_VERSION = "2026-08-26.dahlia"
ORIGINS = {
    ("spruce", "production"): "https://api.sprucehealth.com",
    ("srfax", "production"): "https://secure.srfax.com",
    ("documo", "production"): "https://api.documo.com",
    ("documo", "sandbox"): "https://api.sandbox.documo.com",
    ("stripe", "production"): "https://api.stripe.com",
    ("stripe", "sandbox"): "https://api.stripe.com",
}


class Credential(ProtectedModel):
    selection_sha256: str
    credential_ref: str
    secret: SecretStr


@dataclass(frozen=True, repr=False)
class WireRequest:
    method: str
    path: str
    body: bytes = b""
    content_type: str = "application/json"
    headers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, repr=False)
class WireResponse:
    status: int
    data: dict
    sha256: str
    observed_at: datetime


def checked(command: VendorCommand) -> VendorCommand:
    try:
        if not isinstance(command, VendorCommand):
            raise ValueError
        return VendorCommand.model_validate(command.model_dump(mode="python"))
    except (ValueError, TypeError, AttributeError):
        raise VendorError("request_invalid") from None


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def form_bytes(values: list[tuple[str, str]]) -> bytes:
    return urlencode(values).encode("ascii")


def multipart(operation_id, document: bytes, field: str, values=()) -> tuple[bytes, str]:
    boundary = "cosmas-" + hashlib.sha256(str(operation_id).encode()).hexdigest()
    if ("\r\n--" + boundary).encode() in document:
        raise VendorError("request_invalid")
    parts = []
    for key, value in values:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="document.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode(),
        document, f"\r\n--{boundary}--\r\n".encode()])
    body = b"".join(parts)
    if len(body) > MAX_REQUEST_BYTES:
        raise VendorError("request_invalid")
    return body, "multipart/form-data; boundary=" + boundary


def parse_json(raw: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("nonfinite JSON")

    try:
        if type(raw) is not bytes or len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid_constant)
        if type(result) is not dict:
            raise ValueError
        return result
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise VendorError("response_invalid", attempted=True) from None


def require_reference(command: VendorCommand, reference: ProviderReference, kind: str) -> ProviderReference:
    try:
        reference = ProviderReference.model_validate(reference.model_dump(mode="python"))
        if (reference.vendor != command.selection.vendor or reference.connection_id != command.selection.connection_id
                or reference.environment != command.selection.environment or reference.selection_sha256 != command.selection.commitment()
                or reference.operation_id != command.operation_id or reference.request_sha256 != command.commitment()
                or reference.kind != kind):
            raise ValueError
        if isinstance(command.intent, PortalIntent) and (reference.portal_id != command.intent.portal_id
                or reference.portal_profile_sha256 != command.intent.profile_sha256
                or reference.correspondence_sha256 != command.intent.correspondence.commitment()):
            raise ValueError
        return reference
    except (ValueError, TypeError, AttributeError):
        raise VendorError("reference_unavailable") from None


def reference(command, result, kind, value, *, artifact_sha256=None, request_id=None):
    return ProviderReference(vendor=command.selection.vendor, connection_id=command.selection.connection_id,
        environment=command.selection.environment, selection_sha256=command.selection.commitment(),
        operation_id=command.operation_id, request_sha256=command.commitment(), kind=kind, value=value,
        observed_at=result.observed_at, artifact_sha256=artifact_sha256, request_id=request_id)


def submission(command, now, *, state, ref=None, error=None, response_hash=None):
    return SubmissionObservation(vendor=command.selection.vendor, connection_id=command.selection.connection_id,
        operation_id=command.operation_id, request_sha256=command.commitment(), observed_at=now,
        state=state, reference=ref, safe_error=error, response_sha256=response_hash)


def rejected_http(command, result):
    if result.status < 400:
        return None
    # HTTP status plus arbitrary parseable JSON does not establish a vendor's
    # authoritative rejection schema, or prove that no effect occurred. Keep
    # unknown 4xx conservative, just like 5xx; no automatic retry follows.
    error = "provider_throttled" if result.status == 429 else "response_invalid" if result.status < 500 else "transport_unconfirmed"
    if result.status == 422 and command.selection.vendor == "spruce":
        error = "duplicate_unresolved"
    return submission(command, result.observed_at, state="unconfirmed",
        error=error, response_hash=result.sha256)


class VendorRuntime:
    """Authorization callback must query the real current application authority.

    Returned observations are internal evidence. Revocation after dispatch must
    not erase them; the application separately controls disclosure/publication.
    Dispatch is private to the concrete connectors. Pure WireRequest previews
    cannot be submitted: the runtime reconstructs bytes and chooses its parser
    from the validated command and exact document/reference on every call.
    """

    def __init__(self, selection: ConnectionSelection,
            credentials: Callable[[ConnectionSelection], Awaitable[Credential]], *,
            enabled: bool = False, authorize: Callable[..., Awaitable[bool]] | None = None,
            transport: httpx.AsyncBaseTransport | None = None, now=lambda: datetime.now(UTC),
            timeout_seconds: float = 30):
        self.selection = ConnectionSelection.model_validate(selection.model_dump(mode="python"))
        if type(enabled) is not bool or type(timeout_seconds) not in {int, float} or not 0 < timeout_seconds <= 30:
            raise VendorError("request_invalid")
        self.enabled, self.credentials, self.authorize = enabled, credentials, authorize
        self.transport, self._now, self.timeout_seconds = transport, now, timeout_seconds

    def now(self):
        try:
            value = self._now()
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError
            return value.astimezone(UTC)
        except Exception:
            raise VendorError("request_invalid") from None

    async def _authorized(self, command, approval, mutating):
        if self.authorize is None or await self.authorize(self.selection, command, approval, mutating) is not True:
            raise VendorError("authority_required")
        if mutating:
            if not isinstance(approval, ApprovalBinding):
                raise VendorError("authority_required")
            approval = ApprovalBinding.model_validate(approval.model_dump(mode="python"))
            approval.require_command(command, self.now())

    def _path(self, command, wire, mutating):
        vendor = self.selection.vendor
        paths = {
            ("spruce", True): ("POST", r"/v1/(?:media|internalendpoints/[A-Za-z0-9_%=-]+/conversations)"),
            ("spruce", False): ("GET", r"/v1/conversationItems/[A-Za-z0-9_-]+"),
            ("srfax", True): ("POST", r"/SRF_SecWebSvc\.php"),
            ("srfax", False): ("POST", r"/SRF_SecWebSvc\.php"),
            ("documo", True): ("POST", r"/v1/faxes"),
            ("documo", False): ("GET", r"/v1/fax/[0-9a-f-]{36}/info"),
            ("stripe", True): ("POST", r"/v1/payment_intents"),
            ("stripe", False): ("GET", r"/v1/payment_intents/pi_[A-Za-z0-9]+"),
        }
        rule = paths.get((vendor, mutating))
        if rule is None or wire.method != rule[0] or re.fullmatch(rule[1], wire.path) is None:
            raise VendorError("capability_unavailable")
        if vendor == "spruce" and mutating:
            if isinstance(command.intent, MediaUploadIntent):
                expected_path = "/v1/media"
            elif isinstance(command.intent, SpruceMessageIntent):
                expected_path = "/v1/internalendpoints/" + quote(command.intent.internal_endpoint_id, safe="") + "/conversations"
            else:
                raise VendorError("capability_unavailable")
            if wire.path != expected_path:
                raise VendorError("request_invalid")

    def _adapter(self):
        # Closed dispatch, never a caller-provided encoder or receipt parser.
        from .documo import DocumoConnector
        from .spruce import SpruceConnector
        from .srfax import SRFaxConnector
        from .stripe import StripeConnector

        adapter = {"spruce": SpruceConnector, "srfax": SRFaxConnector,
            "documo": DocumoConnector, "stripe": StripeConnector}.get(self.selection.vendor)
        if adapter is None:
            raise VendorError("capability_unavailable")
        return adapter(self)

    async def _exchange(self, command: VendorCommand, approval=None, *, mutating=False, document=None, ref=None) -> WireResponse:
        command = checked(command)
        if type(mutating) is not bool:
            raise VendorError("request_invalid")
        if not self.enabled:
            raise VendorError("connector_disabled")
        if command.selection != self.selection:
            raise VendorError("connection_changed")
        origin = ORIGINS.get((self.selection.vendor, self.selection.environment))
        if origin is None:
            raise VendorError("capability_unavailable")
        adapter = self._adapter()
        if mutating:
            if ref is not None:
                raise VendorError("request_invalid")
            if self.selection.vendor == "stripe":
                if document is not None:
                    raise VendorError("request_invalid")
                wire = adapter.prepare(command)
            else:
                wire = adapter.prepare(command, document)
        else:
            if document is not None or approval is not None:
                raise VendorError("request_invalid")
            wire = adapter._read_wire(command, ref)
        if type(wire.body) is not bytes or len(wire.body) > MAX_REQUEST_BYTES:
            raise VendorError("request_invalid")
        self._path(command, wire, mutating)
        expected_headers = {}
        if self.selection.vendor == "spruce" and mutating:
            expected_headers = {"s-idempotency-key": str(command.operation_id)}
        elif self.selection.vendor == "stripe":
            expected_headers = {"Stripe-Version": STRIPE_VERSION, **({"Idempotency-Key": str(command.operation_id)} if mutating else {})}
        if dict(wire.headers) != expected_headers or len(wire.headers) != len(expected_headers):
            raise VendorError("request_invalid")
        if self.selection.vendor == "srfax":
            try:
                fields = parse_qsl(wire.body.decode("ascii"), strict_parsing=True, keep_blank_values=True, max_num_fields=10)
                data = dict(fields)
                if (len(data) != len(fields) or data.get("action") != ("Queue_Fax" if mutating else "Get_FaxStatus")
                        or "access_id" in data or "access_pwd" in data
                        or not mutating and set(data) != {"action", "sFaxDetailsID", "sResponseFormat"}):
                    raise ValueError
            except (ValueError, UnicodeError):
                raise VendorError("request_invalid") from None
        attempted, completed = False, None
        try:
            async with asyncio.timeout(self.timeout_seconds) as deadline:
                await self._authorized(command, approval, mutating)
                credential = await self.credentials(self.selection)
                if (not isinstance(credential, Credential) or credential.selection_sha256 != self.selection.commitment()
                        or credential.credential_ref != str(self.selection.credential_ref)):
                    raise VendorError("connection_changed")
                secret = credential.secret.get_secret_value()
                if not 1 <= len(secret.encode()) <= MAX_HEADER_BYTES or any(c in secret for c in "\r\n\x00"):
                    raise VendorError("request_invalid")
                await self._authorized(command, approval, mutating)
                absolute_deadline = deadline.when()
                if absolute_deadline is None or deadline.expired() or asyncio.get_running_loop().time() >= absolute_deadline:
                    raise VendorError("authority_required")
                headers = {"Content-Type": wire.content_type, "Accept": "application/json", "Accept-Encoding": "identity", **dict(wire.headers)}
                body = wire.body
                vendor = self.selection.vendor
                if vendor == "srfax":
                    if not self.selection.remote_account_id.isdigit():
                        raise VendorError("request_invalid")
                    body += b"&" + form_bytes([("access_id", self.selection.remote_account_id), ("access_pwd", secret)])
                else:
                    if any(c.isspace() for c in secret):
                        raise VendorError("request_invalid")
                    if vendor == "stripe":
                        prefix = ("sk_live_", "rk_live_") if self.selection.environment == "production" else ("sk_test_", "rk_test_")
                        if not secret.startswith(prefix):
                            raise VendorError("connection_changed")
                    headers["Authorization"] = ("Basic " if vendor == "documo" else "Bearer ") + secret
                if len(body) > MAX_REQUEST_BYTES:
                    raise VendorError("request_invalid")
                async with httpx.AsyncClient(transport=self.transport, verify=True, trust_env=False,
                        follow_redirects=False, timeout=httpx.Timeout(self.timeout_seconds, connect=min(5, self.timeout_seconds))) as client:
                    attempted = True
                    async with client.stream(wire.method, origin + wire.path, headers=headers,
                            content=body if wire.method == "POST" else None) as response:
                        if (300 <= response.status_code < 400 or response.headers.get("content-encoding", "identity") != "identity"
                                or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"):
                            raise VendorError("response_invalid", attempted=True)
                        raw = bytearray()
                        # Identity encoding is required above. Read the owned
                        # stream without aiter_raw's automatic close so a late
                        # cleanup exception cannot erase a fully read receipt.
                        # Buffered test/cache transports have consumed it already.
                        if response.is_stream_consumed:
                            raw.extend(response.content)
                            if len(raw) > MAX_RESPONSE_BYTES:
                                raise VendorError("response_too_large", attempted=True)
                        else:
                            if not isinstance(response.stream, httpx.AsyncByteStream):
                                raise VendorError("response_invalid", attempted=True)
                            async for chunk in response.stream:
                                raw.extend(chunk)
                                if len(raw) > MAX_RESPONSE_BYTES:
                                    raise VendorError("response_too_large", attempted=True)
                        payload = bytes(raw)
                        data = parse_json(payload)
                        completed = WireResponse(response.status_code, data, hashlib.sha256(payload).hexdigest(), self.now())
                return completed
        except VendorError as error:
            if completed is not None:
                return completed
            if attempted and not error.attempted:
                raise VendorError(error.code, attempted=True) from None
            raise
        except asyncio.CancelledError:
            if completed is not None:
                return completed
            # Caller must durably retain the dispatch claim as uncertain. No
            # retry or statement that cancellation implies "unsent" is made.
            raise
        except Exception:
            # A complete trusted response remains accounting evidence even if
            # expiry/cancellation arrives during transport cleanup. No auth gate
            # after dispatch is allowed to turn known acceptance into "unsent".
            if completed is not None:
                return completed
            raise VendorError("transport_unconfirmed" if attempted else "authority_required", attempted=attempted) from None

    async def _submit(self, command, approval, *, document=None):
        command = checked(command)
        started_at = self.now()
        try:
            result = await self._exchange(command, approval, mutating=True, document=document)
            rejected = rejected_http(command, result)
            if rejected:
                return rejected
            try:
                return self._adapter()._parse_submission(command, result)
            except (ValueError, TypeError, AttributeError, KeyError, VendorError):
                return submission(command, result.observed_at, state="unconfirmed", error="response_invalid", response_hash=result.sha256)
        except VendorError as error:
            if not error.attempted:
                raise
            try:
                observed_at = self.now()
            except VendorError:
                # A failed injected clock cannot turn an attempted write into
                # a pre-dispatch denial. Retain the valid attempt-start time.
                observed_at = started_at
            return submission(command, observed_at, state="unconfirmed", error=error.code)
