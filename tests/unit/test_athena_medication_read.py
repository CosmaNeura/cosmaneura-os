"""Lossless recorded-medication boundaries using invented MockTransport only."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from typing import cast
from uuid import UUID

import httpx
import pytest

from cosmas_os.adapters.athena_medication_read import (
    ORIGINS,
    AthenaMedicationError,
    AthenaMedicationReader,
    AthenaMedicationScope,
    clinical_dumps,
    clinical_loads,
    medication_records,
    patient_identity,
)

SCOPE = AthenaMedicationScope(
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
RAW_SECTION = '{"sectionnote":"Invented notes: café 🧪\\r\\nNo clinical instruction is inferred.","nomedicationsreported":true,"medications":[[{"medicationentryid":"C-invented-one","medication":"Invented tablet","quantity":0.50,"status":"PEND","unstructuredsig":"Invented instruction line\\nKeep wording as recorded.","structuredsig":{"tiny":1e-7,"signedzero":-0,"minimum":-9223372036854775808,"maximum":9223372036854775807,"opaque":{"😀":1E+3,"\ue000":0.500}},"events":[{"type":"ORDER","eventdate":"10/26/2026","userdisplayname":null}]}],[],[{"medicationentryid":"C-invented-one","medication":"Invented repeated record","quantity":0.50}]]}'
EXPECTED_SECTION = '{"medications":[[{"events":[{"eventdate":"10/26/2026","type":"ORDER","userdisplayname":null}],"medication":"Invented tablet","medicationentryid":"C-invented-one","quantity":0.50,"status":"PEND","structuredsig":{"maximum":9223372036854775807,"minimum":-9223372036854775808,"opaque":{"\\ue000":0.500,"\\ud83d\\ude00":1E+3},"signedzero":-0,"tiny":1e-7},"unstructuredsig":"Invented instruction line\\nKeep wording as recorded."}],[],[{"medication":"Invented repeated record","medicationentryid":"C-invented-one","quantity":0.50}]],"nomedicationsreported":true,"sectionnote":"Invented notes: caf\\u00e9 \\ud83e\\uddea\\r\\nNo clinical instruction is inferred."}'


class Harness:
    def __init__(self):
        self.patient, self.section = deepcopy(PATIENT), clinical_loads(RAW_SECTION)
        self.enabled, self.authorized = True, True
        self.calls = []
        self.status = 200
        self.after = lambda: None
        self.raw: bytes | None = None
        self.identity_raw: bytes | None = None
        self.encoding, self.content_type = "identity", "application/json"
        self.transport = httpx.MockTransport(self.send)

    def send(self, request):
        self.calls.append(request)
        self.after()
        assert (
            request.url.host == "api.preview.platform.athenahealth.com" and request.method == "GET"
        )
        if request.url.path.endswith("/patients/903"):
            raw = (
                self.identity_raw
                if self.identity_raw is not None
                else json.dumps([self.patient]).encode()
            )
        else:
            raw = self.raw if self.raw is not None else clinical_dumps(self.section).encode()
        return httpx.Response(
            self.status,
            stream=httpx.ByteStream(raw),
            headers={
                "Content-Type": self.content_type,
                "Content-Encoding": self.encoding,
                "Location": "https://unrelated.example.invalid/not-followed",
            },
        )

    def reader(self, scope=SCOPE):
        return AthenaMedicationReader(
            scope,
            self.transport,
            expected_identity_sha256=patient_identity([PATIENT], scope).identity_sha256,
            enabled=lambda: self.enabled,
            authorize=lambda _: self.authorized,
        )

    def read(self):
        return self.reader().read()


def test_exact_independent_chart_request_and_complete_token_preserving_groups():
    h = Harness()
    observed = h.read()
    assert [str(r.url) for r in h.calls] == [
        ORIGINS["preview"] + "/v1/901/patients/903?departmentid=902",
        ORIGINS["preview"]
        + "/v1/901/chart/903/medications?departmentid=902&medicationtype=ACTIVE&showpend=true&showndc=true&showrxnorm=true",
    ]
    assert observed.section_json == EXPECTED_SECTION
    assert observed.provider_sources[1] == hashlib.sha256(EXPECTED_SECTION.encode()).hexdigest()
    assert [len(group) for group in observed.groups] == [1, 0, 1]
    assert observed.groups[0][0].medication_entry_id == observed.groups[2][0].medication_entry_id
    assert observed.groups[0][0].medication_name == "Invented tablet"
    assert all(
        r.headers["Authorization"] == "Bearer invented-athena-clinical-token" for r in h.calls
    )
    assert observed.coverage == "returned_section_only" and observed.medication_type == "ACTIVE"
    assert observed.includes_pending and observed.includes_ndc and observed.includes_rxnorm
    # Registration department is not the independent authorized chart department.
    assert json.loads(observed.patient.identity_json)["departmentid"] == "999"
    assert observed.scope.department_id == "902"


def test_opaque_objects_cannot_spoof_numbers_and_unicode_sort_is_by_codepoint():
    raw = r'{"structuredsig":{"kind":"number","raw":"0.50","token":"1e-7","__proto__":{"x":true},"controls":"\u0001\b\f\n\r\t","\ud83d\ude00":1E+3,"\ue000":0.500,"numeric_string":"-0"},"quantity":-0}'
    encoded = clinical_dumps(clinical_loads(raw))
    assert (
        encoded
        == r'{"quantity":-0,"structuredsig":{"__proto__":{"x":true},"controls":"\u0001\b\f\n\r\t","kind":"number","numeric_string":"-0","raw":"0.50","token":"1e-7","\ue000":0.500,"\ud83d\ude00":1E+3}}'
    )
    assert clinical_loads(encoded)["quantity"].token == "-0"
    with pytest.raises(AthenaMedicationError):
        clinical_dumps({"quantity": 0.5})


@pytest.mark.parametrize(
    "key,value",
    [("patientid", "904"), ("lastname", "Other"), ("dob", "02/03/1980"), ("departmentid", "998")],
)
def test_fresh_patient_drift_stops_before_medication_request(key, value):
    h = Harness()
    h.patient[key] = value
    with pytest.raises(AthenaMedicationError, match="patient_changed"):
        h.read()
    assert len(h.calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("medication_type", "HISTORICAL"),
        ("medication_type", "DENIED"),
        ("includes_pending", False),
        ("includes_ndc", False),
        ("includes_rxnorm", False),
    ],
)
def test_unqualified_query_profiles_never_become_authority(field, value):
    with pytest.raises(AthenaMedicationError, match="invalid_scope"):
        replace(SCOPE, **{field: value})


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"a":1,"\\u0061":2}',
        b'{"x":{"a":1,"a":2}}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":01}',
        b'{"x":1.}',
        b'{"x":+1}',
        b'{"x":"\\ud800"}',
        b'{"x":"\\udc00"}',
        b'{"x":"\\u0000"}',
        b'{"\\u0000":1}',
        b'{"x":"\x01"}',
        b"{} trailing",
        b"\xff",
        b"\xff\xfe{\x00}\x00",
        b" " * 65537,
        b"[" * 4000 + b"0" + b"]" * 4000,
    ],
)
def test_malformed_duplicate_unicode_and_deep_json_refuse_without_uncaught_parser_errors(raw):
    with pytest.raises(AthenaMedicationError):
        clinical_loads(raw)


def test_exact_generic_codec_bounds_without_expanding_numeric_exponents():
    assert clinical_dumps(clinical_loads("1e" + "9" * 126)) == "1e" + "9" * 126
    with pytest.raises(AthenaMedicationError):
        clinical_loads("1e" + "9" * 127)
    assert clinical_loads("[" * 16 + "0" + "]" * 16)
    with pytest.raises(AthenaMedicationError):
        clinical_loads("[" * 17 + "0" + "]" * 17)
    for value in [[None] * 256, {str(i): None for i in range(64)}, {"k" * 128: "s" * 4096}]:
        assert clinical_loads(clinical_dumps(value)) == value
    for value in [
        [None] * 257,
        {str(i): None for i in range(65)},
        {"k" * 129: None},
        {"x": "s" * 4097},
    ]:
        with pytest.raises(AthenaMedicationError):
            clinical_dumps(value)
    exactly = [[None] * 255 for _ in range(15)] + [[None] * 254]
    assert clinical_loads(clinical_dumps(exactly)) == exactly  # 4096 JSON values
    exactly[-1].append(None)
    with pytest.raises(AthenaMedicationError):
        clinical_dumps(exactly)


@pytest.mark.parametrize("token", ["-9223372036854775808", "9223372036854775807", "-0"])
def test_known_integer_fields_keep_exact_signed_int64_token(token):
    section = clinical_loads('{"medications":[[{"medicationid":' + token + "}]]}")
    assert medication_records(section)[0][0].original_json == '{"medicationid":' + token + "}"


@pytest.mark.parametrize(
    "token", ["-9223372036854775809", "9223372036854775808", "1.0", "1e0", "true", "null"]
)
def test_known_integer_fields_refuse_widening_or_numeric_coercion(token):
    with pytest.raises(AthenaMedicationError):
        medication_records(clinical_loads('{"medications":[[{"refillsallowed":' + token + "}]]}"))


@pytest.mark.parametrize(
    "change",
    [
        "unknown_section",
        "missing_groups",
        "flat_list",
        "null_no_meds",
        "string_no_meds",
        "unknown_record",
        "null_name",
        "null_quantity",
        "null_status",
        "null_structured",
        "unknown_event",
        "null_event_type",
        "unknown_ndc",
        "unknown_rxnorm",
        "too_many_groups",
        "too_many_records",
        "entry_id_too_long",
    ],
)
def test_unqualified_or_oversized_clinical_shape_refuses_entire_read(change):
    h = Harness()
    row = h.section["medications"][0][0]
    if change == "unknown_section":
        h.section["securitylabels"] = ["NOAUTH"]
    elif change == "missing_groups":
        h.section.pop("medications")
    elif change == "flat_list":
        h.section["medications"] = [row]
    elif change == "null_no_meds":
        h.section["nomedicationsreported"] = None
    elif change == "string_no_meds":
        h.section["nomedicationsreported"] = "false"
    elif change == "unknown_record":
        row["modifier"] = "unqualified"
    elif change == "null_name":
        row["medication"] = None
    elif change == "null_quantity":
        row["quantity"] = None
    elif change == "null_status":
        row["status"] = None
    elif change == "null_structured":
        row["structuredsig"] = None
    elif change == "unknown_event":
        row["events"][0]["modifier"] = "unqualified"
    elif change == "null_event_type":
        row["events"][0]["type"] = None
    elif change == "unknown_ndc":
        row["ndcoptions"] = [{"other": "unqualified"}]
    elif change == "unknown_rxnorm":
        row["rxnorm"] = [{"other": "unqualified"}]
    elif change == "too_many_groups":
        h.section["medications"] = [[] for _ in range(26)]
    elif change == "too_many_records":
        h.section["medications"] = [[{}] * 13, [{}] * 13]
    else:
        row["medicationentryid"] = "C" * 301
    with pytest.raises(AthenaMedicationError):
        h.read()
    assert len(h.calls) == 2


def test_empty_and_blank_records_are_preserved_without_fabricated_names_or_ids():
    section = clinical_loads('{"medications":[[],[{}, {"medication":"","medicationentryid":""}]]}')
    groups = medication_records(section)
    assert groups[0] == () and len(groups[1]) == 2
    assert groups[1][0].medication_name is None and groups[1][0].medication_entry_id is None
    assert groups[1][1].medication_name == "" and groups[1][1].medication_entry_id == ""


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
def test_provider_failure_never_retries_follows_or_exposes_response_body(status, code):
    h = Harness()
    h.status = status
    with pytest.raises(AthenaMedicationError, match=code) as error:
        h.read()
    assert str(error.value) == code and len(h.calls) == 1


@pytest.mark.parametrize("where", ["before", "after_patient", "after_section", "disabled"])
def test_independent_authority_is_checked_before_and_after_each_read(where):
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
    with pytest.raises(AthenaMedicationError, match="access_denied|disabled"):
        h.read()
    assert (
        len(h.calls) == {"before": 0, "disabled": 0, "after_patient": 1, "after_section": 2}[where]
    )


def test_mock_only_transport_and_encoded_or_oversized_provider_payload_refuse():
    h = Harness()
    with httpx.HTTPTransport() as live:
        with pytest.raises(AthenaMedicationError, match="synthetic_transport_required"):
            AthenaMedicationReader(
                SCOPE,
                cast(httpx.MockTransport, live),
                expected_identity_sha256="a" * 64,
                enabled=lambda: True,
                authorize=lambda _: True,
            )
    h.encoding = "gzip"
    with pytest.raises(AthenaMedicationError, match="response_invalid"):
        h.read()
    h = Harness()
    h.raw = b" " * 65537
    with pytest.raises(AthenaMedicationError, match="response_too_large"):
        h.read()
    assert len(h.calls) == 2
