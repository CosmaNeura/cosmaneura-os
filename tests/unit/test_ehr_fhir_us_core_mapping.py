"""Golden and unit coverage for C5 US Core → source-review mapping."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cosmas_os.adapters.athena_fhir_r4 import ATHENA_FHIR_R4_BASE_URL, ATHENA_PRACTICE_VALUE
from cosmas_os.adapters.ehr_fhir_vendor import (
    ATHENA_FHIR_ENVIRONMENT,
    FHIR_BASE_BY_VENDOR,
    connection_scope_payload,
    fhir_environment,
    medications_item_kind,
    reviewed_medications_label,
)
from cosmas_os.adapters.tebra_fhir_read import FHIR_BASE as TEBRA_FHIR_BASE
from cosmas_os.application.ehr_fhir_us_core_mapping import (
    MAPPED_SOURCE_TYPES,
    map_bundle_entries,
    map_patient_identity,
    map_review_source,
    provenance_commitment,
    resource_id_hash,
)
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.ports.tebra_fhir_ehr import FhirCommonObservation, FhirPatientsObservation

FIXTURES = Path(__file__).parent / "fixtures" / "ehr_fhir"
READ_TIME = datetime(2026, 11, 6, 16, 0, 0, tzinfo=UTC)


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


def test_tebra_connection_digest_payload_unchanged():
    payload = connection_scope_payload(
        "tebra",
        box_id="11111111-1111-1111-1111-111111111111",
        owner_id="22222222-2222-2222-2222-222222222222",
        account_id="33333333-3333-3333-3333-333333333333",
        connection_id="44444444-4444-4444-4444-444444444444",
        credential_generation="55555555-5555-5555-5555-555555555555",
        display_label="Invented Tebra Clinical",
    )
    assert payload == {
        "contract": "tebra-fhir-connection-scope.v1",
        "fhir_base": TEBRA_FHIR_BASE,
        "box_id": "11111111-1111-1111-1111-111111111111",
        "owner_id": "22222222-2222-2222-2222-222222222222",
        "account_id": "33333333-3333-3333-3333-333333333333",
        "connection_id": "44444444-4444-4444-4444-444444444444",
        "credential_generation": "55555555-5555-5555-5555-555555555555",
        "display_label": "Invented Tebra Clinical",
    }
    assert "ah_practice" not in payload


def test_athena_preview_connection_digest_includes_practice_195900():
    payload = connection_scope_payload(
        "athena",
        box_id="11111111-1111-1111-1111-111111111111",
        owner_id="22222222-2222-2222-2222-222222222222",
        account_id="33333333-3333-3333-3333-333333333333",
        connection_id="44444444-4444-4444-4444-444444444444",
        credential_generation="55555555-5555-5555-5555-555555555555",
        display_label="athena Preview 195900",
    )
    assert payload["contract"] == "athena-fhir-connection-scope.v1"
    assert payload["fhir_base"] == ATHENA_FHIR_R4_BASE_URL
    assert payload["ah_practice"] == ATHENA_PRACTICE_VALUE
    assert payload["practice_id"] == "195900"
    assert fhir_environment("athena") == ATHENA_FHIR_ENVIRONMENT
    assert FHIR_BASE_BY_VENDOR["athena"] == ATHENA_FHIR_R4_BASE_URL


def test_fhir_common_observation_accepts_athena_provider():
    value = FhirPatientsObservation(
        provider="athena",
        protocol="fhir",
        mode="synthetic",
        kind="fhir_patients",
        workspace_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        display_label="athena Preview 195900",
        observed_at=READ_TIME,
        coverage="authorized_candidates_only",
        items=(),
    )
    assert value.provider == "athena"
    assert issubclass(FhirPatientsObservation, FhirCommonObservation)


def test_map_patient_identity_golden():
    patient = _load("patient.json")
    mapped = map_patient_identity(patient, vendor="athena", read_time=READ_TIME)
    assert mapped.fhir_patient_id == "synth-patient-1001"
    assert mapped.provenance.vendor == "athena"
    assert mapped.provenance.resource_type == "Patient"
    assert mapped.provenance.resource_id_hash == resource_id_hash("synth-patient-1001")
    assert mapped.provenance.read_time == READ_TIME
    assert mapped.identity_sha256 == __import__("hashlib").sha256(mapped.identity_json.encode()).hexdigest()
    assert json.loads(mapped.identity_json)["id"] == "synth-patient-1001"
    assert "Northwind" in mapped.identity_json


@pytest.mark.parametrize(
    ("fixture", "kind"),
    [
        ("medication_request.json", "MedicationRequest"),
        ("encounter.json", "Encounter"),
        ("allergy_intolerance.json", "AllergyIntolerance"),
        ("condition.json", "Condition"),
        ("observation.json", "Observation"),
        ("document_reference.json", "DocumentReference"),
    ],
)
def test_map_review_source_provenance_golden(fixture, kind):
    resource = _load(fixture)
    mapped = map_review_source(resource, vendor="athena", read_time=READ_TIME)
    assert mapped.resource_type == kind
    assert kind in MAPPED_SOURCE_TYPES
    provenance = mapped.provenance.as_dict()
    assert provenance == {
        "vendor": "athena",
        "resource_type": kind,
        "resource_id_hash": resource_id_hash(resource["id"]),
        "read_time": READ_TIME.isoformat(),
    }
    assert provenance_commitment(mapped.provenance) == payload_hash(
        {"contract": "ehr-fhir-source-provenance.v1", **provenance}
    )
    assert mapped.source_content.startswith("Athena ")
    assert "Resource id hash:" in mapped.source_content
    assert mapped.content_sha256 == __import__("hashlib").sha256(mapped.source_content.encode()).hexdigest()
    assert reviewed_medications_label("athena") == "Athena: reviewed medication records"
    assert medications_item_kind("athena") == "ehr_athena_fhir_medications_item.v1"
    assert medications_item_kind("tebra") == "ehr_tebra_fhir_medications_item.v1"


def test_map_bundle_entries_covers_c8_resources_against_golden():
    bundle = _load("us_core_synth_bundle.json")
    golden = _load("golden_athena_us_core_provenance.json")
    patient, sources = map_bundle_entries(bundle, vendor="athena", read_time=READ_TIME)
    assert patient is not None
    assert patient.fhir_patient_id == golden["patient_id"]
    assert [(s.resource_type, s.resource_id) for s in sources] == [
        (row["resource_type"], row["resource_id"]) for row in golden["sources"]
    ]
    for source in sources:
        assert source.provenance.as_dict() == {
            "vendor": golden["vendor"],
            "resource_type": source.resource_type,
            "resource_id_hash": resource_id_hash(source.resource_id),
            "read_time": READ_TIME.isoformat(),
        }
        assert source.display_label.startswith("Athena: reviewed ")
        # Mapped content is what the existing human source-review flow admits.
        assert "Preparing this projection does not establish human approval" in source.source_content


def test_appointment_not_mapped_for_athena_path():
    appointment = _load("appointment.json")
    with pytest.raises(ValueError, match="unsupported_fhir_review_resource"):
        map_review_source(appointment, vendor="athena", read_time=READ_TIME)


def test_naive_read_time_rejected():
    patient = _load("patient.json")
    with pytest.raises(ValueError, match="aware_fhir_read_time_required"):
        map_patient_identity(patient, vendor="tebra", read_time=datetime(2026, 11, 6, 16, 0, 0))
