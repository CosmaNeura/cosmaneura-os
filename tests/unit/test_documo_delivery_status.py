"""Documo's authenticated terminal failures must reach delivery reconciliation."""

import asyncio

import httpx
import pytest
from tests.unit.test_vendor_connector_foundation import command, fixture, submit, uid


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
