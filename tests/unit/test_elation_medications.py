"""Invented medication-record reads; no vendor calls, prescribing or reconciliation."""

import asyncio
import copy
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import cast
from urllib.parse import parse_qs
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from cosmas_os.adapters.elation_read import (
    MAX_BODY,
    MAX_ID,
    MEDICATION_SCOPES,
    ORIGIN,
    PROBLEM_SCOPES,
    SCOPES,
    ElationAppointment,
    ElationCredentials,
    ElationMedication,
    ElationPatient,
    ElationReadAdapter,
    ElationReadError,
    ElationReadScope,
)
from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads
from cosmas_os.adapters.elation_sandbox_runtime import (
    ElationSandboxInstallation,
    ManagedElationSandboxReads,
)

SCOPE = ElationReadScope(UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4),
    910, "Invented Elation Sandbox")
NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
PATH = "/api/2.0/medications/"
MEDICATION = {"id": 955, "patient": 930, "practice": 910,
    "medication": {"name": "Invented medication Alpha", "strength": "10 mg", "route": "Oral",
        "form": "Tablet", "practice": None, "rxnorm_cuis": ["unused-code"]},
    "directions": "Invented directions: one tablet with food.\nConfirm with the clinician.",
    "medication_type": "prescription", "order_type": "New", "is_doc_med": True,
    "thread": {"id": 956, "dc_date": None, "is_permanent": False},
    "start_date": "2026-01-02", "document_date": "2026-01-02T12:00:00Z",
    "signed_date": "2026-01-02T12:00:00Z", "deleted_date": None,
    "fulfillment": {"state": "complete", "pharmacy_ncpdpid": "unused-pharmacy"},
    "qty": "unused-quantity", "auth_refills": "unused-refills", "notes": "unused-notes"}
PATIENT = {"id": 930, "caregiver_practice": 910, "first_name": "Alex", "last_name": "Example",
    "dob": "1980-01-02", "primary_physician": 920, "deleted_date": None}
APPOINTMENT = {"id": 940, "practice": 910, "patient": 930, "physician": 920,
    "time_slot_type": "appointment", "scheduled_date": "2026-10-25T11:00:00Z", "duration": 20,
    "status": {"status": "Confirmed"}, "deleted_date": None}
TOKEN = {"access_token": "synthetic-token", "token_type": "Bearer", "expires_in": 3600,
    "scope": MEDICATION_SCOPES}


def response(value):
    # Exercise parser rejection of escaped Unicode surrogates, not an encoder error.
    return httpx.Response(200, content=json.dumps(value, ensure_ascii=True).encode(),
        headers={"content-type": "application/json"})


class Harness:
    def __init__(self, payload=None, *, enabled=True, medications_enabled=True,
            problems_enabled=False, token=None, handler=None):
        self.payload = {"results": [copy.deepcopy(MEDICATION)], "next": None} if payload is None else payload
        self.token = TOKEN if token is None else token
        self.handler = handler
        self.calls: list[httpx.Request] = []
        self.allowed = True
        self.clock = 1000.0
        self.credential_calls = []
        self.credentials = ElationCredentials(SCOPE.commitment(), SecretStr("synthetic-client"),
            SecretStr("synthetic-secret"))
        self.port = ElationReadAdapter(SCOPE, self.secrets, enabled=enabled,
            problems_enabled=problems_enabled, medications_enabled=medications_enabled,
            authorize_read=self.authorize, transport=httpx.MockTransport(self.send),
            now=lambda: NOW, monotonic=lambda: self.clock, sleep=self.sleep)

    async def secrets(self, scope):
        self.credential_calls.append(scope)
        return self.credentials

    async def authorize(self, scope):
        return self.allowed and scope == SCOPE

    async def sleep(self, seconds):
        assert seconds >= 0
        self.clock += seconds

    def send(self, request):
        self.calls.append(request)
        if self.handler is not None:
            return self.handler(request)
        return response(self.token if request.method == "POST" else self.payload)

    def read(self):
        return asyncio.run(self.port.medications(930))


def rejected(operation, code="invalid_response"):
    with pytest.raises(ElationReadError, match="^" + code + "$"):
        asyncio.run(operation)


@pytest.mark.parametrize("enabled,medications_enabled", [(True, False), (False, True), (False, False)])
def test_separate_medication_opt_in_precedes_credentials_and_io(enabled, medications_enabled):
    case = Harness(enabled=enabled, medications_enabled=medications_enabled)
    rejected(case.port.medications(930), "disabled")
    assert case.calls == [] and case.credential_calls == []


