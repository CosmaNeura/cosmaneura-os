"""Synthetic Elation read tools. No live EHR, tokens, or patient records."""

import json
from uuid import uuid4

import anyio
import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from cosmas_os.api.plugin_catalog import CONTRACT, META
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.plugins.elation import (
    EXPIRED,
    MALFORMED,
    NAMES,
    NOT_CONNECTED,
    STALE,
    TIMEOUT,
    UNSUPPORTED,
    WRONG_PRACTICE,
    command_allowed,
    tool_definitions,
)
from cosmas_os.plugins.runtime import AuthenticatedSession, PluginError, PluginRuntime
from cosmas_os.plugins.server import create_server
from cosmas_os.ports.ehr_reads import (
    MedicationsObservation,
    ProblemsObservation,
    WindowObservation,
)
from cosmas_os.ports.elation_lab_ehr import LabReportsObservation

CONNECTION = "33333333-3333-4333-8333-333333333333"
OTHER = "22222222-2222-4222-8222-222222222222"
BINDING = "ab" * 32
OTHER_BINDING = "ff" * 32
VISIT = "44444444-4444-4444-8444-444444444444"
VISIT_SHA = "cd" * 32
ITEM = "55555555-5555-4555-8555-555555555555"
ITEM_SHA = "ef" * 32
WORKSPACE = "66666666-6666-4666-8666-666666666666"
NEW_OBS = "77777777-7777-4777-8777-777777777777"
SOURCE = "12" * 32
KEY = "elation-read-1"
START = "2026-10-30T05:00:00+00:00"
END = "2026-10-31T05:00:00+00:00"
PRACTICE = {"label": "Northwind Family Practice", "timezone": "America/Chicago"}
SENTINEL = "Invented seasonal example"


def catalog(*identities):
    return {"_meta": {"ai.cosmas/contract": CONTRACT},
            "tools": [{"_meta": {META: {"id": identity, "feature_enabled": True}}} for identity in identities]}


def status_body(capability=None, value="available", **changes):
    body = {
        "contract_version": 1, "provider": "elation", "mode": "synthetic", "status": "ready",
        "connection_id": CONNECTION, "binding_sha256": BINDING, "practice": dict(PRACTICE),
        "installation": None, "transport": "mock",
    }
    if capability:
        body[capability] = value
    return body | changes


def disconnected(name, status="not_configured"):
    capability = {"elation_read_problems": "problems", "elation_read_medications": "medications",
                  "elation_read_labs": "labs"}.get(name)
    value = "not_enabled" if status == "not_enabled" else "not_configured"
    return status_body(capability, value, status=status, connection_id=None, binding_sha256=None, practice=None)


def appointment_arguments():
    return {"connection_id": CONNECTION, "binding_sha256": BINDING, "starts_at": START, "ends_at": END,
            "idempotency_key": KEY}


def visit_arguments(name):
    arguments = {"connection_id": CONNECTION, "binding_sha256": BINDING, "observation_id": VISIT,
                 "observation_sha256": VISIT_SHA, "item_handle": ITEM, "item_sha256": ITEM_SHA,
                 "idempotency_key": KEY}
    if name == "elation_read_labs":
        arguments["workspace_id"] = WORKSPACE
    return arguments


def arguments_for(name):
    return appointment_arguments() if name == "elation_read_appointments" else visit_arguments(name)


def window():
    return {"starts_at": START, "ends_at": END}


def patient():
    return {"first_name": "Alex", "last_name": "Example", "birth_date": "1990-04-02"}


def medication_row():
    return {"medication_name": "Invented medication", "strength": None, "route": None, "form": None,
            "directions": None, "medication_type": None, "order_type": None, "is_doc_med": None,
            "is_permanent": None, "start_date": None, "document_date": None, "signed_date": None,
            "deleted_date": None, "discontinue_date": None, "signature_state": "unknown",
            "discontinuation_state": "unknown", "deletion_state": "unknown"}


