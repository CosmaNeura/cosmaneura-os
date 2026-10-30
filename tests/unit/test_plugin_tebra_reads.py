"""Synthetic Tebra read tools. No live EHR, tokens, or patient records."""

import json
from datetime import date, timedelta

import anyio
import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from cosmas_os.api.plugin_catalog import CONTRACT, META
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.plugins.elation import command_allowed as elation_allowed
from cosmas_os.plugins.runtime import AuthenticatedSession, PluginError, PluginRuntime
from cosmas_os.plugins.server import create_server
from cosmas_os.plugins.tebra import (
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
from cosmas_os.ports.ehr_reads import TebraVerifiedObservation, TebraWindowObservation
from cosmas_os.ports.tebra_fhir_ehr import FhirMedicationsObservation, FhirPatientsObservation

CONNECTION = "33333333-3333-4333-8333-333333333333"
OTHER = "22222222-2222-4222-8222-222222222222"
BINDING = "ab" * 32
OTHER_BINDING = "ff" * 32
VISIT = "44444444-4444-4444-8444-444444444444"
VISIT_SHA = "cd" * 32
ITEM = "55555555-5555-4555-8555-555555555555"
ITEM_SHA = "ef" * 32
VERIFIED_SHA = "45" * 32
MED_SHA = "76" * 32
WORKSPACE = "66666666-6666-4666-8666-666666666666"
NEW_OBS = "77777777-7777-4777-8777-777777777777"
SOURCE = "12" * 32
KEY = "tebra-read-1"
START = "2026-10-30T05:00:00+00:00"
END = "2026-10-31T05:00:00+00:00"
OBSERVED = "2026-10-30T15:00:00+00:00"
PRACTICE = {"label": "Northwind Family Practice", "timezone": "America/Chicago"}
LABEL = "Northwind Family Practice"
SECRETS = ("patient-secret", "MRN-SECRET", "drug-secret", "rx-secret", "hidden context")
ACTIONS = {
    "tebra_read_appointments": "observe",
    "tebra_read_visit": "verify",
    "tebra_read_authorized_patients": "fhir_patients",
    "tebra_read_medications": "fhir_medications",
}
IDENTITY = canonical_json({
    "resourceType": "Patient", "id": "patient-secret", "birthDate": "1980-02-03",
    "identifier": [{"system": "https://invented.invalid/mrn", "value": "MRN-SECRET"}],
    "name": [{"family": "Example", "given": ["Alex"]}],
})


def family(name):
    return "fhir" if name in {"tebra_read_authorized_patients", "tebra_read_medications"} else "practice"


def catalog(*identities):
    return {"_meta": {"ai.cosmas/contract": CONTRACT},
            "tools": [{"_meta": {META: {"id": identity, "feature_enabled": True}}} for identity in identities]}


def practice_status(**changes):
    body = {
        "contract_version": 1, "provider": "tebra", "mode": "synthetic", "status": "ready",
        "connection_id": CONNECTION, "binding_sha256": BINDING, "practice": dict(PRACTICE),
        "installation": None, "transport": "mock",
    }
    return body | changes


def fhir_status(**changes):
    body = {
        "contract_version": 1, "provider": "tebra", "protocol": "fhir", "mode": "synthetic",
        "transport": "mock", "status": "ready", "connection_id": CONNECTION,
        "binding_sha256": BINDING, "display_label": LABEL,
    }
    return body | changes


def status_for(name, **changes):
    return fhir_status(**changes) if family(name) == "fhir" else practice_status(**changes)


def disconnected(name, status="not_configured"):
    if family(name) == "fhir":
        return fhir_status(status=status, connection_id=None, binding_sha256=None, display_label=None)
    return practice_status(status=status, connection_id=None, binding_sha256=None, practice=None)


def appointment_arguments():
    return {"connection_id": CONNECTION, "binding_sha256": BINDING, "starts_at": START, "ends_at": END,
            "idempotency_key": KEY}


def visit_arguments():
    return {**appointment_arguments(), "observation_id": VISIT, "observation_sha256": VISIT_SHA,
            "item_handle": ITEM, "item_sha256": ITEM_SHA, "last_name": "Invented", "birth_date": "1980-02-03"}


def patient_arguments():
    return {"connection_id": CONNECTION, "binding_sha256": BINDING, "workspace_id": WORKSPACE,
            "idempotency_key": KEY}


def medication_arguments():
    return {**patient_arguments(), "observation_id": VISIT, "observation_sha256": VISIT_SHA,
            "item_handle": ITEM, "item_sha256": ITEM_SHA}


def arguments_for(name):
    if name == "tebra_read_appointments":
        return appointment_arguments()
    if name == "tebra_read_visit":
        arguments = visit_arguments()
        arguments.pop("starts_at")
        arguments.pop("ends_at")
        return arguments
    if name == "tebra_read_authorized_patients":
        return patient_arguments()
    return medication_arguments()


def window():
    return {"starts_at": START, "ends_at": END}


def appointment_item():
    return {"handle": ITEM, "sha256": ITEM_SHA, "starts_at": "2026-10-30T15:00:00+00:00",
            "ends_at": "2026-10-30T15:30:00+00:00", "status": "Scheduled", "selectable": True}


def medication_row():
    return {
        "status": "active", "intent": "order", "authored_on": "2025-02-03", "do_not_perform": False,
        "reported_json": canonical_json({"reportedBoolean": False}),
        "request_medication_json": canonical_json({"medicationCodeableConcept": {"text": "Invented medication"}}),
        "medication_name": "Invented medication",
        "medication_json": canonical_json({
            "resourceType": "Medication", "id": "drug-secret", "code": {"text": "Invented medication"},
        }),
        "dosage_instructions_json": canonical_json([{"text": "Invented directions"}]),
        "context_json": canonical_json({"note": [{"text": "hidden context"}]}),
    }


def observation_for(name, *, more=False, empty=False):
    if name == "tebra_read_appointments":
        return TebraWindowObservation.model_validate({
            "kind": "window", "provider": "tebra", "mode": "synthetic", "practice": dict(PRACTICE),
            "observed_at": OBSERVED, "window": window(), "coverage": "returned_rows_only",
            "items": [] if empty else [appointment_item()],
        }).model_dump(mode="json")
    if name == "tebra_read_visit":
        item = appointment_item()
        item.pop("selectable")
        item["sha256"] = VERIFIED_SHA
        item["patient"] = {"full_name": "Alex Example", "birth_date": "1980-02-03"}
        return TebraVerifiedObservation.model_validate({
            "kind": "verified_visit", "provider": "tebra", "mode": "synthetic", "practice": dict(PRACTICE),
            "observed_at": OBSERVED, "window": window(), "coverage": "returned_rows_only", "item": item,
        }).model_dump(mode="json")
    if name == "tebra_read_authorized_patients":
        return FhirPatientsObservation.model_validate({
            "provider": "tebra", "protocol": "fhir", "mode": "synthetic", "kind": "fhir_patients",
            "workspace_id": WORKSPACE, "display_label": LABEL, "observed_at": OBSERVED,
            "coverage": "authorized_candidates_only",
            "items": [] if empty else [{"handle": ITEM, "sha256": ITEM_SHA, "patient_identity_json": IDENTITY}],
        }).model_dump(mode="json")
    return FhirMedicationsObservation.model_validate({
        "provider": "tebra", "protocol": "fhir", "mode": "synthetic", "kind": "fhir_medications",
        "workspace_id": WORKSPACE, "display_label": LABEL, "observed_at": OBSERVED,
        "parent": {"observation_id": VISIT, "source_sha256": VISIT_SHA, "item_sha256": ITEM_SHA},
        "item": {
            "handle": ITEM, "sha256": MED_SHA, "patient_identity_json": IDENTITY,
            "coverage": "more_rows_available" if more else "returned_page_only",
            "reported_total": 2 if more else (0 if empty else 1),
            "warnings": [] if empty else ["invented-warning"],
            "records": [] if empty else [medication_row()],
            "source_content": "Record ID: rx-secret", "content_sha256": "98" * 32,
        },
    }).model_dump(mode="json")


def receipt(name, **kwargs):
    observation = observation_for(name, **kwargs)
    body = {
        "provider": "tebra", "contract_version": 1, "observation_id": NEW_OBS, "observation_key": KEY,
        "transport": "mock", "connection_id": CONNECTION, "binding_sha256": BINDING, "source_sha256": SOURCE,
        "payload_sha256": payload_hash(observation), "observation": observation,
    }
    if family(name) == "fhir":
        body["protocol"] = "fhir"
    return body


def runtime_for(handler, *, workspace=None, plugins=()):
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

    runtime = PluginRuntime("https://fixture.invalid", workspace_id=workspace, plugins=plugins,
                            session=AuthenticatedSession(request, lambda: state["revision"]))
    return runtime, state, calls


def ehr_calls(calls):
    return [body for _method, url, options in calls if url.endswith("/connections/ehr/reads")
            for body in (options["json"],)]


def assert_no_secrets(value):
    shown = json.dumps(value)
    for secret in SECRETS:
        assert secret not in shown
    assert "token" not in shown


@pytest.mark.parametrize("name", NAMES)
def test_each_read_returns_one_synthetic_page_and_checks_the_account_again(name):
    def handler(body, _state):
        assert "cursor" not in body and "query" not in body and "token" not in body
        assert command_allowed(body) is True
        if body["action"] == "status":
            assert body["provider"] == "tebra"
            if family(name) == "fhir":
                assert body["protocol"] == "fhir"
            else:
                assert "protocol" not in body
            return httpx.Response(200, json=status_for(name))
        assert body == {**arguments_for(name), "action": ACTIONS[name], "provider": "tebra",
                        **({"protocol": "fhir"} if family(name) == "fhir" else {})}
        return httpx.Response(200, json=receipt(name))

    runtime, _, calls = runtime_for(handler)
    try:
        result = runtime.call(name, arguments_for(name))
        page = result["result"]
        assert page["state"] == "ready" and page["read_only"] is True and page["confirmed"] is True
        assert page["rows"] and page["more_available"] is False
        assert_no_secrets(page)
        if name == "tebra_read_appointments":
            assert page["practice"] == PRACTICE and "Alex" not in json.dumps(page)
            assert "not a complete schedule" in page["message"]
            assert page["rows"][0]["status"] == "Scheduled" and page["rows"][0]["selectable"] is True
        elif name == "tebra_read_visit":
            assert page["patient"] == {"full_name": "Alex Example", "birth_date": "1980-02-03"}
            assert page["rows"][0]["sha256"] == VERIFIED_SHA
            assert "not a complete schedule" in page["message"]
        elif name == "tebra_read_authorized_patients":
            assert page["rows"][0]["names"] == ["Alex Example"]
            assert page["rows"][0]["birth_date"] == "1980-02-03"
            assert "not a complete patient list" in page["message"]
        else:
            assert page["rows"][0]["medication_name"] == "Invented medication"
            assert page["rows"][0]["directions"] == "Invented directions"
            assert page["rows"][0]["do_not_perform"] is False
            assert page["patient"]["names"] == ["Alex Example"]
            assert page["warnings"] == ["invented-warning"]
            assert "not a complete chart" in page["message"]
        assert [body["action"] for body in ehr_calls(calls)] == ["status", ACTIONS[name], "status"]
    finally:
        runtime.close()


@pytest.mark.parametrize("name", NAMES)
def test_wrong_practice_stops_before_the_read(name):
    def handler(body, _state):
        assert body["action"] == "status"
        return httpx.Response(200, json=status_for(name))

    runtime, _, calls = runtime_for(handler)
    try:
        arguments = arguments_for(name)
        arguments["connection_id"] = OTHER
        result = runtime.call(name, arguments)["result"]
        assert result["state"] == "wrong_practice" and result["message"] == WRONG_PRACTICE
        assert "rows" not in result and [body["action"] for body in ehr_calls(calls)] == ["status"]
        assert_no_secrets(result)
    finally:
        runtime.close()


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("status_code,detail", [
    (503, "ehr_read_binding_changed"),
    (403, "workspace_access_denied"),
])
def test_expired_or_revoked_access_tells_the_user_to_reconnect(name, status_code, detail):
    def handler(body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=status_for(name))
        return httpx.Response(status_code, json={"detail": detail})

    runtime, _, calls = runtime_for(handler)
    try:
        result = runtime.call(name, arguments_for(name))["result"]
        assert result["state"] == "expired" and result["message"] == EXPIRED
        assert "Reconnect" in result["message"] and "rows" not in result
        assert [body["action"] for body in ehr_calls(calls)] == ["status", ACTIONS[name]]
    finally:
        runtime.close()


@pytest.mark.parametrize("name", NAMES)
def test_chart_text_beside_a_closed_error_is_not_shown(name):
    def handler(body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=status_for(name))
        return httpx.Response(503, json={"detail": "ehr_read_binding_changed", "patient": "Alex Example"})

    runtime, _, _calls = runtime_for(handler)
    try:
        result = runtime.call(name, arguments_for(name))["result"]
        assert result["state"] == "unavailable" and "rows" not in result
        assert "Alex" not in json.dumps(result)
    finally:
        runtime.close()


@pytest.mark.parametrize("name", NAMES)
def test_malformed_api_response_shows_no_chart(name):
    def handler(body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=status_for(name))
        return httpx.Response(200, json={"observation": {"kind": "window", "note": "Alex Example"}})

    runtime, _, _calls = runtime_for(handler)
    try:
        result = runtime.call(name, arguments_for(name))["result"]
        assert result["state"] == "malformed" and result["message"] == MALFORMED
        assert "Alex" not in json.dumps(result) and "rows" not in result
    finally:
        runtime.close()


def test_duplicate_json_keys_are_malformed():
    def handler(body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=practice_status())
        return httpx.Response(200, content=b'{"observation":{"kind":"window"},"observation":{"kind":"other"}}',
                              headers={"Content-Type": "application/json"})

    runtime, _, _calls = runtime_for(handler)
    try:
        result = runtime.call("tebra_read_appointments", appointment_arguments())["result"]
        assert result["state"] == "malformed" and "rows" not in result
    finally:
        runtime.close()


@pytest.mark.parametrize("name", NAMES)
def test_timeout_is_one_read_and_does_not_retry(name):
    def handler(body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=status_for(name))
        raise httpx.ReadTimeout("private chart timeout")

    runtime, _, calls = runtime_for(handler)
    try:
        result = runtime.call(name, arguments_for(name))["result"]
        assert result["state"] == "timeout" and result["message"] == TIMEOUT
        assert result["automatic_retry"] is False and "private chart timeout" not in json.dumps(result)
        assert [body["action"] for body in ehr_calls(calls)] == ["status", ACTIONS[name]]
    finally:
        runtime.close()


@pytest.mark.parametrize("name", NAMES)
def test_pagination_does_not_ask_for_another_page(name):
    more = name == "tebra_read_medications"

    def handler(body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=status_for(name))
        assert "cursor" not in body
        return httpx.Response(200, json=receipt(name, more=more))

    runtime, _, calls = runtime_for(handler)
    try:
        page = runtime.call(name, arguments_for(name))["result"]
        assert page["state"] == "ready"
        if more:
            assert page["more_available"] is True and "more" in page["message"].lower()
        else:
            assert page["more_available"] is False and "not a complete" in page["message"].lower()
        assert len(ehr_calls(calls)) == 3
        assert "cursor" not in json.dumps(ehr_calls(calls))
    finally:
        runtime.close()


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("extra", ["cursor", "token", "query", "access_token"])
def test_token_cursor_and_free_form_arguments_are_rejected_before_http(name, extra):
    runtime, _, calls = runtime_for(lambda *_: pytest.fail("must not dispatch"))
    try:
        with pytest.raises(PluginError, match="invalid_tool_arguments"):
            runtime.call(name, {**arguments_for(name), extra: "next-page"})
        assert calls == []
    finally:
        runtime.close()


@pytest.mark.parametrize("name", NAMES)
def test_stale_result_after_binding_change_discards_the_page(name):
    seen = {"status": 0}

    def handler(body, _state):
        if body["action"] == "status":
            seen["status"] += 1
            if seen["status"] == 1:
                return httpx.Response(200, json=status_for(name))
            if family(name) == "fhir":
                return httpx.Response(200, json=status_for(name, connection_id=OTHER, binding_sha256=OTHER_BINDING,
                                                            display_label="Other Invented Practice"))
            return httpx.Response(200, json=status_for(
                name, connection_id=OTHER, binding_sha256=OTHER_BINDING,
                practice={"label": "Other Invented Practice", "timezone": "America/Chicago"}))
        return httpx.Response(200, json=receipt(name))

    runtime, _, calls = runtime_for(handler)
    try:
        result = runtime.call(name, arguments_for(name))["result"]
        assert result["state"] == "stale" and result["message"] == STALE
        assert "rows" not in result and NEW_OBS not in json.dumps(result)
        assert "Invented medication" not in json.dumps(result)
        assert len(ehr_calls(calls)) == 3
    finally:
        runtime.close()


@pytest.mark.parametrize("name", NAMES)
def test_stale_result_after_session_account_change_does_not_dispatch_the_read(name):
    runtime, state, calls = runtime_for(lambda body, _state: httpx.Response(200, json=status_for(name)))
    original = runtime.session.request

    def change_after_status(method, url, **options):
        result = original(method, url, **options)
        if url.endswith("/connections/ehr/reads"):
            state["revision"] = "different-account-session"
        return result

    runtime.session = AuthenticatedSession(change_after_status, runtime.session.current_revision)
    try:
        result = runtime.call(name, arguments_for(name))["result"]
        assert result["state"] == "stale" and result["message"] == STALE
        assert [body["action"] for body in ehr_calls(calls)] == ["status"]
    finally:
        runtime.close()


@pytest.mark.parametrize("name", NAMES)
def test_not_connected_is_plain_language_and_does_not_read(name):
    runtime, _, calls = runtime_for(lambda *_: httpx.Response(200, json=disconnected(name)))
    try:
        result = runtime.call(name, arguments_for(name))["result"]
        assert result["state"] == "not_connected" and result["message"] == NOT_CONNECTED
        assert "not connected" in result["message"] and "rows" not in result
        assert [body["action"] for body in ehr_calls(calls)] == ["status"]
    finally:
        runtime.close()


@pytest.mark.parametrize("name", ["tebra_read_appointments", "tebra_read_visit"])
def test_setup_required_is_not_connected(name):
    runtime, _, calls = runtime_for(lambda *_: httpx.Response(200, json=disconnected(name, "setup_required")))
    try:
        result = runtime.call(name, arguments_for(name))["result"]
        assert result["state"] == "not_connected" and result["message"] == NOT_CONNECTED
        assert [body["action"] for body in ehr_calls(calls)] == ["status"]
    finally:
        runtime.close()


@pytest.mark.parametrize("name", NAMES)
def test_unsupported_status_is_plain_language(name):
    runtime, _, calls = runtime_for(lambda *_: httpx.Response(200, json=disconnected(name, "not_enabled")))
    try:
        result = runtime.call(name, arguments_for(name))["result"]
        assert result["state"] == "unsupported" and result["message"] == UNSUPPORTED
        assert "not supported" in result["message"] and [body["action"] for body in ehr_calls(calls)] == ["status"]
    finally:
        runtime.close()


@pytest.mark.parametrize("name", NAMES)
def test_disabled_route_is_unsupported(name):
    runtime, _, calls = runtime_for(lambda *_: httpx.Response(404, json={"detail": "ehr_read_unavailable"}))
    try:
        result = runtime.call(name, arguments_for(name))["result"]
        assert result["state"] == "unsupported" and result["message"] == UNSUPPORTED
        assert [body["action"] for body in ehr_calls(calls)] == ["status"]
    finally:
        runtime.close()


@pytest.mark.parametrize("name", ["tebra_read_appointments", "tebra_read_authorized_patients", "tebra_read_medications"])
def test_empty_page_does_not_mean_the_chart_is_empty(name):
    def handler(body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=status_for(name))
        return httpx.Response(200, json=receipt(name, empty=True))

    runtime, _, _calls = runtime_for(handler)
    try:
        page = runtime.call(name, arguments_for(name))["result"]
        assert page["state"] == "ready" and page["rows"] == []
        assert "does not mean the chart is empty" in page["message"]
    finally:
        runtime.close()


def test_fhir_grant_change_discards_the_medication_page():
    def handler(body, _state):
        if body["action"] == "status":
            return httpx.Response(200, json=status_for("tebra_read_medications"))
        return httpx.Response(409, json={"detail": "ehr_read_fhir_grant_changed"})

    runtime, _, _calls = runtime_for(handler)
    try:
        result = runtime.call("tebra_read_medications", medication_arguments())["result"]
        assert result["state"] == "stale" and result["message"] == STALE
        assert "rows" not in result and "Invented" not in json.dumps(result)
    finally:
        runtime.close()


def test_tools_are_read_only_and_accept_no_token_cursor_or_free_form_query():
    rows = tool_definitions()
    assert {row["name"] for row in rows} == set(NAMES)
    allowed = {
        "connection_id", "binding_sha256", "starts_at", "ends_at", "idempotency_key",
        "observation_id", "observation_sha256", "item_handle", "item_sha256", "workspace_id",
        "last_name", "birth_date",
    }
    for row in rows:
        assert row["annotations"]["readOnlyHint"] is True
        assert row["annotations"]["destructiveHint"] is False
        encoded = json.dumps(row).lower()
        assert "token" not in encoded and "authorization" not in encoded and "password" not in encoded
        assert set(row["inputSchema"]["properties"]) <= allowed
        assert "cursor" not in row["inputSchema"]["properties"]
        assert "query" not in row["inputSchema"]["properties"]


@pytest.mark.parametrize("body", [
    {"action": "install", "provider": "tebra", "installation_id": CONNECTION,
     "installation_sha256": BINDING, "idempotency_key": KEY},
    {"action": "problems", "provider": "tebra", "connection_id": CONNECTION, "binding_sha256": BINDING,
     "observation_id": VISIT, "observation_sha256": VISIT_SHA, "item_handle": ITEM, "item_sha256": ITEM_SHA,
     "idempotency_key": KEY},
    {"action": "medications", "provider": "tebra", "connection_id": CONNECTION, "binding_sha256": BINDING,
     "observation_id": VISIT, "observation_sha256": VISIT_SHA, "item_handle": ITEM, "item_sha256": ITEM_SHA,
     "idempotency_key": KEY},
    {"action": "review", "provider": "tebra", "protocol": "fhir"},
    {"action": "observe", "provider": "tebra", "connection_id": CONNECTION, "binding_sha256": BINDING,
     "starts_at": START, "ends_at": END, "idempotency_key": KEY, "cursor": "next"},
    {"action": "observe", "provider": "tebra", "connection_id": CONNECTION, "binding_sha256": BINDING,
     "starts_at": START, "ends_at": END, "idempotency_key": KEY, "query": "patients where name = 'Alex'"},
    {"action": "observe", "provider": "tebra", "connection_id": CONNECTION, "binding_sha256": BINDING,
     "starts_at": START, "ends_at": END, "idempotency_key": KEY, "token": "secret-token"},
    {"action": "fhir_patients", "provider": "elation", "protocol": "fhir", "connection_id": CONNECTION,
     "binding_sha256": BINDING, "workspace_id": WORKSPACE, "idempotency_key": KEY},
    {"action": "status", "provider": "tebra", "include_problems": True},
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


def test_elation_and_tebra_allowlists_stay_separate():
    elation_body = {"action": "status", "provider": "elation"}
    tebra_body = {"action": "status", "provider": "tebra"}
    assert elation_allowed(elation_body) is True and command_allowed(elation_body) is False
    assert command_allowed(tebra_body) is True and elation_allowed(tebra_body) is False


def test_review_route_stays_outside_the_session_adapter():
    runtime, _, calls = runtime_for(lambda *_: pytest.fail("must not dispatch"))
    try:
        with pytest.raises(PluginError):
            runtime.request("POST", f"/workspaces/{WORKSPACE}/ehr-read/review",
                            headers={"X-Cosmas-Ehr-Read": "1"},
                            body={"action": "review", "provider": "tebra", "protocol": "fhir"}, timeout=45)
        assert calls == []
    finally:
        runtime.close()


def test_visit_rejects_a_padded_surname_and_a_future_birth_date_before_http():
    runtime, _, calls = runtime_for(lambda *_: pytest.fail("must not dispatch"))
    try:
        padded = visit_arguments()
        padded.pop("starts_at")
        padded.pop("ends_at")
        padded["last_name"] = " Invented"
        with pytest.raises(PluginError, match="invalid_tool_arguments"):
            runtime.call("tebra_read_visit", padded)
        future = dict(padded)
        future["last_name"] = "Invented"
        future["birth_date"] = (date.today() + timedelta(days=1)).isoformat()
        with pytest.raises(PluginError, match="invalid_tool_arguments"):
            runtime.call("tebra_read_visit", future)
        assert calls == []
    finally:
        runtime.close()


@pytest.mark.parametrize("name", ["tebra_read_authorized_patients", "tebra_read_medications"])
def test_pinned_workspace_rejects_a_different_encounter_before_http(name):
    runtime, _, calls = runtime_for(lambda *_: pytest.fail("must not dispatch"), workspace=WORKSPACE)
    try:
        arguments = arguments_for(name)
        arguments["workspace_id"] = OTHER
        with pytest.raises(PluginError, match="workspace_outside_session"):
            runtime.call(name, arguments)
        assert calls == []
    finally:
        runtime.close()


def test_plugin_filter_hides_the_other_record_system():
    runtime, _, _calls = runtime_for(lambda *_: pytest.fail("list must not read Tebra"), plugins=("tebra",))
    try:
        assert {row["name"] for row in runtime.tool_definitions()} == set(NAMES)
        with pytest.raises(PluginError, match="unknown_tool"):
            runtime.call("elation_read_appointments", appointment_arguments())
    finally:
        runtime.close()


@pytest.mark.asyncio
async def test_mcp_lists_tebra_reads_as_read_only():
    runtime, _, _calls = runtime_for(lambda *_: pytest.fail("list must not read Tebra"))
    server = create_server(runtime)
    try:
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as group:
                group.start_soon(server.run, *server_streams, server.create_initialization_options())
                async with ClientSession(*client_streams) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    assert set(NAMES) <= {row.name for row in listed.tools}
                    for row in listed.tools:
                        if row.name in NAMES:
                            assert row.annotations.read_only_hint is True
                            assert row.annotations.destructive_hint is False
                group.cancel_scope.cancel()
    finally:
        runtime.close()
