"""Synthetic Athena read tools. No live EHR, tokens, or patient records."""

import json
from uuid import uuid4

import anyio
import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from cosmas_os.adapters.athena_medication_read import RecordedNumber, clinical_dumps
from cosmas_os.api.plugin_catalog import CONTRACT, META
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.plugins.athena import (
    EXPIRED,
    MALFORMED,
    NAMES,
    NOT_CONNECTED,
    STALE,
    TIMEOUT,
    UNSUPPORTED,
    WRONG_PRACTICE,
    command_allowed,
    schedule_command_allowed,
    tool_definitions,
)
from cosmas_os.plugins.runtime import AuthenticatedSession, PluginError, PluginRuntime
from cosmas_os.plugins.server import create_server
from cosmas_os.ports.athena_allergy_ehr import AthenaAllergiesObservation
from cosmas_os.ports.athena_medication_ehr import AthenaMedicationsObservation
from cosmas_os.ports.athena_schedule import AthenaScheduleResponse
from cosmas_os.ports.athena_visit_links import AthenaVisitLinkResponse
from cosmas_os.ports.core_encounters import digest

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
KEY = "athena-read-1"
PRACTICE = "Northwind Family Practice"
DEPARTMENT = "Invented office"
ACCOUNT_SHA = "b" * 64
OTHER_ACCOUNT = "c" * 64
COMMAND = "88888888-8888-4888-8888-888888888888"
COMMAND_SHA = "98" * 32
START = "2026-10-30"
END = "2026-10-30"
HIDDEN = "HIDDEN-SOURCE-TEXT"
ALLERGEN = "Invented allergen"
MEDICATION = "Invented tablet"
ENTRY = "C-invented"
PATIENT_REF = "900000000000000001"
APPOINTMENT_REF = "800000000000000001"
LINK_REF = "athena_visit_link_00000000000000000000000001"


def catalog(*identities):
    return {"_meta": {"ai.cosmas/contract": CONTRACT},
            "tools": [{"_meta": {META: {"id": identity, "feature_enabled": True}}} for identity in identities]}


def connection_snapshot():
    content = {
        "actor_ref": "authority_actor_00000000000000000000000001",
        "tenant_ref": "authority_tenant_00000000000000000000000001",
        "provider_link_ref": "scribe_provider_link_00000000000000000000000001",
        "practice_ref": "practice_00000000000000000000000001",
        "practice_label": PRACTICE,
        "review_sha256": "a" * 64,
    }
    return {**content, "connection_sha256": digest(content)}


CONNECTION_SHA = connection_snapshot()["connection_sha256"]


def account(sha=ACCOUNT_SHA):
    return {
        "account_ref": "184f0f3f-95c4-4e0e-a585-39672d2c1731",
        "account_sha256": sha,
        "department_label": DEPARTMENT,
        "department_timezone": "America/New_York",
        "environment": "preview",
        "state": "practice_enabled",
        "access": "appointments_read_only",
    }


def connection_response(nonce, *, status="connected", account_sha=ACCOUNT_SHA, include_account=True):
    discovery = {
        "action": "connection", "request_nonce": nonce, "checked_at": "2026-10-30T15:00:00+00:00",
        "connection": connection_snapshot(), "account": account(account_sha) if include_account else None,
        "appointments": [], "total_count": None, "next_offset": None, "complete": False, "truncated": False,
    }
    AthenaScheduleResponse.model_validate(discovery)
    return {"contract_version": 1, "action": "athena_connection", "connection_status": status,
            "athena_discovery": discovery}


def appointment_row(status="f"):
    row = {
        "appointment_ref": APPOINTMENT_REF, "patient_ref": PATIENT_REF,
        "source_local_start": "2026-10-30T09:30:00", "department_timezone": "America/New_York",
        "duration_minutes": 30, "source_status": status,
    }
    row["source_sha256"] = digest({"account_sha256": ACCOUNT_SHA, **row})
    return row


