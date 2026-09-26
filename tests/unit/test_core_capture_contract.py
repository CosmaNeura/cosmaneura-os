import gzip
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from cosmas_os.adapters.core_capture import HttpCoreCaptureBinding
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_capture import (
    CoreCaptureSelection,
    CoreInteractionCredential,
    build_core_capture_binding,
)

NOW = datetime(2026, 9, 17, 1, 0, tzinfo=UTC)
HEADERS = {"Content-Type": "application/json", "Cache-Control": "private,no-store",
           "X-Cosmaneura-Capture-Version": "1"}


def ref(prefix, digit="1"):
    return prefix + "_" + "0" * 25 + digit


@pytest.fixture
def selection():
    return CoreCaptureSelection(workspace_id=uuid4(), appointment_ref=ref("appointment"),
        expected_actor_ref=ref("authority_actor"), expected_tenant_ref=ref("authority_tenant"))


@pytest.fixture
def credential():
    return CoreInteractionCredential(mount_context_token=SecretStr("context_PRIVATE_invented"),
        interaction_ref="interaction_invented_0001", client_turn_id=uuid4())


def payload(request, selection, **changes):
    return dict(contract_version="1", binding_ref=ref("scribe_capture_binding"),
        workspace_id=str(selection.workspace_id), appointment_ref=selection.appointment_ref,
        actor_ref=selection.expected_actor_ref, tenant_ref=selection.expected_tenant_ref,
        request_nonce=json.loads(request.content)["request_nonce"], checked_at=NOW.isoformat(), **changes)


def client(handler, **kwargs):
    return HttpCoreCaptureBinding("https://core.example.invalid", lambda: "workload_PRIVATE_invented",
                                  transport=httpx.MockTransport(handler), now=lambda: NOW, **kwargs)


def test_fresh_scope_check_uses_existing_core_workload_and_context_headers(selection, credential):
    calls = []

    def handle(request):
        calls.append(request)
        assert str(request.url) == "https://core.example.invalid/service/v1/agent/scribe/capture-bindings/resolve"
        assert set(json.loads(request.content)) == {"workspace_id", "appointment_ref", "request_nonce"}
        assert request.headers["authorization"] == "Bearer workload_PRIVATE_invented"
        assert request.headers["x-cosmaneura-mount-context"] == "context_PRIVATE_invented"
        assert request.headers["x-cosmaneura-interaction-ref"] == credential.interaction_ref
        assert request.headers["x-cosmaneura-client-turn-id"] == str(credential.client_turn_id)
        assert request.headers["x-cosmaneura-capture-version"] == "1"
        assert "x-tenant-id" not in request.headers and "x-actor-principal-id" not in request.headers
        return httpx.Response(200, json=payload(request, selection), headers=HEADERS)

    port = client(handle)
    try:
        first = port.resolve_binding(selection, credential)
        second = port.resolve_binding(selection, credential)
        assert first.binding_ref == second.binding_ref
        assert first.request_nonce != second.request_nonce
        assert len(calls) == 2
        assert "PRIVATE" not in repr(credential) and "authority_actor" not in repr(first)
    finally:
        port.close()


@pytest.mark.parametrize("change", [
    {"workspace_id": str(uuid4())}, {"appointment_ref": ref("appointment", "2")},
    {"actor_ref": ref("authority_actor", "2")}, {"tenant_ref": ref("authority_tenant", "2")},
    {"request_nonce": str(uuid4())}, {"checked_at": (NOW - timedelta(seconds=31)).isoformat()},
    {"checked_at": (NOW + timedelta(seconds=6)).isoformat()},
])
def test_mismatched_or_stale_scope_is_rejected(selection, credential, change):
    def handle(request):
        body = {**payload(request, selection), **change}
        return httpx.Response(200, json=body, headers=HEADERS)
    port = client(handle)
    try:
        with pytest.raises(ConnectorUnavailable, match="scope_conflict"):
            port.resolve_binding(selection, credential)
    finally:
        port.close()


