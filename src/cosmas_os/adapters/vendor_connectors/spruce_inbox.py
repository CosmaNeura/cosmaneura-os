"""Bounded Spruce secure-message GETs. No registration, polling or outgoing API.

The production origin is fixed. Supplying a transport is an internal testing
seam, not a URL setting. Read authorization is separate from delivery grants.
"""

import asyncio
import hashlib
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, get_args
from urllib.parse import quote

import httpx
from pydantic import TypeAdapter

from cosmas_os.adapters.vendor_connectors.transport import (
    MAX_HEADER_BYTES,
    Credential,
    WireResponse,
    parse_json,
)
from cosmas_os.ports.vendor_connectors import EndpointID, OpaqueID, Timestamp, VendorError, digest
from cosmas_os.ports.vendor_inbox import (
    MAX_INBOX_PARTICIPANTS,
    MAX_INBOX_TEXT_BYTES,
    AttachmentKind,
    SpruceInboxReadBinding,
    SpruceInboxSnapshot,
    SpruceInboxUnsupported,
)

SPRUCE_INBOX_ORIGIN = "https://api.sprucehealth.com"
MAX_ITEM_RESPONSE_BYTES = 131_072
MAX_CONVERSATION_RESPONSE_BYTES = 65_536
MAX_SOURCE_COLLECTION = 32
_ID = TypeAdapter(OpaqueID)
_ENDPOINT_ID = TypeAdapter(EndpointID)
_TIME = TypeAdapter(Timestamp)


def _shape(value, allowed: set[str], required: set[str]) -> dict:
    if type(value) is not dict or set(value) - allowed or not required <= set(value):
        raise ValueError("unsupported response shape")
    return value


def _bounded_json(value, depth=0, count=None):
    count = [0] if count is None else count
    count[0] += 1
    if depth > 16 or count[0] > 4096:
        raise ValueError("unsupported response structure")
    if type(value) is dict:
        for child in value.values():
            _bounded_json(child, depth + 1, count)
    elif type(value) is list:
        for child in value:
            _bounded_json(child, depth + 1, count)


def _collection(value):
    if type(value) is not list or len(value) > MAX_SOURCE_COLLECTION:
        raise ValueError("unsupported content collection")
    if any(type(entry) is not dict for entry in value):
        raise ValueError("unsupported content entry")
    return value


