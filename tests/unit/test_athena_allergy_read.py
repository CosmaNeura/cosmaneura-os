"""Meaningful athenaOne allergy boundaries, with no live transport or credentials."""

import json
from copy import deepcopy
from dataclasses import replace
from typing import cast
from uuid import UUID

import httpx
import pytest

from cosmas_os.adapters.athena_allergy_read import (
    ORIGINS,
    AthenaAllergyError,
    AthenaAllergyReader,
    AthenaAllergyScope,
    patient_identity,
)

SCOPE = AthenaAllergyScope(
    box_id=UUID(int=1),
    owner_id=UUID(int=2),
    account_id=UUID(int=3),
    connection_id=UUID(int=4),
    credential_generation=UUID(int=5),
    workspace_id=UUID(int=6),
    patient_link_id=UUID(int=7),
    practice_id="901",
    department_id="902",
    patient_id="903",
    practice_label="Invented Clinic",
    department_label="Invented chart department",
    authorization_sha256="a" * 64,
)
PATIENT = {
    "patientid": "903",
    "firstname": "Alex",
    "lastname": "Éxample",
    "dob": "01/02/1980",
    "departmentid": "999",
}
SECTION = {
    "nkda": False,
    "sectionnote": "Original section\nqualifier",
    "lastmodifieddatetime": "10/20/2026 13:14:15",
    "allergies": [
        {
            "id": "9012",
            "allergenid": 442,
            "allergenname": "Invented allergen",
            "criticality": "recorded criticality",
            "categories": ["food", "medication"],
            "onsetdate": "2024",
            "deactivatedate": "10/01/2026",
            "note": "Première ligne\r\n\tOriginal second line",
            "reactions": [
                {
                    "reactionname": "Invented reaction",
                    "severity": "recorded severity",
                    "severitysnomedcode": 255604002,
                    "snomedcode": 123456789012345678,
                }
            ],
        }
    ],
}


class Harness:
    def __init__(self):
        self.patient, self.section = deepcopy(PATIENT), deepcopy(SECTION)
        self.enabled, self.authorized = True, True
        self.calls = []
        self.status = 200
        self.after = lambda: None
        self.raw: bytes | None = None
        self.encoding = "identity"
        self.content_type = "application/json"
        self.transport = httpx.MockTransport(self.send)

    def send(self, request):
        self.calls.append(request)
        self.after()
        assert (
            request.url.host == "api.preview.platform.athenahealth.com" and request.method == "GET"
        )
        data = [self.patient] if request.url.path.endswith("/patients/903") else self.section
        raw = self.raw if self.raw is not None else json.dumps(data).encode()
        return httpx.Response(
            self.status,
            stream=httpx.ByteStream(raw),
            headers={
                "Content-Type": self.content_type,
                "Content-Encoding": self.encoding,
                "Location": "https://unrelated.example.invalid/steal",
            },
        )

    def reader(self, scope=SCOPE):
        return AthenaAllergyReader(
            scope,
            self.transport,
            expected_identity_sha256=patient_identity([PATIENT], scope).identity_sha256,
            enabled=lambda: self.enabled,
            authorize=lambda _: self.authorized,
        )

    def read(self):
        return self.reader().read()


def test_exact_patient_and_chart_requests_preserve_original_values():
    h = Harness()
    value = h.read()
    assert [str(r.url) for r in h.calls] == [
        ORIGINS["preview"] + "/v1/901/patients/903?departmentid=902",
        ORIGINS["preview"] + "/v1/901/chart/903/allergies?departmentid=902&showinactive=true",
    ]
    assert json.loads(value.section_json) == SECTION
    assert json.loads(value.records[0].original_json) == SECTION["allergies"][0]
    assert value.includes_inactive is True and value.coverage == "returned_section_only"
    assert (
        len(value.provider_sources) == 2
        and "Éxample" in json.loads(value.patient.identity_json)["lastname"]
    )
    assert all(
        r.headers["Authorization"] == "Bearer invented-athena-clinical-token" for r in h.calls
    )


@pytest.mark.parametrize("change", ["patient_id", "name", "birth_date", "registration_department"])
def test_patient_identity_drift_stops_before_clinical_read(change):
    h = Harness()
    key = {
        "patient_id": "patientid",
        "name": "lastname",
        "birth_date": "dob",
        "registration_department": "departmentid",
    }[change]
    h.patient[key] = {
        "patientid": "904",
        "lastname": "Other",
        "dob": "02/03/1980",
        "departmentid": "998",
    }[key]
    with pytest.raises(AthenaAllergyError, match="patient_changed"):
        h.read()
    assert len(h.calls) == 1


