"""Runtime authority boundaries use invented grants and exact MockTransport only."""

import json
from copy import deepcopy
from dataclasses import replace
from typing import cast
from uuid import UUID

import httpx
import pytest

from cosmas_os.adapters.ehr_read_runtime import (
    EhrReadRuntimes,
    runtime_protocol,
    runtime_provider,
    select_runtime,
)
from cosmas_os.adapters.tebra_fhir_read import FHIR_BASE, TebraFhirReadError
from cosmas_os.adapters.tebra_fhir_read_runtime import (
    SyntheticTebraFhirReads,
    TebraFhirAuthorizedPatient,
    TebraFhirConnectionScope,
)
from cosmas_os.adapters.tebra_read_runtime import SyntheticTebraReads
from cosmas_os.application.tebra_fhir_snapshot import TebraFhirSnapshotError
from cosmas_os.domain.hashing import canonical_json, payload_hash

CONNECTION = TebraFhirConnectionScope(UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4),
    UUID(int=5), "Invented FHIR clinic")
PATIENT = {"resourceType": "Patient", "id": "fhir-patient-A",
    "name": [{"given": ["Alex"], "family": "Example"}], "birthDate": "1980"}
GRANT = TebraFhirAuthorizedPatient(UUID(int=6), CONNECTION, UUID(int=7), UUID(int=8),
    "fhir-patient-A", "a"*64, canonical_json(PATIENT), payload_hash(PATIENT))
SELF = FHIR_BASE+"/MedicationRequest?patient=fhir-patient-A&intent=order%2Cplan&_include=MedicationRequest%3Amedication&_count=25"


class Harness:
    def __init__(self):
        self.enabled = True
        self.authorized = True
        self.calls = []
        self.after = lambda: None
        self.patient = deepcopy(PATIENT)
        self.row = {"resourceType": "MedicationRequest", "id": "record-A",
            "subject": {"reference": "Patient/fhir-patient-A"}, "status": "stopped", "intent": "plan",
            "authoredOn": "2025-01", "doNotPerform": True, "reportedBoolean": True,
            "medicationCodeableConcept": {"text": "Invented medication"},
            "dosageInstruction": [{"text": " First line\r\n\tSecond line ", "asNeededBoolean": True}],
            "note": [{"text": "Original qualifier; do not infer current use."}]}
        self.transport = httpx.MockTransport(self.send)
        self.port = SyntheticTebraFhirReads((CONNECTION,), (GRANT,), self.transport,
            enabled=lambda: self.enabled)

    def send(self, request):
        self.calls.append(request)
        self.after()
        if request.url.path == "/fhir-request/Patient/fhir-patient-A":
            body = self.patient
        elif request.url.path == "/fhir-request/MedicationRequest":
            body = {"resourceType": "Bundle", "type": "searchset", "total": 1,
                "link": [{"relation": "self", "url": SELF}], "entry": [
                    {"fullUrl": FHIR_BASE+"/MedicationRequest/record-A", "resource": self.row,
                     "search": {"mode": "match"}}]}
        else:
            raise AssertionError("Unexpected mock request")
        return httpx.Response(200, headers={"Content-Type": "application/fhir+json"},
            stream=httpx.ByteStream(json.dumps(body).encode()))

    def read(self, scope=CONNECTION, grant=GRANT):
        return self.port.medications(scope, grant, authorize=lambda: self.authorized)


def test_protocol_is_closed_and_never_falls_back_to_soap():
    h = Harness()
    soap = object.__new__(SyntheticTebraReads)
    ports = EhrReadRuntimes(tebra=soap, tebra_fhir=h.port)
    assert runtime_provider(h.port) == "tebra" and runtime_protocol(h.port) == "fhir"
    assert select_runtime(ports, "tebra") is soap
    assert select_runtime(ports, "tebra", "fhir") is h.port
    assert select_runtime(h.port, "tebra") is None
    assert select_runtime(h.port, "tebra", "fhir") is h.port
    assert select_runtime(soap, "tebra", "fhir") is None
    assert select_runtime(ports, "elation", "fhir") is None
    assert select_runtime(ports, "tebra", "soap") is None
    assert select_runtime(EhrReadRuntimes(tebra=soap), "tebra", "fhir") is None
    assert select_runtime(EhrReadRuntimes(tebra_fhir=h.port), "tebra") is None
    for kwargs in ({"tebra": h.port}, {"tebra_fhir": soap}):
        with pytest.raises(ValueError, match="explicit_ehr_runtimes_required"):
            EhrReadRuntimes(**kwargs)
    assert h.calls == []


def test_candidates_are_exact_authorized_contexts_without_provider_calls():
    h = Harness()
    assert h.port.patient_candidates(CONNECTION, GRANT.workspace_id, GRANT.patient_link_id,
        authorize=lambda: True) == (GRANT,)
    for workspace, patient_link in [(UUID(int=999), GRANT.patient_link_id),
                                  (GRANT.workspace_id, UUID(int=999))]:
        assert h.port.patient_candidates(CONNECTION, workspace, patient_link, authorize=lambda: True) == ()
    with pytest.raises(TebraFhirReadError, match="access_denied"):
        h.port.patient_candidates(CONNECTION, GRANT.workspace_id, GRANT.patient_link_id, authorize=lambda: False)
    h.enabled = False
    with pytest.raises(TebraFhirReadError, match="access_denied"):
        h.port.patient_candidates(CONNECTION, GRANT.workspace_id, GRANT.patient_link_id, authorize=lambda: True)
    assert h.calls == []


