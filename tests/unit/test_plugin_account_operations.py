"""Callable account descriptors follow closed handlers without human approvals."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cosmas_os.api import google_calendar_schemas as calendar
from cosmas_os.api import google_message_schemas as message
from cosmas_os.api.google_calendar_routes import router as calendar_router
from cosmas_os.api.google_connection_routes import GoogleCommand
from cosmas_os.api.google_message_routes import router as message_router
from cosmas_os.api.microsoft_connection_routes import MicrosoftCommand
from cosmas_os.api.microsoft_connection_routes import router as microsoft_router
from cosmas_os.api.plugin_account_operations import configured, definitions
from cosmas_os.api.plugin_catalog import META, tool
from cosmas_os.application import google_calendar, google_message
from cosmas_os.application import workspace as ws

EXACT_SCHEMAS = {
    "google.message_status": message.Status,
    "google.list_messages": message.ListMessages,
    "google.read_message": message.ReadMessage,
    "google.inspect_message": message.InspectMessage,
    "google.resolve_message": message.ResolveMessage,
    "google.calendar_status": calendar.Status,
    "google.observe_calendar": calendar.Observe,
    "google.inspect_calendar": calendar.Inspect,
    "google.resolve_calendar": calendar.Resolve,
}


def operation(identifier):
    return next(item for item in definitions() if item.id == identifier)


def test_callable_inventory_preserves_current_identity_and_excludes_human_assertions():
    items = definitions()
    assert len(items) == len({item.id for item in items}) == 14
    assert not {"google.mail_headers", "google.calendar_summaries", "microsoft.mail_headers", "microsoft.calendar_summaries"} & {item.id for item in items}
    for item in items:
        assert item.agent_callable and item.deadline_seconds == 45
        assert item.request["additionalProperties"] is False
        assert not {"account_id", "email", "url", "token", "content", "patient_link_id"} & item.request["properties"].keys()
        assert not any(field.startswith("reviewed_") for field in item.request["properties"])
        assert not any(part in item.path for part in ("/review", "/decide", "/execute", "/callback"))
        descriptor = tool(item, True)
        assert descriptor["_meta"][META]["http"]["authentication"] == "current_clerk_jwt"
        assert descriptor["_meta"][META]["external_send"] is False
        assert descriptor["_meta"][META]["account_status"] == "not_checked"
        assert descriptor["_meta"][META]["operation_health"] == "not_checked"


@pytest.mark.parametrize("identifier,model", EXACT_SCHEMAS.items())
def test_google_argument_schema_is_the_actual_closed_handler_model(identifier, model):
    item = operation(identifier)
    assert item.request == model.model_json_schema()
    expected_path = "/connections/google/messages" if item.header == "X-Cosmas-Google-Messages" else "/connections/google/calendar-summaries"
    assert item.path == expected_path


@pytest.mark.parametrize("body,adapter", [
    ({"action": "status"}, message.MESSAGE_COMMAND),
    ({"action": "list", "idempotency_key": "invented-list-1"}, message.MESSAGE_COMMAND),
    ({"action": "read", "idempotency_key": "invented-read-1", "observation_id": str(uuid4()), "observation_sha256": "a" * 64, "message_id": "invented-message"}, message.MESSAGE_COMMAND),
    ({"action": "inspect", "read_id": str(uuid4())}, message.MESSAGE_COMMAND),
    ({"action": "resolve", "idempotency_key": "invented-read-1", "kind": "message"}, message.MESSAGE_COMMAND),
    ({"action": "observe", "idempotency_key": "invented-calendar-1"}, calendar.CALENDAR_COMMAND),
    ({"action": "inspect", "observation_id": str(uuid4())}, calendar.CALENDAR_COMMAND),
    ({"action": "resolve", "idempotency_key": "invented-calendar-1"}, calendar.CALENDAR_COMMAND),
])
def test_real_command_validation_rejects_account_content_and_review_injection(body, adapter):
    assert adapter.validate_python(body).action == body["action"]
    for field, value in (("account_id", str(uuid4())), ("content", "invented replacement"),
                         ("reviewed_untrusted_source", True), ("url", "https://example.invalid")):
        with pytest.raises(ValidationError):
            adapter.validate_python({**body, field: value})


def test_database_recovery_operations_do_not_assert_success_or_repeat_provider_work():
    for name in ("google.resolve_message", "google.resolve_calendar", "google.inspect_message", "google.inspect_calendar"):
        item = operation(name)
        assert item.read_only and not item.public_read
    assert "unconfirmed" in operation("google.resolve_message").completion
    assert "not_found" in operation("google.resolve_calendar").completion
    saved = operation("google.inspect_saved_sources")
    assert saved.method == "GET" and saved.path == "/workspaces/{workspace_id}"
    assert saved.header == "X-Cosmas-Model-Contract"
    assert saved.read_only and "original journal key" in saved.recovery
    assert "human review" in operation("google.read_message").permission[-1]
    # Provider reads also create immutable local observations, so they must not
    # promise the same read-only behavior as database-only recovery.
    assert not operation("google.read_message").read_only
    assert not operation("google.list_messages").read_only
    assert not operation("google.observe_calendar").read_only


def test_separate_feature_gates_never_infer_full_source_access_from_connected_google():
    settings = SimpleNamespace(workspace_available=True, workspace_google_connection_enabled=True,
                               workspace_google_message_available=False, workspace_google_calendar_available=False,
                               workspace_microsoft_connection_enabled=True)
    runtime = SimpleNamespace(google_connection=object(), microsoft_connection=None)
    assert configured(operation("google.connection_status"), settings, runtime)
    assert not configured(operation("google.read_message"), settings, runtime)
    assert not configured(operation("google.observe_calendar"), settings, runtime)
    assert not configured(operation("microsoft.read_mail"), settings, runtime)
    settings.workspace_google_message_available = True
    assert configured(operation("google.read_message"), settings, runtime)
    assert not configured(operation("google.observe_calendar"), settings, runtime)
    runtime.google_connection = None
    assert not configured(operation("google.read_message"), settings, runtime)
    assert configured(operation("google.inspect_saved_sources"), settings, runtime)


def test_status_and_microsoft_reads_never_expand_into_consent_or_write_actions():
    google = operation("google.connection_status")
    assert GoogleCommand.model_validate({"action": "status", "include_capabilities": True}).include_capabilities
    assert google.request["properties"]["include_capabilities"] == {"type": "boolean", "const": True}
    for identifier, action in (("microsoft.connection_status", "status"), ("microsoft.read_mail", "mail"), ("microsoft.read_calendar", "calendar")):
        item = operation(identifier)
        assert item.path == "/connections/microsoft/session" and item.header == "X-Cosmas-Microsoft-Connection"
        assert item.request["properties"]["action"] == {"type": "string", "const": action}
        assert MicrosoftCommand.model_validate({"action": action}).action == action
        assert item.read_only
    assert "no database resolve handler" in operation("microsoft.read_mail").recovery
    assert "Exchange mailbox" in operation("microsoft.connection_status").description


def test_returned_schemas_cannot_change_the_future_allowlist():
    first = operation("google.read_message")
    first.request["properties"]["action"]["const"] = "send"
    assert operation("google.read_message").request["properties"]["action"]["const"] == "read"


@pytest.mark.parametrize("provider", ["google_message", "google_calendar", "microsoft"])
def test_descriptors_call_actual_closed_routes_with_current_server_identity(monkeypatch, provider):
    identity = SimpleNamespace(box_id=str(uuid4()), principal_id=str(uuid4()), external_identity_id=str(uuid4()))
    session = object()
    calls = []
    app = FastAPI()

    @app.exception_handler(ws.WorkspaceError)
    async def refused(_request, error):
        return JSONResponse({"detail": error.code}, status_code=error.status)

    def identity_dependency():
        return identity

    def session_dependency():
        return session

    def gate():
        return None

    def fence(_request, supplied_session, supplied_identity):
        assert supplied_session is session and supplied_identity is identity

    def local_service(*args, **kwargs):
        calls.append((args, kwargs))
        return {"state": "synthetic_local_receipt"}

    service = SimpleNamespace(message_status=local_service, calendar_status=local_service,
                              status=local_service, mail=local_service, calendar=local_service)
    if provider == "microsoft":
        app.include_router(microsoft_router(runtime=lambda: service, identity_dependency=identity_dependency, workspace_gate=gate))
        cases = [("microsoft.connection_status", {"action": "status"}), ("microsoft.read_mail", {"action": "mail"}),
                 ("microsoft.read_calendar", {"action": "calendar"})]
    else:
        module, router = (google_message, message_router) if provider == "google_message" else (google_calendar, calendar_router)
        names = ("list_observed", "read_selected", "inspect_read", "resolve_read") if provider == "google_message" else ("observe", "inspect_observation", "resolve_observation")
        for name in names:
            monkeypatch.setattr(module, name, local_service)
        app.include_router(router(runtime=lambda: service, configuration=lambda: SimpleNamespace(workspace_google_message_available=True,
                           workspace_google_calendar_available=True), identity_dependency=identity_dependency,
                           session_dependency=session_dependency, workspace_gate=gate, fence=fence))
        if provider == "google_message":
            cases = [("google.message_status", {"action": "status"}),
                     ("google.list_messages", {"action": "list", "idempotency_key": "synthetic-list-1"}),
                     ("google.read_message", {"action": "read", "idempotency_key": "synthetic-read-1", "observation_id": str(uuid4()),
                                              "observation_sha256": "a" * 64, "message_id": "synthetic-message"}),
                     ("google.inspect_message", {"action": "inspect", "read_id": str(uuid4())}),
                     ("google.resolve_message", {"action": "resolve", "kind": "message", "idempotency_key": "synthetic-read-1"})]
        else:
            cases = [("google.calendar_status", {"action": "status"}),
                     ("google.observe_calendar", {"action": "observe", "idempotency_key": "synthetic-calendar-1"}),
                     ("google.inspect_calendar", {"action": "inspect", "observation_id": str(uuid4())}),
                     ("google.resolve_calendar", {"action": "resolve", "idempotency_key": "synthetic-calendar-1"})]
    with TestClient(app) as client:
        for identifier, body in cases:
            item = operation(identifier)
            headers = {"Authorization": "Bearer invented-current-identity", item.header: "1"}
            prior = len(calls)
            response = client.post(item.path, json=body, headers=headers)
            assert response.status_code == 200 and response.json() == {"state": "synthetic_local_receipt"}
            assert len(calls) == prior + 1
            args, _kwargs = calls[-1]
            if body["action"] == "status" or provider == "microsoft":
                assert args[0] is identity
            else:
                assert args[:4] == (session, identity.box_id, identity.principal_id, identity.external_identity_id)
            for invalid, bad_headers in (({**body, "account_id": str(uuid4())}, headers), (body, {"Authorization": headers["Authorization"]})):
                response = client.post(item.path, json=invalid, headers=bad_headers)
                assert response.status_code == 422 and len(calls) == prior + 1
