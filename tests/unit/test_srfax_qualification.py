"""Offline SRFax wire contracts; persistent workflow runs live in the agent lab."""

import asyncio
import base64
from urllib.parse import parse_qs

import httpx
import pytest
from tests.unit.test_vendor_connector_foundation import (
    PDF,
    approval,
    command,
    fixture,
    submit,
)

from cosmas_os.ports.vendor_connectors import VendorError


def status(**changes):
    return {"Status": "Success", "Result": {
        "ToFaxNumber": "12125550101", "SentStatus": "Sent", "Pages": 1, **changes}}


async def reference(cmd):
    creator, _ = fixture(cmd)
    return (await submit(creator, cmd)).reference


@pytest.mark.asyncio
async def test_srfax_send_encodes_only_exact_reviewed_document_sender_and_destination():
    cmd = command("srfax")
    connector, seen = fixture(cmd)
    prepared = connector.prepare(cmd, PDF)
    assert seen.calls == [] and seen.credentials == seen.authorities == 0
    preview = parse_qs(prepared.body.decode("ascii"), strict_parsing=True)
    assert preview == {
        "action": ["Queue_Fax"], "sResponseFormat": ["JSON"], "sCallerID": ["2125550100"],
        "sSenderEmail": ["fax@example.invalid"], "sFaxType": ["SINGLE"],
        "sToFaxNumber": ["12125550101"], "sRetries": ["0"],
        "sFileName_1": ["document.pdf"], "sFileContent_1": [base64.b64encode(PDF).decode("ascii")],
    }
    result = await connector.submit(cmd, approval(cmd), PDF)
    assert result.state == "accepted" and len(seen.calls) == 1
    assert seen.authorities == 2 and seen.credentials == 1
    request = seen.calls[0]
    assert str(request.url) == "https://secure.srfax.com/SRF_SecWebSvc.php"
    assert request.method == "POST" and "Authorization" not in request.headers
    assert "Idempotency-Key" not in request.headers
    assert parse_qs(request.content.decode("ascii"), strict_parsing=True) == {
        **preview, "access_id": [cmd.selection.remote_account_id],
        "access_pwd": ["synthetic-only-secret"],
    }
    assert "synthetic-only-secret" not in result.model_dump_json()
    assert "transport_delivered" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("sender_email", None), ("sender_email", "bad-address"),
    ("caller_id", "12125550100"), ("destination", "2125550101")])
async def test_srfax_invalid_sender_or_destination_is_rejected_before_credentials(field, value):
    cmd = command("srfax")
    cmd = cmd.model_copy(update={"intent": cmd.intent.model_copy(update={field: value})})
    connector, seen = fixture(cmd)
    with pytest.raises(VendorError, match="request_invalid"):
        await connector.submit(cmd, approval(cmd), PDF)
    assert seen.calls == [] and seen.credentials == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,state", [
    ({"Status": "Success", "Result": 123456}, "accepted"),
    ({"Status": "Success", "Result": True}, "unconfirmed"),
    ({"Status": "Success", "Result": 0}, "unconfirmed"),
    ({"Status": "Success", "Result": -1}, "unconfirmed"),
    ({"Status": "Success", "Result": "123456,123457"}, "unconfirmed"),
    ({"Status": "Success", "Result": ""}, "unconfirmed"),
    ({"Status": "Failed", "Result": "PRIVATE expired account credentials"}, "rejected"),
])
async def test_srfax_submission_requires_one_positive_reference_and_does_not_retry(payload, state):
    cmd = command("srfax")
    connector, seen = fixture(cmd, lambda _: asyncio.sleep(0, result=httpx.Response(200, json=payload)))
    result = await submit(connector, cmd)
    assert result.state == state and len(seen.calls) == 1
    assert (result.reference is not None) == (state == "accepted")
    assert "PRIVATE" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("sent_status", [None, True, 0, [], {}, ["Sent"]])
