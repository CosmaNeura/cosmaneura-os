"""eFax Corporate REST submission and metadata; host supplies its current bearer.

Official request/response contracts:
https://consensus.stoplight.io/docs/fax-services/7931576e60a00-send-a-fax
https://consensus.stoplight.io/docs/fax-services/29f303372fff1-retrieve-a-fax-s-metadata
An API-enabled Corporate account and current bearer token are required; an API key
alone is not a bearer token. Token minting invalidates the current token, so this
adapter never mints or rotates it. Credential lifecycle remains host-managed.
"""

import base64
import re
from datetime import datetime

from cosmas_os.ports.vendor_connectors import DeliveryObservation, FaxIntent, VendorError

from .transport import WireRequest, checked, json_bytes, reference, require_reference, submission


def _same_number(value, expected):
    # The documented send response may omit the North American country code.
    # Accept only these complete representations of the exact reviewed number.
    return type(value) is str and value in {expected, "+" + expected, expected[1:]}


def _completed_timestamp(value):
    if type(value) is not str or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:?[0-9]{2})", value):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None
    except ValueError:
        return False


class EFaxConnector:
    def __init__(self, runtime):
        self.runtime = runtime

    def prepare(self, command, document):
        command = checked(command)
        if command.selection.vendor != "efax" or not isinstance(command.intent, FaxIntent):
            raise VendorError("capability_unavailable")
        intent = command.intent
        intent.document.require_bytes(document)
        body = json_bytes({
            "destinations": [{"fax_number": "+" + intent.destination}],
            "documents": [{"document_type": "PDF", "document_content": base64.b64encode(document).decode("ascii")}],
            "fax_options": {"custom_CallerID": "1" + intent.caller_id, "include_cover_page": False,
                            "non_billable_retries": 0, "billable_retries": 0},
        })
        return WireRequest("POST", "/faxes", body, headers=(("user-id", command.selection.remote_account_id),))

    async def submit(self, command, approval, document):
        command = checked(command)
        if command.selection.vendor != "efax":
            raise VendorError("capability_unavailable")
        return await self.runtime._submit(command, approval, document=document)

    def _parse_submission(self, command, result):
        if result.status != 201 or type(result.data) is not list or len(result.data) != 1:
            raise ValueError
        data = result.data[0]
        if type(data) is not dict or not _same_number(data.get("destination_fax_number"), command.intent.destination):
            raise ValueError
        ref = reference(command, result, "fax", data["fax_id"])
        return submission(command, result.observed_at, state="accepted", ref=ref, response_hash=result.sha256)

    def _read_wire(self, command, ref):
        command = checked(command)
        if command.selection.vendor != "efax" or not isinstance(command.intent, FaxIntent):
            raise VendorError("capability_unavailable")
        ref = require_reference(command, ref, "fax")
        return WireRequest("GET", "/faxes/" + ref.value + "/metadata",
                           headers=(("user-id", command.selection.remote_account_id),))

    async def observe(self, command, ref):
        command = checked(command)
        if command.selection.vendor != "efax" or not isinstance(command.intent, FaxIntent):
            raise VendorError("capability_unavailable")
        ref = require_reference(command, ref, "fax")
        result = await self.runtime._exchange(command, ref=ref)
        try:
            data = result.data
            # The authenticated user-id scopes ownership. The saved UUID and
            # destination bind this command; custom_CallerID is not a documented
            # echo contract for metadata.originating_fax_number.
            if (result.status != 200 or type(data) is not dict or data.get("fax_id") != ref.value
                    or data.get("direction") != "OUTBOUND"
                    or not _same_number(data.get("destination_fax_number"), command.intent.destination)):
                raise ValueError
            pages, transmission = data["pages"], data["transmission_data"]
            if type(pages) is not int or not 0 <= pages <= 1_000_000 or type(transmission) is not dict:
                raise ValueError
            status = transmission["transmission_status"]
            if type(status) is not str:
                raise ValueError
            state = "pending" if status in {"NEW", "INPROGRESS"} else "unknown"
            # fax_status STORED/NOT_STORED describes the image, never delivery.
            if (status == "COMPLETE" and pages > 0 and transmission.get("error_code") == ""
                    and transmission.get("error_message") == "" and _completed_timestamp(data.get("completed_timestamp"))):
                state = "transport_delivered"
            elif status in {"ERROR", "CANCELED"}:
                state = "transport_failed"
            return DeliveryObservation(reference=ref, observed_at=result.observed_at, state=state,
                pages_total=pages, pages_delivered=pages if state == "transport_delivered" else None,
                response_sha256=result.sha256)
        except (ValueError, TypeError, KeyError):
            raise VendorError("reference_unavailable" if result.status == 404 else "response_invalid", attempted=True) from None
