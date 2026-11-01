"""HTTP and OperationOutcome mapping onto existing plugin error states."""

from __future__ import annotations

import json

import httpx
import pytest

from cosmas_os.plugins.athena import (
    EXPIRED as ATHENA_EXPIRED,
)
from cosmas_os.plugins.athena import (
    MALFORMED as ATHENA_MALFORMED,
)
from cosmas_os.plugins.athena import (
    NOT_CONNECTED as ATHENA_NOT_CONNECTED,
)
from cosmas_os.plugins.athena import (
    STALE as ATHENA_STALE,
)
from cosmas_os.plugins.athena import (
    TIMEOUT as ATHENA_TIMEOUT,
)
from cosmas_os.plugins.athena import (
    WRONG_PRACTICE as ATHENA_WRONG_PRACTICE,
)
from cosmas_os.plugins.ehr_fhir import (
    ERROR_STATES,
    FhirR4ReadClient,
    error_result,
    map_http_status,
    map_operation_outcome,
    map_operation_outcome_code,
    messages_for,
)

SANDBOX = "https://fhir.sandbox.example.com/r4"

# States shared with Athena / Elation / Tebra plugins.
SHARED_PLUGIN_STATES = frozenset(
    {"not_connected", "expired", "wrong_practice", "malformed", "timeout", "stale"}
)


def outcome(code: str, severity: str = "error") -> dict:
    return {
        "resourceType": "OperationOutcome",
        "issue": [{"severity": severity, "code": code, "diagnostics": "synthetic-only"}],
    }


def response(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"Content-Type": "application/fhir+json"},
        content=json.dumps(payload).encode(),
    )


def test_error_state_names_include_shared_plugins_and_lane_additions():
    assert SHARED_PLUGIN_STATES <= ERROR_STATES
    assert "rate_limited" in ERROR_STATES
    assert "refused" in ERROR_STATES
    assert ERROR_STATES == SHARED_PLUGIN_STATES | {"rate_limited", "refused"}


def test_messages_reuse_athena_wording_with_label():
    messages = messages_for("Athena")
    assert messages["not_connected"] == ATHENA_NOT_CONNECTED
    assert messages["wrong_practice"] == ATHENA_WRONG_PRACTICE
    assert messages["expired"] == ATHENA_EXPIRED
    assert messages["malformed"] == ATHENA_MALFORMED
    assert messages["timeout"] == ATHENA_TIMEOUT
    assert messages["stale"] == ATHENA_STALE


@pytest.mark.parametrize(
    ("status", "state"),
    [
        (401, "expired"),
        (403, "expired"),
        (404, "not_connected"),
        (408, "timeout"),
        (409, "stale"),
        (412, "stale"),
        (421, "wrong_practice"),
        (400, "malformed"),
        (422, "malformed"),
        (429, "rate_limited"),
        (504, "timeout"),
    ],
)
def test_http_status_mapping(status: int, state: str):
    result = map_http_status(status, "EHR")
    assert result.state == state
    assert result.message == messages_for("EHR")[state]


def test_http_429_is_rate_limited_not_malformed():
    result = map_http_status(429, "Athena")
    assert result.state == "rate_limited"
    assert result.state != "malformed"
    assert "limiting reads" in result.message
    assert result.message == messages_for("Athena")["rate_limited"]


@pytest.mark.parametrize(
    ("code", "state"),
    [
        ("login", "expired"),
        ("expired", "expired"),
        ("security", "expired"),
        ("forbidden", "expired"),
        ("multiple-matches", "wrong_practice"),
        ("not-found", "not_connected"),
        ("not-supported", "not_connected"),
        ("timeout", "timeout"),
        ("transient", "timeout"),
        ("deleted", "stale"),
        ("superseded", "stale"),
        ("invalid", "malformed"),
        ("structure", "malformed"),
        ("required", "malformed"),
        ("value", "malformed"),
        ("conflict", "malformed"),
        ("processing", "malformed"),
    ],
)
def test_operation_outcome_code_mapping(code: str, state: str):
    mapped = map_operation_outcome_code(code, "Elation")
    assert mapped is not None
    assert mapped.state == state
    assert mapped.message == messages_for("Elation")[state]


def test_http_status_wins_over_body_error_code():
    # Body says "processing" (malformed); HTTP 401 must still map to expired.
    result = map_http_status(401, "EHR", outcome_code="processing")
    assert result.state == "expired"
    assert result.message == messages_for("EHR")["expired"]


def test_operation_outcome_payload_mapping_ignores_warnings():
    payload = {
        "resourceType": "OperationOutcome",
        "issue": [
            {"severity": "warning", "code": "informational"},
            {"severity": "error", "code": "login"},
        ],
    }
    mapped = map_operation_outcome(payload, "Tebra")
    assert mapped is not None
    assert mapped.state == "expired"
    assert mapped.message == messages_for("Tebra")["expired"]


def test_client_maps_http_errors_through_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        return response(outcome("forbidden"), status=403)

    client = FhirR4ReadClient(
        SANDBOX,
        transport=httpx.MockTransport(handler),
        display_label="Athena",
    )
    result = client.read("Patient", "synth-patient-1001")
    assert result.state == "expired"
    assert result.message == ATHENA_EXPIRED
    assert result.resources == ()


def test_client_http_status_wins_over_body_processing_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return response(outcome("processing"), status=401)

    client = FhirR4ReadClient(SANDBOX, transport=httpx.MockTransport(handler))
    result = client.read("Patient", "synth-patient-1001")
    assert result.state == "expired"
    assert result.message == messages_for("EHR")["expired"]
    assert result.resources == ()


def test_client_maps_http_429_to_rate_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        return response(outcome("transient"), status=429)

    client = FhirR4ReadClient(
        SANDBOX,
        transport=httpx.MockTransport(handler),
        display_label="Athena",
    )
    result = client.search("Patient", {"patient": "synth-patient-1001"})
    assert result.state == "rate_limited"
    assert result.message == messages_for("Athena")["rate_limited"]
    assert result.resources == ()


def test_client_maps_operation_outcome_on_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return response(outcome("not-found"))

    client = FhirR4ReadClient(SANDBOX, transport=httpx.MockTransport(handler))
    result = client.search("Encounter", {"patient": "synth-patient-1001"})
    assert result.state == "not_connected"
    assert result.message == messages_for("EHR")["not_connected"]


def test_client_maps_timeout_transport_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    client = FhirR4ReadClient(SANDBOX, transport=httpx.MockTransport(handler))
    result = client.read("Appointment", "synth-appointment-3001")
    assert result.state == "timeout"
    assert result.message == messages_for("EHR")["timeout"]


def test_client_maps_connection_errors_to_not_connected():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic disconnect", request=request)

    client = FhirR4ReadClient(SANDBOX, transport=httpx.MockTransport(handler))
    result = client.search("AllergyIntolerance")
    assert result.state == "not_connected"


def test_off_origin_next_link_is_stale():
    payload = {
        "resourceType": "Bundle",
        "type": "searchset",
        "link": [
            {"relation": "self", "url": f"{SANDBOX}/Patient"},
            {"relation": "next", "url": "https://fhir.prd.cloud.tebra.com/fhir-request/Patient?page=2"},
        ],
        "entry": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return response(payload)

    client = FhirR4ReadClient(SANDBOX, transport=httpx.MockTransport(handler))
    result = client.search("Patient")
    assert result.state == "stale"
    assert result.message == messages_for("EHR")["stale"]


def test_error_result_helper():
    err = error_result("wrong_practice", "Athena")
    assert err.as_dict() == {"state": "wrong_practice", "message": ATHENA_WRONG_PRACTICE}