def appointments_response(nonce, *, more=False):
    row = appointment_row()
    discovery = {
        "action": "appointments", "request_nonce": nonce, "checked_at": "2026-10-30T15:00:00+00:00",
        "connection": connection_snapshot(), "account": account(), "appointments": [row],
        "total_count": 2 if more else 1, "next_offset": 1 if more else None,
        "complete": not more, "truncated": False,
    }
    AthenaScheduleResponse.model_validate(discovery)
    return {"contract_version": 1, "action": "athena_appointments", "connection_status": "connected",
            "athena_discovery": discovery}


def visit_response(nonce, command_key, command_sha, *, state="linked"):
    applied = state != "not_found"
    link = {
        "contract_version": "1", "action": "status", "request_nonce": nonce,
        "checked_at": "2026-10-30T15:00:00+00:00", "connection": connection_snapshot(), "account": account(),
        "state": state, "source": appointment_row() if state == "linked" else None, "encounter": None,
        "link_ref": LINK_REF if applied else None, "plan_sha256": None,
        "command_key": command_key, "command_sha256": command_sha,
        "operation": None if not applied else "unlink" if state == "removed" else "link",
        "applied": applied,
    }
    parsed = AthenaVisitLinkResponse.model_validate(link)
    return {"contract_version": 1, "action": "athena_visit_status", "connection_status": "connected",
            "athena_visit_link": parsed.model_dump(mode="json")}


def identity():
    return canonical_json({"dob": "04/02/1990", "firstname": "Alex", "lastname": "Example"})


def allergy_section():
    return canonical_json({
        "allergies": [{
            "allergenname": ALLERGEN, "criticality": "low", "id": "private-allergy-ref",
            "reactions": [{"reactionname": "Invented reaction", "severity": "mild"}],
        }],
        "nkda": False,
    })


def medication_section():
    return clinical_dumps({
        "medications": [[{
            "medication": MEDICATION, "medicationentryid": ENTRY, "quantity": RecordedNumber("0.50"),
            "route": "oral", "status": "PEND", "unstructuredsig": "Invented instruction",
        }]],
        "nomedicationsreported": False,
    })


def chart_item(section, *, medication=False):
    item = {
        "handle": ITEM, "sha256": ITEM_SHA, "patient_identity_json": identity(),
        "department_label": DEPARTMENT, "coverage": "returned_section_only",
        "section_json": section, "source_content": HIDDEN, "content_sha256": "ab" * 32,
    }
    if medication:
        item.update(medication_type="ACTIVE", includes_pending=True, includes_ndc=True, includes_rxnorm=True)
    else:
        item["includes_inactive"] = True
    return item


def observation_for(name):
    common = {
        "provider": "athena", "protocol": "core", "mode": "synthetic", "workspace_id": WORKSPACE,
        "practice_label": PRACTICE, "observed_at": "2026-10-30T15:00:00+00:00",
        "parent": {"observation_id": VISIT, "source_sha256": VISIT_SHA, "item_sha256": ITEM_SHA},
    }
    if name == "athena_read_medications":
        return AthenaMedicationsObservation.model_validate({
            **common, "clinical_scope": "medications", "kind": "core_medications",
            "item": chart_item(medication_section(), medication=True),
        }).model_dump(mode="json")
    return AthenaAllergiesObservation.model_validate({
        **common, "kind": "core_allergies", "item": chart_item(allergy_section()),
    }).model_dump(mode="json")


def ehr_status(name, **changes):
    body = {
        "contract_version": 1, "provider": "athena", "protocol": "core", "mode": "synthetic",
        "status": "ready", "connection_id": CONNECTION, "binding_sha256": BINDING,
        "practice_label": PRACTICE, "transport": "mock",
    }
    if name == "athena_read_medications":
        body["clinical_scope"] = "medications"
    return body | changes


def ehr_receipt(name):
    observation = observation_for(name)
    body = {
        "provider": "athena", "protocol": "core", "contract_version": 1, "observation_id": NEW_OBS,
        "observation_key": KEY, "transport": "mock", "connection_id": CONNECTION, "binding_sha256": BINDING,
        "source_sha256": SOURCE, "payload_sha256": payload_hash(observation), "observation": observation,
    }
    if name == "athena_read_medications":
        body["clinical_scope"] = "medications"
    return body