def observation_for(name, *, more=False):
    common = {"provider": "elation", "mode": "synthetic", "practice": dict(PRACTICE),
              "observed_at": "2026-10-30T15:00:00+00:00", "window": window(), "coverage": "end_of_results"}
    if name == "elation_read_appointments":
        return WindowObservation.model_validate({
            **common, "kind": "window", "coverage": "more_rows_available" if more else "end_of_results",
            "items": [{"handle": ITEM, "sha256": ITEM_SHA, "starts_at": "2026-10-30T15:00:00+00:00",
                       "ends_at": "2026-10-30T15:30:00+00:00", "status": "Scheduled", "selectable": True}],
        }).model_dump(mode="json")
    if name == "elation_read_problems":
        return ProblemsObservation.model_validate({
            **common, "kind": "verified_problems",
            "parent": {"observation_id": VISIT, "source_sha256": VISIT_SHA, "item_sha256": ITEM_SHA},
            "item": {"handle": ITEM, "sha256": ITEM_SHA, "starts_at": "2026-10-30T15:00:00+00:00",
                     "ends_at": "2026-10-30T15:30:00+00:00", "status": "Scheduled", "patient": patient(),
                     "problems": {"coverage": "more_rows_available" if more else "end_of_results",
                                  "total_count": 2 if more else 1,
                                  "items": [{"description": SENTINEL, "status": "Active",
                                             "start_date": "2020-01-15", "resolved_date": None,
                                             "verification_status": "unconfirmed"}]}},
        }).model_dump(mode="json")
    if name == "elation_read_medications":
        return MedicationsObservation.model_validate({
            **common, "kind": "verified_medications",
            "parent": {"observation_id": VISIT, "source_sha256": VISIT_SHA, "item_sha256": ITEM_SHA},
            "item": {"handle": ITEM, "sha256": ITEM_SHA, "starts_at": "2026-10-30T15:00:00+00:00",
                     "ends_at": "2026-10-30T15:30:00+00:00", "status": "Scheduled", "patient": patient(),
                     "medications": {"coverage": "more_rows_available" if more else "end_of_results",
                                     "total_count": 2 if more else 1, "items": [medication_row()]}},
        }).model_dump(mode="json")
    return LabReportsObservation.model_validate({
        "kind": "lab_reports", "provider": "elation", "mode": "synthetic", "workspace_id": WORKSPACE,
        "practice": dict(PRACTICE), "window": window(), "observed_at": "2026-10-30T15:00:00+00:00",
        "patient_identity_json": canonical_json({"dob": "1990-04-02", "first_name": "Alex", "last_name": "Example"}),
        "parent": {"observation_id": VISIT, "source_sha256": VISIT_SHA, "item_sha256": ITEM_SHA},
        "coverage": "more_rows_available" if more else "returned_page_only",
        "returned_report_count": 1, "other_report_count": 0, "reported_total": "2" if more else "1",
        "items": [{"handle": str(uuid4()), "sha256": "98" * 32,
                   "metadata_json": canonical_json({"custom_title": SENTINEL, "report_type": "Lab"})}],
    }).model_dump(mode="json")


def receipt(name, *, more=False):
    observation = observation_for(name, more=more)
    return {"contract_version": 1, "observation_id": NEW_OBS, "observation_key": KEY, "transport": "mock",
            "connection_id": CONNECTION, "binding_sha256": BINDING, "source_sha256": SOURCE,
            "payload_sha256": payload_hash(observation), "observation": observation}


def capability_for(name):
    return {"elation_read_problems": "problems", "elation_read_medications": "medications",
            "elation_read_labs": "labs"}.get(name)


def runtime_for(handler, *, workspace=None):
    state = {"revision": "signed-in-session-1"}
    calls = []

    def request(method, url, **options):
        calls.append((method, url, options))
        assert "Authorization" not in options.get("headers", {})
        assert "Cookie" not in options.get("headers", {})
        if url.endswith("/connections/plugins"):
            return httpx.Response(200, json=catalog("workspace.read"))
        assert method == "POST" and url.endswith("/connections/ehr/reads")
        assert options["headers"]["X-Cosmas-Ehr-Read"] == "1"
        assert options["params"] is None
        return handler(options["json"], state)

    runtime = PluginRuntime("https://fixture.invalid", workspace_id=workspace,
                            session=AuthenticatedSession(request, lambda: state["revision"]))
    return runtime, state, calls


def ehr_calls(calls):
    return [body for _method, url, options in calls if url.endswith("/connections/ehr/reads")
            for body in (options["json"],)]


