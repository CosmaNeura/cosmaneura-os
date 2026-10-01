"""Offline wire/evidence checks against the public eFax Corporate REST contract."""

import base64
import gzip
import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr
from tests.unit.test_vendor_connector_foundation import NOW, PDF, approval, document, uid

from cosmas_os.adapters.vendor_connectors.efax import EFaxConnector
from cosmas_os.adapters.vendor_connectors.transport import (
    MAX_RESPONSE_BYTES,
    Credential,
    VendorRuntime,
    parse_json,
)
from cosmas_os.ports.vendor_connectors import (
    ConnectionSelection,
    FaxIntent,
    VendorCommand,
    VendorError,
)


def command(*, environment="production"):
    selection = ConnectionSelection(vendor="efax", connection_id=uid(1), box_id=uid(2), owner_id=uid(3),
        environment=environment, remote_account_id="synthetic_api_user", credential_ref=uid(4), configuration_sha256="a" * 64)
    return VendorCommand(selection=selection, operation_id=uid(6), revision_id=uid(7), expires_at=NOW + timedelta(minutes=2),
        intent=FaxIntent(caller_id="2125550100", destination="12125550101", document=document()))


def accepted(**changes):
    return [{"fax_id": str(uid(10)), "destination_fax_number": "2125550101", **changes}]


def metadata(**changes):
    return {"fax_id": str(uid(10)), "fax_status": "STORED", "direction": "OUTBOUND", "pages": 2,
        "originating_fax_number": "12125550100", "destination_fax_number": "+12125550101",
        "completed_timestamp": "2026-09-21T12:00:00.000+0000",
        "transmission_data": {"transmission_status": "COMPLETE", "error_code": "", "error_message": ""}, **changes}


def fixture(cmd, handler=None, *, enabled=True, authorize=None):
    seen = SimpleNamespace(calls=[], credentials=0, authorities=0, now=NOW)

    async def credentials(selected):
        seen.credentials += 1
        return Credential(selection_sha256=selected.commitment(), credential_ref=str(selected.credential_ref),
                          secret=SecretStr("synthetic-current-bearer"))

    async def allowed(*args):
        seen.authorities += 1
        return authorize(seen.authorities) if authorize else True

    async def exchange(request):
        seen.calls.append(request)
        if handler:
            return handler(request)
        return httpx.Response(201, json=accepted()) if request.method == "POST" else httpx.Response(200, json=metadata())

    runtime = VendorRuntime(cmd.selection, credentials, enabled=enabled, authorize=allowed,
        transport=httpx.MockTransport(exchange), now=lambda: seen.now)
    return EFaxConnector(runtime), seen


async def reference(cmd):
    sender, _ = fixture(cmd)
    return (await sender.submit(cmd, approval(cmd), PDF)).reference


def test_preparation_binds_one_pdf_destination_sender_and_documented_retry_options():
    cmd = command()
    connector, seen = fixture(cmd)
    wire = connector.prepare(cmd, PDF)
    assert wire.method == "POST" and wire.path == "/faxes" and wire.content_type == "application/json"
    assert json.loads(wire.body) == {
        "destinations": [{"fax_number": "+12125550101"}],
        "documents": [{"document_type": "PDF", "document_content": base64.b64encode(PDF).decode("ascii")}],
        "fax_options": {"custom_CallerID": "12125550100", "include_cover_page": False,
                        "non_billable_retries": 0, "billable_retries": 0},
    }
    assert wire.headers == (("user-id", "synthetic_api_user"),)
    assert connector.prepare(cmd, PDF) == wire
    assert seen.credentials == seen.authorities == 0 and seen.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("destination", ["2125550101", "12125550101", "+12125550101"])
async def test_one_send_uses_current_bound_bearer_and_exact_api_user_without_token_mint(destination):
    cmd = command()
    connector, seen = fixture(cmd, lambda _: httpx.Response(201, json=accepted(destination_fax_number=destination)))
    result = await connector.submit(cmd, approval(cmd), PDF)
    assert result.state == "accepted" and result.reference.value == str(uid(10))
    assert result.reference.request_sha256 == result.request_sha256 == cmd.commitment()
    assert result.reference.selection_sha256 == cmd.selection.commitment()
    assert seen.credentials == 1 and seen.authorities == 2 and len(seen.calls) == 1
    request = seen.calls[0]
    assert str(request.url) == "https://api.securedocex.com/faxes" and request.method == "POST"
    assert request.headers["Authorization"] == "Bearer synthetic-current-bearer"
    assert request.headers["user-id"] == cmd.selection.remote_account_id
    assert "transaction-id" not in request.headers and "Idempotency-Key" not in request.headers
    assert "synthetic-current-bearer" not in result.model_dump_json()
    assert "transport_delivered" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["disabled", "sandbox", "artifact", "approval", "authority_before", "authority_after"])