@pytest.mark.parametrize(
    "field",
    [
        "practice_id",
        "department_id",
        "patient_id",
        "authorization_sha256",
        "credential_generation",
        "account_id",
        "patient_link_id",
    ],
)
def test_each_authority_dimension_changes_scope_commitment(field):
    value = (
        "904"
        if field.endswith("_id") and field in ("practice_id", "department_id", "patient_id")
        else "b" * 64
        if field == "authorization_sha256"
        else UUID(int=90)
    )
    assert replace(SCOPE, **{field: value}).commitment() != SCOPE.commitment()


@pytest.mark.parametrize(
    "change", ["duplicate", "nested_duplicate", "too_large", "nan", "surrogate"]
)
def test_untrusted_json_fails_closed_without_clinical_read(change):
    h = Harness()
    h.raw = {
        "duplicate": b'[{"patientid":"903","patientid":"904"}]',
        "nested_duplicate": b'[{"x":{"a":1,"a":2}}]',
        "too_large": b" " * 65537,
        "nan": b'[{"x":NaN}]',
        "surrogate": b'[{"x":"\\ud800"}]',
    }[change]
    with pytest.raises(AthenaAllergyError):
        h.read()
    assert len(h.calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        "unknown",
        "null_nkda",
        "string_nkda",
        "missing_list",
        "too_many",
        "duplicate_id",
        "reaction_type",
        "code_bool",
        "unknown_reaction",
    ],
)
def test_malformed_or_unqualified_clinical_meaning_refuses_entire_section(change):
    h = Harness()
    if change == "unknown":
        h.section["securitylabels"] = ["NOAUTH"]
    elif change == "null_nkda":
        h.section["nkda"] = None
    elif change == "string_nkda":
        h.section["nkda"] = "false"
    elif change == "missing_list":
        h.section.pop("allergies")
    elif change == "too_many":
        h.section["allergies"] *= 26
    elif change == "duplicate_id":
        h.section["allergies"] *= 2
    elif change == "reaction_type":
        h.section["allergies"][0]["reactions"] = {}
    elif change == "code_bool":
        h.section["allergies"][0]["reactions"][0]["snomedcode"] = True
    else:
        h.section["allergies"][0]["reactions"][0]["modifier"] = "unsupported"
    with pytest.raises(AthenaAllergyError):
        h.read()
    assert len(h.calls) == 2


@pytest.mark.parametrize(
    "status,code",
    [
        (302, "provider_unavailable"),
        (401, "access_denied"),
        (403, "access_denied"),
        (429, "rate_limited"),
        (500, "provider_unavailable"),
    ],
)
def test_status_failures_do_not_retry_follow_or_expose_body(status, code):
    h = Harness()
    h.status = status
    with pytest.raises(AthenaAllergyError, match=code) as error:
        h.read()
    assert str(error.value) == code and len(h.calls) == 1


@pytest.mark.parametrize("where", ["before", "after_patient", "after_section", "disabled"])
def test_authority_is_rechecked_before_and_after_provider_io(where):
    h = Harness()
    if where == "before":
        h.authorized = False
    elif where == "disabled":
        h.enabled = False
    else:

        def after():
            if len(h.calls) == (1 if where == "after_patient" else 2):
                h.authorized = False

        h.after = after
    with pytest.raises(AthenaAllergyError, match="disabled|access_denied"):
        h.read()
    assert (
        len(h.calls) == {"before": 0, "disabled": 0, "after_patient": 1, "after_section": 2}[where]
    )


def test_live_transport_and_compressed_response_are_refused():
    h = Harness()
    with httpx.HTTPTransport() as live_transport:
        with pytest.raises(AthenaAllergyError, match="synthetic_transport_required"):
            AthenaAllergyReader(
                SCOPE,
                cast(httpx.MockTransport, live_transport),
                expected_identity_sha256="a" * 64,
                enabled=lambda: True,
                authorize=lambda _: True,
            )
    h.encoding = "gzip"
    with pytest.raises(AthenaAllergyError, match="response_invalid"):
        h.read()
