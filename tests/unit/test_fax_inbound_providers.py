"""Synthetic provider plans/parsers only; no credentials, account calls or installed UI."""

import asyncio
import base64
import io
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pypdf import PdfWriter

from cosmas_os.adapters.vendor_connectors.documo_inbound import DocumoInbound
from cosmas_os.adapters.vendor_connectors.spruce_fax_inbound import SpruceFaxInbound
from cosmas_os.adapters.vendor_connectors.srfax_inbound import SRFaxInbound
from cosmas_os.ports.fax_inbound import MAX_PDF_BYTES, ImageApproval, InboundFailure, ReadScope
from cosmas_os.ports.vendor_connectors import ConnectionSelection

NOW = datetime(2026, 10, 3, 16, tzinfo=UTC)


def fixture(provider):
    selection = ConnectionSelection(
        vendor=provider,
        environment="production",
        box_id=uuid4(),
        owner_id=uuid4(),
        connection_id=uuid4(),
        credential_ref=uuid4(),
        configuration_sha256="a" * 64,
        remote_account_id=str(uuid4()) if provider == "documo" else "12345",
    )
    scope = ReadScope(
        selection,
        NOW - timedelta(days=1),
        NOW,
        uuid4(),
        account_timezone="America/New_York",
        account_date_format="%Y-%m-%d %H:%M:%S",
        received_status="Received",
        conversation_id="t_invented",
        internal_endpoint_id="ep_invented",
    )
    at = NOW - timedelta(hours=1)
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    writer.write(stream)
    doc = stream.getvalue()
    if provider == "srfax":
        raw = {
            "Status": "Success",
            "Result": [
                {
                    "FileName": "invented.pdf|123456789012345",
                    "ReceiveStatus": "Received",
                    "Date": "2026-10-03 11:00:00",
                    "Pages": 1,
                    "Size": len(doc),
                    "ViewedStatus": "N",
                }
            ],
        }
        parent = None
    elif provider == "documo":
        raw = {
            "rows": [
                {
                    "accountId": selection.remote_account_id,
                    "direction": "inbound",
                    "status": "success",
                    "messageId": str(uuid4()),
                    "createdAt": at.isoformat(),
                    "pagesCount": 1,
                    "pagesComplete": 1,
                    "resultCode": "0",
                    "isRead": False,
                    "isFilePurged": False,
                }
            ]
        }
        parent = None
    else:
        raw = {
            "conversationItems": [
                {
                    "id": "ti_invented",
                    "conversationId": scope.conversation_id,
                    "direction": "inbound",
                    "isInternalNote": False,
                    "createdAt": at.isoformat(),
                    "author": {"displayName": "Invented sender"},
                    "attachments": [
                        {
                            "type": "document",
                            "data": {
                                "mimetype": "application/pdf",
                                "signedUrl": {
                                    "url": "https://unverified.invalid/private?token=invented",
                                    "expiresAt": (NOW + timedelta(minutes=5)).isoformat(),
                                },
                            },
                        }
                    ],
                }
            ]
        }
        parent = {
            "conversation": {
                "id": scope.conversation_id,
                "type": "fax",
                "internalEndpoint": {
                    "id": scope.internal_endpoint_id,
                    "channel": "fax",
                    "isInternal": True,
                },
            }
        }
    return scope, raw, parent, doc


def parse(provider, scope, raw, parent=None):
    encoded = json.dumps(raw).encode()
    return (
        SpruceFaxInbound.parse(scope, encoded, json.dumps(parent).encode(), NOW)
        if provider == "spruce"
        else {"srfax": SRFaxInbound, "documo": DocumoInbound}[provider].parse(scope, encoded)
    )


@pytest.mark.parametrize("provider", ["srfax", "documo", "spruce"])
@pytest.mark.parametrize("round", [1, 2])
def test_two_rounds_metadata_selected_locator_approved_pdf_or_explicit_block(provider, round):
    scope, raw, parent, document = fixture(provider)
    adapter = {"srfax": SRFaxInbound, "documo": DocumoInbound, "spruce": SpruceFaxInbound}[provider]
    page = parse(provider, scope, raw, parent)
    assert len(page.items) == 1 and not page.inbox_complete
    source = page.items[0]
    approval = ImageApproval(
        scope.key(), source.key(), scope.selection.owner_id, NOW + timedelta(minutes=5)
    )
    if provider == "spruce":
        assert (
            not source.image_available and source.image_block_reason == "download_host_unverified"
        )
        with pytest.raises(InboundFailure, match="download_host_unverified"):
            adapter.image_plan(scope, source, approval, NOW)
    else:
        plan = adapter.image_plan(scope, source, approval, NOW)
        if provider == "srfax":
            fields = dict(plan.fields)
            assert fields["sMarkasViewed"] == "N" and fields["sDirection"] == "IN"
            assert "sSubUserID" not in fields and "access_pwd" not in fields
            assert source.locator[1] == "123456789012345"  # Not coerced to a UUID.
            payload = json.dumps(
                {"Status": "Success", "Result": base64.b64encode(document).decode()}
            ).encode()
        else:
            assert plan.method == "GET" and plan.path.endswith("/download?format=pdf")
            payload = document
        assert asyncio.run(adapter.image(scope, source, approval, NOW, payload)) == document
        # Reopening validates exact metadata only, never repeats an acquisition.
        assert parse(provider, scope, raw, parent).items[0].key() == source.key()
    assert "private" not in repr(source) and "123456789012345" not in repr(source)