@pytest.mark.parametrize("field", ["box_id", "owner_id", "account_id", "connection_id", "credential_generation"])
def test_recomputed_connection_hash_does_not_authorize_another_owner_or_generation(field):
    h = Harness()
    changed = replace(CONNECTION, **{field: UUID(int=999)})
    assert changed.commitment() != CONNECTION.commitment()
    with pytest.raises(TebraFhirReadError, match="access_denied"):
        h.read(changed, replace(GRANT, connection_scope=changed))
    assert h.calls == []


@pytest.mark.parametrize("field,value", [("grant_id", UUID(int=999)), ("workspace_id", UUID(int=999)),
    ("patient_link_id", UUID(int=999)), ("fhir_patient_id", "another-patient"),
    ("authorization_sha256", "b"*64), ("identity_sha256", "b"*64)])
def test_unregistered_client_reconstructed_grant_never_authorizes_a_read(field, value):
    h = Harness()
    with pytest.raises(TebraFhirReadError, match="access_denied"):
        h.read(grant=replace(GRANT, **{field: value}))
    assert h.calls == []


def test_fresh_patient_verified_before_medications_and_complete_source_prepared():
    h = Harness()
    result = h.read()
    assert [str(call.url) for call in h.calls] == [FHIR_BASE+"/Patient/fhir-patient-A", SELF]
    assert all(call.method == "GET" and "cookie" not in call.headers for call in h.calls)
    assert result.observation.scope == GRANT.read_scope()
    assert result.patient_birth_date.value == "1980" and result.patient_birth_date.state == "recorded"
    row = result.records[0].record
    assert (row.status, row.intent, row.authored_on, row.do_not_perform) == ("stopped", "plan", "2025-01", True)
    assert row.dosage_instructions_json is not None and row.reported_json is not None
    assert json.loads(row.dosage_instructions_json) == h.row["dosageInstruction"]
    assert json.loads(row.reported_json) == {"reportedBoolean": True}
    assert json.loads(row.context_json)["note"] == h.row["note"]
    assert "not a reconciled current list" in result.source_content
    assert "synthetic-tebra-fhir-token" not in result.source_content
    assert GRANT.authorization_sha256 not in result.source_content
    assert "Alex" not in repr(result) and "Alex" not in repr(GRANT)


def test_same_patient_id_with_changed_identity_stops_before_clinical_request():
    h = Harness()
    h.patient["birthDate"] = "1981"
    with pytest.raises(TebraFhirReadError, match="patient_changed"):
        h.read()
    assert len(h.calls) == 1


@pytest.mark.parametrize("target", ["enabled", "authorized"])
def test_authority_loss_during_patient_response_prevents_medication_request(target):
    h = Harness()
    h.after = lambda: setattr(h, target, False)
    with pytest.raises(TebraFhirReadError, match="access_denied"):
        h.read()
    assert len(h.calls) == 1


def test_formatter_refuses_entire_oversized_history_instead_of_shortening_instructions():
    h = Harness()
    h.row["dosageInstruction"] = [{"text": "x"*3800}]
    with pytest.raises(TebraFhirSnapshotError, match="snapshot_too_large"):
        h.read()
    assert len(h.calls) == 2


def test_constructor_rejects_real_transport_and_unknown_transport_subclasses():
    h = Harness()

    class OtherTransport(httpx.MockTransport):
        pass

    for transport in (httpx.HTTPTransport(), OtherTransport(h.send)):
        try:
            with pytest.raises(ValueError, match="explicit_synthetic_tebra_fhir_installation_required"):
                SyntheticTebraFhirReads((CONNECTION,), (GRANT,), cast(httpx.MockTransport, transport), enabled=lambda: True)
        finally:
            transport.close()
    assert h.calls == []


@pytest.mark.parametrize("patient", [
    replace(GRANT, identity_json=json.dumps(PATIENT)),
    replace(GRANT, identity_sha256="b"*64),
    replace(GRANT, fhir_patient_id="different-patient"),
    replace(GRANT, identity_json=canonical_json(PATIENT | {"implicitRules": "https://invented.invalid/rule"})),
])
def test_grant_setup_requires_exact_canonical_qualified_patient_identity(patient):
    with pytest.raises(ValueError, match="explicit_synthetic_tebra_fhir_installation_required"):
        SyntheticTebraFhirReads((CONNECTION,), (patient,), httpx.MockTransport(lambda _: httpx.Response(500)), enabled=lambda: True)


def test_empty_authorized_roster_is_allowed_but_duplicate_or_oversized_roster_is_refused():
    h = Harness()
    empty = SyntheticTebraFhirReads((CONNECTION,), (), h.transport, enabled=lambda: True)
    assert empty.patient_candidates(CONNECTION, GRANT.workspace_id, GRANT.patient_link_id, authorize=lambda: True) == ()
    with pytest.raises(ValueError, match="explicit_synthetic_tebra_fhir_installation_required"):
        SyntheticTebraFhirReads((CONNECTION,), (GRANT, replace(GRANT, grant_id=UUID(int=99))), h.transport, enabled=lambda: True)
    rows = []
    for i in range(26):
        identity = PATIENT | {"id": f"patient-{i}"}
        rows.append(replace(GRANT, grant_id=UUID(int=100+i), fhir_patient_id=identity["id"],
            identity_json=canonical_json(identity), identity_sha256=payload_hash(identity)))
    with pytest.raises(ValueError, match="explicit_synthetic_tebra_fhir_installation_required"):
        SyntheticTebraFhirReads((CONNECTION,), tuple(rows), h.transport, enabled=lambda: True)
