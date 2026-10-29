"""Synthetic Elation REST contracts: no accounts, credentials or network calls."""

import asyncio
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from typing import NoReturn
from urllib.parse import parse_qs, urlencode
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import SecretStr

from cosmas_os.adapters.elation_read import (
    MAX_BODY,
    ORIGIN,
    PAGE_SIZE,
    SCOPES,
    ElationAppointment,
    ElationCredentials,
    ElationCursor,
    ElationPatient,
    ElationPractice,
    ElationReadAdapter,
    ElationReadError,
    ElationReadScope,
)

SCOPE = ElationReadScope(UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4),
                         910, "Invented Elation Sandbox")
START = datetime(2026, 10, 25, 12, tzinfo=UTC)
END = START + timedelta(days=1)
BIRTH = date(1980, 1, 2)
PATIENT = {"id": 930, "caregiver_practice": 910, "first_name": "Alex",
           "last_name": "Example", "dob": "1980-01-02", "primary_physician": 920,
           "deleted_date": None, "ssn": "never project", "email": "never project"}
APPOINTMENT = {"id": 940, "practice": 910, "patient": 930, "physician": 920,
               "scheduled_date": "2026-10-25T13:00:00Z", "duration": 30,
               "time_slot_type": "appointment", "status": {"status": "Confirmed"},
               "deleted_date": None, "description": "never project"}
PRACTICE = {"id": 910, "name": "Invented Elation Sandbox", "status": "active",
            "timezone": "America/New_York", "physicians": [920]}
TOKEN = {"access_token": "synthetic-token", "token_type": "Bearer", "expires_in": 3600,
         "scope": SCOPES, "refresh_token": "synthetic-unused-refresh"}


class Clock:
    def __init__(self):
        self.value = 1000.0
        self.waits = []

    def __call__(self):
        return self.value

    async def sleep(self, seconds):
        assert seconds >= 0
        self.waits.append(seconds)
        self.value += seconds


def page(*rows, next_url=None):
    # Cursor pages have no count field in Elation's documented contract.
    return {"next": next_url, "previous": None, "results": list(rows)}


def adapter(payload=None, *, enabled=True, status=200, handler=None, token=None,
            authorize=None, credentials=None, scope=SCOPE, permit=None):
    calls, credential_calls, clock = [], [], Clock()

    async def allowed(current):
        return current == scope

    async def secrets(current):
        credential_calls.append(current)
        return ElationCredentials(current.commitment(), SecretStr("synthetic-client"),
                                  SecretStr("synthetic-secret"))

    def handle(request):
        calls.append(request)
        if handler is not None:
            return handler(request)
        if request.url.path == "/api/2.0/oauth2/token/":
            return httpx.Response(200, json=TOKEN if token is None else token)
        return httpx.Response(status, json=PATIENT if payload is None else payload)

    port = ElationReadAdapter(scope, credentials or secrets, enabled=enabled,
        authorize_read=authorize or allowed, permit_request=permit,
        transport=httpx.MockTransport(handle), now=lambda: START,
        monotonic=clock, sleep=clock.sleep)
    return port, calls, credential_calls, clock


def read(port):
    return asyncio.run(port.patient(930))


def expect_error(code, request):
    with pytest.raises(ElationReadError, match="^" + code + "$") as raised:
        asyncio.run(request)
    assert str(raised.value) == code


def test_default_inactive_and_missing_current_authority_never_resolve_credentials_or_connect():
    calls = []
    async def credentials(_):
        calls.append("credentials")
        raise AssertionError
    def forbidden_network(_: httpx.Request) -> NoReturn:
        calls.append("network")
        raise AssertionError("A disabled or unauthorized adapter cannot contact the provider")
    port = ElationReadAdapter(SCOPE, credentials,
        transport=httpx.MockTransport(forbidden_network))
    expect_error("disabled", port.patient(930))
    port = ElationReadAdapter(SCOPE, credentials, enabled=True,
        transport=httpx.MockTransport(forbidden_network))
    expect_error("access_denied", port.patient(930))
    assert calls == []


