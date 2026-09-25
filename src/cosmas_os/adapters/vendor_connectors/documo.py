"""Documented Documo v1 fax submission/status; callbacks remain untrusted hints."""

import hashlib
from uuid import UUID

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
    multipart,
    parse_json,
    reference,
    require_reference,
    submission,
)


class DocumoConnector:
    def __init__(self, runtime):
        self.runtime = runtime

    def prepare(self, command, document):
        command = checked(command)
        if command.selection.vendor != "documo" or not isinstance(command.intent, FaxIntent):
            raise VendorError("capability_unavailable")
        command.intent.document.require_bytes(document)
        body, content_type = multipart(command.operation_id, document, "attachments", [
            ("faxNumber", command.intent.destination), ("callerId", command.intent.caller_id), ("coverPage", "false")])
        return WireRequest("POST", "/v1/faxes", body, content_type)

    async def submit(self, command, approval, document):
        command = checked(command)
        if command.selection.vendor != "documo":
            raise VendorError("capability_unavailable")
        return await self.runtime._submit(command, approval, document=document)

    def _parse_submission(self, command, result):
        if result.status != 200:
            raise ValueError
        ref = reference(command, result, "fax", result.data["messageId"])
        # Optional full submit responses must not contradict the selected
        # account/destination; async minimal responses prove only acceptance.
        self._scope(command, result.data, optional=True)
        return submission(command, result.observed_at, state="accepted", ref=ref, response_hash=result.sha256)

    def _scope(self, command, data, *, optional=False):
        expected = {"accountId": command.selection.remote_account_id, "direction": "outbound",
            "faxNumber": "+" + command.intent.destination}
        for key, value in expected.items():
            if (not optional or key in data) and data.get(key) != value:
                raise ValueError

    def _read_wire(self, command, ref):
        command = checked(command)
        if command.selection.vendor != "documo" or not isinstance(command.intent, FaxIntent):
            raise VendorError("capability_unavailable")
        ref = require_reference(command, ref, "fax")
        return WireRequest("GET", "/v1/fax/" + ref.value + "/info")

    async def observe(self, command, ref):
        command = checked(command)
        ref = require_reference(command, ref, "fax")
        result = await self.runtime._exchange(command, ref=ref)
        try:
            data = result.data
            if result.status != 200 or data["messageId"] != ref.value:
                raise ValueError
            self._scope(command, data)
            total, complete = data.get("pagesCount"), data.get("pagesComplete")
            if any(type(n) is not int or not 0 <= n <= 1_000_000 for n in (total, complete)) or complete > total:
                raise ValueError
            state = "pending" if data["status"] in {"processing", "transmitting"} else "unknown"
            if data["status"] == "success" and data.get("resultCode") == "0" and total == complete and total > 0:
                state = "transport_delivered"
            return DeliveryObservation(reference=ref, observed_at=result.observed_at, state=state,
                pages_total=total, pages_delivered=complete, response_sha256=result.sha256)
        except (ValueError, TypeError, KeyError):
            raise VendorError("reference_unavailable" if result.status == 404 else "response_invalid", attempted=True) from None


def notification_hint(raw: bytes, selection, now):
    try:
        if selection.vendor != "documo" or type(raw) is not bytes or len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError
        data = parse_json(raw)
        identifier = str(UUID(data["messageId"]))
        return EventCandidate(vendor="documo", connection_id=selection.connection_id, observed_at=now,
            authenticity="untrusted_hint", body_sha256=hashlib.sha256(raw).hexdigest(),
            event_type="fax.notification", object_id=identifier)
    except (ValueError, TypeError, KeyError, AttributeError, VendorError):
        raise VendorError("event_untrusted") from None
