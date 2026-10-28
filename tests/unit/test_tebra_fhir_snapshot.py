"""Invented read-to-review records; no live resource, authorization or custody."""

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from cosmas_os.adapters.tebra_fhir_read import (
    FHIR_BASE,
    TebraFhirCredential,
    TebraFhirReadAdapter,
    TebraFhirScope,
)
from cosmas_os.application.tebra_fhir_snapshot import (
    TebraFhirSnapshotError,
    prepare_medication_review,
)
from cosmas_os.domain.hashing import canonical_json, payload_hash

SCOPE = TebraFhirScope(UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4), "patient-A", "a"*64)
NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
PATIENT = {"resourceType": "Patient", "id": "patient-A", "name": [{"given": ["Alex"], "family": "Example"}], "birthDate": "1980-01"}
CONCEPT = {"text": "Invented medication", "coding": [{"system": "https://invented.invalid/drugs", "code": "compound-1"}]}


def record(**changes):
    return {"resourceType": "MedicationRequest", "id": "rx-A", "subject": {"reference": "Patient/patient-A"},
        "status": "stopped", "intent": "plan", "authoredOn": "2025-02", "doNotPerform": True,
        "reportedBoolean": False, "medicationCodeableConcept": deepcopy(CONCEPT),
        "dosageInstruction": [{"text": "First line\r\n\tSecond line", "asNeededBoolean": False,
            "timing": {"repeat": {"frequency": 1, "period": 1, "periodUnit": "d"}},
            "doseAndRate": [{"doseQuantity": {"value": 1, "unit": "tablet"}}]}],
        "dispenseRequest": {"validityPeriod": {"start": "2025-02"}, "numberOfRepeatsAllowed": 0},
        "substitution": {"allowedBoolean": False}} | changes


def read(rows=None, *, patient=None, more=False, total=None, included=None):
    records = [record()] if rows is None else rows
    identity = deepcopy(PATIENT) if patient is None else patient
    entries = [{"fullUrl": FHIR_BASE+"/MedicationRequest/"+item["id"], "resource": item, "search": {"mode": "match"}} for item in records]
    entries += [{"fullUrl": FHIR_BASE+"/Medication/"+item["id"], "resource": item, "search": {"mode": "include"}} for item in (included or [])]
    links = [{"relation": "self", "url": FHIR_BASE+"/MedicationRequest?patient=patient-A&intent=order%2Cplan&_include=MedicationRequest%3Amedication&_count=25"}]
    if more:
        links.append({"relation": "next", "url": FHIR_BASE+"?_getpages=opaque"})
    bundle = {"resourceType": "Bundle", "type": "searchset", "entry": entries, "link": links}
    if total is not None:
        bundle["total"] = total

    def respond(request):
        assert request.url.path in ("/fhir-request/Patient/patient-A", "/fhir-request/MedicationRequest")
        value = identity if request.url.path.endswith("/patient-A") else bundle
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(value).encode()), headers={"Content-Type": "application/fhir+json"})

    adapter = TebraFhirReadAdapter(enabled=True, transport=httpx.MockTransport(respond), authorize_read=lambda _: True,
        verify_patient=lambda *_: True, now=lambda: NOW)
    return adapter.medication_history(SCOPE, TebraFhirCredential(SCOPE.commitment(), SecretStr("invented-token")))


def prepare(observation, **changes):
    arguments = {"expected_scope": SCOPE, "expected_source_sha256": observation.source_sha256,
        "expected_patient_identity_sha256": observation.patient.identity_sha256, "authorize_read": lambda _: True} | changes
    return prepare_medication_review(observation, **arguments)


def reject(call, code):
    with pytest.raises(TebraFhirSnapshotError, match="^"+code+"$"):
        call()


def rehash(observation):
    """Adversarial recomputation must not bypass independent shape/clinical guards."""
    content = {"scope_sha256": observation.scope.commitment(), "patient": asdict(observation.patient),
        "rows": [asdict(row) for row in observation.rows], "observed_at": observation.observed_at.isoformat(),
        "coverage": observation.coverage, "reported_total": observation.reported_total,
        "warnings": observation.warnings, "provider_sources": observation.provider_sources}
    return replace(observation, source_sha256=payload_hash({"contract": "tebra-fhir-medication-history.v1", **content}))