def test_documented_client_credentials_and_exact_read_scopes_are_used():
    port, calls, custody, clock = adapter()
    result = read(port)
    token_request, patient_request = calls
    assert str(token_request.url) == ORIGIN + "/api/2.0/oauth2/token/"
    assert token_request.method == "POST"
    assert token_request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert parse_qs(token_request.content.decode()) == {
        "grant_type": ["client_credentials"], "client_id": ["synthetic-client"],
        "client_secret": ["synthetic-secret"], "scope": [SCOPES],
    }
    assert "authorization" not in token_request.headers
    assert patient_request.method == "GET"
    assert str(patient_request.url) == ORIGIN + "/api/2.0/patients/930/"
    assert patient_request.headers["authorization"] == "Bearer synthetic-token"
    assert "cookie" not in patient_request.headers and "act-as-user" not in patient_request.headers
    assert custody == [SCOPE] and sum(clock.waits) >= 0.51 - 1e-9
    assert result.scope == SCOPE and result.coverage == "selected_record"
    patient = result.rows[0]
    assert isinstance(patient, ElationPatient)
    assert patient.birth_date == BIRTH and patient.patient_id == 930
    assert "never project" not in str(asdict(result))
    assert "Alex" not in repr(result) and "Alex" not in repr(result.rows[0])
    assert "synthetic" not in repr(port)
    assert len(result.source_sha256) == len(result.request_sha256) == 64


def test_tokens_are_reused_only_with_current_custody_and_new_tokens_use_client_credentials():
    port, calls, custody, clock = adapter()
    async def scenario():
        first = await port.patient(930)
        second = await port.patient(930)
        clock.value += 3600
        third = await port.patient(930)
        return first, second, third
    result = asyncio.run(scenario())
    assert [r.method for r in calls] == ["POST", "GET", "GET", "POST", "GET"]
    assert len(custody) == 3
    assert all(r.source_sha256 == result[0].source_sha256 for r in result)
    assert all(parse_qs(r.content.decode())["grant_type"] == ["client_credentials"]
               for r in calls if r.method == "POST")


@pytest.mark.parametrize("field,value", [
    ("scope", "apiv2"), ("scope", SCOPES + " act_as_user"),
    ("scope", "system/patients.read"), ("scope", None),
    ("token_type", "Basic"), ("expires_in", True), ("expires_in", 0),
    ("access_token", "bad\r\ntoken"), ("access_token", "é"),
])
def test_bad_or_excessive_token_authority_never_reaches_patient_endpoint(field, value):
    port, calls, _, _ = adapter(token={**TOKEN, field: value})
    expect_error("invalid_response", port.patient(930))
    assert len(calls) == 1 and calls[0].method == "POST"


def test_credential_generation_mismatch_and_unversioned_rotation_discard_cached_token():
    current = ElationCredentials(SCOPE.commitment(), SecretStr("synthetic-client"),
                                 SecretStr("synthetic-secret"))
    async def credentials(_):
        return current
    port, calls, _, _ = adapter(credentials=credentials)
    async def scenario():
        nonlocal current
        await port.patient(930)
        current = replace(current, client_secret=SecretStr("synthetic-rotated"))
        with pytest.raises(ElationReadError, match="^connection_changed$"):
            await port.patient(930)
    asyncio.run(scenario())
    assert len(calls) == 2 and port._token is None
    current = replace(current, scope_sha256=replace(SCOPE, credential_generation=UUID(int=5)).commitment())
    port, calls, _, _ = adapter(credentials=credentials)
    expect_error("connection_changed", port.patient(930))
    assert calls == []


def test_authority_revoked_during_provider_response_withholds_the_entire_observation():
    permitted = True
    async def allowed(_):
        return permitted
    def handle(request):
        nonlocal permitted
        if request.method == "POST":
            return httpx.Response(200, json=TOKEN)
        permitted = False
        return httpx.Response(200, json=PATIENT)
    port, calls, _, _ = adapter(handler=handle, authorize=allowed)
    expect_error("access_denied", port.patient(930))
    assert len(calls) == 2 and port._token is None


@pytest.mark.parametrize("status,code", [
    (401, "authentication_required"), (403, "permission_denied"),
    (404, "record_unavailable"), (410, "record_unavailable"),
    (429, "rate_limited"), (500, "unavailable"), (503, "unavailable"),
    (302, "invalid_response"), (201, "invalid_response"), (409, "invalid_response"),
])
def test_provider_statuses_are_closed_no_retry_and_no_provider_text_escapes(status, code):
    port, calls, _, _ = adapter({"detail": "synthetic-secret patient Alex"}, status=status)
    expect_error(code, port.patient(930))
    assert len(calls) == 2
    if status == 401:
        assert port._token is None


@pytest.mark.parametrize("failure,code", [(httpx.ReadTimeout, "timeout"),
                                         (httpx.ConnectError, "unavailable")])
