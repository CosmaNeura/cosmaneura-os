"""Synthetic FHIR patient/history projection; no real credentials or vendor calls."""

import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from cosmas_os.adapters.tebra_fhir_read import (
    FHIR_BASE,
    MAX_BYTES,
    TebraFhirCredential,
    TebraFhirReadAdapter,
    TebraFhirReadError,
    TebraFhirScope,
)
from cosmas_os.domain.hashing import payload_hash

SCOPE = TebraFhirScope(UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4), "patient-A", "a"*64)
CREDENTIAL = TebraFhirCredential(SCOPE.commitment(), SecretStr("invented-fhir-token"))
NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
PATIENT = {"resourceType": "Patient", "id": "patient-A", "name": [{"given": ["Alex"], "family": "Example"}],
    "birthDate": "1980-01-02", "identifier": [{"system": "https://invented.invalid/mrn", "value": "not-a-soap-id"}]}
CONCEPT = {"text": "Invented medication", "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "invented-code"}]}
SELF = FHIR_BASE+"/MedicationRequest?patient=patient-A&intent=order%2Cplan&_include=MedicationRequest%3Amedication&_count=25"


def medication(identifier="drug-A"):
    return {"resourceType": "Medication", "id": identifier, "code": deepcopy(CONCEPT),
        "form": {"text": "Tablet"}, "ingredient": [{"itemCodeableConcept": {"text": "Invented ingredient"},
        "strength": {"numerator": {"value": 10, "unit": "mg"}, "denominator": {"value": 1, "unit": "tablet"}}}]}


def record(identifier="rx-A", **changes):
    return {"resourceType": "MedicationRequest", "id": identifier, "subject": {"reference": "Patient/patient-A"},
        "status": "active", "intent": "order", "authoredOn": "2025-01-02", "requester": {"display": "Invented clinician"},
        "medicationCodeableConcept": deepcopy(CONCEPT), "dosageInstruction": [{"sequence": 1,
        "text": "First line\r\n\tSecond line", "patientInstruction": "With food", "asNeededBoolean": False,
        "timing": {"repeat": {"frequency": 1, "period": 1, "periodUnit": "d"}},
        "doseAndRate": [{"doseQuantity": {"value": 1, "unit": "tablet"}}]}]} | changes


def page(rows=None, includes=None, **changes):
    rows = [record()] if rows is None else rows
    entries = [{"fullUrl": FHIR_BASE+"/MedicationRequest/"+row["id"], "resource": row, "search": {"mode": "match"}} for row in rows]
    entries += [{"fullUrl": FHIR_BASE+"/Medication/"+row["id"], "resource": row, "search": {"mode": "include"}} for row in (includes or [])]
    return {"resourceType": "Bundle", "type": "searchset", "total": len(rows), "link": [{"relation": "self", "url": SELF}], "entry": entries} | changes


def with_reference(row, reference):
    row = deepcopy(row)
    row.pop("medicationCodeableConcept")
    row["medicationReference"] = {"reference": reference}
    return row


def response(value, **kwargs):
    headers = {"Content-Type": "application/fhir+json"} | kwargs.pop("headers", {})
    return httpx.Response(200, stream=httpx.ByteStream(json.dumps(value, ensure_ascii=True).encode()), headers=headers, **kwargs)


class Harness:
    def __init__(self, bundle=None, patient=None):
        self.bundle = page() if bundle is None else bundle
        self.patient = deepcopy(PATIENT) if patient is None else patient
        self.resources = {"drug-A": medication()}
        self.calls = []
        self.allowed = True
        self.identity = True
        self.clock = 1.0
        self.after: Callable[[httpx.Request], None] = lambda _: None
        self.override: Callable[[httpx.Request], httpx.Response] | None = None
        self.verified = []
        self.port = TebraFhirReadAdapter(enabled=True, transport=httpx.MockTransport(self.send),
            authorize_read=lambda scope: self.allowed and scope == SCOPE, verify_patient=self.verify,
            now=lambda: NOW, monotonic=lambda: self.clock)

    def verify(self, scope, patient):
        self.verified.append(patient)
        assert scope == SCOPE
        return self.identity

    def send(self, request):
        self.calls.append(request)
        self.after(request)
        if self.override is not None:
            return self.override(request)
        if request.url.path == "/fhir-request/Patient/patient-A":
            return response(self.patient)
        if request.url.path == "/fhir-request/MedicationRequest":
            return response(self.bundle)
        if request.url.path.startswith("/fhir-request/Medication/"):
            return response(self.resources[request.url.path.split("/")[-1]])
        raise AssertionError("Unexpected endpoint")

    def read(self):
        return self.port.medication_history(SCOPE, CREDENTIAL)


def reject(call, code="response_invalid"):
    with pytest.raises(TebraFhirReadError, match="^"+code+"$"):
        call()


def test_disabled_and_real_transports_are_unreachable():
    h = Harness()
    port = TebraFhirReadAdapter(transport=httpx.MockTransport(h.send))
    reject(lambda: port.medication_history(SCOPE, CREDENTIAL), "connector_disabled")
    for transport in (None, httpx.HTTPTransport()):
        port = TebraFhirReadAdapter(enabled=True, transport=transport, authorize_read=lambda _: True, verify_patient=lambda *_: True)
        reject(lambda port=port: port.medication_history(SCOPE, CREDENTIAL), "provider_qualification_required")
        if transport:
            transport.close()
    assert h.calls == []


def test_exact_patient_query_projection_and_nonclinical_reprs():
    h = Harness()
    result = h.read()
    assert [str(r.url) for r in h.calls] == [FHIR_BASE+"/Patient/patient-A", SELF]
    assert all(r.method == "GET" and r.headers["Authorization"] == "Bearer invented-fhir-token" and "cookie" not in r.headers for r in h.calls)
    row = result.rows[0]
    assert row.medication_name == "Invented medication"
    assert row.dosage_instructions_json is not None
    assert json.loads(row.dosage_instructions_json) == record()["dosageInstruction"]
    assert row.authored_on == "2025-01-02"
    assert row.do_not_perform is None and row.reported_json is None
    assert result.patient.identity_sha256 == payload_hash(json.loads(result.patient.identity_json))
    assert result.scope == SCOPE and len(result.provider_sources) == 2
    assert result.coverage == "returned_page_only" and result.reported_total == 1
    assert "Invented" not in repr(row)+repr(result)+repr(result.patient)+repr(h.port)+repr(CREDENTIAL)
    assert "invented-fhir-token" not in json.dumps(asdict(result), default=str)


def test_all_reference_forms_and_shared_reference_fetch_once():
    contained = with_reference(record("rx-contained"), "#local")
    contained["contained"] = [medication("local")]
    rows = [record("rx-code"), contained, with_reference(record("rx-include"), "Medication/included"),
        with_reference(record("rx-fetch"), FHIR_BASE+"/Medication/drug-A"), with_reference(record("rx-fetch-again"), "Medication/drug-A")]
    h = Harness(page(rows, [medication("included")]))
    result = h.read()
    assert len(result.rows) == 5 and result.reported_total == 5
    assert len(h.calls) == 3 and h.calls[-1].url.path.endswith("/Medication/drug-A")
    assert all(row.medication_name == "Invented medication" for row in result.rows)
    assert json.loads(result.rows[1].medication_json)["ingredient"][0]["strength"]["numerator"]["value"] == 10


def test_reported_history_negation_dates_and_structured_instructions_are_preserved():
    original = record(intent="plan", status="entered-in-error", doNotPerform=True, reportedReference={"reference": "Patient/patient-A"},
        authoredOn="2025-01", statusReason={"text": "Preserved reason"})
    h = Harness(page([original]))
    row = h.read().rows[0]
    assert (row.intent, row.status, row.do_not_perform, row.authored_on) == ("plan", "entered-in-error", True, "2025-01")
    assert row.reported_json is not None and row.dosage_instructions_json is not None
    assert json.loads(row.reported_json) == {"reportedReference": {"reference": "Patient/patient-A"}}
    assert json.loads(row.context_json)["statusReason"] == original["statusReason"]
    assert json.loads(row.dosage_instructions_json) == original["dosageInstruction"]


@pytest.mark.parametrize("date_value", ["2024", "2024-02", "2024-02-29", "2024-02-29T12:34:56.123456789Z", "2024-02-29T12:34:60+14:00"])
def test_fhir_recorded_precision_is_not_normalized(date_value):
    assert Harness(page([record(authoredOn=date_value)])).read().rows[0].authored_on == date_value


@pytest.mark.parametrize("date_value", ["0000", "2025-02-29", "2024-13", "2024-02-29T12:34:56", "2024-02-29T12:34:56+14:01", "2024-02-29T12:34:56+00:60", "2024-02-29T24:00:00Z", "2024-02-29\n"])
def test_bad_fhir_dates_rejected(date_value):
    reject(Harness(page([record(authoredOn=date_value)])).read)


@pytest.mark.parametrize("change", [{"status": "dispensed"}, {"status": []}, {"intent": "proposal"}, {"doNotPerform": "false"},
    {"reportedBoolean": 1}, {"reportedBoolean": False, "reportedReference": {}},
    {"dosageInstruction": "one tablet"}, {"dosageInstruction": [{"text": "x\x1f"}]},
    {"dosageInstruction": [{"asNeededBoolean": "no"}]}, {"dosageInstruction": [{"text": "x"*4001}]},
    {"authoredOn": None}, {"medicationCodeableConcept": {"text": "x\ud800"}}])
def test_malformed_clinical_values_never_project(change):
    reject(Harness(page([record(**change)])).read)


@pytest.mark.parametrize("where", ["record", "dosage", "patient", "medication"])
def test_unknown_modifier_extension_is_not_ignored(where):
    h = Harness()
    target = {"record": h.bundle["entry"][0]["resource"], "dosage": h.bundle["entry"][0]["resource"]["dosageInstruction"][0], "patient": h.patient}
    if where == "medication":
        h.bundle = page([with_reference(record(), "Medication/drug-A")])
        chosen = h.resources["drug-A"]
    else:
        chosen = target[where]
    chosen["modifierExtension"] = [{"url": "https://invented.invalid/do-not-ignore", "valueBoolean": True}]
    reject(h.read, "unsupported_record")


@pytest.mark.parametrize("where", ["patient", "bundle", "record", "included", "fetched", "contained"])
def test_unqualified_implicit_rules_are_never_interpreted(where):
    h = Harness()
    if where == "included":
        h.bundle = page([with_reference(record(), "Medication/drug-A")], [medication()])
        chosen = h.bundle["entry"][1]["resource"]
    elif where == "fetched":
        h.bundle = page([with_reference(record(), "Medication/drug-A")])
        chosen = h.resources["drug-A"]
    elif where == "contained":
        original = with_reference(record(), "#local")
        original["contained"] = [medication("local")]
        h.bundle = page([original])
        chosen = original["contained"][0]
    else:
        chosen = {"patient": h.patient, "bundle": h.bundle, "record": h.bundle["entry"][0]["resource"]}[where]
    chosen["implicitRules"] = "https://invented.invalid/unqualified-interpretation"
    reject(h.read, "unsupported_record")
    assert len(h.calls) == (1 if where == "patient" else 3 if where == "fetched" else 2)


def test_original_medication_choice_and_reference_metadata_survive_resolution():
    original = with_reference(record("rx-reference"), "Medication/drug-A")
    original["medicationReference"] |= {"display": "Conflicting request label", "type": "Patient"}
    coded = record("rx-code")
    rows = Harness(page([original, coded])).read().rows
    assert json.loads(rows[0].request_medication_json) == {"medicationReference": original["medicationReference"]}
    assert json.loads(rows[1].request_medication_json) == {"medicationCodeableConcept": coded["medicationCodeableConcept"]}
    assert rows[0].medication_name == "Invented medication"
    assert "Conflicting request label" not in rows[0].medication_json
    assert json.loads(rows[0].medication_json) == medication()


def test_patient_verification_precedes_clinical_io_and_identity_is_complete():
    h = Harness()
    h.identity = False
    reject(h.read, "patient_changed")
    assert len(h.calls) == 1
    assert json.loads(h.verified[0].identity_json) == PATIENT


@pytest.mark.parametrize("foreign", ["Patient/another", FHIR_BASE+"/Patient/another"])
def test_foreign_medication_subject_rejects_page(foreign):
    h = Harness(page([record(subject={"reference": foreign})]))
    reject(h.read, "scope_changed")
    assert len(h.calls) == 2


@pytest.mark.parametrize("reference", ["https://evil.invalid/Medication/drug-A", "http://fhir.prd.cloud.tebra.com/fhir-request/Medication/drug-A", "Medication/..", "Medication/drug-A/_history/1", "Medication/%2e%2e", "//evil.invalid/a"])
def test_unsafe_reference_is_never_requested(reference):
    h = Harness(page([with_reference(record(), reference)]))
    with pytest.raises(TebraFhirReadError):
        h.read()
    assert len(h.calls) == 2


@pytest.mark.parametrize("tamper", ["duplicate", "bad_fullurl", "wrong_include_type", "unrelated_include", "missing_contained", "two_variants", "wrong_returned_id"])
def test_ambiguous_reference_failures(tamper):
    h = Harness(page([with_reference(record(), "Medication/drug-A")]))
    if tamper == "duplicate":
        h.bundle["entry"] *= 2
        h.bundle["total"] = 2
    elif tamper == "bad_fullurl":
        h.bundle["entry"][0]["fullUrl"] = FHIR_BASE+"/MedicationRequest/other"
    elif tamper == "wrong_include_type":
        h.bundle = page([record()], [medication() | {"resourceType": "Patient"}])
    elif tamper == "unrelated_include":
        h.bundle = page([record()], [medication("unrelated")])
    elif tamper == "missing_contained":
        h.bundle = page([with_reference(record(), "#missing")])
    elif tamper == "two_variants":
        h.bundle["entry"][0]["resource"]["medicationCodeableConcept"] = CONCEPT
    else:
        h.resources["drug-A"]["id"] = "wrong"
    reject(h.read)


def test_next_is_reported_but_never_followed_and_total_excludes_includes():
    h = Harness(page([with_reference(record(), "Medication/drug-A")], [medication()], total=20,
        link=[{"relation": "self", "url": SELF}, {"relation": "next", "url": FHIR_BASE+"?_getpages=opaque"}]))
    result = h.read()
    assert result.coverage == "more_rows_available" and result.reported_total == 20 and len(result.rows) == 1
    assert len(h.calls) == 2
    empty = Harness(page([])).read()
    assert empty.coverage == "returned_page_only" and empty.rows == ()


@pytest.mark.parametrize("tamper", ["foreign_self", "ignored_patient", "ignored_intent", "active_only", "external_next", "duplicate_self", "wrong_type", "bad_total", "extra_date_filter", "ignored_include"])
def test_bundle_binding_and_shape_failures(tamper):
    h = Harness()
    if tamper == "foreign_self":
        h.bundle["link"][0]["url"] = SELF.replace("tebra.com", "evil.invalid")
    elif tamper == "ignored_patient":
        h.bundle["link"][0]["url"] = SELF.replace("patient-A", "other")
    elif tamper == "ignored_intent":
        h.bundle["link"][0]["url"] = SELF.replace("order%2Cplan", "order")
    elif tamper == "active_only":
        h.bundle["link"][0]["url"] += "&status=active"
    elif tamper == "external_next":
        h.bundle["link"].append({"relation": "next", "url": "https://evil.invalid/?secret=value"})
    elif tamper == "duplicate_self":
        h.bundle["link"] *= 2
    elif tamper == "wrong_type":
        h.bundle["type"] = "collection"
    elif tamper == "extra_date_filter":
        h.bundle["link"][0]["url"] += "&authoredon=gt2025-01-01"
    elif tamper == "ignored_include":
        h.bundle["link"][0]["url"] = SELF.replace("MedicationRequest%3Amedication", "*")
    else:
        h.bundle["total"] = True
    reject(h.read)


def test_outcome_warning_preserved_without_diagnostic_prose_and_error_refused():
    h = Harness()
    outcome = {"resourceType": "OperationOutcome", "issue": [{"severity": "warning", "code": "incomplete", "diagnostics": "Excluded sensitive prose"}]}
    h.bundle["entry"].append({"resource": outcome, "search": {"mode": "outcome"}})
    result = h.read()
    assert result.warnings == ("incomplete",) and "Excluded sensitive prose" not in json.dumps(asdict(result), default=str)
    outcome["issue"][0]["severity"] = "error"
    reject(h.read, "provider_rejected")


def test_access_and_grant_binding_fail_before_io_or_before_disclosure():
    h = Harness()
    h.allowed = False
    reject(h.read, "access_denied")
    assert h.calls == []
    h.allowed = True
    reject(lambda: h.port.medication_history(SCOPE, replace(CREDENTIAL, scope_sha256="b"*64)), "scope_changed")
    assert h.calls == []
    h.after = lambda _: setattr(h, "allowed", False)
    reject(h.read, "access_denied")
    assert len(h.calls) == 1


def test_deadline_and_response_budgets_apply_to_whole_read():
    h = Harness()
    h.after = lambda _: setattr(h, "clock", 31.0)
    reject(h.read, "transport_unconfirmed")
    h = Harness()
    h.override = lambda _: httpx.Response(200, stream=httpx.ByteStream(b" "*(MAX_BYTES+1)), headers={"Content-Type": "application/fhir+json"})
    reject(h.read, "response_too_large")
    reject(Harness(page([record("rx-"+str(i)) for i in range(26)])).read, "too_many_results")


@pytest.mark.parametrize("raw", [b'{"resourceType":"Patient","resourceType":"Patient"}', b'{"value":NaN}', b'{"value":1e999}', b'[]'])
def test_malformed_json_is_fixed_error(raw):
    h = Harness()
    h.override = lambda _: httpx.Response(200, stream=httpx.ByteStream(raw), headers={"Content-Type": "application/fhir+json"})
    reject(h.read)


@pytest.mark.parametrize("status,code", [(429, "provider_throttled"), (401, "provider_rejected"), (302, "provider_rejected")])
def test_http_errors_are_not_retried(status, code):
    h = Harness()
    h.override = lambda _: httpx.Response(status, headers={"Location": "https://evil.invalid"}, text="Must not leak")
    reject(h.read, code)
    assert len(h.calls) == 1


def test_resource_bytes_are_accumulated_across_patient_search_and_medication():
    h = Harness(page([with_reference(record(), "Medication/drug-A")]))
    h.patient["extension"] = [{"url": "https://invented.invalid/padding", "valueString": "p"*7000} for _ in range(15)]
    h.resources["drug-A"]["extension"] = [{"url": "https://invented.invalid/padding", "valueString": "m"*7000} for _ in range(23)]
    sizes = [len(json.dumps(value).encode()) for value in (h.patient, h.bundle, h.resources["drug-A"])]
    assert max(sizes) < MAX_BYTES < sum(sizes)
    reject(h.read, "response_too_large")
    assert len(h.calls) == 3


def test_large_projected_packet_is_refused_whole_without_truncating_instructions():
    h = Harness(page([record("rx-"+str(i), dosageInstruction=[{"text": "x"*4000}]) for i in range(20)]))
    assert len(json.dumps(h.bundle).encode()) < MAX_BYTES
    reject(h.read, "response_too_large")
    assert len(h.calls) == 2


def test_no_display_is_invented_for_code_only_medication_and_request_details_survive():
    original = record(medicationCodeableConcept={"coding": [{"system": "https://invented.invalid/codes", "code": "opaque-1"}]},
        dispenseRequest={"validityPeriod": {"start": "2025-01-02", "end": "2025-02-02"},
            "numberOfRepeatsAllowed": 0, "quantity": {"value": 12, "unit": "tablet"}},
        substitution={"allowedBoolean": False}, courseOfTherapyType={"text": "Recorded course"})
    row = Harness(page([original])).read().rows[0]
    assert row.medication_name is None
    context = json.loads(row.context_json)
    for key in ("dispenseRequest", "substitution", "courseOfTherapyType"):
        assert context[key] == original[key]
    assert "dispensed" not in asdict(row)


def test_clinical_response_revocation_and_changed_patient_are_not_disclosed():
    h = Harness()
    h.after = lambda request: setattr(h, "allowed", request.url.path != "/fhir-request/MedicationRequest")
    reject(h.read, "access_denied")
    assert len(h.calls) == 2
    h = Harness(patient=PATIENT | {"id": "other"})
    reject(h.read)
    assert len(h.calls) == 1 and h.verified == []


def test_cookies_cannot_move_between_patient_and_medication_requests():
    h = Harness()
    h.override = lambda request: response(h.patient if request.url.path.endswith("/patient-A") else h.bundle,
        headers={"Set-Cookie": "injected=ignored; Path=/"})
    h.read()
    assert all("cookie" not in request.headers for request in h.calls)
