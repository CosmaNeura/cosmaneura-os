"""Documented Spruce posting must never masquerade as fax delivery."""

import asyncio
import base64
import hmac
import json

import httpx
import pytest
from tests.unit.test_vendor_connector_foundation import (
    NOW,
    command,
    document,
    fixture,
    selection,
    uid,
)

from cosmas_os.adapters.vendor_connectors.spruce import verify_webhook
from cosmas_os.ports.vendor_connectors import (
    PhoneDestination,
    ProviderReference,
    SpruceMessageIntent,
    UploadedMedia,
    VendorError,
)


def fax_command():
    upload = command("spruce")
    reference = ProviderReference(vendor="spruce", connection_id=upload.selection.connection_id,
        environment="production", selection_sha256=upload.selection.commitment(),
        operation_id=uid(24), request_sha256="b" * 64, kind="media", value=str(uid(25)),
        artifact_sha256=document().sha256, observed_at=NOW)
    return command("spruce", SpruceMessageIntent(internal_endpoint_id="invented_endpoint",
        destination=PhoneDestination(channel="fax", number="+12125550101"), text="",
        attachment=UploadedMedia(document=document(), reference=reference)))


def item_reference(cmd):
    return ProviderReference(vendor="spruce", connection_id=cmd.selection.connection_id,
        environment="production", selection_sha256=cmd.selection.commitment(), operation_id=cmd.operation_id,
        request_sha256=cmd.commitment(), kind="conversation_item", value="ti_invented",
        request_id="asyncRequest_invented", observed_at=NOW)


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"status": "delivered"}, {"status": "failed"}, {"delivered": True},
    {"pages": [{"id": "page_invented", "memberId": "entity_invented", "resolved": True}]},
    {"event": {"type": "outboundCall", "data": {"answered": True, "failed": False}}},
])
async def test_fax_posted_item_never_infers_transport_from_undocumented_status_or_pages(changes):
    cmd = fax_command()
    ref = item_reference(cmd)
    data = {"conversationItem": {"id": ref.value, "requestId": ref.request_id, "object": "conversationItem",
        "direction": "outbound", "isInternalNote": False, **changes}}
    connector, seen = fixture(cmd, lambda _: asyncio.sleep(0, result=httpx.Response(200, json=data)))
    result = await connector.observe(cmd, ref)
    assert result.state == "pending"
    assert len(seen.calls) == 1 and seen.calls[0].method == "GET"
    assert "pages" not in result.model_dump() and "event" not in result.model_dump()


@pytest.mark.asyncio
@pytest.mark.parametrize("object_type", ["fax", "contact", "conversation", None, True])
async def test_current_fax_item_rejects_conflicting_object_type(object_type):
    cmd = fax_command()
    ref = item_reference(cmd)
    data = {"conversationItem": {"id": ref.value, "requestId": ref.request_id,
        "direction": "outbound", "isInternalNote": False, "object": object_type}}
    connector, _ = fixture(cmd, lambda _: asyncio.sleep(0, result=httpx.Response(200, json=data)))
    with pytest.raises(VendorError, match="response_invalid"):
        await connector.observe(cmd, ref)


def event(item_changes):
    raw = json.dumps({"object": "event", "type": "conversationItem.created", "eventTime": NOW.isoformat(),
        "data": {"object": {"id": "ti_invented", "requestId": "asyncRequest_invented",
                            "object": "conversationItem", "direction": "outbound", "isInternalNote": False,
                            **item_changes}}}, separators=(",", ":")).encode()
    secret = b"invented-spruce-event-secret"
    signature = base64.b64encode(hmac.digest(secret, raw, "sha256")).decode()
    return raw, signature, secret


@pytest.mark.parametrize("changes", [{"direction": "inbound"}, {"direction": "none"}, {"isInternalNote": True}])
def test_signed_inbound_or_internal_item_cannot_correlate_to_outbound_fax(changes):
    candidate = verify_webhook(*event(changes), selection("spruce"), NOW)
    assert candidate.authenticity == "signature_verified"
    assert candidate.object_id == "ti_invented" and candidate.request_id is None


@pytest.mark.parametrize("changes", [{"object": "contact"}, {"object": None}, {"direction": "delivered"},
    {"direction": True}, {"direction": []}, {"isInternalNote": 0}, {"isInternalNote": "false"}])
def test_signed_conflicting_item_schema_fails_closed(changes):
    with pytest.raises(VendorError, match="signature_invalid"):
        verify_webhook(*event(changes), selection("spruce"), NOW)


def test_signed_outbound_item_keeps_exact_request_for_current_read_only():
    candidate = verify_webhook(*event({}), selection("spruce"), NOW)
    assert candidate.request_id == "asyncRequest_invented"
    assert not {"transport", "delivery", "pages", "text"} & candidate.model_dump().keys()
