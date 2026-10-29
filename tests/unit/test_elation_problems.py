"""Invented problem-list contracts using MockTransport; no vendor calls."""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from typing import cast
from urllib.parse import parse_qs
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from cosmas_os.adapters.elation_read import (
    MAX_BODY,
    MAX_ID,
    ORIGIN,
    PROBLEM_SCOPES,
    SCOPES,
    ElationCredentials,
    ElationProblem,
    ElationReadAdapter,
    ElationReadError,
    ElationReadResult,
    ElationReadScope,
)

SCOPE = ElationReadScope(UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4),
    910, "Invented Elation Sandbox")
NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
PATH = "/api/2.0/problems/"
PROBLEM: dict[str, object] = {
    "id": 950, "patient": 930, "practice": 910, "description": "Invented example problem",
    "status": "Active", "start_date": "2026-01-02", "resolved_date": None,
    "verification_status": "confirmed", "deleted_date": None,
    "synopsis": "private unused synopsis", "dx": [{"snomed": "private unused code"}],
}
PATIENT = {"id": 930, "caregiver_practice": 910, "first_name": "Alex", "last_name": "Example",
    "dob": "1980-01-02", "primary_physician": 920, "deleted_date": None}
TOKEN: dict[str, object] = {"access_token": "synthetic-token", "token_type": "Bearer",
    "expires_in": 3600, "scope": PROBLEM_SCOPES}


