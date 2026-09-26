"""Documented Spruce v1 upload/send; acceptance is not delivery."""

import base64
import hashlib
import hmac
from datetime import datetime
from urllib.parse import quote

from cosmas_os.ports.vendor_connectors import (
    DeliveryObservation,
    EventCandidate,
    MediaUploadIntent,
    SpruceMessageIntent,
    VendorError,
)

from .transport import (
    MAX_HEADER_BYTES,
    MAX_RESPONSE_BYTES,
    WireRequest,
    checked,
    json_bytes,
    multipart,
    parse_json,
    reference,
    require_reference,
    submission,
)


class SpruceConnector:
    def __init__(self, runtime):
        self.runtime = runtime

    def prepare(self, command, document=None):
        command = checked(command)
        if command.selection.vendor != "spruce":
            raise VendorError("capability_unavailable")
        intent = command.intent
        if isinstance(intent, MediaUploadIntent):
            if document is None:
                raise VendorError("artifact_changed")
            intent.document.require_bytes(document)
            body, content_type = multipart(command.operation_id, document, "media")
            path = "/v1/media"
        elif isinstance(intent, SpruceMessageIntent):
            if document is not None:
                raise VendorError("request_invalid")
            target = intent.destination
            if target.channel == "secure":
                destination = {"secureEndpoint": {"contactId": target.contact_id,
                    "deliveryMethod": "only_conversations_matching_internal_endpoint"}}
            elif target.channel == "fax":
                destination = {"faxEndpoint": target.number}
            else:
                destination = {"smsOrEmailEndpoint": target.address if target.channel == "email" else target.number}
            message = {"body": [{"type": "text", "value": intent.text}], "internal": False}
            if intent.attachment:
                message["attachments"] = [{"attachmentId": intent.attachment.reference.value, "title": "document.pdf"}]
            body, content_type = json_bytes({"destination": destination, "message": message}), "application/json"
            # This dedicated field is validated as the documented Base64 ID
            # alphabet, then encoded once. No raw slash or double decoding.
            path = "/v1/internalendpoints/" + quote(intent.internal_endpoint_id, safe="") + "/conversations"
        else:
            raise VendorError("capability_unavailable")
        return WireRequest("POST", path, body, content_type, (("s-idempotency-key", str(command.operation_id)),))

    async def submit(self, command, approval, document=None):
        command = checked(command)
        if command.selection.vendor != "spruce":
            raise VendorError("capability_unavailable")
        return await self.runtime._submit(command, approval, document=document)

    def _parse_submission(self, command, result):
        if result.status != 200:
            raise ValueError
        if isinstance(command.intent, MediaUploadIntent):
            object_type = result.data["object"]
            if type(object_type) is not str or not 1 <= len(object_type) <= 64 or not object_type.isprintable():
                raise ValueError
            ref = reference(command, result, "media", result.data["id"], artifact_sha256=command.intent.document.sha256)
        else:
            ref = reference(command, result, "async_request", result.data["requestId"])
        return submission(command, result.observed_at, state="accepted", ref=ref, response_hash=result.sha256)

    def _read_wire(self, command, ref):
        command = checked(command)
        if not isinstance(command.intent, SpruceMessageIntent):
            raise VendorError("capability_unavailable")
        ref = require_reference(command, ref, "conversation_item")
        if ref.request_id is None:
            raise VendorError("reference_unavailable")
        return WireRequest("GET", "/v1/conversationItems/" + ref.value)

    async def observe(self, command, ref):
        command = checked(command)
        ref = require_reference(command, ref, "conversation_item")
        result = await self.runtime._exchange(command, ref=ref)
        try:
            item = result.data["conversationItem"]
            if (result.status != 200 or type(item) is not dict or item["id"] != ref.value
                    or item.get("requestId") != ref.request_id or item["direction"] != "outbound"
                    or item["isInternalNote"] is not False):
                raise ValueError
            # Item-posted/read status does not establish fax transport delivery.
            return DeliveryObservation(reference=ref, observed_at=result.observed_at,
                state="pending", response_sha256=result.sha256)
        except (ValueError, TypeError, KeyError):
            raise VendorError("response_invalid", attempted=True) from None


def verify_webhook(raw: bytes, signature: str, secret: bytes, selection, now):
    try:
        if (selection.vendor != "spruce" or type(raw) is not bytes or len(raw) > MAX_RESPONSE_BYTES
                or type(signature) is not str or len(signature.encode()) > MAX_HEADER_BYTES
                or type(secret) is not bytes or not 1 <= len(secret) <= MAX_HEADER_BYTES):
            raise ValueError
        supplied = base64.b64decode(signature, validate=True)
        if not hmac.compare_digest(hmac.digest(secret, raw, "sha256"), supplied):
            raise ValueError
        data = parse_json(raw)
        item = data["data"]["object"]
        event_time = datetime.fromisoformat(data["eventTime"].replace("Z", "+00:00"))
        if (data["object"] != "event" or data["type"] not in {"conversationItem.created", "conversationItem.updated",
                "conversationItem.deleted", "conversationItem.restored"} or event_time.utcoffset() is None):
            raise ValueError
        return EventCandidate(vendor="spruce", connection_id=selection.connection_id, observed_at=now,
            authenticity="signature_verified", body_sha256=hashlib.sha256(raw).hexdigest(),
            event_type=data["type"], object_id=item["id"], request_id=item.get("requestId"))
    except (ValueError, TypeError, KeyError, AttributeError, VendorError):
        raise VendorError("signature_invalid") from None