@pytest.mark.parametrize("change", [
    {"contract_version": "2"}, {"checked_at": "2026-09-17T01:00:00"},
    {"actor_ref": "doctor_" + "0" * 26}, {"extra_private_field": "PRIVATE"},
])
def test_unknown_contract_or_fields_fail_without_echoing_values(selection, credential, change):
    port = client(lambda request: httpx.Response(200, json={**payload(request, selection), **change}, headers=HEADERS))
    try:
        with pytest.raises(ConnectorUnavailable, match="receipt_invalid") as caught:
            port.resolve_binding(selection, credential)
        assert "PRIVATE" not in str(caught.value)
    finally:
        port.close()


@pytest.mark.parametrize("headers", [
    {**HEADERS, "Cache-Control": "private"}, {**HEADERS, "X-Cosmaneura-Capture-Version": "2"},
    {**HEADERS, "Content-Type": "text/html"},
])
def test_response_requires_version_and_no_store(selection, credential, headers):
    port = client(lambda request: httpx.Response(200, json=payload(request, selection), headers=headers))
    try:
        with pytest.raises(ConnectorUnavailable, match="receipt_invalid"):
            port.resolve_binding(selection, credential)
    finally:
        port.close()


@pytest.mark.parametrize("status", [302, 401, 403, 404, 410, 503])
def test_no_redirect_retry_or_remote_error_disclosure(selection, credential, status):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, text="PRIVATE remote failure", headers={"Location": "https://elsewhere.invalid/PRIVATE"})
    port = client(handle)
    try:
        with pytest.raises(ConnectorUnavailable) as caught:
            port.resolve_binding(selection, credential)
        assert "PRIVATE" not in str(caught.value)
        assert len(calls) == 1
    finally:
        port.close()


def test_decoded_body_is_bounded(selection, credential):
    port = client(lambda _: httpx.Response(200, content=gzip.compress(b"x" * 16385),
                                          headers={**HEADERS, "Content-Encoding": "gzip"}))
    try:
        with pytest.raises(ConnectorUnavailable, match="receipt_invalid"):
            port.resolve_binding(selection, credential)
    finally:
        port.close()


def test_timeout_has_no_automatic_retry(selection, credential):
    calls = []
    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("PRIVATE transport details", request=request)
    port = client(handle)
    try:
        with pytest.raises(ConnectorUnavailable, match="request_unconfirmed"):
            port.resolve_binding(selection, credential)
        assert len(calls) == 1
    finally:
        port.close()


@pytest.mark.parametrize("token", ["", "bad token", "x\x00invalid", "x" * 8193])
def test_invalid_workload_identity_never_calls_network(selection, credential, token):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(500)
    port = HttpCoreCaptureBinding("https://core.example.invalid", lambda: token,
                                  transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(ConnectorUnavailable, match="identity_unavailable"):
            port.resolve_binding(selection, credential)
        assert calls == []
    finally:
        port.close()


@pytest.mark.parametrize("origin", ["http://core.invalid", "https://core.invalid:8443", "https://user:PRIVATE@core.invalid",
                                  "https://core.invalid/path", "https://core.invalid?target=other"])
def test_only_configured_https_origin_is_accepted(origin):
    with pytest.raises(ValueError, match="configured HTTPS origin"):
        HttpCoreCaptureBinding(origin, lambda: "invented")


def test_no_runtime_activation_or_caller_selected_identity_fields(selection, credential):
    with pytest.raises(ConnectorUnavailable, match="connection_required"):
        build_core_capture_binding().resolve_binding(selection, credential)
    with pytest.raises(ValidationError):
        CoreCaptureSelection.model_validate({**selection.model_dump(), "approved": True})
    with pytest.raises(ValidationError):
        CoreInteractionCredential(mount_context_token=SecretStr("invalid\nPRIVATE"), interaction_ref=credential.interaction_ref,
                                  client_turn_id=credential.client_turn_id)