@pytest.mark.parametrize("provider", ["srfax", "documo", "spruce"])
def test_changed_account_approval_and_oversized_collection_fail_closed(provider):
    scope, raw, parent, _ = fixture(provider)
    source = parse(provider, scope, raw, parent).items[0]
    approval = ImageApproval(scope.key(), source.key(), uuid4(), NOW + timedelta(minutes=5))
    with pytest.raises(InboundFailure, match="approval_changed"):
        approval.check(scope, source, NOW)
    changed = replace(scope, request_id=uuid4())
    with pytest.raises(InboundFailure, match="approval_changed"):
        ImageApproval(
            scope.key(), source.key(), scope.selection.owner_id, NOW + timedelta(minutes=5)
        ).check(changed, source, NOW)
    key = {"srfax": "Result", "documo": "rows", "spruce": "conversationItems"}[provider]
    raw[key] = raw[key] * 26
    with pytest.raises(InboundFailure):
        parse(provider, scope, raw, parent)


def test_srfax_timezone_status_and_no_mutation_plan():
    scope, raw, _, _ = fixture("srfax")
    fields = dict(SRFaxInbound.list_plan(scope).fields)
    assert fields["sViewedStatus"] == "ALL" and "sIncludeSubUsers" not in fields
    with pytest.raises(InboundFailure):
        SRFaxInbound.list_plan(replace(scope, account_timezone=None))
    with pytest.raises(InboundFailure):
        SRFaxInbound.list_plan(replace(scope, received_status=None))
    raw["Result"][0]["ReceiveStatus"] = "Unknown"
    with pytest.raises(InboundFailure, match="receive_status_unknown"):
        parse("srfax", scope, raw)


@pytest.mark.parametrize("provider", ["srfax", "documo"])
def test_pdf_malformed_and_limit_rejected(provider):
    scope, raw, parent, _ = fixture(provider)
    source = parse(provider, scope, raw, parent).items[0]
    approval = ImageApproval(
        scope.key(), source.key(), scope.selection.owner_id, NOW + timedelta(minutes=5)
    )
    adapter = SRFaxInbound if provider == "srfax" else DocumoInbound
    for document in [b"not a PDF", b"%PDF-" + b"x" * MAX_PDF_BYTES]:
        payload = (
            json.dumps(
                {"Status": "Success", "Result": base64.b64encode(document).decode()}
            ).encode()
            if provider == "srfax"
            else document
        )
        with pytest.raises(InboundFailure):
            asyncio.run(adapter.image(scope, source, approval, NOW, payload))


@pytest.mark.parametrize(
    "patch",
    [
        {"accountId": str(uuid4())},
        {"direction": "outbound"},
        {"status": "processing"},
        {"pagesComplete": 0},
    ],
)
def test_documo_wrong_account_direction_or_incomplete_status(patch):
    scope, raw, _, _ = fixture("documo")
    raw["rows"][0].update(patch)
    with pytest.raises(InboundFailure):
        parse("documo", scope, raw)


def test_spruce_expired_cross_conversation_and_attachment_ambiguity():
    scope, raw, parent, _ = fixture("spruce")
    raw["conversationItems"][0]["conversationId"] = "t_other"
    with pytest.raises(InboundFailure):
        parse("spruce", scope, raw, parent)
    scope, raw, parent, _ = fixture("spruce")
    raw["conversationItems"][0]["attachments"] *= 2
    with pytest.raises(InboundFailure):
        parse("spruce", scope, raw, parent)
    scope, raw, parent, _ = fixture("spruce")
    raw["conversationItems"][0]["attachments"][0]["data"]["signedUrl"]["expiresAt"] = (
        NOW.isoformat()
    )
    with pytest.raises(InboundFailure, match="attachment_expired"):
        parse("spruce", scope, raw, parent)


@pytest.mark.parametrize("provider", ["srfax", "documo"])
def test_forged_locator_and_zero_page_cannot_prepare_image(provider):
    scope, raw, parent, _ = fixture(provider)
    source = parse(provider, scope, raw, parent).items[0]
    with pytest.raises(InboundFailure):
        replace(source, locator=())
    with pytest.raises(InboundFailure):
        replace(source, pages=0)
    forged = replace(source, locator=("../private",))
    approval = ImageApproval(
        scope.key(), forged.key(), scope.selection.owner_id, NOW + timedelta(minutes=5)
    )
    adapter = SRFaxInbound if provider == "srfax" else DocumoInbound
    with pytest.raises(InboundFailure, match="locator_invalid"):
        adapter.image_plan(scope, forged, approval, NOW)


def test_srfax_unknown_zone_and_ambiguous_dst_fail_closed():
    scope, raw, _, _ = fixture("srfax")
    with pytest.raises(InboundFailure):
        SRFaxInbound.list_plan(replace(scope, account_timezone="Unknown/Zone"))
    with pytest.raises(InboundFailure):
        SRFaxInbound.list_plan(replace(scope, received_status="x" * 16))
    at = datetime(2026, 11, 1, 8, tzinfo=UTC)
    scope = replace(scope, starts_at=at - timedelta(days=1), ends_at=at)
    raw["Result"][0]["Date"] = "2026-11-01 01:30:00"
    with pytest.raises(InboundFailure, match="account_date_unsupported"):
        parse("srfax", scope, raw)
