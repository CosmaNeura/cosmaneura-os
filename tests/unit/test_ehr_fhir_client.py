"""Shared FHIR R4 read client: resource reads, search, paging, write refusal.

Uses recorded synthetic US Core fixtures and httpx.MockTransport only.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from cosmas_os.plugins.ehr_fhir import (
    DEFAULT_MAX_PAGES,
    READABLE_RESOURCES,
    FhirR4ReadClient,
    messages_for,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ehr_fhir"
SANDBOX = "https://fhir.sandbox.example.com/r4"
FIXTURE_FILES = {
    "Patient": "patient.json",
    "Encounter": "encounter.json",
    "Appointment": "appointment.json",
    "AllergyIntolerance": "allergy_intolerance.json",
    "MedicationRequest": "medication_request.json",
    "Medication": "medication.json",
    "Condition": "condition.json",
    "Observation": "observation.json",
    "DocumentReference": "document_reference.json",
    "Practitioner": "practitioner.json",
    "Organization": "organization.json",
}


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def bundle(resource_type: str, rows: list[dict], *, next_url: str | None = None) -> dict:
    links = [{"relation": "self", "url": f"{SANDBOX}/{resource_type}"}]
    if next_url is not None:
        links.append({"relation": "next", "url": next_url})
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(rows),
        "link": links,
        "entry": [
            {
                "fullUrl": f"{SANDBOX}/{resource_type}/{row['id']}",
                "resource": row,
                "search": {"mode": "match"},
            }
            for row in rows
        ],
    }


def response(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"Content-Type": "application/fhir+json"},
        content=json.dumps(payload).encode(),
    )


class Harness:
    def __init__(self, handler, **kwargs):
        self.calls: list[httpx.Request] = []
        self.handler = handler
        self.client = FhirR4ReadClient(
            SANDBOX,
            transport=httpx.MockTransport(self.send),
            access_token="invented-sandbox-token",
            display_label="EHR",
            **kwargs,
        )

    def send(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return self.handler(request)


def test_readable_resources_match_ticket_set():
    assert READABLE_RESOURCES == {
        "Patient",
        "Encounter",
        "Appointment",
        "AllergyIntolerance",
        "MedicationRequest",
        "Medication",
        "Condition",
        "Observation",
        "DocumentReference",
        "Practitioner",
        "Organization",
    }


@pytest.mark.parametrize("resource_type", sorted(FIXTURE_FILES))
def test_read_each_resource_type(resource_type: str):
    resource = load(FIXTURE_FILES[resource_type])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith(f"/{resource_type}/{resource['id']}")
        assert request.headers["Authorization"] == "Bearer invented-sandbox-token"
        return response(resource)

    harness = Harness(handler)
    result = harness.client.read(resource_type, resource["id"])
    assert result.ok
    assert result.state == "ready"
    assert result.resource_type == resource_type
    assert len(result.resources) == 1
    assert result.resources[0]["id"] == resource["id"]
    assert result.pages_read == 1
    assert "Northwind" in json.dumps(result.resources) or resource_type != "Patient"


@pytest.mark.parametrize("resource_type", sorted(FIXTURE_FILES))
def test_search_each_resource_type(resource_type: str):
    resource = load(FIXTURE_FILES[resource_type])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert f"/{resource_type}" in request.url.path
        return response(bundle(resource_type, [resource]))

    harness = Harness(handler)
    result = harness.client.search(resource_type, {"patient": "synth-patient-1001"})
    assert result.ok
    assert result.resource_type == resource_type
    assert [row["id"] for row in result.resources] == [resource["id"]]
    assert result.more_available is False


def test_search_follows_bundle_paging_within_limit():
    first = load("patient.json")
    second = {**first, "id": "synth-patient-1002", "name": [{"family": "Example", "given": ["Blair"]}]}
    pages = {
        f"{SANDBOX}/Patient?_count=1": bundle(
            "Patient", [first], next_url=f"{SANDBOX}/Patient?_count=1&page=2"
        ),
        f"{SANDBOX}/Patient?_count=1&page=2": bundle("Patient", [second]),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return response(pages[str(request.url)])

    harness = Harness(handler)
    result = harness.client.search("Patient", {"_count": "1"})
    assert result.ok
    assert [row["id"] for row in result.resources] == ["synth-patient-1001", "synth-patient-1002"]
    assert result.pages_read == 2
    assert result.more_available is False
    assert len(harness.calls) == 2
    assert all(call.method == "GET" for call in harness.calls)


def test_search_stops_at_page_limit_and_reports_more():
    rows = [
        {**load("condition.json"), "id": f"synth-condition-{index}"}
        for index in range(1, DEFAULT_MAX_PAGES + 2)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        query = dict(httpx.URL(str(request.url)).params)
        page = int(query.get("page", "1"))
        next_url = f"{SANDBOX}/Condition?page={page + 1}"
        return response(bundle("Condition", [rows[page - 1]], next_url=next_url))

    harness = Harness(handler, max_pages=3)
    result = harness.client.search("Condition")
    assert result.ok
    assert result.pages_read == 3
    assert result.more_available is True
    assert len(result.resources) == 3
    assert len(harness.calls) == 3
    assert "More EHR records are available" in result.message


def test_search_rejects_oversized_response():
    huge = bundle("Observation", [load("observation.json")])
    huge["entry"][0]["resource"] = {
        **huge["entry"][0]["resource"],
        "note": [{"text": "x" * 4000}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/fhir+json"},
            content=json.dumps(huge).encode() + b"y" * 8000,
        )

    harness = Harness(handler, max_response_bytes=4096)
    result = harness.client.search("Observation")
    assert result.state == "malformed"
    assert result.message == messages_for("EHR")["malformed"]
    assert result.resources == ()


def test_write_verbs_are_refused_without_transport():
    harness = Harness(lambda request: pytest.fail(f"unexpected {request.method}"))
    refused = messages_for("EHR")["write_refused"]
    for call in (
        harness.client.create,
        harness.client.update,
        harness.client.patch,
        harness.client.delete,
        harness.client.post,
        harness.client.put,
    ):
        result = call({"resourceType": "Patient"})
        assert result.state == "refused"
        assert result.message == refused
        assert "could not read" not in result.message
        assert result.resources == ()
    assert harness.client.request("POST", "/Patient").state == "refused"
    assert harness.client.request("DELETE", "/Patient/1").state == "refused"
    assert harness.client.request("PATCH", "/Patient/1").message == refused
    assert harness.calls == []


def test_unknown_resource_type_is_malformed():
    harness = Harness(lambda request: pytest.fail("no transport"))
    assert harness.client.read("Binary", "x").state == "malformed"
    assert harness.client.search("Provenance").state == "malformed"
    assert harness.calls == []


def test_ready_result_dict_omits_rows_on_error_paths():
    harness = Harness(lambda request: response({"resourceType": "OperationOutcome", "issue": []}))
    failed = harness.client.read("Patient", "missing")
    assert failed.as_dict() == {"state": "malformed", "message": messages_for("EHR")["malformed"]}
