"""SRFax SINGLE queue/status. No invented submission idempotency or signature."""

import base64
import hashlib
from typing import Literal
from urllib.parse import parse_qsl

from cosmas_os.ports.vendor_connectors import (
    DeliveryObservation,
    EventCandidate,
    FaxIntent,
    VendorError,
)

from .transport import (
    MAX_RESPONSE_BYTES,
    WireRequest,
    checked,
    form_bytes,
    reference,
    require_reference,
    submission,
)

PATH = "/SRF_SecWebSvc.php"


class SRFaxConnector:
    def __init__(self, runtime):
        self.runtime = runtime

    def prepare(self, command, document):
        command = checked(command)
        if command.selection.vendor != "srfax" or not isinstance(command.intent, FaxIntent):
            raise VendorError("capability_unavailable")
        intent = command.intent
        if intent.sender_email is None:
            raise VendorError("request_invalid")
        intent.document.require_bytes(document)
        body = form_bytes([("action", "Queue_Fax"), ("sResponseFormat", "JSON"),
            ("sCallerID", intent.caller_id), ("sSenderEmail", intent.sender_email),
            ("sFaxType", "SINGLE"), ("sToFaxNumber", intent.destination), ("sRetries", "0"),
            ("sFileName_1", "document.pdf"), ("sFileContent_1", base64.b64encode(document).decode("ascii"))])
        return WireRequest("POST", PATH, body, "application/x-www-form-urlencoded")

    async def submit(self, command, approval, document):
        command = checked(command)
        if command.selection.vendor != "srfax":
            raise VendorError("capability_unavailable")
        return await self.runtime._submit(command, approval, document=document)

    def _parse_submission(self, command, result):
        if result.status != 200:
            raise ValueError
        if result.data["Status"] == "Failed":
            if type(result.data["Result"]) is not str or not 1 <= len(result.data["Result"]) <= 4096:
                raise ValueError
            return submission(command, result.observed_at, state="rejected", error="provider_rejected", response_hash=result.sha256)
        if result.data["Status"] != "Success" or type(result.data["Result"]) not in {int, str}:
            raise ValueError
        ref = reference(command, result, "fax", str(result.data["Result"]))
        return submission(command, result.observed_at, state="accepted", ref=ref, response_hash=result.sha256)

    def _read_wire(self, command, ref):
        command = checked(command)
        if command.selection.vendor != "srfax" or not isinstance(command.intent, FaxIntent):
            raise VendorError("capability_unavailable")
        ref = require_reference(command, ref, "fax")
        body = form_bytes([("action", "Get_FaxStatus"), ("sFaxDetailsID", ref.value), ("sResponseFormat", "JSON")])
        return WireRequest("POST", PATH, body, "application/x-www-form-urlencoded")

    async def observe(self, command, ref):
        command = checked(command)
        if command.selection.vendor != "srfax" or not isinstance(command.intent, FaxIntent):
            raise VendorError("capability_unavailable")
        ref = require_reference(command, ref, "fax")
        result = await self.runtime._exchange(command, ref=ref)
        try:
            data = result.data["Result"]
            if (result.status != 200 or result.data["Status"] != "Success" or type(data) is not dict
                    or data["ToFaxNumber"] != command.intent.destination):
                raise ValueError
            statuses: dict[str, Literal["pending", "transport_delivered", "transport_failed", "unknown"]] = {"In Progress": "pending", "Sending Email": "pending", "Sent": "transport_delivered", "Failed": "transport_failed"}
            state = statuses.get(data["SentStatus"], "unknown")
            pages = data.get("Pages")
            if pages is not None and (type(pages) is not int or not 0 <= pages <= 1_000_000):
                raise ValueError
            if state == "transport_delivered" and (pages is None or pages < 1):
                state = "unknown"
            return DeliveryObservation(reference=ref, observed_at=result.observed_at, state=state,
                pages_total=pages, pages_delivered=pages if state == "transport_delivered" else None, response_sha256=result.sha256)
        except (ValueError, TypeError, KeyError):
            raise VendorError("reference_unavailable" if result.status == 404 else "response_invalid", attempted=True) from None


def notification_hint(raw: bytes, selection, now):
    try:
        if selection.vendor != "srfax" or type(raw) is not bytes or len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError
        pairs = parse_qsl(raw.decode("utf-8"), strict_parsing=True, max_num_fields=30)
        data = dict(pairs)
        if len(data) != len(pairs) or not data["FaxDetailsID"].isdigit() or int(data["FaxDetailsID"]) <= 0:
            raise ValueError
        return EventCandidate(vendor="srfax", connection_id=selection.connection_id, observed_at=now,
            authenticity="untrusted_hint", body_sha256=hashlib.sha256(raw).hexdigest(),
            event_type="fax.notification", object_id=data["FaxDetailsID"])
    except (ValueError, TypeError, KeyError, AttributeError):
        raise VendorError("event_untrusted") from None