def arguments_for(name):
    if name == "athena_read_appointments":
        return {"connection_sha256": CONNECTION_SHA, "account_sha256": ACCOUNT_SHA,
                "start_date": START, "end_date": END}
    if name == "athena_read_visit_link_status":
        return {"connection_sha256": CONNECTION_SHA, "account_sha256": ACCOUNT_SHA,
                "command_key": COMMAND, "command_sha256": COMMAND_SHA}
    return {"connection_id": CONNECTION, "binding_sha256": BINDING, "workspace_id": WORKSPACE,
            "observation_id": VISIT, "observation_sha256": VISIT_SHA, "item_handle": ITEM,
            "item_sha256": ITEM_SHA, "idempotency_key": KEY}


def runtime_for(handler, *, workspace=None):
    state = {"revision": "signed-in-session-1"}
    calls = []

    def request(method, url, **options):
        calls.append((method, url, options))
        assert "Authorization" not in options.get("headers", {})
        assert "Cookie" not in options.get("headers", {})
        if url.endswith("/connections/plugins"):
            return httpx.Response(200, json=catalog("workspace.read"))
        if url.endswith("/connections/ehr/reads"):
            assert method == "POST" and options["headers"]["X-Cosmas-Ehr-Read"] == "1"
            assert options["timeout"] == 45 and options["params"] is None
            return handler("ehr", options["json"], state)
        if url.endswith("/connections/cosmaneura/read"):
            assert method == "POST" and options["headers"]["X-Cosmas-Connection-Contract"] == "1"
            assert options["timeout"] == 30 and options["params"] is None
            return handler("schedule", options["json"], state)
        raise AssertionError(url)

    runtime = PluginRuntime("https://fixture.invalid", workspace_id=workspace,
                            session=AuthenticatedSession(request, lambda: state["revision"]))
    return runtime, state, calls


def bodies(calls, suffix):
    return [options["json"] for _method, url, options in calls if url.endswith(suffix)]


def route_for(name):
    return "schedule" if name in {"athena_read_appointments", "athena_read_visit_link_status"} else "ehr"


def success_handler(name, *, more=False):
    def handler(route, body, _state):
        assert "token" not in body and "cursor" not in body and "query" not in body
        if route == "ehr":
            if body["action"] == "status":
                assert body["provider"] == "athena" and body["protocol"] == "core"
                return httpx.Response(200, json=ehr_status(name))
            assert body["idempotency_key"] == KEY
            return httpx.Response(200, json=ehr_receipt(name))
        if body["action"] == "athena_connection":
            return httpx.Response(200, json=connection_response(body["request_nonce"]))
        if name == "athena_read_appointments":
            assert body["offset"] == 0
            return httpx.Response(200, json=appointments_response(body["request_nonce"], more=more))
        assert body["action"] == "athena_visit_status"
        return httpx.Response(200, json=visit_response(
            body["request_nonce"], body["command_key"], body["command_sha256"]))
    return handler