def test_network_errors_are_closed_and_not_automatically_retried(failure, code):
    def handle(request):
        raise failure("synthetic private details", request=request)
    port, calls, _, _ = adapter(handler=handle)
    expect_error(code, port.patient(930))
    assert len(calls) == 1


def test_provider_redirects_are_not_followed_and_token_cookies_are_not_reused():
    def handle(request):
        if request.method == "POST":
            return httpx.Response(200, json=TOKEN, headers={"Set-Cookie": "session=synthetic; Path=/"})
        assert "cookie" not in request.headers
        return httpx.Response(302, headers={"Location": "https://example.invalid/collect"})
    port, calls, _, _ = adapter(handler=handle)
    expect_error("invalid_response", port.patient(930))
    assert len(calls) == 2 and all(r.url.host == "sandbox.elationemr.com" for r in calls)


def test_compressed_body_is_rejected_before_decompression_can_expand_the_byte_budget():
    def handle(request):
        if request.method == "POST":
            return httpx.Response(200, json=TOKEN)
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, stream=httpx.ByteStream(b"untrusted compressed content"),
            headers={"Content-Type": "application/json", "Content-Encoding": "gzip"})
    port, calls, _, _ = adapter(handler=handle)
    expect_error("invalid_response", port.patient(930))
    assert len(calls) == 2


@pytest.mark.parametrize("payload,content_type,code", [
    (b'{"id":930,"id":931}', "application/json", "invalid_response"),
    (b'{"id":NaN}', "application/json", "invalid_response"),
    (b"[]", "application/json", "invalid_response"),
    (b"not json", "application/json", "invalid_response"),
    (b"{}", "text/html", "invalid_response"),
    (b"x" * (MAX_BODY + 1), "application/json", "response_too_large"),
])
def test_malformed_duplicate_or_oversized_response_cannot_become_an_empty_success(payload, content_type, code):
    def handle(request):
        if request.method == "POST":
            return httpx.Response(200, json=TOKEN)
        return httpx.Response(200, content=payload, headers={"Content-Type": content_type})
    port, calls, _, _ = adapter(handler=handle)
    expect_error(code, port.patient(930))
    assert len(calls) == 2


@pytest.mark.parametrize("change", [
    {"caregiver_practice": 911}, {"id": 931}, {"id": True},
    {"id": 2**63}, {"primary_physician": None}, {"dob": "1980-99-02"},
    {"first_name": "Alex\nExample"},
])
def test_wrong_patient_scope_or_identity_invalidates_the_whole_result(change):
    port, _, _, _ = adapter({**PATIENT, **change})
    expect_error("invalid_response", port.patient(930))


def test_patient_search_is_exact_and_preserves_possible_duplicates_for_human_selection():
    duplicate = {**PATIENT, "id": 931, "first_name": "ALEX"}
    port, calls, _, _ = adapter(page(PATIENT, duplicate))
    result = asyncio.run(port.patients("Alex", "Example", BIRTH))
    assert dict(calls[-1].url.params) == {"practice": "910", "limit": str(PAGE_SIZE),
        "first_name": "Alex", "last_name": "Example", "dob": "1980-01-02"}
    assert len(result.rows) == 2 and result.coverage == "end_of_results"
    assert result.next_cursor is None and not hasattr(result, "patient_link")
    port, _, _, _ = adapter(page(PATIENT, {**PATIENT, "id": 931, "last_name": "Other"}))
    expect_error("invalid_response", port.patients("Alex", "Example", BIRTH))


def test_empty_search_is_observed_no_match_not_missing_or_malformed_data():
    port, _, _, _ = adapter(page())
    result = asyncio.run(port.patients("Alex", "Example", BIRTH))
    assert result.rows == () and result.coverage == "end_of_results"
    for payload in ({"next": None, "previous": None}, {"results": []},
                    page(*([{**PATIENT, "id": i + 1} for i in range(PAGE_SIZE + 1)])),
                    page(PATIENT, PATIENT)):
        port, _, _, _ = adapter(payload)
        expect_error("invalid_response", port.patients("Alex", "Example", BIRTH))