@pytest.mark.parametrize("name", NAMES)
def test_each_read_returns_one_synthetic_page_and_checks_the_account_again(name):
    def handler(body, _state):
        if body["action"] == "status":
            assert body["provider"] == "elation"
            assert "cursor" not in body and "query" not in body and "token" not in body
            return httpx.Response(200, json=status_body(capability_for(name)))
        assert body["action"] == {"elation_read_appointments": "observe", "elation_read_problems": "problems",
                                  "elation_read_medications": "medications", "elation_read_labs": "lab_reports"}[name]
        assert body["provider"] == "elation" and body["idempotency_key"] == KEY
        return httpx.Response(200, json=receipt(name))

    runtime, _, calls = runtime_for(handler)
    try:
        result = runtime.call(name, arguments_for(name))
        page = result["result"]
        assert page["state"] == "ready" and page["read_only"] is True and page["confirmed"] is True
        assert page["practice"] == PRACTICE and page["rows"] and page["more_available"] is False
        shown = json.dumps(page)
        if name == "elation_read_problems":
            assert SENTINEL in shown
        elif name == "elation_read_medications":
            assert "Invented medication" in shown
        elif name == "elation_read_labs":
            assert SENTINEL in shown
        assert "patient_id" not in shown and "token" not in shown
        bodies = ehr_calls(calls)
        assert [body["action"] for body in bodies] == ["status",
            {"elation_read_appointments": "observe", "elation_read_problems": "problems",
             "elation_read_medications": "medications", "elation_read_labs": "lab_reports"}[name], "status"]
    finally:
        runtime.close()


def test_wrong_practice_stops_before_the_read():
    def handler(body, _state):
        assert body["action"] == "status"
        return httpx.Response(200, json=status_body())

    runtime, _, calls = runtime_for(handler)
    try:
        arguments = appointment_arguments()
        arguments["connection_id"] = OTHER
        result = runtime.call("elation_read_appointments", arguments)["result"]
        assert result["state"] == "wrong_practice" and result["message"] == WRONG_PRACTICE
        assert "rows" not in result and [body["action"] for body in ehr_calls(calls)] == ["status"]
    finally:
        runtime.close()


@pytest.mark.parametrize("status,detail", [(503, "ehr_read_binding_changed"), (403, "workspace_access_denied")])
def test_expired_or_revoked_access_returns_no_chart(status, detail):
    def handler(body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=status_body("problems"))
        return httpx.Response(status, json={"detail": detail, "patient": "Alex Example"})

    runtime, _, calls = runtime_for(handler)
    try:
        result = runtime.call("elation_read_problems", visit_arguments("elation_read_problems"))["result"]
        # An extra chart field beside the closed code is dropped, not shown.
        if status == 403:
            assert result["state"] == "expired" and result["message"] == EXPIRED
        else:
            assert result["state"] == "unavailable"
        assert "Alex" not in json.dumps(result) and "rows" not in result and SENTINEL not in json.dumps(result)
        assert [body["action"] for body in ehr_calls(calls)] == ["status", "problems"]
    finally:
        runtime.close()


def test_revoked_binding_code_is_the_expired_state():
    def handler(body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=status_body())
        return httpx.Response(503, json={"detail": "ehr_read_binding_changed"})

    runtime, _, _calls = runtime_for(handler)
    try:
        result = runtime.call("elation_read_appointments", appointment_arguments())["result"]
        assert result == {"state": "expired", "message": EXPIRED, "read_only": True, "confirmed": False}
    finally:
        runtime.close()


@pytest.mark.parametrize("payload", [
    {"observation": {"kind": "window", "note": "Alex Example"}},
    {"contract_version": 1, "observation": {"kind": "window", "items": [{"patient_id": "Alex Example"}]}},
])
def test_malformed_api_response_shows_no_chart(payload):
    def handler(body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=status_body())
        return httpx.Response(200, json=payload)

    runtime, _, _calls = runtime_for(handler)
    try:
        result = runtime.call("elation_read_appointments", appointment_arguments())["result"]
        assert result["state"] == "malformed" and result["message"] == MALFORMED
        assert "Alex" not in json.dumps(result) and "rows" not in result
    finally:
        runtime.close()


def test_duplicate_json_keys_are_malformed():
    def handler(body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=status_body())
        return httpx.Response(200, content=b'{"observation":{"kind":"window"},"observation":{"kind":"other"}}',
                              headers={"Content-Type": "application/json"})

    runtime, _, _calls = runtime_for(handler)
    try:
        result = runtime.call("elation_read_appointments", appointment_arguments())["result"]
        assert result["state"] == "malformed" and "rows" not in result
    finally:
        runtime.close()