async def test_srfax_status_requires_string_state(sent_status):
    cmd = command("srfax")
    connector, seen = fixture(cmd, lambda _: asyncio.sleep(0,
        result=httpx.Response(200, json=status(SentStatus=sent_status))))
    with pytest.raises(VendorError, match="response_invalid"):
        await connector.observe(cmd, await reference(cmd))
    assert len(seen.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,expected", [
    ({"SentStatus": "In Progress"}, "pending"),
    ({"SentStatus": "Sending Email"}, "pending"),
    ({"SentStatus": "Future Success"}, "unknown"),
    ({"SentStatus": "Failed"}, "transport_failed"),
    ({"Pages": 0}, "unknown"), ({"Pages": None}, "unknown"), ({}, "transport_delivered"),
])
async def test_srfax_status_reports_only_documented_transport_evidence(changes, expected):
    cmd = command("srfax")
    ref = await reference(cmd)
    connector, seen = fixture(cmd, lambda _: asyncio.sleep(0, result=httpx.Response(200, json=status(**changes))))
    observed = await connector.observe(cmd, ref)
    assert observed.state == expected
    assert observed.pages_delivered == (1 if expected == "transport_delivered" else None)
    assert len(seen.calls) == 1
    fields = parse_qs(seen.calls[0].content.decode("ascii"))
    assert fields == {"action": ["Get_FaxStatus"], "sResponseFormat": ["JSON"],
        "sFaxDetailsID": [ref.value], "access_id": [cmd.selection.remote_account_id],
        "access_pwd": ["synthetic-only-secret"]}
    assert "sFileContent_1" not in fields


@pytest.mark.asyncio
@pytest.mark.parametrize("error_code,expected", [
    ("", "transport_delivered"), ("Busy", "unknown"), ("No Answer", "unknown"),
    ("No Remote Fax", "unknown"), ("PRIVATE provider explanation", "unknown"), ("0", "unknown"),
])
async def test_srfax_sent_with_conflicting_error_text_does_not_establish_delivery(error_code, expected):
    cmd = command("srfax")
    connector, _ = fixture(cmd, lambda _: asyncio.sleep(0,
        result=httpx.Response(200, json=status(ErrorCode=error_code))))
    observed = await connector.observe(cmd, await reference(cmd))
    assert observed.state == expected
    assert observed.pages_delivered == (1 if expected == "transport_delivered" else None)
    assert "PRIVATE" not in observed.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    status(ToFaxNumber="12125550102"), status(ToFaxNumber=12125550101),
    status(Pages=True), status(Pages=-1), status(Pages=1.0), status(Pages="1"),
    {"Status": "Failed", "Result": "PRIVATE account rejected"},
    {"Status": "Success", "Result": []}, status(ErrorCode=None), status(ErrorCode=0),
    status(ErrorCode=False), status(ErrorCode={}),
])
async def test_srfax_invalid_delivery_response_does_not_leak_or_become_delivered(payload):
    cmd = command("srfax")
    connector, seen = fixture(cmd, lambda _: asyncio.sleep(0, result=httpx.Response(200, json=payload)))
    with pytest.raises(VendorError) as error:
        await connector.observe(cmd, await reference(cmd))
    assert error.value.code == "response_invalid" and error.value.attempted
    assert "PRIVATE" not in str(error.value) and len(seen.calls) == 1


@pytest.mark.asyncio
async def test_srfax_lost_acceptance_reply_is_unconfirmed_with_one_request():
    async def lost(_):
        raise httpx.ReadTimeout("PRIVATE provider reply lost")

    cmd = command("srfax")
    connector, seen = fixture(cmd, lost)
    result = await submit(connector, cmd)
    assert result.state == "unconfirmed" and result.safe_error == "transport_unconfirmed"
    assert result.reference is None and len(seen.calls) == 1
    assert "PRIVATE" not in result.model_dump_json()