def test_cursor_pages_keep_exact_filters_and_never_follow_a_provider_url():
    def handle(request):
        if request.method == "POST":
            return httpx.Response(200, json=TOKEN)
        if "cursor" in request.url.params:
            return httpx.Response(200, json=page({**PATIENT, "id": 931}))
        return httpx.Response(200, json=page(PATIENT,
            next_url=ORIGIN + "/api/2.0/patients?cursor=cD0xMjM%3D"))
    port, calls, _, _ = adapter(handler=handle)
    async def scenario():
        first = await port.patients("Alex", "Example", BIRTH)
        assert first.coverage == "more_rows_available" and first.next_cursor is not None
        final = await port.patients("Alex", "Example", BIRTH, cursor=first.next_cursor)
        patient = final.rows[0]
        assert isinstance(patient, ElationPatient)
        assert final.coverage == "end_of_results" and patient.patient_id == 931
        assert first.source_sha256 != final.source_sha256
        before = len(calls)
        with pytest.raises(ElationReadError, match="^invalid_request$"):
            await port.patients("Alex", "Other", BIRTH, cursor=first.next_cursor)
        assert len(calls) == before
    asyncio.run(scenario())
    assert dict(calls[-1].url.params) == {"practice": "910", "limit": "25",
        "first_name": "Alex", "last_name": "Example", "dob": "1980-01-02", "cursor": "cD0xMjM="}
    assert all(r.url.host == "sandbox.elationemr.com" for r in calls)


@pytest.mark.parametrize("next_url", [
    "https://example.invalid/api/2.0/patients/?cursor=next",
    "http://sandbox.elationemr.com/api/2.0/patients/?cursor=next",
    ORIGIN + "/api/2.0/appointments/?cursor=next",
    ORIGIN + "/api/2.0/patients/?cursor=next&practice=911",
    ORIGIN + "/api/2.0/patients/?cursor=next&first_name=Other",
    ORIGIN + "/api/2.0/patients/?cursor=next&cursor=second",
    ORIGIN + "/api/2.0/patients/?cursor=next&offset=25",
    ORIGIN + "/api/2.0/patients/?cursor=next#fragment",
    ORIGIN + "/api/2.0/patients/?cursor=%0A",
    ORIGIN + "/api/2.0/patients/",
])
def test_untrusted_next_page_cannot_change_host_practice_query_or_mode(next_url):
    port, calls, _, _ = adapter(page(PATIENT, next_url=next_url))
    expect_error("invalid_response", port.patients("Alex", "Example", BIRTH))
    assert len(calls) == 2


def test_repeated_cursor_and_cursor_from_another_connection_are_rejected():
    next_url = ORIGIN + "/api/2.0/patients/?" + urlencode({
        "cursor": "next", "practice": "910", "limit": "25", "first_name": "Alex",
        "last_name": "Example", "dob": "1980-01-02"})
    port, calls, _, _ = adapter(page(PATIENT, next_url=next_url))
    async def scenario():
        first = await port.patients("Alex", "Example", BIRTH)
        with pytest.raises(ElationReadError, match="^invalid_response$"):
            await port.patients("Alex", "Example", BIRTH, cursor=first.next_cursor)
        other, other_calls, _, _ = adapter(scope=replace(SCOPE, connection_id=UUID(int=5)))
        with pytest.raises(ElationReadError, match="^invalid_request$"):
            await other.patients("Alex", "Example", BIRTH, cursor=first.next_cursor)
        assert other_calls == []
    asyncio.run(scenario())
    assert len(calls) == 3


def test_schedule_uses_utc_bounds_and_preserves_status_and_deletion_without_claiming_free_time():
    deleted = {**APPOINTMENT, "id": 941, "status": {"status": "Cancelled"},
               "deleted_date": "2026-10-25T11:00:00Z"}
    port, calls, _, _ = adapter(page(APPOINTMENT, deleted))
    result = asyncio.run(port.appointments(START, END, physician_id=920))
    assert dict(calls[-1].url.params) == {"practice": "910", "limit": "25",
        "from_date": "2026-10-25T12:00:00Z", "to_date": "2026-10-26T12:00:00Z",
        "time_slot_type": "appointment", "physician": "920"}
    first, cancelled = result.rows
    assert isinstance(first, ElationAppointment) and isinstance(cancelled, ElationAppointment)
    assert first.starts_at == START + timedelta(hours=1)
    assert first.ends_at == START + timedelta(hours=1, minutes=30)
    assert first.scheduled_date_raw == APPOINTMENT["scheduled_date"]
    assert first.source_status == "Confirmed" and cancelled.deleted_at is not None
    assert "never project" not in str(asdict(result)) and not hasattr(result, "available_slots")


def test_schedule_duration_limit_uses_elapsed_utc_time_across_fall_back():
    zone = ZoneInfo("America/New_York")
    port, calls, custody, _ = adapter(page())
    start = datetime(2026, 10, 31, 12, tzinfo=zone)
    end = datetime(2026, 11, 7, 12, tzinfo=zone)
    # Seven wall-clock days cover 169 elapsed hours across the DST transition.
    expect_error("invalid_request", port.appointments(start, end))
    assert calls == custody == []