def test_timeout_is_one_read_and_does_not_retry(name="elation_read_appointments"):
    def handler(body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=status_body())
        raise httpx.ReadTimeout("private chart timeout")

    runtime, _, calls = runtime_for(handler)
    try:
        result = runtime.call(name, appointment_arguments())["result"]
        assert result["state"] == "timeout" and result["message"] == TIMEOUT
        assert result["automatic_retry"] is False and "private chart timeout" not in json.dumps(result)
        assert [body["action"] for body in ehr_calls(calls)] == ["status", "observe"]
    finally:
        runtime.close()


@pytest.mark.parametrize("name", NAMES)
def test_pagination_reports_more_rows_and_does_not_ask_for_the_next_page(name):
    def handler(body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=status_body(capability_for(name)))
        assert "cursor" not in body
        return httpx.Response(200, json=receipt(name, more=True))

    runtime, _, calls = runtime_for(handler)
    try:
        page = runtime.call(name, arguments_for(name))["result"]
        assert page["state"] == "ready" and page["more_available"] is True
        assert "more" in page["message"].lower()
        assert [body["action"] for body in ehr_calls(calls)].count("status") == 2
        assert len(ehr_calls(calls)) == 3
    finally:
        runtime.close()


def test_cursor_argument_is_rejected_before_http():
    runtime, _, calls = runtime_for(lambda *_: pytest.fail("must not dispatch"))
    try:
        with pytest.raises(PluginError, match="invalid_tool_arguments"):
            runtime.call("elation_read_appointments", {**appointment_arguments(), "cursor": "next-page"})
        assert calls == []
    finally:
        runtime.close()


def test_stale_result_after_binding_change_discards_the_page():
    seen = {"status": 0}

    def handler(body, _state):
        if body["action"] == "status":
            seen["status"] += 1
            if seen["status"] == 1:
                return httpx.Response(200, json=status_body("problems"))
            return httpx.Response(200, json=status_body("problems", connection_id=OTHER, binding_sha256=OTHER_BINDING))
        return httpx.Response(200, json=receipt("elation_read_problems"))

    runtime, _, calls = runtime_for(handler)
    try:
        result = runtime.call("elation_read_problems", visit_arguments("elation_read_problems"))["result"]
        assert result["state"] == "stale" and result["message"] == STALE
        assert SENTINEL not in json.dumps(result) and NEW_OBS not in json.dumps(result)
        assert len(ehr_calls(calls)) == 3
    finally:
        runtime.close()


def test_stale_result_after_session_account_change_does_not_dispatch_the_read():
    runtime, state, calls = runtime_for(lambda body, _state: httpx.Response(200, json=status_body()))
    original = runtime.session.request

    def change_after_status(method, url, **options):
        result = original(method, url, **options)
        if url.endswith("/connections/ehr/reads"):
            state["revision"] = "different-account-session"
        return result

    runtime.session = AuthenticatedSession(change_after_status, runtime.session.current_revision)
    try:
        result = runtime.call("elation_read_appointments", appointment_arguments())["result"]
        assert result["state"] == "stale" and result["message"] == STALE
        assert [body["action"] for body in ehr_calls(calls)] == ["status"]
    finally:
        runtime.close()


@pytest.mark.parametrize("status", ["not_configured", "setup_required"])
def test_not_connected_is_plain_language_and_does_not_read(status):
    runtime, _, calls = runtime_for(lambda *_: httpx.Response(200, json=disconnected("elation_read_appointments", status)))
    try:
        result = runtime.call("elation_read_appointments", appointment_arguments())["result"]
        assert result["state"] == "not_connected" and result["message"] == NOT_CONNECTED
        assert "not connected" in result["message"] and "rows" not in result
        assert [body["action"] for body in ehr_calls(calls)] == ["status"]
    finally:
        runtime.close()


@pytest.mark.parametrize("name", ["elation_read_problems", "elation_read_medications", "elation_read_labs"])
def test_unsupported_capability_is_plain_language(name):
    capability = capability_for(name)
    runtime, _, calls = runtime_for(
        lambda *_: httpx.Response(200, json=status_body(capability, "not_enabled")))
    try:
        result = runtime.call(name, visit_arguments(name))["result"]
        assert result["state"] == "unsupported" and result["message"] == UNSUPPORTED
        assert "not supported" in result["message"] and [body["action"] for body in ehr_calls(calls)] == ["status"]
    finally:
        runtime.close()


def test_disabled_elation_route_is_unsupported():
    runtime, _, calls = runtime_for(lambda *_: httpx.Response(404, json={"detail": "ehr_read_unavailable"}))
    try:
        result = runtime.call("elation_read_appointments", appointment_arguments())["result"]
        assert result["state"] == "unsupported" and result["message"] == UNSUPPORTED
        assert [body["action"] for body in ehr_calls(calls)] == ["status"]
    finally:
        runtime.close()