def _snapshot(binding, item_response, conversation_response, observed_at):
    _shape(item_response.data, {"conversationItem"}, {"conversationItem"})
    _shape(conversation_response.data, {"conversation"}, {"conversation"})
    item = _shape(item_response.data["conversationItem"], {
        "apiURL", "appURL", "attachments", "author", "bulkRequestId", "buttons", "canDelete",
        "conversationId", "createdAt", "direction", "event", "id", "isInternalNote",
        "modifiedAt", "object", "pages", "requestId", "text",
    }, {"id", "conversationId", "createdAt", "modifiedAt", "direction", "isInternalNote",
        "author", "text", "attachments", "pages", "buttons"})
    parent = _shape(conversation_response.data["conversation"], {
        "apiURL", "appURL", "archived", "assignedToMemberId", "associatedContactIds", "createdAt",
        "externalParticipants", "id", "internalEndpoint", "internalMemberIds", "isReadOnly",
        "lastMessageAt", "object", "subtitle", "tags", "title", "type",
    }, {"id", "type", "internalEndpoint", "externalParticipants", "archived", "isReadOnly"})
    if (item["id"] != binding.item_id or item["conversationId"] != binding.conversation_id
            or parent["id"] != binding.conversation_id or item["direction"] != "inbound"
            or item["isInternalNote"] is not False or parent["type"] != "secure"):
        raise ValueError("source identity mismatch")
    if type(parent["archived"]) is not bool or type(parent["isReadOnly"]) is not bool:
        raise ValueError("invalid conversation flags")
    author = _shape(item["author"], {"id", "displayName", "deviceInformation"}, {"id"})
    if author["id"] != binding.contact_id:
        raise ValueError("source author mismatch")
    endpoint = _shape(parent["internalEndpoint"], {
        "id", "channel", "displayValue", "rawValue", "isInternal", "label", "object",
    }, {"id", "channel", "rawValue", "isInternal"})
    _ENDPOINT_ID.validate_python(endpoint["id"])
    if (endpoint["channel"] != "secure" or endpoint["isInternal"] is not True
            or endpoint["rawValue"] != binding.secure_endpoint_raw_value):
        raise ValueError("secure endpoint mismatch")
    participants = parent["externalParticipants"]
    if type(participants) is not list or not 1 <= len(participants) <= MAX_INBOX_PARTICIPANTS:
        raise ValueError("ambiguous participants")
    contacts = []
    for participant in participants:
        # Secure participants have no phone/email endpoint. A contact/display
        # name/associatedContactId coincidence cannot substitute for this set.
        p = _shape(participant, {"contact", "displayName"}, {"contact"})
        contacts.append(_ID.validate_python(p["contact"]))
    if len(set(contacts)) != len(contacts) or tuple(sorted(contacts)) != tuple(
        p.contact_id for p in binding.permitted_participants
    ):
        raise ValueError("unreviewed participants")
    text = item["text"]
    if type(text) is not str or len(text.encode("utf-8")) > MAX_INBOX_TEXT_BYTES:
        raise ValueError("invalid text")
    attachments = _collection(item["attachments"])
    pages, buttons = _collection(item["pages"]), _collection(item["buttons"])
    event = item.get("event")
    if "event" in item and type(event) is not dict:
        raise ValueError("unsupported event")
    known_kinds = get_args(AttachmentKind)
    kinds = sorted({entry.get("type") if entry.get("type") in known_kinds else "unknown"
                    for entry in attachments})
    values: dict[str, Any] = dict(
        binding=binding, created_at=_TIME.validate_python(item["createdAt"]),
        modified_at=_TIME.validate_python(item["modifiedAt"]), observed_at=observed_at, text=text,
        item_response_sha256=item_response.sha256,
        conversation_response_sha256=conversation_response.sha256,
        item_content_sha256=digest("cosmas-spruce-inbox-item-json.v1", item),
        conversation_content_sha256=digest("cosmas-spruce-inbox-parent-json.v1", parent),
        unsupported=SpruceInboxUnsupported.model_validate(dict(
            attachments=bool(attachments), pages=bool(pages), buttons=bool(buttons),
            event="event" in item, attachment_types=tuple(kinds))),
        conversation_archived=parent["archived"], conversation_read_only=parent["isReadOnly"],
        trust="untrusted_external_text",
    )
    # Construct solely to compute the commitment; full validation follows.
    unsigned = SpruceInboxSnapshot.model_construct(**values)
    return SpruceInboxSnapshot.model_validate({**values, "source_sha256": unsigned.snapshot_digest()})