async def test_pre_dispatch_fences_never_send(failure):
    cmd = command(environment="sandbox" if failure == "sandbox" else "production")
    connector, seen = fixture(cmd, enabled=failure != "disabled", authorize=lambda attempt:
        not (failure == "authority_before" and attempt == 1 or failure == "authority_after" and attempt == 2))
    auth = approval(cmd)
    if failure == "approval":
        auth = auth.model_copy(update={"approved_payload_sha256": "0" * 64})
    with pytest.raises(VendorError):
        await connector.submit(cmd, auth, PDF + b"changed" if failure == "artifact" else PDF)
    assert seen.calls == []
    assert seen.credentials == (1 if failure == "authority_after" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    [], accepted() * 2, accepted()[0], [None], accepted(fax_id="not-a-uuid"),
    accepted(destination_fax_number="442125550101"), accepted(destination_fax_number="12125550999"),
    accepted(destination_fax_number="+2125550101"), accepted(destination_fax_number=12125550101),
])
async def test_ambiguous_or_mismatched_submission_never_becomes_accepted(payload):
    cmd = command()
    connector, seen = fixture(cmd, lambda _: httpx.Response(201, json=payload))
    result = await connector.submit(cmd, approval(cmd), PDF)
    assert result.state == "unconfirmed" and result.reference is None and result.safe_error == "response_invalid"
    assert len(seen.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 429, 500])
async def test_other_http_results_never_mint_a_token_or_resend(status):
    cmd = command()
    connector, seen = fixture(cmd, lambda _: httpx.Response(status, json={"detail": "PRIVATE provider explanation"}))
    result = await connector.submit(cmd, approval(cmd), PDF)
    assert result.state == "unconfirmed" and result.reference is None and len(seen.calls) == 1
    assert "PRIVATE" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_unknown_send_timeout_is_not_retried():
    def lost(_):
        raise httpx.ReadTimeout("PRIVATE transport detail")

    cmd = command()
    connector, seen = fixture(cmd, lost)
    result = await connector.submit(cmd, approval(cmd), PDF)
    assert result.state == "unconfirmed" and result.safe_error == "transport_unconfirmed"
    assert len(seen.calls) == 1 and "PRIVATE" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("state,expected", [("NEW", "pending"), ("INPROGRESS", "pending"),
    ("COMPLETE", "transport_delivered"), ("ERROR", "transport_failed"), ("CANCELED", "transport_failed"), ("FUTURE", "unknown")])
async def test_authenticated_metadata_correlates_exact_fax_and_reports_transport_only(state, expected):
    cmd = command()
    ref = await reference(cmd)
    data = metadata(fax_status="NOT_STORED", transmission_data={"transmission_status": state, "error_code": "", "error_message": ""})
    reader, seen = fixture(cmd, lambda _: httpx.Response(200, json=data))
    observed = await reader.observe(cmd, ref)
    assert observed.state == expected and observed.pages_total == 2
    assert observed.pages_delivered == (2 if expected == "transport_delivered" else None)
    assert len(seen.calls) == 1 and seen.calls[0].method == "GET"
    assert str(seen.calls[0].url) == f"https://api.securedocex.com/faxes/{ref.value}/metadata"
    assert seen.calls[0].headers["user-id"] == cmd.selection.remote_account_id
    assert "document_content" not in str(seen.calls[0].content)


@pytest.mark.asyncio
async def test_stored_image_does_not_establish_transport_delivery():
    cmd = command()
    reader, _ = fixture(cmd, lambda _: httpx.Response(200, json=metadata(
        fax_status="STORED", transmission_data={"transmission_status": "NEW"})))
    observed = await reader.observe(cmd, await reference(cmd))
    assert observed.state == "pending" and observed.pages_delivered is None


