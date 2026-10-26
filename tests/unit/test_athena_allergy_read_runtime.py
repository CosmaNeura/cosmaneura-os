"""Independent clinical grants, exact department reads and closed synthetic dispatch."""

import json
from copy import deepcopy
from dataclasses import replace
from typing import cast
from uuid import UUID

import httpx
import pytest
from tests.unit.test_athena_allergy_read import PATIENT, SECTION

from cosmas_os.adapters.athena_allergy_read import AthenaAllergyError
from cosmas_os.adapters.athena_allergy_read_runtime import (
    AthenaAllergyConnectionScope,
    AthenaAuthorizedPatient,
    SyntheticAthenaAllergyReads,
)
from cosmas_os.adapters.ehr_read_runtime import (
    EhrReadRuntimes,
    runtime_protocol,
    runtime_provider,
    select_runtime,
)
from cosmas_os.domain.hashing import canonical_json, payload_hash

CONNECTION = AthenaAllergyConnectionScope(UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4),
    UUID(int=5), "901", "Invented Athena Clinical")
GRANT = AthenaAuthorizedPatient(UUID(int=6), CONNECTION, UUID(int=7), UUID(int=8), "902", "Invented chart department",
    "903", "a"*64, canonical_json(PATIENT), payload_hash(PATIENT))


class Harness:
    def __init__(self):
        self.enabled, self.authorized = True, True
        self.patient, self.section = deepcopy(PATIENT), deepcopy(SECTION)
        self.calls = []
        self.after = lambda: None
        self.transport = httpx.MockTransport(self.send)
        self.port = SyntheticAthenaAllergyReads((CONNECTION,), (GRANT,), self.transport, enabled=lambda: self.enabled)

    def send(self, request):
        self.calls.append(request)
        self.after()
        if request.url.path == "/v1/901/patients/903":
            body = [self.patient]
        else:
            assert request.url.path == "/v1/901/chart/903/allergies"
            body = self.section
        return httpx.Response(200, headers={"Content-Type": "application/json"}, stream=httpx.ByteStream(json.dumps(body).encode()))

    def read(self, scope=CONNECTION, grant=GRANT):
        return self.port.allergies(scope, grant, authorize=lambda: self.authorized)


def test_explicit_core_dispatch_is_required_and_no_other_provider_can_select_it():
    h = Harness()
    ports = EhrReadRuntimes(athena_core=h.port)
    assert runtime_provider(h.port) == "athena" and runtime_protocol(h.port) == "core"
    assert select_runtime(ports, "athena", "core") is h.port
    assert select_runtime(h.port, "athena", "core") is h.port
    for provider, protocol in [("athena", None), ("athena", "fhir"), ("tebra", "core"), ("elation", "core")]:
        assert select_runtime(ports, provider, protocol) is None
        assert select_runtime(h.port, provider, protocol) is None
    for key in ("tebra", "tebra_fhir", "elation"):
        with pytest.raises(ValueError, match="explicit_ehr_runtimes_required"):
            EhrReadRuntimes(**{key: h.port})
    assert h.calls == []


def test_candidates_are_only_server_owned_contexts_without_roster_search():
    h = Harness()
    assert h.port.patient_candidates(CONNECTION, GRANT.workspace_id, GRANT.patient_link_id, authorize=lambda: True) == (GRANT,)
    for workspace, link in [(UUID(int=999), GRANT.patient_link_id), (GRANT.workspace_id, UUID(int=999))]:
        assert h.port.patient_candidates(CONNECTION, workspace, link, authorize=lambda: True) == ()
    with pytest.raises(AthenaAllergyError, match="access_denied"):
        h.port.patient_candidates(CONNECTION, GRANT.workspace_id, GRANT.patient_link_id, authorize=lambda: False)
    h.enabled = False
    with pytest.raises(AthenaAllergyError, match="access_denied"):
        h.port.patient_candidates(CONNECTION, GRANT.workspace_id, GRANT.patient_link_id, authorize=lambda: True)
    assert h.calls == []


@pytest.mark.parametrize("field,value", [("box_id", UUID(int=999)), ("owner_id", UUID(int=999)),
    ("account_id", UUID(int=999)), ("connection_id", UUID(int=999)), ("credential_generation", UUID(int=999)),
    ("practice_id", "999"), ("environment", "production")])
def test_rehashed_connection_cannot_authorize_another_owner_practice_or_environment(field, value):
    h = Harness()
    changed = replace(CONNECTION, **{field: value})
    assert changed.commitment() != CONNECTION.commitment()
    with pytest.raises(AthenaAllergyError, match="access_denied"):
        h.read(changed, replace(GRANT, connection_scope=changed))
    assert h.calls == []


