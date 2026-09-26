import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from cosmas_os.adapters.core_capture_admission import HttpCoreCaptureAdmission
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_capture import CoreCaptureSelection, CoreConsentAttestation

NOW = datetime.now(UTC)


def ref(kind):
    return kind + "_" + "0" * 25 + "1"


def selection():
    return CoreCaptureSelection(
        workspace_id=uuid4(),
        appointment_ref=ref("appointment"),
        expected_actor_ref=ref("authority_actor"),
        expected_tenant_ref=ref("authority_tenant"),
    )


def exchange_body():
    return {
        "context_token": "synthetic_PRIVATE_context",
        "token_type": "Bearer",
        "issued_at": NOW.isoformat(),
        "refresh_after": (NOW + timedelta(minutes=5)).isoformat(),
        "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
    }


def core_handler(selected, calls, mutate=lambda phase, body, headers: None):
    def handler(request):
        phase = request.url.path.rsplit("/", 1)[-1]
        calls.append(request)
        body = json.loads(request.content) if request.content else None
        headers = {"Cache-Control": "no-store", "Content-Type": "application/json"}
        if phase == "exchange":
            assert request.headers["Authorization"] == "Bearer synthetic_PRIVATE_jwt"
            assert body == {
                "requested_surface": "provider_assistant",
                "record_ref": selected.appointment_ref,
            }
            response = exchange_body()
            headers["X-Cosmaneura-Embed-Version"] = "1.0"
            status = 201
        elif request.url.path.endswith("/mount-context/resolve"):
            assert request.headers["Authorization"] == "Bearer synthetic_PRIVATE_workload"
            assert request.headers["X-Cosmaneura-Mount-Context"] == "synthetic_PRIVATE_context"
            response = {
                "surface": "provider_assistant",
                "auth_tier": "provider",
                "capabilities": [],
                "actor_id": selected.expected_actor_ref,
                "tenant_id": selected.expected_tenant_ref,
            }
            headers["X-Cosmaneura-Interaction-Ref"] = "synthetic_interaction_0001"
            headers["X-Cosmaneura-Client-Turn-ID"] = request.headers["X-Cosmaneura-Client-Turn-ID"]
            status = 200
        elif "capture-bindings" in request.url.path:
            assert isinstance(body, dict)
            response = {
                "contract_version": "1",
                "binding_ref": ref("scribe_capture_binding"),
                "workspace_id": str(selected.workspace_id),
                "appointment_ref": selected.appointment_ref,
                "actor_ref": selected.expected_actor_ref,
                "tenant_ref": selected.expected_tenant_ref,
                "request_nonce": body["request_nonce"],
                "checked_at": NOW.isoformat(),
            }
            headers["X-Cosmaneura-Capture-Version"] = "1"
            status = 200
        else:
            assert phase == "capture-admissions"
            assert isinstance(body, dict)
            assert set(body) == {"binding_ref", "workspace_id", "request_nonce", "attestation"}
            response = {
                "contract_version": "1",
                "binding_ref": body["binding_ref"],
                "workspace_id": body["workspace_id"],
                "appointment_ref": selected.appointment_ref,
                "operation_ref": ref("scribe_admission"),
                "consent_record_id": str(uuid4()),
                "session_id": str(uuid4()),
                "status": "admitted",
                "request_nonce": body["request_nonce"],
                "checked_at": NOW.isoformat(),
            }
            headers["X-Cosmaneura-Capture-Version"] = "1"
            status = 200
        mutate(phase, response, headers)
        return httpx.Response(status, json=response, headers=headers)

    return handler


def open_port(selected, calls, mutate=lambda *_: None):
    return HttpCoreCaptureAdmission(
        "https://core.example.invalid",
        lambda: "synthetic_PRIVATE_workload",
        transport=httpx.MockTransport(core_handler(selected, calls, mutate)),
        now=lambda: NOW,
    )


def run_admission(port, selected, regions=("US-NY",)):
    token = port.exchange_context(selected, SecretStr("synthetic_PRIVATE_jwt"))
    credential = port.resolve_context(selected, token)
    binding = port.resolve_binding(selected, credential)
    return port.admit_capture(
        binding,
        credential,
        CoreConsentAttestation(
            modality="in_person",
            method="verbal_attestation",
            participant_regions=regions,
            all_parties_consented=True,
            granted_at=NOW,
        ),
        "synthetic-admission-key",
    )