@pytest.mark.asyncio
async def test_metadata_does_not_invent_a_custom_caller_id_echo_contract():
    cmd = command()
    reader, _ = fixture(cmd, lambda _: httpx.Response(200, json=metadata(originating_fax_number="12125550999")))
    observed = await reader.observe(cmd, await reference(cmd))
    assert observed.state == "transport_delivered"
    assert "originating_fax_number" not in observed.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"pages": 0}, {"completed_timestamp": None}, {"completed_timestamp": "2026-09-21T12:00:00"},
    {"completed_timestamp": "2026-99-21T12:00:00Z"},
    {"transmission_data": {"transmission_status": "COMPLETE", "error_code": "123", "error_message": ""}},
    {"transmission_data": {"transmission_status": "COMPLETE", "error_code": "", "error_message": "PRIVATE error"}},
    {"transmission_data": {"transmission_status": "COMPLETE"}},
])
async def test_incomplete_or_conflicting_completion_evidence_remains_unknown(changes):
    cmd = command()
    reader, _ = fixture(cmd, lambda _: httpx.Response(200, json=metadata(**changes)))
    observed = await reader.observe(cmd, await reference(cmd))
    assert observed.state == "unknown" and observed.pages_delivered is None
    assert "PRIVATE" not in observed.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"fax_id": str(uid(11))}, {"direction": "INBOUND"}, {"destination_fax_number": "442125550101"},
    {"pages": True}, {"pages": -1}, {"pages": 2.0},
    {"transmission_data": []}, {"transmission_data": {"transmission_status": None}},
])
async def test_wrong_scope_or_invalid_metadata_cannot_establish_delivery(changes):
    cmd = command()
    reader, seen = fixture(cmd, lambda _: httpx.Response(200, json=metadata(**changes)))
    with pytest.raises(VendorError, match="response_invalid") as failure:
        await reader.observe(cmd, await reference(cmd))
    assert failure.value.attempted is True and len(seen.calls) == 1


@pytest.mark.asyncio
async def test_foreign_local_reference_is_denied_before_credentials_or_read():
    cmd = command()
    ref = (await reference(cmd)).model_copy(update={"selection_sha256": "0" * 64})
    reader, seen = fixture(cmd)
    with pytest.raises(VendorError, match="reference_unavailable"):
        await reader.observe(cmd, ref)
    assert seen.calls == [] and seen.credentials == 0


@pytest.mark.asyncio
async def test_missing_provider_reference_is_not_a_reason_to_resend():
    cmd = command()
    reader, seen = fixture(cmd, lambda _: httpx.Response(404, json={"detail": "PRIVATE missing fax"}))
    with pytest.raises(VendorError, match="reference_unavailable"):
        await reader.observe(cmd, await reference(cmd))
    assert len(seen.calls) == 1 and seen.calls[0].method == "GET"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(201, content=b'[{"fax_id":"first","fax_id":"second"}]', headers={"Content-Type": "application/json"}),
    httpx.Response(201, content=b" " * (MAX_RESPONSE_BYTES + 1), headers={"Content-Type": "application/json"}),
    httpx.Response(302, headers={"Location": "https://outside.invalid", "Content-Type": "application/json"}),
    httpx.Response(201, content=gzip.compress(json.dumps(accepted()).encode()), headers={"Content-Type": "application/json", "Content-Encoding": "gzip"}),
])
async def test_response_bounds_duplicates_and_redirects_remain_closed(response):
    cmd = command()
    connector, seen = fixture(cmd, lambda _: response)
    result = await connector.submit(cmd, approval(cmd), PDF)
    assert result.state == "unconfirmed" and len(seen.calls) == 1


def test_array_response_exception_does_not_change_default_json_contract():
    raw = json.dumps(accepted()).encode()
    with pytest.raises(VendorError, match="response_invalid"):
        parse_json(raw)
    assert parse_json(raw, allow_array=True) == accepted()


@pytest.mark.asyncio
async def test_array_response_is_not_allowed_for_efax_metadata():
    cmd = command()
    reader, seen = fixture(cmd, lambda _: httpx.Response(200, json=[metadata()]))
    with pytest.raises(VendorError, match="response_invalid"):
        await reader.observe(cmd, await reference(cmd))
    assert len(seen.calls) == 1


@pytest.mark.asyncio
async def test_complete_acceptance_survives_expiry_after_dispatch():
    cmd = command()

    def response(_):
        seen.now = cmd.expires_at + timedelta(seconds=1)
        return httpx.Response(201, json=accepted())

    connector, seen = fixture(cmd, response)
    result = await connector.submit(cmd, approval(cmd), PDF)
    assert result.state == "accepted" and result.observed_at > cmd.expires_at
    assert result.response_sha256 == hashlib.sha256(httpx.Response(201, json=accepted()).content).hexdigest()
    assert len(seen.calls) == 1