def test_default_medication_access_is_off_with_base_or_problem_access_enabled():
    case = Harness()
    for problems in (False, True):
        port = ElationReadAdapter(SCOPE, case.secrets, enabled=True, problems_enabled=problems,
            authorize_read=case.authorize, transport=httpx.MockTransport(case.send))
        rejected(port.medications(930), "disabled")
    assert case.calls == []


@pytest.mark.parametrize("value", [1, "true", None])
def test_malformed_medication_opt_in_fails_construction(value):
    with pytest.raises(ElationReadError, match="^invalid_request$"):
        Harness(medications_enabled=cast(bool, value))


def test_exact_query_profile_projection_and_private_representation():
    case = Harness()
    result = case.read()
    oauth, resource = case.calls
    assert parse_qs(oauth.content.decode()) == {"grant_type": ["client_credentials"],
        "client_id": ["synthetic-client"], "client_secret": ["synthetic-secret"], "scope": [MEDICATION_SCOPES]}
    assert str(oauth.url) == ORIGIN + "/api/2.0/oauth2/token/"
    assert resource.method == "GET" and resource.url.path == PATH
    assert dict(resource.url.params) == {"patient": "930", "practice": "910", "limit": "25"}
    assert "cookie" not in resource.headers and "x-on-behalf-of" not in resource.headers
    row = result.rows[0]
    assert isinstance(row, ElationMedication)
    assert asdict(row) == {"medication_id": 955, "patient_id": 930, "practice_id": 910,
        "medication_name": "Invented medication Alpha", "strength": "10 mg", "route": "Oral", "form": "Tablet",
        "directions": MEDICATION["directions"], "medication_type": "prescription", "order_type": "New",
        "is_doc_med": True, "is_permanent": False, "start_date": "2026-01-02",
        "document_date": "2026-01-02T12:00:00Z", "signed_date": "2026-01-02T12:00:00Z",
        "deleted_date": None, "discontinue_date": None, "signature_state": "date_recorded",
        "discontinuation_state": "no_date_recorded", "deletion_state": "no_date_recorded"}
    assert result.coverage == "end_of_results" and result.total_count is None and result.next_cursor is None
    assert result.scope == SCOPE and result.observed_at == NOW
    assert "unused-" not in str(asdict(result))
    assert "Invented" not in repr(result) + repr(row) + repr(case.port)


@pytest.mark.parametrize("scope", [SCOPES, PROBLEM_SCOPES, MEDICATION_SCOPES + " system/medications.write",
    MEDICATION_SCOPES + " apiv2", "system/medications.read", None])
def test_missing_or_excess_scopes_prevent_medication_read(scope):
    case = Harness(token={**TOKEN, "scope": scope})
    rejected(case.port.medications(930))
    assert [call.method for call in case.calls] == ["POST"]


@pytest.mark.parametrize("patient", [0, -1, True, "930", None, MAX_ID + 1])
def test_invalid_selected_patient_is_rejected_before_io(patient):
    case = Harness()
    rejected(case.port.medications(patient), "invalid_request")
    assert case.calls == [] and case.credential_calls == []


@pytest.mark.parametrize("path,value", [
    (("id",), 0), (("id",), True), (("id",), MAX_ID + 1), (("id",), "955"),
    (("patient",), 931), (("patient",), True), (("patient",), "930"),
    (("practice",), 911), (("practice",), True), (("practice",), "910"),
    (("medication",), None), (("medication",), []),
    (("medication", "name"), None), (("medication", "name"), ""),
    (("medication", "name"), " \u2003"), (("medication", "name"), "x" * 301),
    (("medication", "name"), "bad\nname"), (("medication", "name"), "bad\ud800"),
    (("medication", "strength"), "x" * 256), (("medication", "route"), "x" * 101),
    (("medication", "form"), "x" * 101), (("medication", "route"), 1),
    (("directions",), "x" * 1001), (("directions",), "bad\x00instructions"),
    (("directions",), "bad\x7finstructions"), (("directions",), "bad\udfff"),
    (("medication_type",), "x" * 41), (("order_type",), []),
    (("is_doc_med",), "true"), (("is_doc_med",), 1), (("thread",), []),
    (("thread", "is_permanent"), 0), (("start_date",), "2026-1-02"),
    (("start_date",), "2026-02-30"), (("start_date",), "2026-W01-1"),
    (("start_date",), "2026-01-02T12:00:00Z"), (("document_date",), "2026-01-02"),
    (("signed_date",), "2026-01-02T25:00:00Z"), (("signed_date",), "2026-01-02T12:00:60Z"),
    (("signed_date",), "2026-01-02T12:00:00+24:00"), (("signed_date",), "2026-01-02T12:00:00+00:60"),
    (("signed_date",), "2026-01-02T12:00:00-01:60"), (("signed_date",), "2026-01-02T12:00:00.1234567Z"),
    (("deleted_date",), ""), (("thread", "dc_date"), "2026-02-30"),
    (("thread", "dc_date"), True),
])
def test_malformed_or_mismatched_row_refuses_the_entire_page(path, value):
    row = copy.deepcopy(MEDICATION)
    row["id"] = 956
    target = row
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    case = Harness({"results": [MEDICATION, row]})
    rejected(case.port.medications(930))
    assert len(case.calls) == 2