class Harness:
    def __init__(self, payload: object = None, *, enabled: bool = True,
            problems_enabled: bool = True, token: dict[str, object] | None = None,
            handler: Callable[[httpx.Request], httpx.Response] | None = None):
        self.payload = {"results": [PROBLEM], "next": None} if payload is None else payload
        self.token = TOKEN if token is None else token
        self.handler = handler
        self.calls: list[httpx.Request] = []
        self.credential_calls: list[ElationReadScope] = []
        self.allowed = True
        self.clock = 1000.0
        self.credentials = ElationCredentials(SCOPE.commitment(), SecretStr("synthetic-client"),
            SecretStr("synthetic-secret"))
        self.port = ElationReadAdapter(SCOPE, self.secrets, enabled=enabled,
            problems_enabled=problems_enabled, authorize_read=self.authorize,
            transport=httpx.MockTransport(self.send), now=lambda: NOW,
            monotonic=lambda: self.clock, sleep=self.sleep)

    async def secrets(self, scope: ElationReadScope) -> ElationCredentials:
        self.credential_calls.append(scope)
        return self.credentials

    async def authorize(self, scope: ElationReadScope) -> bool:
        return self.allowed and scope == SCOPE

    async def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.clock += seconds

    def send(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.handler is not None:
            return self.handler(request)
        if request.method == "POST":
            return httpx.Response(200, json=self.token)
        return httpx.Response(200, json=self.payload)

    def read(self) -> ElationReadResult:
        return asyncio.run(self.port.problems(930))


def rejected(operation: Coroutine[object, object, ElationReadResult],
        code: str = "invalid_response") -> None:
    with pytest.raises(ElationReadError, match="^" + code + "$") as failure:
        asyncio.run(operation)
    assert str(failure.value) == code


@pytest.mark.parametrize("enabled,problems_enabled", [(True, False), (False, True), (False, False)])
def test_separate_opt_in_precedes_credentials_and_transport(enabled: bool, problems_enabled: bool):
    case = Harness(enabled=enabled, problems_enabled=problems_enabled)
    rejected(case.port.problems(930), "disabled")
    assert case.calls == [] and case.credential_calls == []


def test_default_problems_option_is_disabled_even_when_base_adapter_is_enabled():
    case = Harness()
    port = ElationReadAdapter(SCOPE, case.secrets, enabled=True,
        authorize_read=case.authorize, transport=httpx.MockTransport(case.send))
    rejected(port.problems(930), "disabled")
    assert case.calls == [] and case.credential_calls == []


@pytest.mark.parametrize("value", [1, "true", None])
def test_malformed_opt_in_is_rejected_at_construction(value: object):
    with pytest.raises(ElationReadError, match="^invalid_request$"):
        Harness(problems_enabled=cast(bool, value))


def test_exact_authority_query_projection_and_private_representation():
    case = Harness()
    result = case.read()
    oauth, resource = case.calls
    assert oauth.method == "POST" and str(oauth.url) == ORIGIN + "/api/2.0/oauth2/token/"
    assert parse_qs(oauth.content.decode()) == {
        "grant_type": ["client_credentials"], "client_id": ["synthetic-client"],
        "client_secret": ["synthetic-secret"], "scope": [PROBLEM_SCOPES],
    }
    assert resource.method == "GET" and resource.url.path == PATH
    assert dict(resource.url.params) == {"patient": "930", "practice": "910", "limit": "25"}
    assert resource.headers["authorization"] == "Bearer synthetic-token"
    assert resource.headers["accept-encoding"] == "identity"
    assert "cookie" not in resource.headers and "x-on-behalf-of" not in resource.headers
    assert case.credential_calls == [SCOPE]
    assert result.scope == SCOPE and result.observed_at == NOW and result.operation == PATH
    assert result.next_cursor is None and result.coverage == "end_of_results"
    assert result.total_count is None
    row = result.rows[0]
    assert isinstance(row, ElationProblem)
    assert asdict(row) == {"problem_id": 950, "patient_id": 930, "practice_id": 910,
        "description": "Invented example problem", "status": "Active",
        "start_date": date(2026, 1, 2), "resolved_date": None, "verification_status": "confirmed"}
    assert "private unused" not in str(asdict(result))
    assert "Invented" not in repr(result) + repr(row) + repr(case.port)


@pytest.mark.parametrize("scope", [SCOPES, PROBLEM_SCOPES + " system/problems.write",
    PROBLEM_SCOPES + " apiv2", "system/problems.read", None])
def test_missing_or_excess_token_scopes_prevent_resource_read(scope: object):
    case = Harness(token={**TOKEN, "scope": scope})
    rejected(case.port.problems(930))
    assert [call.method for call in case.calls] == ["POST"]


@pytest.mark.parametrize("patient", [0, -1, True, "930", None, MAX_ID + 1])
def test_invalid_selected_patient_rejected_before_io(patient: object):
    case = Harness()
    rejected(case.port.problems(cast(int, patient)), "invalid_request")
    assert case.calls == [] and case.credential_calls == []


@pytest.mark.parametrize("field,value", [
    ("id", 0), ("id", True), ("id", MAX_ID + 1), ("id", "950"),
    ("patient", 931), ("patient", True), ("patient", "930"),
    ("practice", 911), ("practice", True), ("practice", "910"),
    ("description", ""), ("description", "   "), ("description", "\u2003"),
    ("description", "x" * 201), ("description", "bad\ntext"),
    ("description", "bad\x7ftext"), ("description", None),
    ("status", "active"), ("status", None), ("status", []),
    ("verification_status", "unknown"), ("verification_status", True),
    ("verification_status", []),
    ("start_date", None), ("start_date", "2026-02-30"), ("start_date", "2026-W01-1"),
    ("start_date", "2026-1-02"), ("start_date", "2026-01-02T00:00:00Z"),
    ("resolved_date", "2026-01-03"), ("resolved_date", "bad date"),
    ("deleted_date", "bad stamp"),
])
def test_malformed_or_mismatched_problem_refuses_entire_page(field: str, value: object):
    case = Harness({"results": [PROBLEM, {**PROBLEM, "id": 951, field: value}], "next": None})
    rejected(case.port.problems(930))
    assert len(case.calls) == 2


@pytest.mark.parametrize("field", ["id", "patient", "practice", "description", "status",
    "start_date", "deleted_date"])
def test_missing_identity_or_required_clinical_field_refuses_page(field: str):
    row = dict(PROBLEM)
    del row[field]
    case = Harness({"results": [row]})
    rejected(case.port.problems(930))


def test_deleted_problem_is_unavailable_and_not_silently_omitted():
    case = Harness({"results": [PROBLEM, {**PROBLEM, "id": 951,
        "deleted_date": "2026-10-24T12:00:00Z"}]})
    rejected(case.port.problems(930), "record_unavailable")


@pytest.mark.parametrize("status", ["Active", "Controlled", "Resolved"])
@pytest.mark.parametrize("verification", ["confirmed", "differential", "entered_in_error",
    "provisional", "refuted", "unconfirmed", "", None])
def test_official_statuses_and_verification_are_preserved(status: str, verification: str | None):
    case = Harness({"results": [{**PROBLEM, "status": status,
        "verification_status": verification, "description": " " + "x" * 198 + " "}]})
    row = case.read().rows[0]
    assert isinstance(row, ElationProblem)
    assert row.status == status and row.verification_status == verification
    assert row.description == " " + "x" * 198 + " "


def test_optional_fields_absent_and_resolved_date_follow_documented_shape():
    row = {key: value for key, value in PROBLEM.items()
        if key not in {"verification_status", "resolved_date", "dx", "synopsis"}}
    case = Harness({"results": [row, {**row, "id": 951, "status": "Resolved",
        "resolved_date": "2026-10-24"}]})
    first, second = case.read().rows
    assert isinstance(first, ElationProblem) and isinstance(second, ElationProblem)
    assert first.verification_status is None and first.resolved_date is None
    assert second.resolved_date == date(2026, 10, 24)


@pytest.mark.parametrize("rows", [[PROBLEM, PROBLEM], [PROBLEM, None], [PROBLEM, 1],
    [{**PROBLEM, "id": 950 + i} for i in range(26)], "not a list"])
def test_duplicate_malformed_or_oversized_result_sets_are_rejected(rows: object):
    case = Harness({"results": rows})
    rejected(case.port.problems(930))


@pytest.mark.parametrize("metadata,coverage,total", [
    ({}, "unknown", None), ({"count": 1}, "unknown", 1),
    ({"count": 4}, "unknown", 4), ({"next": None}, "end_of_results", None),
    ({"next": None, "previous": None, "count": 1}, "end_of_results", 1),
    ({"next": ORIGIN + PATH + "?offset=25"}, "more_rows_available", None),
    ({"next": ORIGIN + PATH + "?patient=930&practice=910&limit=25&offset=25", "count": 26},
        "more_rows_available", 26),
])
def test_single_page_coverage_honors_only_supplied_metadata_and_never_follows(
        metadata: dict[str, object], coverage: str, total: int | None):
    case = Harness({"results": [PROBLEM], **metadata})
    result = case.read()
    assert result.coverage == coverage and result.total_count == total
    assert result.next_cursor is None and len(result.rows) == 1
    assert len(case.calls) == 2
    assert "offset=" not in str(asdict(result))


@pytest.mark.parametrize("metadata", [
    {"count": None}, {"count": True}, {"count": -1}, {"count": 0},
    {"count": MAX_ID + 1}, {"count": "1"}, {"next": None, "count": 2},
    {"next": ORIGIN + PATH + "?offset=25", "count": 1},
    {"previous": ORIGIN + PATH + "?offset=0"}, {"next": ""}, {"next": False},
    {"unexpected": "private provider detail"},
])
def test_inconsistent_or_unknown_page_metadata_is_rejected(metadata: dict[str, object]):
    case = Harness({"results": [PROBLEM], **metadata})
    rejected(case.port.problems(930))


@pytest.mark.parametrize("url", [
    "http://sandbox.elationemr.com/api/2.0/problems/?offset=25",
    "https://example.invalid/api/2.0/problems/?offset=25",
    ORIGIN + ":443" + PATH + "?offset=25", ORIGIN + PATH + "?offset=25#fragment",
    "https://user@sandbox.elationemr.com" + PATH + "?offset=25",
    ORIGIN + "/api/2.0/patients/?offset=25", ORIGIN + PATH + "?cursor=opaque",
    ORIGIN + PATH + "?offset=25&cursor=opaque", ORIGIN + PATH + "?offset=25&offset=50",
    ORIGIN + PATH + "?offset=25&patient=931", ORIGIN + PATH + "?offset=25&practice=911",
    ORIGIN + PATH + "?offset=25&limit=100", ORIGIN + PATH + "?offset=25&unknown=1",
    ORIGIN + PATH + "?offset=0", ORIGIN + PATH + "?offset=-1",
    ORIGIN + PATH + "?offset=01", ORIGIN + PATH + "?offset=1.5",
    ORIGIN + PATH + "?offset=", ORIGIN + PATH + "?offset=25&broken",
    ORIGIN + PATH + "?offset=" + str(MAX_ID + 1),
    ORIGIN + PATH + "?offset=" + "1" * 2048, ORIGIN + PATH + "?offset=25\n",
])
def test_unsupported_continuation_is_refused_without_following(url: str):
    case = Harness({"results": [PROBLEM], "next": url})
    rejected(case.port.problems(930))
    assert len(case.calls) == 2


def test_empty_and_full_boundary_pages_do_not_claim_a_complete_chart():
    empty = Harness({"results": [], "next": None, "count": 0}).read()
    assert empty.rows == () and empty.coverage == "end_of_results" and empty.total_count == 0
    full = Harness({"results": [{**PROBLEM, "id": 950 + i} for i in range(25)]}).read()
    assert len(full.rows) == 25 and full.coverage == "unknown"
    rejected(Harness({"results": [], "next": ORIGIN + PATH + "?offset=25"}).port.problems(930))


def test_current_authority_is_required_before_and_after_provider_io():
    case = Harness()
    case.allowed = False
    rejected(case.port.problems(930), "access_denied")
    assert case.calls == [] and case.credential_calls == []
    case.allowed = True

    def revoke(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=TOKEN)
        case.allowed = False
        return httpx.Response(200, json=case.payload)

    case.handler = revoke
    rejected(case.port.problems(930), "access_denied")
    assert len(case.calls) == 2 and case.port._token is None


def test_rotation_is_detected_even_with_a_cached_four_scope_token():
    case = Harness()

    async def scenario() -> None:
        await case.port.problems(930)
        await case.port.problems(930)
        case.credentials = replace(case.credentials, client_secret=SecretStr("synthetic-rotated"))
        with pytest.raises(ElationReadError, match="^connection_changed$"):
            await case.port.problems(930)

    asyncio.run(scenario())
    assert [call.method for call in case.calls] == ["POST", "GET", "GET"]
    assert len(case.credential_calls) == 3 and case.port._token is None
    case = Harness()
    case.credentials = replace(case.credentials,
        scope_sha256=replace(SCOPE, credential_generation=UUID(int=5)).commitment())
    rejected(case.port.problems(930), "connection_changed")
    assert case.calls == []


@pytest.mark.parametrize("status,code", [(401, "authentication_required"),
    (403, "permission_denied"), (404, "record_unavailable"), (429, "rate_limited"),
    (503, "unavailable"), (302, "invalid_response")])
def test_problem_http_failures_have_closed_errors_and_no_retry(status: int, code: str):
    def send(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=TOKEN) if request.method == "POST" else httpx.Response(
            status, json={"detail": "private provider details"})

    case = Harness(handler=send)
    rejected(case.port.problems(930), code)
    assert len(case.calls) == 2


@pytest.mark.parametrize("mode,code", [("timeout", "timeout"), ("size", "response_too_large"),
    ("duplicate-key", "invalid_response"), ("encoding", "invalid_response")])
def test_problem_responses_keep_shared_transport_bounds(mode: str, code: str):
    def send(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=TOKEN)
        if mode == "timeout":
            raise httpx.ReadTimeout("private provider details", request=request)
        if mode == "size":
            return httpx.Response(200, content=b" " * (MAX_BODY + 1),
                headers={"content-type": "application/json"})
        if mode == "duplicate-key":
            return httpx.Response(200, content=b'{"results":[],"results":[]}',
                headers={"content-type": "application/json"})
        return httpx.Response(200, json={"results": []}, headers={"content-encoding": "br"})

    case = Harness(handler=send)
    rejected(case.port.problems(930), code)
    assert len(case.calls) == 2


def test_problem_commitment_binds_projection_count_coverage_but_excludes_unused_fields():
    unknown = Harness({"results": [PROBLEM]}).read()
    counted = Harness({"results": [PROBLEM], "count": 1}).read()
    ended = Harness({"results": [PROBLEM], "count": 1, "next": None}).read()
    changed = Harness({"results": [{**PROBLEM, "description": "Another invented problem"}]}).read()
    ignored = Harness({"results": [{**PROBLEM, "dx": [], "synopsis": "changed unused text"}]}).read()
    assert len({unknown.source_sha256, counted.source_sha256,
        ended.source_sha256, changed.source_sha256}) == 4
    assert unknown.source_sha256 == ignored.source_sha256
    assert unknown.request_sha256 == counted.request_sha256 == ended.request_sha256


def test_legacy_profile_and_record_hash_are_independent_of_opt_in():
    old = Harness(PATIENT, problems_enabled=False, token={**TOKEN, "scope": SCOPES})
    enabled = Harness(PATIENT)
    old_result = asyncio.run(old.port.patient(930))
    enabled_result = asyncio.run(enabled.port.patient(930))
    assert old_result.source_sha256 == enabled_result.source_sha256
    assert old_result.request_sha256 == enabled_result.request_sha256
    assert old_result.scope.commitment() == enabled_result.scope.commitment()
    assert old_result.total_count is None and enabled_result.total_count is None
    assert parse_qs(old.calls[0].content.decode())["scope"] == [SCOPES]
    assert parse_qs(enabled.calls[0].content.decode())["scope"] == [PROBLEM_SCOPES]