def test_tools_are_read_only_and_accept_no_token_cursor_or_free_form_query():
    rows = tool_definitions()
    assert [row["name"] for row in rows] == list(NAMES)
    for row in rows:
        assert row["annotations"]["readOnlyHint"] is True
        assert row["annotations"]["destructiveHint"] is False
        encoded = json.dumps(row).lower()
        assert "token" not in encoded and "authorization" not in encoded and "password" not in encoded
        assert set(row["inputSchema"]["properties"]) <= {
            "connection_id", "binding_sha256", "starts_at", "ends_at", "idempotency_key",
            "observation_id", "observation_sha256", "item_handle", "item_sha256", "workspace_id",
        }
        assert "cursor" not in row["inputSchema"]["properties"]
        assert "query" not in row["inputSchema"]["properties"]


@pytest.mark.parametrize("body", [
    {"action": "install", "provider": "elation", "installation_id": CONNECTION,
     "installation_sha256": BINDING, "idempotency_key": KEY},
    {"action": "verify", "provider": "elation", "connection_id": CONNECTION, "binding_sha256": BINDING,
     "observation_id": VISIT, "observation_sha256": VISIT_SHA, "item_handle": ITEM, "item_sha256": ITEM_SHA,
     "idempotency_key": KEY},
    {"action": "lab_report", "provider": "elation", "connection_id": CONNECTION, "binding_sha256": BINDING,
     "workspace_id": WORKSPACE, "observation_id": VISIT, "observation_sha256": VISIT_SHA,
     "item_handle": ITEM, "item_sha256": ITEM_SHA, "idempotency_key": KEY},
    {"action": "observe", "provider": "elation", "connection_id": CONNECTION, "binding_sha256": BINDING,
     "starts_at": START, "ends_at": END, "idempotency_key": KEY, "cursor": "next"},
    {"action": "observe", "provider": "elation", "connection_id": CONNECTION, "binding_sha256": BINDING,
     "starts_at": START, "ends_at": END, "idempotency_key": KEY, "query": "patients where name = 'Alex'"},
    {"action": "fhir_patients", "provider": "elation"},
])
def test_session_refuses_writes_cursors_and_free_form_queries(body):
    assert command_allowed(body) is False
    runtime, _, calls = runtime_for(lambda *_: pytest.fail("must not dispatch"))
    try:
        with pytest.raises(PluginError):
            runtime.request("POST", "/connections/ehr/reads", headers={"X-Cosmas-Ehr-Read": "1"},
                            body=body, timeout=45, closed_detail=True)
        assert calls == []
    finally:
        runtime.close()


def test_review_route_stays_outside_the_session_adapter():
    runtime, _, calls = runtime_for(lambda *_: pytest.fail("must not dispatch"))
    try:
        with pytest.raises(PluginError):
            runtime.request("POST", f"/workspaces/{WORKSPACE}/ehr-read/review",
                            headers={"X-Cosmas-Ehr-Read": "1"}, body={"action": "review"}, timeout=45)
        assert calls == []
    finally:
        runtime.close()


def test_pinned_workspace_rejects_a_different_encounter_before_http():
    runtime, _, calls = runtime_for(lambda *_: pytest.fail("must not dispatch"), workspace=WORKSPACE)
    try:
        arguments = visit_arguments("elation_read_labs")
        arguments["workspace_id"] = OTHER
        with pytest.raises(PluginError, match="workspace_outside_session"):
            runtime.call("elation_read_labs", arguments)
        assert calls == []
    finally:
        runtime.close()


@pytest.mark.asyncio
async def test_mcp_lists_elation_reads_as_read_only():
    runtime, _, _calls = runtime_for(lambda *_: pytest.fail("list must not read Elation"))
    server = create_server(runtime)
    try:
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as group:
                group.start_soon(server.run, *server_streams, server.create_initialization_options())
                async with ClientSession(*client_streams) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    names = [row.name for row in listed.tools]
                    # Later EHR tools follow Elation, so Elation is not always the tail of the list.
                    start = names.index(NAMES[0])
                    assert names[start:start + len(NAMES)] == list(NAMES)
                    for row in listed.tools:
                        if row.name in NAMES:
                            assert row.annotations.read_only_hint is True
                            assert row.annotations.destructive_hint is False
                group.cancel_scope.cancel()
    finally:
        runtime.close()