@pytest.mark.parametrize("regions", [("US-NY",), ()])
def test_context_exchange_binding_and_admission_keep_credentials_in_transport_only(regions):
    selected, calls = selection(), []
    port = open_port(selected, calls)
    try:
        result = run_admission(port, selected, regions)
        assert result.workspace_id == selected.workspace_id and len(calls) == 4
        assert json.loads(calls[-1].content)["attestation"]["participant_regions"] == list(regions)
        assert "PRIVATE" not in str(result) and "PRIVATE" not in result.model_dump_json()
        assert calls[0].headers["Authorization"] != calls[-1].headers["Authorization"]
    finally:
        port.close()


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_uncollected_location_still_requires_explicit_consent(value):
    with pytest.raises(ValidationError):
        CoreConsentAttestation.model_validate({
            "modality": "in_person", "method": "verbal_attestation",
            "participant_regions": [], "all_parties_consented": value,
            "granted_at": NOW,
        })


@pytest.mark.parametrize(
    "mutation",
    ["actor", "tenant", "turn", "surface", "expired", "workspace", "nonce", "extra", "version"],
)
def test_wrong_context_or_receipt_cannot_prepare_capture(mutation):
    selected, calls = selection(), []

    def mutate(phase, body, headers):
        if phase == "exchange" and mutation == "expired":
            body["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
        if phase == "resolve" and "actor_id" in body:
            if mutation == "actor":
                body["actor_id"] = ref("authority_actor")[:-1] + "2"
            if mutation == "tenant":
                body["tenant_id"] = ref("authority_tenant")[:-1] + "2"
            if mutation == "turn":
                headers["X-Cosmaneura-Client-Turn-ID"] = str(uuid4())
            if mutation == "surface":
                body["surface"] = "public"
        if phase == "capture-admissions":
            if mutation == "workspace":
                body["workspace_id"] = str(uuid4())
            if mutation == "nonce":
                body["request_nonce"] = str(uuid4())
            if mutation == "extra":
                body["private_data"] = "PRIVATE"
            if mutation == "version":
                headers["X-Cosmaneura-Capture-Version"] = "2"

    port = open_port(selected, calls, mutate)
    try:
        with pytest.raises(ConnectorUnavailable) as caught:
            run_admission(port, selected)
        assert "PRIVATE" not in str(caught.value)
    finally:
        port.close()


@pytest.mark.parametrize("fault", ["redirect", "oversized", "html", "malformed", "transport"])
def test_exchange_failures_are_bounded_and_do_not_follow_redirects(fault):
    calls = []

    def handler(request):
        calls.append(request)
        if fault == "redirect":
            return httpx.Response(307, headers={"Location": "https://other.invalid/PRIVATE"})
        if fault == "oversized":
            return httpx.Response(
                201,
                headers={"Cache-Control": "no-store", "Content-Type": "application/json"},
                content=b" " * 16385,
            )
        if fault == "html":
            return httpx.Response(201, headers={"Cache-Control": "no-store"}, text="PRIVATE")
        if fault == "malformed":
            return httpx.Response(
                201, headers={"Cache-Control": "no-store"}, json={"PRIVATE": True}
            )
        raise httpx.ReadError("PRIVATE", request=request)

    port = HttpCoreCaptureAdmission(
        "https://core.example.invalid", lambda: "unused", transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(ConnectorUnavailable) as caught:
            port.exchange_context(selection(), SecretStr("synthetic_PRIVATE_jwt"))
        assert "PRIVATE" not in str(caught.value) and len(calls) == 1
    finally:
        port.close()


@pytest.mark.parametrize("status", [401, 403, 404, 410])
def test_middleware_denial_without_protocol_headers_keeps_access_denial(status):
    port = HttpCoreCaptureAdmission(
        "https://core.example.invalid",
        lambda: "unused",
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text="PRIVATE")),
    )
    try:
        with pytest.raises(ConnectorUnavailable) as caught:
            port.exchange_context(selection(), SecretStr("synthetic_PRIVATE_jwt"))
        assert str(caught.value) == "core_capture_access_unavailable"
    finally:
        port.close()