@pytest.mark.parametrize("name", NAMES)
def test_each_read_returns_one_synthetic_page_and_checks_the_account_again(name):
    runtime, _, calls = runtime_for(success_handler(name))
    try:
        page = runtime.call(name, arguments_for(name))["result"]
        shown = json.dumps(page)
        assert page["state"] == "ready" and page["read_only"] is True and page["confirmed"] is True
        assert page["practice"]["label"] == PRACTICE
        assert HIDDEN not in shown and "authority_actor" not in shown and "patient_ref" not in shown
        assert "token" not in shown
        if name == "athena_read_appointments":
            assert page["rows"][0]["status"] == "Booked" and page["more_available"] is False
            assert APPOINTMENT_REF not in shown and PATIENT_REF not in shown
            actions = [body["action"] for body in bodies(calls, "/connections/cosmaneura/read")]
            assert actions == ["athena_connection", "athena_appointments", "athena_connection"]
        elif name == "athena_read_medications":
            assert page["rows"][0]["medication_name"] == MEDICATION
            assert page["rows"][0]["quantity"] == "0.50"
            assert page["patient"]["first_name"] == "Alex" and ENTRY not in shown
            assert page["more_available"] is False
        elif name == "athena_read_allergies":
            assert page["rows"][0]["allergen_name"] == ALLERGEN
            assert page["rows"][0]["reactions"][0]["name"] == "Invented reaction"
            assert "private-allergy-ref" not in shown and page["more_available"] is False
        else:
            assert page["link_state"] == "linked" and "linked" in page["message"]
            assert "rows" not in page and PATIENT_REF not in shown and LINK_REF not in shown
            assert page["more_available"] is False
        if route_for(name) == "ehr":
            actions = [body["action"] for body in bodies(calls, "/connections/ehr/reads")]
            assert actions == ["status", "core_medications" if name == "athena_read_medications" else "core_allergies", "status"]
    finally:
        runtime.close()


def test_wrong_practice_stops_before_the_read():
    def handler(route, body, _state):
        assert route == "schedule" and body["action"] == "athena_connection"
        return httpx.Response(200, json=connection_response(body["request_nonce"]))

    runtime, _, calls = runtime_for(handler)
    try:
        arguments = arguments_for("athena_read_appointments")
        arguments["connection_sha256"] = "d" * 64
        result = runtime.call("athena_read_appointments", arguments)["result"]
        assert result["state"] == "wrong_practice" and result["message"] == WRONG_PRACTICE
        assert "rows" not in result
        assert [body["action"] for body in bodies(calls, "/connections/cosmaneura/read")] == ["athena_connection"]
    finally:
        runtime.close()


@pytest.mark.parametrize("status,detail", [(503, "ehr_read_binding_changed"), (403, "workspace_access_denied")])
def test_expired_or_revoked_access_returns_no_chart(status, detail):
    def handler(route, body, _state):
        if route == "ehr" and body["action"] == "status":
            return httpx.Response(200, json=ehr_status("athena_read_allergies"))
        return httpx.Response(status, json={"detail": detail, "patient": "Alex Example"})

    runtime, _, calls = runtime_for(handler)
    try:
        result = runtime.call("athena_read_allergies", arguments_for("athena_read_allergies"))["result"]
        # An extra chart field beside the closed code is dropped, not shown.
        if status == 403:
            assert result["state"] == "expired" and result["message"] == EXPIRED
        else:
            assert result["state"] == "unavailable"
        assert "Alex" not in json.dumps(result) and "rows" not in result and ALLERGEN not in json.dumps(result)
        assert [body["action"] for body in bodies(calls, "/connections/ehr/reads")] == ["status", "core_allergies"]
    finally:
        runtime.close()


def test_revoked_binding_code_is_the_expired_state():
    def handler(route, body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=ehr_status("athena_read_allergies"))
        return httpx.Response(503, json={"detail": "ehr_read_binding_changed"})

    runtime, _, _calls = runtime_for(handler)
    try:
        result = runtime.call("athena_read_allergies", arguments_for("athena_read_allergies"))["result"]
        assert result == {"state": "expired", "message": EXPIRED, "read_only": True, "confirmed": False}
    finally:
        runtime.close()


def test_revoked_schedule_access_is_the_expired_state():
    def handler(route, body, _state):
        if body["action"] == "athena_connection":
            return httpx.Response(200, json=connection_response(body["request_nonce"]))
        return httpx.Response(403, json={"detail": "core_connection_access_denied", "patient": "Alex Example"})

    runtime, _, _calls = runtime_for(handler)
    try:
        result = runtime.call("athena_read_appointments", arguments_for("athena_read_appointments"))["result"]
        assert result["state"] == "expired" and result["message"] == EXPIRED
        assert "Alex" not in json.dumps(result) and "rows" not in result
    finally:
        runtime.close()