class SpruceInboxConnector:
    def __init__(
        self, selection: object,
        credentials: Callable[..., Awaitable[Credential]], *,
        enabled: bool = False,
        authorize: Callable[[SpruceInboxReadBinding], Awaitable[bool]] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        timeout_seconds: float = 15,
    ):
        from cosmas_os.ports.vendor_connectors import ConnectionSelection

        try:
            if not isinstance(selection, ConnectionSelection):
                raise ValueError
            self.selection = ConnectionSelection.model_validate(selection.model_dump(mode="python"))
            if self.selection.vendor != "spruce" or self.selection.environment != "production":
                raise ValueError
            if (type(enabled) is not bool or type(timeout_seconds) not in {int, float}
                    or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 15):
                raise ValueError
        except (ValueError, TypeError):
            raise VendorError("request_invalid") from None
        self.enabled, self.credentials, self.authorize = enabled, credentials, authorize
        self.transport, self._now, self.timeout_seconds = transport, now, timeout_seconds

    async def _authorized(self, binding, deadline):
        try:
            if self.authorize is None or await self.authorize(binding) is not True:
                raise ValueError
            end = deadline.when()
            if end is None or deadline.expired() or asyncio.get_running_loop().time() >= end:
                raise ValueError
        except Exception:
            raise VendorError("authority_required") from None
        if self.selection != binding.selection:
            raise VendorError("connection_changed")

    async def _get(self, client, path, cap, headers):
        async with client.stream("GET", SPRUCE_INBOX_ORIGIN + path, headers=headers) as response:
            header_size = sum(len(k) + len(v) for k, v in response.headers.raw)
            if header_size > MAX_HEADER_BYTES:
                raise VendorError("response_too_large", attempted=True)
            if response.status_code == 429:
                raise VendorError("provider_throttled", attempted=True)
            if response.status_code in {404, 410}:
                raise VendorError("reference_unavailable", attempted=True)
            if (response.status_code != 200
                    or response.headers.get("content-encoding", "identity") != "identity"
                    or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"):
                raise VendorError("response_invalid", attempted=True)
            declared = response.headers.get("content-length")
            if declared is not None and (not declared.isascii() or not declared.isdigit()):
                raise VendorError("response_invalid", attempted=True)
            if declared is not None and int(declared) > cap:
                raise VendorError("response_too_large", attempted=True)
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                if len(raw) + len(chunk) > cap:
                    raise VendorError("response_too_large", attempted=True)
                raw.extend(chunk)
            if declared is not None and len(raw) != int(declared):
                raise VendorError("response_invalid", attempted=True)
            data = parse_json(bytes(raw))
            _bounded_json(data)
            return WireResponse(200, data, hashlib.sha256(raw).hexdigest(), datetime.now(UTC))

    async def read(self, binding: SpruceInboxReadBinding) -> SpruceInboxSnapshot:
        try:
            if not isinstance(binding, SpruceInboxReadBinding):
                raise ValueError
            binding = SpruceInboxReadBinding.model_validate(binding.model_dump(mode="python"))
        except (ValueError, TypeError, AttributeError):
            raise VendorError("request_invalid") from None
        if not self.enabled:
            raise VendorError("connector_disabled")
        if binding.selection != self.selection:
            raise VendorError("connection_changed")
        attempted = False
        try:
            async with asyncio.timeout(self.timeout_seconds) as deadline:
                await self._authorized(binding, deadline)
                credential = await self.credentials(self.selection)
                if (not isinstance(credential, Credential)
                        or credential.selection_sha256 != self.selection.commitment()
                        or credential.credential_ref != str(self.selection.credential_ref)):
                    raise VendorError("connection_changed")
                secret = credential.secret.get_secret_value()
                if (not 1 <= len(secret.encode("ascii")) <= MAX_HEADER_BYTES
                        or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in secret)):
                    raise VendorError("request_invalid")
                headers = {"Authorization": "Bearer " + secret, "Accept": "application/json",
                           "Accept-Encoding": "identity"}
                async with httpx.AsyncClient(
                    transport=self.transport, verify=True, trust_env=False, follow_redirects=False,
                    timeout=httpx.Timeout(self.timeout_seconds, connect=min(5, self.timeout_seconds)),
                ) as client:
                    await self._authorized(binding, deadline)
                    attempted = True
                    item = await self._get(client, "/v1/conversationItems/" + quote(binding.item_id, safe=""),
                                           MAX_ITEM_RESPONSE_BYTES, headers)
                    await self._authorized(binding, deadline)
                    parent = await self._get(client, "/v1/conversations/" + quote(binding.conversation_id, safe=""),
                                             MAX_CONVERSATION_RESPONSE_BYTES, headers)
                    observed_at = _TIME.validate_python(self._now())
                    snapshot = _snapshot(binding, item, parent, observed_at)
                # Unlike outgoing accounting, a completed GET is not disclosed
                # after revocation, cancellation, deadline expiry or cleanup failure.
                await self._authorized(binding, deadline)
                return snapshot
        except VendorError as error:
            raise VendorError(error.code, attempted=attempted or error.attempted) from None
        except asyncio.CancelledError:
            raise
        except (ValueError, TypeError, AttributeError, KeyError, UnicodeError, RecursionError):
            raise VendorError("response_invalid" if attempted else "request_invalid", attempted=attempted) from None
        except Exception:
            raise VendorError("transport_unconfirmed" if attempted else "authority_required", attempted=attempted) from None