@pytest.mark.parametrize("key", ["id", "patient", "practice", "medication"])
def test_required_identity_and_medication_name_cannot_be_missing(key):
    row = copy.deepcopy(MEDICATION)
    del row[key]
    rejected(Harness({"results": [row]}).port.medications(930))


def test_optional_raw_values_are_not_rewritten_or_interpreted_as_current_medications():
    row = copy.deepcopy(MEDICATION)
    row.update(medication_type="discontinued", order_type="VendorFutureValue", is_doc_med=False,
        directions=" \t" + "x" * 995 + "\r\n ", signed_date=None,
        deleted_date="2026-10-24T12:00:00-04:00", start_date="2027-01-01")
    row["medication"].update(name=" " + "x" * 298 + " ", strength="", route=None, form=" ")
    row["thread"].update(dc_date="2027-01-01T15:03:02.123456", is_permanent=True)
    result = Harness({"results": [row]}).read().rows[0]
    assert isinstance(result, ElationMedication)
    assert result.medication_name == row["medication"]["name"] and result.directions == row["directions"]
    assert result.strength == "" and result.form == " " and result.route is None
    assert result.medication_type == "discontinued" and result.order_type == "VendorFutureValue"
    assert result.signature_state == "no_date_recorded" and result.discontinuation_state == "date_recorded"
    assert result.discontinue_date == "2027-01-01T15:03:02.123456" and result.is_permanent is True
    assert result.deleted_date == "2026-10-24T12:00:00-04:00" and result.deletion_state == "date_recorded"
    assert result.start_date == "2027-01-01" and not hasattr(result, "active")


@pytest.mark.parametrize("value", ["2026-01-02", "2026-01-02T12:34:56Z",
    "2026-01-02T12:34:56.123456-04:00", "2026-01-02T12:34:56"])
def test_official_date_or_datetime_discontinue_representations_remain_verbatim(value):
    row = copy.deepcopy(MEDICATION)
    row["thread"]["dc_date"] = value
    result = Harness({"results": [row]}).read().rows[0]
    assert isinstance(result, ElationMedication)
    assert result.discontinue_date == value and result.discontinuation_state == "date_recorded"


def test_missing_fields_are_unknown_and_explicit_null_date_metadata_is_distinct():
    minimal = {"id": 955, "patient": 930, "practice": 910, "medication": {"name": "Invented medicine"}}
    unknown = Harness({"results": [minimal]}).read().rows[0]
    explicit = Harness({"results": [{**minimal, "signed_date": None, "deleted_date": None,
        "thread": {"dc_date": None}}]}).read().rows[0]
    assert isinstance(unknown, ElationMedication) and isinstance(explicit, ElationMedication)
    assert unknown.signature_state == unknown.discontinuation_state == unknown.deletion_state == "unknown"
    assert explicit.signature_state == explicit.discontinuation_state == explicit.deletion_state == "no_date_recorded"
    assert unknown.is_doc_med is None and unknown.is_permanent is None and unknown.directions is None


@pytest.mark.parametrize("rows", [[MEDICATION, MEDICATION], [MEDICATION, None], [MEDICATION, 1],
    [{**MEDICATION, "id": 955 + i} for i in range(26)], "not a list"])
def test_duplicate_or_malformed_or_oversized_pages_are_not_partially_returned(rows):
    rejected(Harness({"results": rows}).port.medications(930))