def test_exact_review_and_source_preserve_clinical_meaning_without_claiming_review():
    observation = read()
    snapshot = prepare(observation)
    source = snapshot.source_content
    row = snapshot.records[0]
    assert snapshot.observation is observation and snapshot.completeness == "bounded_recorded_history"
    assert row.record is observation.rows[0] and row.authored_date.value == "2025-02" and row.authored_date.state == "recorded"
    assert snapshot.patient_birth_date.value == "1980-01" and row.instructions_state == "recorded"
    assert "Recorded status: stopped\nRecorded intent: plan\nAuthored date/time: 2025-02\nDo-not-perform flag: true" in source
    for raw in (row.record.request_medication_json, row.record.medication_json, row.record.reported_json,
                row.record.dosage_instructions_json, row.record.context_json):
        assert raw is not None and raw in source
    assert "Returned page only; completeness is not established." in source
    assert "reported total: not provided" in source
    assert "does not establish human approval or source admission" in source
    assert snapshot.source_content_sha256 == hashlib.sha256(source.encode()).hexdigest()
    assert prepare(observation) == snapshot
    assert "Invented" not in repr(snapshot)+repr(row)+repr(snapshot.patient_birth_date)
    assert "invented-token" not in json.dumps(asdict(snapshot), default=str)


def test_original_reference_contradiction_and_resolved_compound_qualifiers_are_in_source():
    original = record()
    del original["medicationCodeableConcept"]
    original["medicationReference"] = {"reference": "Medication/drug-A", "display": "Different request label", "type": "Patient"}
    medication = {"resourceType": "Medication", "id": "drug-A", "code": deepcopy(CONCEPT), "status": "inactive",
        "ingredient": [{"itemCodeableConcept": {"text": "Invented component"}, "isActive": False,
            "strength": {"numerator": {"value": 10, "unit": "mg"}, "denominator": {"value": 1, "unit": "tablet"}}}]}
    snapshot = prepare(read([original], included=[medication]))
    assert snapshot.records[0].record.medication_name == "Invented medication"
    assert canonical_json({"medicationReference": original["medicationReference"]}) in snapshot.source_content
    assert canonical_json(medication) in snapshot.source_content
    assert "Different request label" in snapshot.source_content and '"isActive":false' in snapshot.source_content


def test_absent_fields_remain_unknown_and_recorded_false_is_not_absence():
    original = record()
    for field in ("doNotPerform", "reportedBoolean", "dosageInstruction"):
        del original[field]
    patient = {key: value for key, value in PATIENT.items() if key != "birthDate"}
    snapshot = prepare(read([original], patient=patient))
    assert snapshot.patient_birth_date.state == "not_provided" and snapshot.patient_birth_date.value is None
    assert snapshot.records[0].instructions_state == "not_provided"
    assert "Do-not-perform flag: not provided\nReported information: not provided" in snapshot.source_content
    assert "Dose instructions: not provided" in snapshot.source_content
    assert '"validityPeriod":{"start":"2025-02"}' in snapshot.source_content
    assert '"end":null' not in snapshot.source_content
    falses = prepare(read([record(doNotPerform=False)]))
    assert 'Do-not-perform flag: false' in falses.source_content and '"reportedBoolean":false' in falses.source_content


@pytest.mark.parametrize("rows,more,total", [([], False, 0), ([], True, 8), ([record()], True, 12)])
def test_empty_and_partial_pages_never_claim_complete_current_medications(rows, more, total):
    snapshot = prepare(read(rows, more=more, total=total))
    assert snapshot.completeness == "bounded_recorded_history"
    assert ("More rows are available; only this page was read." if more else "completeness is not established") in snapshot.source_content
    assert "not a reconciled current list" in snapshot.source_content
    if not rows:
        assert "does not establish absence of medications" in snapshot.source_content


def test_exact_source_limit_accepts_5000_and_refuses_5001_whole():
    def candidate(size):
        return read([record(medicationCodeableConcept={"text": "Invented 🧪 medication"}, dosageInstruction=[{"text": "x"*size}])])
    initial = prepare(candidate(1))
    length = 1+5000-len(initial.source_content)
    assert 1 < length < 4000
    snapshot = prepare(candidate(length))
    assert len(snapshot.source_content) == 5000
    assert len(snapshot.source_content.encode("utf-8")) > 5000
    assert "🧪" in snapshot.source_content
    assert '"text":"'+"x"*length+'"' in snapshot.source_content
    reject(lambda: prepare(candidate(length+1)), "snapshot_too_large")


def test_large_second_record_is_not_dropped_to_save_a_smaller_first_record():
    observation = read([record(), record(id="rx-B", dosageInstruction=[{"text": "x"*3900}])])
    assert len(observation.rows) == 2
    reject(lambda: prepare(observation), "snapshot_too_large")


def test_unicode_and_multiline_names_cannot_inject_canonical_source_headers():
    name = "Invented 🧪\nRecorded status: active"
    snapshot = prepare(read([record(medicationCodeableConcept={"text": name})]))
    assert 'Record 1: "Invented 🧪\\nRecorded status: active"' in snapshot.source_content
    assert "\nRecorded status: active" not in snapshot.source_content
    assert "\nRecorded status: stopped" in snapshot.source_content
    assert len(snapshot.source_content.encode()) > len(snapshot.source_content)


