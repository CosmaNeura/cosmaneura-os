"""Documo's authenticated terminal failures must reach delivery reconciliation."""

import asyncio

import httpx
import pytest
from tests.unit.test_vendor_connector_foundation import command, fixture, submit, uid

from cosmas_os.ports.vendor_connectors import VendorError


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,expected", [
    ({}, "transport_failed"),
    ({"resultCode": "8000", "pagesComplete": 1}, "transport_failed"),
    ({"resultCode": "5200", "pagesCount": 0}, "transport_failed"),
    ({"resultCode": "0"}, "unknown"),
    ({"resultCode": "1000"}, "unknown"),
    ({"resultCode": "future_code"}, "unknown"),
    ({"resultCode": 6100}, "unknown"),
    ({"resultCode": None}, "unknown"),
    ({"resultCode": ["6100"]}, "unknown"),
    ({"status": "transmitting"}, "pending"),
    ({"status": "success", "pagesComplete": 2}, "unknown"),
])
async def test_failed_fax_is_observed_without_resending_or_disclosing_provider_details(changes, expected):
    cmd = command("documo")
    creator, _ = fixture(cmd)
    ref = (await submit(creator, cmd)).reference
    data = {
        "messageId": str(uid(10)), "accountId": str(uid(9)), "direction": "outbound",
        "faxNumber": "+12125550101", "pagesCount": 2, "pagesComplete": 0,
        "status": "failed", "resultCode": "6100", "resultInfo": "PRIVATE provider detail",
        **changes,
    }
    reader, reads = fixture(cmd, lambda _req: asyncio.sleep(0, result=httpx.Response(200, json=data)))
    observed = await reader.observe(cmd, ref)
    assert observed.state == expected
    assert observed.pages_delivered == data["pagesComplete"]
    assert "PRIVATE" not in observed.model_dump_json()
    assert len(reads.calls) == 1
    assert reads.calls[0].method == "GET"
    assert reads.calls[0].url.path == f"/v1/fax/{ref.value}/info"


def complete_receipt(**changes):
    return {"messageId": str(uid(10)), "accountId": str(uid(9)), "direction": "outbound",
        "faxNumber": "+12125550101", "pagesCount": 2, "pagesComplete": 2,
        "status": "success", "resultCode": "0", **changes}


@pytest.mark.asyncio
async def test_send_requests_immediate_minimal_acceptance_and_later_reads_delivery():
    cmd = command("documo")
    connector, seen = fixture(cmd)
    accepted = await submit(connector, cmd)
    assert accepted.state == "accepted"
    assert len(seen.calls) == 1
    wire = seen.calls[0]
    assert wire.headers["Authorization"] == "Basic synthetic-only-secret"
    assert b'name="async"\r\n\r\ntrue\r\n' in wire.content
    assert b'name="coverPage"\r\n\r\nfalse\r\n' in wire.content
    assert wire.content.count(b'name="attachments"') == 1
    assert b"attachmentUrls" not in wire.content and b"scheduledDate" not in wire.content
    reader, reads = fixture(cmd, lambda _req: asyncio.sleep(0,
        result=httpx.Response(200, json=complete_receipt())))
    assert (await reader.observe(cmd, accepted.reference)).state == "transport_delivered"
    assert len(reads.calls) == 1 and reads.calls[0].method == "GET"


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy,expected", [
    (None, "transport_delivered"), ("", "transport_delivered"), ("0", "transport_delivered"),
    ("6100", "unknown"), (0, "unknown"), (False, "unknown"), (["0"], "unknown"),
])
async def test_conflicting_legacy_result_cannot_confirm_delivery(legacy, expected):
    cmd = command("documo")
    connector, _ = fixture(cmd)
    ref = (await submit(connector, cmd)).reference
    reader, seen = fixture(cmd, lambda _req: asyncio.sleep(0,
        result=httpx.Response(200, json=complete_receipt(errorCode=legacy))))
    assert (await reader.observe(cmd, ref)).state == expected
    assert len(seen.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy,expected", [("6100", "transport_failed"), ("0", "unknown"), (6100, "unknown")])
async def test_conflicting_legacy_result_cannot_confirm_failure(legacy, expected):
    cmd = command("documo")
    connector, _ = fixture(cmd)
    ref = (await submit(connector, cmd)).reference
    reader, _ = fixture(cmd, lambda _req: asyncio.sleep(0, result=httpx.Response(200,
        json=complete_receipt(status="failed", pagesComplete=0, resultCode="6100", errorCode=legacy))))
    assert (await reader.observe(cmd, ref)).state == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"pagesCount": "2"}, {"pagesCount": None}, {"pagesComplete": True},
    {"pagesComplete": -1}, {"pagesComplete": 3}, {"pagesCount": 1_000_001},
    {"status": ["success"]}, {"status": {"value": "success"}},
    {"status": None}, {"status": True}, {"status": 1},
    {"accountId": str(uid(99))}, {"messageId": str(uid(99))},
    {"faxNumber": "+12125550102"}, {"direction": "inbound"},
])
async def test_malformed_or_foreign_delivery_evidence_fails_closed(changes):
    cmd = command("documo")
    connector, _ = fixture(cmd)
    ref = (await submit(connector, cmd)).reference
    reader, seen = fixture(cmd, lambda _req: asyncio.sleep(0,
        result=httpx.Response(200, json=complete_receipt(**changes))))
    with pytest.raises(VendorError, match="response_invalid") as error:
        await reader.observe(cmd, ref)
    assert error.value.attempted is True
    assert len(seen.calls) == 1 and seen.calls[0].method == "GET"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
async def test_expired_access_and_provider_failures_do_not_retry_or_disclose_response(status):
    cmd = command("documo")
    connector, _ = fixture(cmd)
    ref = (await submit(connector, cmd)).reference
    reader, seen = fixture(cmd, lambda _req: asyncio.sleep(0,
        result=httpx.Response(status, json={"error": "PRIVATE provider response"})))
    with pytest.raises(VendorError) as error:
        await reader.observe(cmd, ref)
    assert "PRIVATE" not in str(error.value)
    assert error.value.attempted is True
    assert len(seen.calls) == 1 and seen.calls[0].method == "GET"


@pytest.mark.asyncio
async def test_documo_timeout_is_bounded_and_does_not_start_another_send():
    cmd = command("documo")

    async def stalled(_request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={"messageId": str(uid(10))})

    connector, seen = fixture(cmd, stalled, timeout=.01)
    result = await submit(connector, cmd)
    assert result.state == "unconfirmed" and result.reference is None
    assert len(seen.calls) == 1