@pytest.mark.parametrize("metadata,coverage,total", [({}, "unknown", None),
    ({"count": 1}, "unknown", 1), ({"count": 26}, "unknown", 26),
    ({"next": None}, "end_of_results", None),
    ({"next": None, "previous": None, "count": 1}, "end_of_results", 1),
    ({"next": ORIGIN + PATH + "?offset=25", "count": 26}, "more_rows_available", 26)])
def test_coverage_comes_only_from_page_metadata_and_never_follows_the_next_url(metadata, coverage, total):
    case = Harness({"results": [MEDICATION], **metadata})
    result = case.read()
    assert result.coverage == coverage and result.total_count == total and result.next_cursor is None
    assert len(case.calls) == 2


@pytest.mark.parametrize("metadata", [{"count": 2**31}, {"count": None}, {"count": True},
    {"count": 0}, {"next": None, "count": 2}, {"next": ""}, {"next": False},
    {"next": "http://sandbox.elationemr.com" + PATH + "?offset=25"},
    {"next": "https://example.invalid" + PATH + "?offset=25"},
    {"next": ORIGIN + PATH + "?offset=25&patient=931"},
    {"next": ORIGIN + PATH + "?offset=25&discontinued=false"},
    {"next": ORIGIN + PATH + "?offset=25&limit=100"},
    {"next": ORIGIN + PATH + "?cursor=opaque"}, {"next": ORIGIN + PATH + "?offset=01"},
    {"previous": ORIGIN + PATH + "?offset=0"}, {"extra": "private provider text"}])
def test_inconsistent_foreign_or_unsupported_pagination_is_refused(metadata):
    rejected(Harness({"results": [MEDICATION], **metadata}).port.medications(930))


def test_empty_and_boundary_pages_do_not_claim_no_active_medications_or_a_complete_chart():
    result = Harness({"results": [], "next": None, "count": 0}).read()
    assert result.rows == () and result.total_count == 0 and result.coverage == "end_of_results"
    result = Harness({"results": [{**MEDICATION, "id": 955 + i} for i in range(25)]}).read()
    assert len(result.rows) == 25 and result.coverage == "unknown"


def test_authority_is_rechecked_after_the_medication_response():
    case = Harness()
    case.allowed = False
    rejected(case.port.medications(930), "access_denied")
    assert case.calls == [] and case.credential_calls == []
    case.allowed = True

    def revoke(request):
        if request.method == "POST":
            return response(TOKEN)
        case.allowed = False
        return response(case.payload)

    case.handler = revoke
    rejected(case.port.medications(930), "access_denied")
    assert len(case.calls) == 2 and case.port._token is None


@pytest.mark.parametrize("status,code", [(401, "authentication_required"), (403, "permission_denied"),
    (404, "record_unavailable"), (429, "rate_limited"), (503, "unavailable"), (302, "invalid_response")])
def test_medication_failures_use_closed_errors_without_retry(status, code):
    def send(request):
        return response(TOKEN) if request.method == "POST" else httpx.Response(status,
            json={"detail": "private provider detail"})

    case = Harness(handler=send)
    rejected(case.port.medications(930), code)
    assert len(case.calls) == 2


@pytest.mark.parametrize("mode,code", [("timeout", "timeout"), ("size", "response_too_large"),
    ("duplicate-key", "invalid_response"), ("encoding", "invalid_response")])
def test_medication_reads_keep_shared_bounded_transport(mode, code):
    def send(request):
        if request.method == "POST":
            return response(TOKEN)
        if mode == "timeout":
            raise httpx.ReadTimeout("private provider detail", request=request)
        if mode == "size":
            return httpx.Response(200, content=b" " * (MAX_BODY + 1), headers={"content-type": "application/json"})
        if mode == "duplicate-key":
            return httpx.Response(200, content=b'{"results":[],"results":[]}', headers={"content-type": "application/json"})
        return httpx.Response(200, json={"results": []}, headers={"content-encoding": "br"})

    case = Harness(handler=send)
    rejected(case.port.medications(930), code)
    assert len(case.calls) == 2