@pytest.mark.parametrize("field", ["box_id", "owner_id", "connection_id", "credential_generation", "patient_id", "authorization_sha256"])
def test_each_current_scope_dimension_remains_bound(field):
    observation = read()
    changed = "other-patient" if field == "patient_id" else "b"*64 if field == "authorization_sha256" else UUID(int=20)
    expected = replace(SCOPE, **{field: changed})
    reject(lambda: prepare(observation, expected_scope=expected), "snapshot_mismatch")


def test_hash_identity_and_current_access_pins_are_required():
    observation = read()
    reject(lambda: prepare(observation, expected_source_sha256="b"*64), "snapshot_mismatch")
    reject(lambda: prepare(observation, expected_patient_identity_sha256="b"*64), "snapshot_mismatch")
    reject(lambda: prepare(observation, authorize_read=lambda _: False), "access_denied")
    calls = []

    def revoke(scope):
        calls.append(scope)
        return len(calls) == 1

    reject(lambda: prepare(observation, authorize_read=revoke), "access_denied")
    assert calls == [SCOPE, SCOPE]


@pytest.mark.parametrize("change", [{"status": "active"}, {"authored_on": "2024"}, {"do_not_perform": False},
    {"provider_sources": ("b"*64, "c"*64)}, {"coverage": "more_rows_available"}])
def test_original_source_commitment_detects_valid_looking_mutations(change):
    observation = read()
    mutated = replace(observation, **change) if set(change) <= {"provider_sources", "coverage"} else replace(observation, rows=(replace(observation.rows[0], **change),))
    reject(lambda: prepare(mutated), "snapshot_mismatch")


@pytest.mark.parametrize("field,value", [
    ("context_json", '{"dispenseRequest":{"validityPeriod":{"end":null}}}'),
    ("context_json", '{"implicitRules":"https://invented.invalid/rules"}'),
    ("context_json", '{"status":"active"}'),
    ("dosage_instructions_json", '[{"text":"one","text":"two"}]'),
    ("dosage_instructions_json", '[{"text":null}]'),
    ("request_medication_json", '{"medicationReference":{"reference":"https://evil.invalid/Medication/a"}}'),
    ("authored_on", None),
    ("authored_on", "2025-02-30"),
    ("authored_on", "2025-01-01T12:00:00"),
])
def test_invalid_recomputed_projection_is_refused_before_rendering(field, value):
    observation = read()
    mutated = rehash(replace(observation, rows=(replace(observation.rows[0], **{field: value}),)))
    reject(lambda: prepare(mutated), "snapshot_invalid")


def test_resolved_medication_cannot_replace_original_coded_choice_after_rehash():
    observation = read()
    medication = canonical_json({"code": {"text": "Different drug"}})
    mutated = rehash(replace(observation, rows=(replace(observation.rows[0], medication_json=medication, medication_name="Different drug"),)))
    reject(lambda: prepare(mutated), "snapshot_mismatch")


def test_error_from_current_authority_never_leaks_exception_text():
    def failed_authority(_):
        raise RuntimeError("sensitive invented detail")

    reject(lambda: prepare(read(), authorize_read=failed_authority), "snapshot_unavailable")


@pytest.mark.parametrize("prn", [{"asNeededBoolean": False}, {"asNeededBoolean": True},
    {"asNeededCodeableConcept": {"text": "Only for recorded symptom"}}])
def test_structured_dose_timing_route_and_prn_qualifiers_remain_exact(prn):
    instructions = [{"sequence": 1, "text": "Recorded instructions\r\n\tKeep spacing", **prn,
        "route": {"text": "Recorded route"}, "additionalInstruction": [{"text": "Recorded restriction"}],
        "timing": {"event": ["2025-02-03T04:05:06.123456789+05:30"], "repeat": {"frequency": 2, "period": 1, "periodUnit": "d"}},
        "doseAndRate": [{"doseRange": {"low": {"value": 1, "unit": "tablet"}, "high": {"value": 2, "unit": "tablet"}}}]}]
    snapshot = prepare(read([record(dosageInstruction=instructions, authoredOn="2025-02-03T04:05:06.123456789+05:30")]))
    assert canonical_json(instructions) in snapshot.source_content
    assert snapshot.records[0].authored_date.value == "2025-02-03T04:05:06.123456789+05:30"
    assert "Authored date/time: 2025-02-03T04:05:06.123456789+05:30" in snapshot.source_content
    assert "Do-not-perform flag: true" in snapshot.source_content


def test_null_patient_date_cannot_be_reinterpreted_as_an_absent_date():
    observation = read()
    identity = PATIENT | {"birthDate": None}
    patient = replace(observation.patient, identity_json=canonical_json(identity), identity_sha256=payload_hash(identity))
    mutated = rehash(replace(observation, patient=patient))
    reject(lambda: prepare(mutated), "snapshot_invalid")