def test_schedule_accepts_the_real_hour_between_repeated_local_clock_times():
    zone = ZoneInfo("America/New_York")
    port, calls, _, _ = adapter(page())
    start = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    end = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    result = asyncio.run(port.appointments(start, end))
    assert result.rows == ()
    assert calls[-1].url.params["from_date"] == "2026-11-01T05:30:00Z"
    assert calls[-1].url.params["to_date"] == "2026-11-01T06:30:00Z"


@pytest.mark.parametrize("change", [
    {"practice": 911}, {"time_slot_type": "event"}, {"time_slot_type": "appointment_slot"},
    {"physician": 921}, {"duration": True}, {"duration": 0}, {"duration": 1441},
    {"status": {"status": "Ready for prescribing"}}, {"status": "Confirmed"},
    {"scheduled_date": "2026-10-25T13:00:00"},
    {"scheduled_date": "2026-10-25T11:59:59Z"},
    {"scheduled_date": "2026-10-26T12:00:01Z"},
])
def test_schedule_scope_unknown_status_and_unbounded_time_fail_closed(change):
    port, _, _, _ = adapter(page({**APPOINTMENT, **change}))
    expect_error("invalid_response", port.appointments(START, END, physician_id=920))


def test_selected_deleted_records_are_unavailable_and_missing_deletion_state_is_invalid():
    for name, row, identifier in (("patient", PATIENT, 930), ("appointment", APPOINTMENT, 940)):
        port, _, _, _ = adapter({**row, "deleted_date": "2026-10-25T11:00:00Z"})
        expect_error("record_unavailable", getattr(port, name)(identifier))
        absent = dict(row)
        del absent["deleted_date"]
        port, _, _, _ = adapter(absent)
        expect_error("invalid_response", getattr(port, name)(identifier))


def test_practice_read_requires_exact_active_practice_and_real_timezone():
    port, calls, _, _ = adapter(PRACTICE)
    result = asyncio.run(port.practice())
    assert calls[-1].url.path == "/api/2.0/practices/910/"
    practice = result.rows[0]
    assert isinstance(practice, ElationPractice)
    assert practice.timezone == "America/New_York"
    assert practice.active_physician_ids == (920,)
    for change in ({"id": 911}, {"status": "inactive"}, {"timezone": "Not/AZone"},
                   {"physicians": [920, 920]}, {"physicians": [True]}):
        port, _, _, _ = adapter({**PRACTICE, **change})
        expect_error("invalid_response", port.practice())


def test_invalid_user_inputs_fail_before_credentials_or_io():
    port, calls, custody, _ = adapter()
    requests = [port.patient(True), port.patient(0), port.appointment(-1),
        port.appointments(START.replace(tzinfo=None), END),
        port.appointments(START, START), port.appointments(START, START + timedelta(days=8)),
        port.appointments(START, END, physician_id=True),
        port.patients("", "Example", BIRTH), port.patients(" Alex", "Example", BIRTH),
        port.patients("Alex", "Example", START),
        port.patients("Alex", "Example", BIRTH, cursor=ElationCursor("wrong-query", "next"))]
    for request in requests:
        expect_error("invalid_request", request)
    assert calls == custody == []


def test_budget_denial_does_not_reach_provider_and_auth_failure_never_becomes_a_no_match():
    async def denied(_):
        return False
    port, calls, _, _ = adapter(permit=denied)
    expect_error("rate_limited", port.patient(930))
    assert calls == []
    async def broken_auth(_):
        raise RuntimeError("private authorization detail")
    port, calls, custody, _ = adapter(authorize=broken_auth)
    expect_error("access_denied", port.patient(930))
    assert calls == custody == []


def test_source_commitment_changes_with_scope_generation_and_raw_observation():
    first, _, _, _ = adapter()
    second, _, _, _ = adapter(scope=replace(SCOPE, credential_generation=UUID(int=5)))
    changed, _, _, _ = adapter({**PATIENT, "first_name": "Jordan"})
    assert len({read(port).source_sha256 for port in (first, second, changed)}) == 3
    assert SCOPE.commitment() != replace(SCOPE, box_id=UUID(int=6)).commitment()


def test_production_configuration_is_rejected_before_any_io():
    async def credentials(_):
        raise AssertionError
    with pytest.raises(ElationReadError, match="^invalid_request$"):
        ElationReadAdapter(replace(SCOPE, environment="production"), credentials)