@pytest.mark.parametrize("payload", [
    {"observation": {"kind": "core_allergies", "note": "Alex Example"}},
    {"contract_version": 1, "observation": {"kind": "core_allergies", "patient_id": "Alex Example"}},
])
def test_malformed_api_response_shows_no_chart(payload):
    def handler(route, body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=ehr_status("athena_read_allergies"))
        return httpx.Response(200, json=payload)

    runtime, _, _calls = runtime_for(handler)
    try:
        result = runtime.call("athena_read_allergies", arguments_for("athena_read_allergies"))["result"]
        assert result["state"] == "malformed" and result["message"] == MALFORMED
        assert "Alex" not in json.dumps(result) and "rows" not in result
    finally:
        runtime.close()


def test_duplicate_json_keys_are_malformed():
    def handler(route, body, _state):
        if body["action"] == "athena_connection":
            return httpx.Response(200, json=connection_response(body["request_nonce"]))
        return httpx.Response(200, content=b'{"action":"athena_appointments","action":"other"}',
                              headers={"Content-Type": "application/json"})

    runtime, _, _calls = runtime_for(handler)
    try:
        result = runtime.call("athena_read_appointments", arguments_for("athena_read_appointments"))["result"]
        assert result["state"] == "malformed" and "rows" not in result
    finally:
        runtime.close()


def test_timeout_is_one_read_and_does_not_retry():
    def handler(route, body, _state):
        if body["action"] == "athena_connection":
            return httpx.Response(200, json=connection_response(body["request_nonce"]))
        raise httpx.ReadTimeout("private chart timeout")

    runtime, _, calls = runtime_for(handler)
    try:
        result = runtime.call("athena_read_appointments", arguments_for("athena_read_appointments"))["result"]
        assert result["state"] == "timeout" and result["message"] == TIMEOUT
        assert result["automatic_retry"] is False and "private chart timeout" not in json.dumps(result)
        actions = [body["action"] for body in bodies(calls, "/connections/cosmaneura/read")]
        assert actions == ["athena_connection", "athena_appointments"]
    finally:
        runtime.close()


@pytest.mark.parametrize("name", NAMES)
def test_pagination_reports_the_page_and_does_not_ask_for_the_next_page(name):
    runtime, _, calls = runtime_for(success_handler(name, more=True))
    try:
        page = runtime.call(name, arguments_for(name))["result"]
        assert page["state"] == "ready"
        if name == "athena_read_appointments":
            assert page["more_available"] is True and "more appointments" in page["message"]
            assert "does not ask for the next page" in page["message"]
            schedule = bodies(calls, "/connections/cosmaneura/read")
            assert [body["action"] for body in schedule].count("athena_appointments") == 1
            assert schedule[1]["offset"] == 0
        else:
            assert page["more_available"] is False
            assert "does not ask for another page" in page["message"] or "not a list" in page["message"] or "does not change the link" in page["message"]
            sent = json.dumps(bodies(calls, "/connections/ehr/reads") + bodies(calls, "/connections/cosmaneura/read"))
            assert "cursor" not in sent and "offset" not in sent
    finally:
        runtime.close()


def test_cursor_argument_is_rejected_before_http():
    runtime, _, calls = runtime_for(lambda *_: pytest.fail("must not dispatch"))
    try:
        with pytest.raises(PluginError, match="invalid_tool_arguments"):
            runtime.call("athena_read_appointments", {**arguments_for("athena_read_appointments"), "cursor": "next-page"})
        assert calls == []
    finally:
        runtime.close()


def test_stale_result_after_account_change_discards_the_page():
    seen = {"connection": 0}

    def handler(route, body, _state):
        if body["action"] == "athena_appointments":
            return httpx.Response(200, json=appointments_response(body["request_nonce"]))
        seen["connection"] += 1
        sha = ACCOUNT_SHA if seen["connection"] == 1 else OTHER_ACCOUNT
        return httpx.Response(200, json=connection_response(body["request_nonce"], account_sha=sha))

    runtime, _, calls = runtime_for(handler)
    try:
        result = runtime.call("athena_read_appointments", arguments_for("athena_read_appointments"))["result"]
        assert result["state"] == "stale" and result["message"] == STALE
        shown = json.dumps(result)
        assert "Booked" not in shown and PATIENT_REF not in shown
        actions = [body["action"] for body in bodies(calls, "/connections/cosmaneura/read")]
        assert actions == ["athena_connection", "athena_appointments", "athena_connection"]
    finally:
        runtime.close()