@pytest.mark.parametrize("field,value", [("grant_id", UUID(int=999)), ("workspace_id", UUID(int=999)),
    ("patient_link_id", UUID(int=999)), ("department_id", "999"), ("patient_id", "999"),
    ("authorization_sha256", "b"*64), ("identity_sha256", "b"*64)])
def test_unregistered_grant_cannot_substitute_patient_department_or_authorization(field, value):
    h = Harness()
    with pytest.raises(AthenaAllergyError, match="access_denied"):
        h.read(grant=replace(GRANT, **{field: value}))
    assert h.calls == []


def test_fresh_identity_then_exact_authorized_chart_department_preserves_complete_section():
    h = Harness()
    result = h.read()
    assert [str(request.url) for request in h.calls] == [
        "https://api.preview.platform.athenahealth.com/v1/901/patients/903?departmentid=902",
        "https://api.preview.platform.athenahealth.com/v1/901/chart/903/allergies?departmentid=902&showinactive=true"]
    # Recorded registration department 999 never substitutes for authorized chart department 902.
    assert json.loads(result.observation.patient.identity_json)["departmentid"] == "999"
    assert result.observation.scope.department_id == "902"
    assert json.loads(result.observation.section_json) == SECTION
    assert "123456789012345678" in result.source_content
    assert "No known drug allergies statement: Explicitly false" in result.source_content
    assert result.observation.section_json in result.source_content
    assert "patientid" not in result.source_content and GRANT.authorization_sha256 not in result.source_content
    assert "Alex" not in repr(result) and "Alex" not in repr(GRANT)


def test_changed_patient_identity_stops_before_any_clinical_request():
    h = Harness()
    h.patient["dob"] = "01/02/1981"
    with pytest.raises(AthenaAllergyError, match="patient_changed"):
        h.read()
    assert len(h.calls) == 1


@pytest.mark.parametrize("target", ["enabled", "authorized"])
def test_authority_loss_during_patient_response_prevents_allergy_request(target):
    h = Harness()
    h.after = lambda: setattr(h, target, False)
    with pytest.raises(AthenaAllergyError, match="disabled" if target == "enabled" else "access_denied"):
        h.read()
    assert len(h.calls) == 1


def test_formatter_refuses_entire_oversized_section_without_shortening_original_notes():
    h = Harness()
    h.section["sectionnote"] = "x"*4000
    with pytest.raises(AthenaAllergyError, match="source_too_large"):
        h.read()
    assert len(h.calls) == 2


def test_constructor_requires_exact_mock_transport():
    h = Harness()
    class OtherTransport(httpx.MockTransport):
        pass
    for transport in (httpx.HTTPTransport(), OtherTransport(h.send)):
        try:
            with pytest.raises(ValueError, match="explicit_synthetic_athena_allergy_installation_required"):
                SyntheticAthenaAllergyReads((CONNECTION,), (GRANT,), cast(httpx.MockTransport, transport), enabled=lambda: True)
        finally:
            transport.close()
    assert h.calls == []


@pytest.mark.parametrize("patient", [replace(GRANT, identity_json=json.dumps(PATIENT)),
    replace(GRANT, identity_sha256="b"*64), replace(GRANT, patient_id="999"),
    replace(GRANT, identity_json=canonical_json(PATIENT | {"unqualified": "not identity"}))])
def test_grant_requires_exact_canonical_qualified_identity(patient):
    with pytest.raises(ValueError, match="explicit_synthetic_athena_allergy_installation_required"):
        SyntheticAthenaAllergyReads((CONNECTION,), (patient,), httpx.MockTransport(lambda _: httpx.Response(500)), enabled=lambda: True)


def test_empty_roster_and_distinct_authorized_departments_are_explicit_but_duplicates_are_refused():
    h = Harness()
    empty = SyntheticAthenaAllergyReads((CONNECTION,), (), h.transport, enabled=lambda: True)
    assert empty.patient_candidates(CONNECTION, GRANT.workspace_id, GRANT.patient_link_id, authorize=lambda: True) == ()
    another = replace(GRANT, grant_id=UUID(int=99), department_id="999", department_label="Other authorized chart department")
    distinct = SyntheticAthenaAllergyReads((CONNECTION,), (GRANT, another), h.transport, enabled=lambda: True)
    assert distinct.patient_candidates(CONNECTION, GRANT.workspace_id, GRANT.patient_link_id, authorize=lambda: True) == (GRANT, another)
    for rows in [(GRANT, replace(GRANT, grant_id=UUID(int=99))),
                 tuple(replace(GRANT, grant_id=UUID(int=100+i), department_id=str(100+i)) for i in range(26))]:
        with pytest.raises(ValueError, match="explicit_synthetic_athena_allergy_installation_required"):
            SyntheticAthenaAllergyReads((CONNECTION,), rows, h.transport, enabled=lambda: True)