def test_commitment_binds_raw_dates_unknowns_instructions_count_and_coverage():
    original = Harness({"results": [MEDICATION]}).read()
    changed = copy.deepcopy(MEDICATION)
    changed["directions"] += "\nRetain exact wording."
    differently_dated = copy.deepcopy(MEDICATION)
    differently_dated["signed_date"] = "2026-01-02T07:00:00-05:00"
    unsigned = copy.deepcopy(MEDICATION)
    unsigned["signed_date"] = None
    unknown = copy.deepcopy(MEDICATION)
    del unknown["signed_date"]
    cases = [Harness({"results": [row]}).read() for row in (changed, differently_dated, unsigned, unknown)]
    cases += [Harness({"results": [MEDICATION], "count": 1}).read(),
        Harness({"results": [MEDICATION], "count": 1, "next": None}).read()]
    assert len({original.source_sha256, *(item.source_sha256 for item in cases)}) == 7
    ignored = copy.deepcopy(MEDICATION)
    ignored.update(qty="different unused quantity", fulfillment=None)
    assert Harness({"results": [ignored]}).read().source_sha256 == original.source_sha256


def test_legacy_scope_and_patient_hash_are_stable_when_medications_are_not_enabled():
    assert MEDICATION_SCOPES == SCOPES + " system/medications.read"
    assert PROBLEM_SCOPES == SCOPES + " system/problems.read"
    old = Harness(PATIENT, medications_enabled=False, token={**TOKEN, "scope": SCOPES})
    enabled = Harness(PATIENT)
    old_result = asyncio.run(old.port.patient(930))
    enabled_result = asyncio.run(enabled.port.patient(930))
    assert old_result.request_sha256 == enabled_result.request_sha256
    assert old_result.source_sha256 == enabled_result.source_sha256
    assert old_result.scope.commitment() == enabled_result.scope.commitment()
    assert parse_qs(old.calls[0].content.decode())["scope"] == [SCOPES]
    assert parse_qs(enabled.calls[0].content.decode())["scope"] == [MEDICATION_SCOPES]


def runtime_case(*, enabled=True, current=True, verify=True, changed_patient=False, medication_enabled=True):
    calls = []
    def send(request):
        calls.append(request)
        if request.method == "POST":
            return response(TOKEN)
        if request.url.path == "/api/2.0/appointments/940/":
            return response({**APPOINTMENT, "patient": 931} if changed_patient else APPOINTMENT)
        if request.url.path == "/api/2.0/patients/930/":
            return response(PATIENT)
        assert request.url.path == PATH
        return response({"results": [MEDICATION], "next": None})
    runtime = SyntheticElationReads((SCOPE,), httpx.MockTransport(send), enabled=lambda: enabled,
        problems_enabled=lambda: True, medications_enabled=lambda: medication_enabled)
    proofs = []
    def identity(appointment, patient):
        proofs.append((appointment.appointment_id, patient.patient_id))
        return verify
    return runtime, calls, proofs, lambda: runtime.medication_list(SCOPE, 940, 930,
        authorize=lambda: current, verify_identity=identity)


def test_runtime_reverifies_the_exact_appointment_and_patient_before_clinical_io():
    runtime, calls, proofs, run = runtime_case()
    appointment, patient, result = run()
    assert [request.url.path for request in calls] == ["/api/2.0/oauth2/token/",
        "/api/2.0/appointments/940/", "/api/2.0/patients/930/", PATH]
    assert proofs == [(940, 930)]
    assert isinstance(appointment.rows[0], ElationAppointment)
    assert isinstance(patient.rows[0], ElationPatient) and isinstance(result.rows[0], ElationMedication)
    assert appointment.rows[0].patient_id == patient.rows[0].patient_id == result.rows[0].patient_id == 930
    assert runtime.problems_available(SCOPE) and runtime.medications_available(SCOPE)
    assert parse_qs(calls[0].content.decode())["scope"] == [MEDICATION_SCOPES]


@pytest.mark.parametrize("settings,code,expected_reads", [({"medication_enabled": False}, "disabled", 0),
    ({"enabled": False}, "disabled", 0), ({"current": False}, "access_denied", 0),
    ({"verify": False}, "record_unavailable", 3), ({"changed_patient": True}, "record_unavailable", 2)])
def test_runtime_cannot_read_clinical_records_after_a_failed_parent_or_permission_check(settings, code, expected_reads):
    _runtime, calls, _proofs, run = runtime_case(**settings)
    with pytest.raises(ElationReadError, match="^" + code + "$"):
        run()
    assert len(calls) == expected_reads and all(request.url.path != PATH for request in calls)