def test_stale_chart_after_binding_change_discards_the_page():
    seen = {"status": 0}

    def handler(route, body, _state):
        if body["action"] == "status":
            seen["status"] += 1
            if seen["status"] == 1:
                return httpx.Response(200, json=ehr_status("athena_read_medications"))
            return httpx.Response(200, json=ehr_status(
                "athena_read_medications", connection_id=OTHER, binding_sha256=OTHER_BINDING))
        return httpx.Response(200, json=ehr_receipt("athena_read_medications"))

    runtime, _, calls = runtime_for(handler)
    try:
        result = runtime.call("athena_read_medications", arguments_for("athena_read_medications"))["result"]
        assert result["state"] == "stale" and result["message"] == STALE
        assert MEDICATION not in json.dumps(result) and NEW_OBS not in json.dumps(result)
        assert len(bodies(calls, "/connections/ehr/reads")) == 3
    finally:
        runtime.close()


def test_stale_result_after_session_account_change_does_not_dispatch_the_read():
    runtime, state, calls = runtime_for(success_handler("athena_read_appointments"))
    original = runtime.session.request

    def change_after_status(method, url, **options):
        result = original(method, url, **options)
        if url.endswith("/connections/cosmaneura/read"):
            state["revision"] = "different-account-session"
        return result

    runtime.session = AuthenticatedSession(change_after_status, runtime.session.current_revision)
    try:
        result = runtime.call("athena_read_appointments", arguments_for("athena_read_appointments"))["result"]
        assert result["state"] == "stale" and result["message"] == STALE
        assert [body["action"] for body in bodies(calls, "/connections/cosmaneura/read")] == ["athena_connection"]
    finally:
        runtime.close()


@pytest.mark.parametrize("status", ["not_configured", "setup_required"])
def test_not_connected_is_plain_language_and_does_not_read(status):
    runtime, _, calls = runtime_for(lambda route, body, _state: httpx.Response(
        200, json=ehr_status("athena_read_allergies", status=status, connection_id=None,
                             binding_sha256=None, practice_label=None)))
    try:
        result = runtime.call("athena_read_allergies", arguments_for("athena_read_allergies"))["result"]
        assert result["state"] == "not_connected" and result["message"] == NOT_CONNECTED
        assert "not connected" in result["message"] and "rows" not in result
        assert [body["action"] for body in bodies(calls, "/connections/ehr/reads")] == ["status"]
    finally:
        runtime.close()


def test_schedule_without_a_core_account_is_not_connected():
    def handler(route, body, _state):
        assert body["action"] == "athena_connection"
        return httpx.Response(409, json={"detail": "core_connection_required"})

    runtime, _, calls = runtime_for(handler)
    try:
        result = runtime.call("athena_read_visit_link_status", arguments_for("athena_read_visit_link_status"))["result"]
        assert result["state"] == "not_connected" and result["message"] == NOT_CONNECTED
        assert [body["action"] for body in bodies(calls, "/connections/cosmaneura/read")] == ["athena_connection"]
    finally:
        runtime.close()


def test_unsupported_medication_flag_is_plain_language():
    runtime, _, calls = runtime_for(lambda route, body, _state: httpx.Response(
        200, json=ehr_status("athena_read_medications", status="not_enabled", connection_id=None,
                             binding_sha256=None, practice_label=None)))
    try:
        result = runtime.call("athena_read_medications", arguments_for("athena_read_medications"))["result"]
        assert result["state"] == "unsupported" and result["message"] == UNSUPPORTED
        assert "not supported" in result["message"]
        assert [body["action"] for body in bodies(calls, "/connections/ehr/reads")] == ["status"]
    finally:
        runtime.close()


@pytest.mark.parametrize("name,status,detail", [
    ("athena_read_allergies", 404, "ehr_read_unavailable"),
    ("athena_read_visit_link_status", 404, "core_connection_unavailable"),
])
def test_disabled_route_is_unsupported(name, status, detail):
    runtime, _, calls = runtime_for(lambda route, body, _state: httpx.Response(status, json={"detail": detail}))
    try:
        result = runtime.call(name, arguments_for(name))["result"]
        assert result["state"] == "unsupported" and result["message"] == UNSUPPORTED
        assert calls
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
        assert "cursor" not in row["inputSchema"]["properties"]
        assert "query" not in row["inputSchema"]["properties"]
        assert "offset" not in row["inputSchema"]["properties"]


@pytest.mark.parametrize("body", [
    {"action": "review", "provider": "athena", "protocol": "core"},
    {"action": "core_patients", "provider": "athena", "protocol": "core", "connection_id": CONNECTION,
     "binding_sha256": BINDING, "workspace_id": WORKSPACE, "idempotency_key": KEY},
    {"action": "core_allergies", "provider": "athena", "protocol": "core", "connection_id": CONNECTION,
     "binding_sha256": BINDING, "workspace_id": WORKSPACE, "observation_id": VISIT,
     "observation_sha256": VISIT_SHA, "item_handle": ITEM, "item_sha256": ITEM_SHA,
     "idempotency_key": KEY, "query": "patients where name = 'Alex'"},
    {"action": "observe", "provider": "athena", "protocol": "core"},
])
def test_session_refuses_chart_writes_and_free_form_queries(body):
    assert command_allowed(body) is False
    runtime, _, calls = runtime_for(lambda *_: pytest.fail("must not dispatch"))
    try:
        with pytest.raises(PluginError):
            runtime.request("POST", "/connections/ehr/reads", headers={"X-Cosmas-Ehr-Read": "1"},
                            body=body, timeout=45, closed_detail=True)
        assert calls == []
    finally:
        runtime.close()


@pytest.mark.parametrize("body", [
    {"action": "athena_visit_link", "request_nonce": str(uuid4()), "connection_sha256": "a" * 64,
     "account_sha256": ACCOUNT_SHA, "confirmed": True},
    {"action": "athena_visit_unlink", "request_nonce": str(uuid4()), "connection_sha256": "a" * 64,
     "account_sha256": ACCOUNT_SHA},
    {"action": "athena_appointments", "request_nonce": str(uuid4()), "connection_sha256": "a" * 64,
     "account_sha256": ACCOUNT_SHA, "start_date": START, "end_date": END, "offset": 1},
    {"action": "connect", "request_nonce": str(uuid4())},
])
def test_session_refuses_booking_linking_and_later_pages(body):
    assert schedule_command_allowed(body) is False
    runtime, _, calls = runtime_for(lambda *_: pytest.fail("must not dispatch"))
    try:
        with pytest.raises(PluginError):
            runtime.request("POST", "/connections/cosmaneura/read",
                            headers={"X-Cosmas-Connection-Contract": "1"},
                            body=body, timeout=30, closed_detail=True)
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
        arguments = arguments_for("athena_read_allergies")
        arguments["workspace_id"] = OTHER
        with pytest.raises(PluginError, match="workspace_outside_session"):
            runtime.call("athena_read_allergies", arguments)
        assert calls == []
    finally:
        runtime.close()


@pytest.mark.asyncio
async def test_mcp_lists_athena_reads_as_read_only():
    runtime, _, _calls = runtime_for(lambda *_: pytest.fail("list must not read Athena"))
    server = create_server(runtime)
    try:
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as group:
                group.start_soon(server.run, *server_streams, server.create_initialization_options())
                async with ClientSession(*client_streams) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    names = [row.name for row in listed.tools]
                    assert names[-4:] == list(NAMES)
                    for row in listed.tools:
                        if row.name in NAMES:
                            assert row.annotations.read_only_hint is True
                            assert row.annotations.destructive_hint is False
                group.cancel_scope.cancel()
    finally:
        runtime.close()