def test_managed_scope_commitments_keep_old_profiles_and_require_both_medication_opt_ins():
    base = ElationSandboxInstallation(UUID(int=11), UUID(int=12), SCOPE, "UTC", "a" * 64, "b" * 64)
    problem = replace(base, problems_enabled=True)
    medication = replace(base, medications_enabled=True)
    both = replace(problem, medications_enabled=True)
    assert len({base.commitment(), problem.commitment(), medication.commitment(), both.commitment()}) == 4
    assert base.commitment() == replace(base, medications_enabled=False).commitment()
    assert problem.commitment() == replace(problem, medications_enabled=False).commitment()
    async def credentials(scope):
        return ElationCredentials(scope.commitment(), SecretStr("synthetic-client"), SecretStr("synthetic-secret"))
    for installed, host_enabled in ((base, True), (medication, False), (medication, True)):
        runtime = ManagedElationSandboxReads((installed,), credentials=credentials,
            credentials_current=lambda scope: scope == SCOPE, sessions=lambda: None,
            enabled=lambda: True, medications_enabled=lambda active=host_enabled: active)
        assert runtime.medications_available(SCOPE) is (installed.medications_enabled and host_enabled)
        if not runtime.medications_available(SCOPE):
            with pytest.raises(ElationReadError, match="^disabled$"):
                runtime.medication_list(SCOPE, 940, 930, authorize=lambda: True, verify_identity=lambda *_: True)
        runtime.close()
        assert not runtime.medications_available(SCOPE)


@pytest.mark.parametrize("failure,code,reads", [(None, None, 4),
    ("parent-proof", "record_unavailable", 3), ("flag-revoked", "access_denied", 3),
    ("credentials-revoked", "access_denied", 4), ("quota-exhausted", "rate_limited", 3),
    ("flag-revoked-during-quota", "access_denied", 3)])
def test_managed_runtime_preserves_clinical_parent_custody_and_each_io_fence(monkeypatch, failure, code, reads):
    installed = ElationSandboxInstallation(UUID(int=11), UUID(int=12), SCOPE, "UTC", "a" * 64,
        "b" * 64, problems_enabled=True, medications_enabled=True)
    authority = {"flag": True, "credentials": True}
    calls = []
    quota_calls = []
    proofs = []

    async def credentials(scope):
        assert scope == SCOPE
        return ElationCredentials(scope.commitment(), SecretStr("synthetic-client"), SecretStr("synthetic-secret"))

    async def permit(client_commitment):
        quota_calls.append(client_commitment)
        if len(quota_calls) == 4:
            if failure == "flag-revoked-during-quota":
                authority["flag"] = False
            if failure == "quota-exhausted":
                return False
        return True

    def send(request):
        calls.append(request)
        if request.method == "POST":
            return response(TOKEN)
        if request.url.path == "/api/2.0/appointments/940/":
            return response(APPOINTMENT)
        if request.url.path == "/api/2.0/patients/930/":
            if failure == "flag-revoked":
                authority["flag"] = False
            return response(PATIENT)
        assert request.url.path == PATH
        if failure == "credentials-revoked":
            authority["credentials"] = False
        return response({"results": [MEDICATION], "next": None, "count": 1})

    def identity(appointment, patient):
        proofs.append((appointment.appointment_id, patient.patient_id))
        return failure != "parent-proof"

    runtime = ManagedElationSandboxReads((installed,), credentials=credentials,
        credentials_current=lambda scope: scope == SCOPE and authority["credentials"],
        sessions=lambda: None, enabled=lambda: True, medications_enabled=lambda: authority["flag"],
        problems_enabled=lambda: True, transport_factory=lambda: httpx.MockTransport(send))
    monkeypatch.setattr(runtime._quota, "permit", permit)
    try:
        if code is None:
            _appointment, _patient, result = runtime.medication_list(SCOPE, 940, 930,
                authorize=lambda: True, verify_identity=identity)
            assert isinstance(result.rows[0], ElationMedication) and result.total_count == 1
        else:
            with pytest.raises(ElationReadError, match="^" + code + "$"):
                runtime.medication_list(SCOPE, 940, 930, authorize=lambda: True, verify_identity=identity)
        assert len(calls) == reads and all(value == "a" * 64 for value in quota_calls)
        assert parse_qs(calls[0].content.decode())["scope"] == [MEDICATION_SCOPES]
        assert proofs == ([] if failure == "flag-revoked" else [(940, 930)])
    finally:
        runtime.close()
