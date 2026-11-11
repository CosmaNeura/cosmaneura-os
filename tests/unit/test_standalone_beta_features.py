"""Optional standalone beta features use invented configuration and HTTP only."""

import asyncio
import base64
import json
from contextlib import contextmanager
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from tests.unit import test_standalone_clerk_runtime as clerk_tests

from cosmas_os.adapters.gpt41 import ENDPOINT, GPT41Connector
from cosmas_os.ports.bot_capabilities import BotContext, ModelCallFailure
from cosmas_os.standalone_runtime import standalone_request_allowed

MODEL_ORIGIN = "https://invented-cosmabot.openai.azure.com"
standalone = clerk_tests.standalone
clerk_standalone = clerk_tests.clerk_standalone


def model_values():
    return {"workspace_llm_backend": "azure_gpt41", "workspace_llm_deployment": "gpt-4.1",
        "workspace_llm_endpoint": MODEL_ORIGIN + "/openai/v1",
        "standalone_model_origin_allowlist": MODEL_ORIGIN,
        "workspace_llm_api_key": SecretStr("invented-model-key")}


def google_values():
    return {"workspace_google_connection_enabled": True, "workspace_google_message_enabled": True,
        "workspace_google_calendar_enabled": True,
        "google_connection_client_id": "invented-client.apps.googleusercontent.com",
        "google_connection_client_secret": SecretStr("invented-oauth-secret"),
        "google_connection_callback_uri": "https://api.invented-cosmabot.test/connections/google/callback",
        "google_connection_return_origin": "https://workspace.invented-cosmabot.test",
        "google_connection_encryption_key": SecretStr(base64.urlsafe_b64encode(b"x" * 32).decode())}


def microsoft_values():
    return {"workspace_microsoft_connection_enabled": True, "workspace_microsoft_message_enabled": True,
        "workspace_microsoft_calendar_enabled": True,
        "microsoft_connection_tenant_id": "10000000-0000-4000-8000-000000000001",
        "microsoft_connection_client_id": "10000000-0000-4000-8000-000000000002",
        "microsoft_connection_client_secret": SecretStr("invented-microsoft-secret"),
        "microsoft_connection_callback_uri": "https://api.invented-cosmabot.test/connections/microsoft/callback",
        "microsoft_connection_return_origin": "https://workspace.invented-cosmabot.test",
        "microsoft_connection_encryption_key": SecretStr(base64.urlsafe_b64encode(b"m" * 32).decode())}


def core_capture_values():
    return {"workspace_capture_backend": "core", "workspace_capture_notes_enabled": True,
            "workspace_agent_tools_enabled": True,
            "core_capture_origin": "https://staging-app.cosmaneura.com",
            "core_web_origin": "https://staging-app.cosmaneura.com",
            "core_capture_scope": "api://invented-core-audience/.default",
            "core_capture_managed_identity_client_id": "00000000-0000-4000-8000-0000000000aa",
            # CosmaBot API origin only — never Scribe/Core blob (no Cosmas CORS).
            "workspace_capture_proxy_origin": "https://api.invented-cosmabot.test"}


@pytest.mark.parametrize("features", [model_values(), google_values(), microsoft_values(),
    microsoft_values() | {"microsoft_connection_tenant_id": "organizations"},
    model_values() | google_values() | microsoft_values(),
    model_values() | google_values() | core_capture_values()])
def test_explicit_optional_features_preserve_independent_profile(clerk_standalone, features):
    runtime = clerk_standalone.runtime.model_copy(update=features)
    runtime.validate_runtime_configuration()
    assert runtime.workspace_llm_available == ("workspace_llm_backend" in features)
    assert runtime.workspace_google_message_available == ("workspace_google_connection_enabled" in features)
    assert runtime.workspace_google_calendar_available == ("workspace_google_connection_enabled" in features)
    assert runtime.workspace_microsoft_message_available == ("workspace_microsoft_connection_enabled" in features)
    assert runtime.workspace_microsoft_calendar_available == ("workspace_microsoft_connection_enabled" in features)
    assert not runtime.workspace_core_connection_available
    if "workspace_capture_backend" in features:
        assert runtime.workspace_agent_tools_enabled
        assert runtime.workspace_capture_available
    else:
        assert not runtime.workspace_agent_tools_enabled
        assert not runtime.workspace_capture_available
    assert not runtime.workspace_routines_enabled
    assert not runtime.sync_worker


@pytest.mark.parametrize("change", [
    {"standalone_model_origin_allowlist": ""},
    {"standalone_model_origin_allowlist": "https://other.openai.azure.com"},
    {"standalone_model_origin_allowlist": MODEL_ORIGIN + "," + MODEL_ORIGIN},
    {"workspace_llm_endpoint": "https://api.invented-cosmabot.test/openai/v1"},
    {"workspace_llm_endpoint": MODEL_ORIGIN + "/openai/v1?alternate=1"},
    {"workspace_llm_endpoint": MODEL_ORIGIN + "/openai/v1\n"},
    {"workspace_llm_endpoint": MODEL_ORIGIN.replace("https", "http") + "/openai/v1"},
    {"workspace_llm_endpoint": "https://user@invented-cosmabot.openai.azure.com/openai/v1"},
    {"workspace_llm_deployment": "other-model"}, {"workspace_llm_api_key": None},
    {"workspace_llm_backend": "disabled"},
    {"workspace_routines_enabled": True}, {"core_capture_origin": "https://core.example.invalid"},
    {"workspace_capture_corrections_enabled": True},
])
def test_model_incomplete_or_broadened_configuration_fails(clerk_standalone, change):
    runtime = clerk_standalone.runtime.model_copy(update=model_values() | change)
    assert runtime.runtime_configuration_errors()


@pytest.mark.parametrize("change", [
    {"core_capture_origin": "https://app.cosmaneura.com"},
    {"core_web_origin": "https://app.cosmaneura.com"},
    {"core_capture_scope": "https://not-api-scope"},
    {"core_capture_managed_identity_client_id": "not-a-uuid"},
    {"workspace_capture_notes_enabled": False},
    {"workspace_agent_tools_enabled": False},
    {"workspace_core_connection_enabled": True},
    {"core_connection_tenant_ref": "authority_tenant_01arz3ndektsv4rrffq69g5fav"},
    {"workspace_capture_corrections_enabled": True},
    {"workspace_session_prep_enabled": True},
    {"workspace_capture_proxy_origin": "https://cosmaneurastaginguploads.blob.core.windows.net"},
    {"workspace_capture_proxy_origin": "https://staging-app.cosmaneura.com"},
    {"workspace_capture_proxy_origin": ""},
])
def test_core_capture_incomplete_or_broadened_configuration_fails(clerk_standalone, change):
    runtime = clerk_standalone.runtime.model_copy(update=model_values() | google_values() | core_capture_values() | change)
    assert runtime.runtime_configuration_errors()


def test_independent_core_capture_opt_in_with_empty_proxy_refuses_at_config(clerk_standalone):
    """Opt-in on + empty proxy must fail at Settings validation, not at upload time."""
    runtime = clerk_standalone.runtime.model_copy(
        update=model_values() | google_values() | core_capture_values() | {
            "workspace_capture_proxy_origin": "",
        }
    )
    errors = runtime.runtime_configuration_errors()
    assert errors
    assert any("proxy origin" in error.lower() for error in errors)


def test_agent_tools_alone_without_core_capture_still_allowed_with_model(clerk_standalone):
    runtime = clerk_standalone.runtime.model_copy(update=model_values() | {"workspace_agent_tools_enabled": True})
    runtime.validate_runtime_configuration()
    assert runtime.workspace_agent_tools_enabled
    assert not runtime.workspace_capture_available


@pytest.mark.parametrize("change", [
    {"google_connection_client_id": "not-an-oauth-client"},
    {"google_connection_client_secret": None}, {"google_connection_encryption_key": SecretStr("short")},
    {"google_connection_callback_uri": "https://api.cosmaneura.com/connections/google/callback"},
    {"google_connection_callback_uri": "https://api.invented-cosmabot.test/other"},
    {"google_connection_callback_uri": "https://api.invented-cosmabot.test/connections/google/callback?x=1"},
    {"google_connection_return_origin": "https://other.invented-cosmabot.test"},
    {"workspace_google_connection_enabled": False}, {"workspace_microsoft_connection_enabled": True},
])
def test_google_incomplete_or_broadened_configuration_fails(clerk_standalone, change):
    assert clerk_standalone.runtime.model_copy(update=google_values() | change).runtime_configuration_errors()


def test_offline_profile_remains_closed(clerk_standalone):
    for values in (model_values(), google_values(), microsoft_values()):
        assert clerk_standalone.offline.model_copy(update=values).runtime_configuration_errors()


@pytest.mark.parametrize("change", [
    *[{"microsoft_connection_tenant_id": value} for value in (
        "common", "consumers", "Organizations", " organizations", "organizations/",
        "https://login.microsoftonline.com/organizations", "organizations?tenant=other")],
    {"microsoft_connection_client_id": "invented-not-a-uuid"},
    {"microsoft_connection_client_secret": None}, {"microsoft_connection_encryption_key": SecretStr("short")},
    {"microsoft_connection_callback_uri": "https://api.cosmaneura.com/connections/microsoft/callback"},
    {"microsoft_connection_callback_uri": "https://api.invented-cosmabot.test/other"},
    {"microsoft_connection_callback_uri": "https://api.invented-cosmabot.test/connections/microsoft/callback?x=1"},
    {"microsoft_connection_return_origin": "https://other.invented-cosmabot.test"},
    {"workspace_microsoft_connection_enabled": False},
])
def test_microsoft_incomplete_or_broadened_configuration_stays_unavailable(clerk_standalone, change):
    runtime = clerk_standalone.runtime.model_copy(update=microsoft_values() | change)
    assert runtime.runtime_configuration_errors()
    assert not runtime.workspace_microsoft_message_available
    assert not runtime.workspace_microsoft_calendar_available


def test_microsoft_opens_only_selected_actor_authenticated_routes(clerk_standalone):
    base = clerk_standalone.runtime
    microsoft = base.model_copy(update=microsoft_values())
    visit = "/workspaces/" + str(uuid4())
    for path in ("/connections/microsoft/session", "/connections/microsoft/messages",
                 "/connections/microsoft/calendar-summaries", visit + "/microsoft-messages/review",
                 visit + "/microsoft-calendar/review"):
        assert standalone_request_allowed("POST", path, microsoft)
        assert not standalone_request_allowed("POST", path, base)
        assert not standalone_request_allowed("POST", path, clerk_standalone.offline)
    for path in ("/connections/microsoft/session/extra", visit + "/microsoft-calendar/review/extra",
                 visit + "/handoffs", "/practice-access/invitations", "/connections/google/session"):
        assert not standalone_request_allowed("POST", path, microsoft)


def test_microsoft_standalone_lifecycle_opens_only_configured_personal_service(clerk_standalone, monkeypatch):
    from cosmas_os import standalone_runtime
    from cosmas_os.adapters import microsoft_connection_runtime
    from cosmas_os.api import app as api

    runtime = clerk_standalone.runtime.model_copy(update=microsoft_values())
    calls = []

    class Microsoft:
        def __init__(self, selected, _sessions):
            assert selected is runtime
            calls.append("microsoft_created")

        def close(self):
            calls.append("microsoft_closed")

    monkeypatch.setattr(api, "settings", runtime)
    monkeypatch.setattr(standalone_runtime, "validate_standalone_runtime", lambda *_: calls.append("owned_guard"))
    monkeypatch.setattr(microsoft_connection_runtime, "MicrosoftPersonalConnection", Microsoft)
    app = FastAPI()

    async def exercise():
        async with api.lifespan(app):
            assert app.state.workspace_worker_progress == {}
            assert app.state.microsoft_connection is not None
            assert app.state.google_connection is None

    asyncio.run(exercise())
    assert app.state.microsoft_connection is None
    assert calls == ["owned_guard", "microsoft_created", "microsoft_closed"]


def test_only_selected_write_paths_open_and_durable_resolution_survives_disable(clerk_standalone):
    base = clerk_standalone.runtime
    model = base.model_copy(update=model_values())
    google = base.model_copy(update=google_values())
    visit = "/workspaces/" + str(uuid4())
    assert not standalone_request_allowed("POST", visit + "/conversation", base)
    assert standalone_request_allowed("POST", visit + "/conversation", model)
    assert standalone_request_allowed("POST", visit + "/conversation/resolve", base)
    assert not standalone_request_allowed("POST", visit + "/conversation/resolve", clerk_standalone.offline)
    for path in ("/connections/google/session", "/connections/google/messages",
                 "/connections/google/calendar-summaries", visit + "/google-messages/review",
                 visit + "/google-calendar/review"):
        assert standalone_request_allowed("POST", path, google)
        assert not standalone_request_allowed("POST", path, base)
    for path in (visit + "/handoffs", visit + "/handoffs/" + str(uuid4()) + "/retry",
                 "/chase/open", "/tickets", "/practice-access/invitations", "/provider-team/rehearsal",
                 "/connections/microsoft/session", "/connections/google/session/extra"):
        assert not standalone_request_allowed("POST", path, model.model_copy(update=google_values()))


@pytest.mark.parametrize("enabled", [False, True])
def test_standalone_lifecycle_constructs_only_optional_google_without_workers(clerk_standalone, monkeypatch, enabled):
    from cosmas_os import standalone_runtime
    from cosmas_os.adapters import google_connection_runtime
    from cosmas_os.api import app as api

    runtime = clerk_standalone.runtime.model_copy(update=model_values() | (google_values() if enabled else {}))
    calls = []

    class Google:
        def __init__(self, selected, _sessions, *, broker=None, transport=None):
            assert broker is None
            assert transport is None
            assert selected is runtime
            calls.append("google_created")

        def close(self):
            calls.append("google_closed")

    @contextmanager
    def forbidden(*_args, **_kwargs):
        pytest.fail("standalone started unrelated runtime")
        yield

    monkeypatch.setattr(api, "settings", runtime)
    monkeypatch.setattr(standalone_runtime, "validate_standalone_runtime", lambda *_: calls.append("owned_guard"))
    monkeypatch.setattr(google_connection_runtime, "GooglePersonalConnection", Google)
    for name in ("portal_services_lifespan", "microsoft_connection_lifespan", "scheduling_login_lifespan",
                 "scheduling_lifespan", "managed_services_lifespan"):
        monkeypatch.setattr(api, name, forbidden)
    app = FastAPI()

    async def exercise():
        async with api.lifespan(app):
            assert app.state.workspace_worker_progress == {}
            assert (app.state.google_connection is not None) is enabled

    asyncio.run(exercise())
    assert app.state.google_connection is None
    assert calls == (["owned_guard", "google_created", "google_closed"] if enabled else ["owned_guard"])


def test_adapter_uses_exact_selected_endpoint_without_tools_or_fallback():
    requests = []
    endpoint = MODEL_ORIGIN + "/openai/v1/chat/completions"

    def respond(request):
        assert str(request.url) == endpoint
        body = json.loads(request.content)
        assert body["model"] == "gpt-4.1" and body["store"] is False and "tools" not in body
        requests.append(body)
        return httpx.Response(200, json={"model": "gpt-4.1",
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant",
                "content": json.dumps({"answer": "Invented draft for review.", "source_ids": []})}}]})

    adapter = GPT41Connector(lambda: "invented-key", endpoint=endpoint, transport=httpx.MockTransport(respond))
    context = BotContext("invented-workspace", 1, "chief", "Organize my notes", "brief", (), ())
    reply = adapter.review(context)
    assert reply.content == "Invented draft for review."
    assert len(requests) == 1
    assert GPT41Connector(lambda: "invented-key").endpoint == ENDPOINT
    with pytest.raises(ValueError):
        GPT41Connector(lambda: pytest.fail("must not read key"), endpoint="https://unreviewed.invalid/chat")


@pytest.mark.parametrize("fault", ["tool_contract", "handoff", "disabled"])
def test_dispatch_rechecks_plain_contract_and_model_admission_before_http(clerk_standalone, monkeypatch, fault):
    from cosmas_os.application import model_work

    runtime = clerk_standalone.runtime.model_copy(update=model_values())
    envelope = GPT41Connector(lambda: "invented-key").prepare(
        BotContext("invented-workspace", 1, "chief", "Draft a plan", "brief", (), ()))
    if fault == "tool_contract":
        envelope["contract"] = model_work.TOOL_PREPARED_CONTRACT
    elif fault == "handoff":
        envelope["flags"]["can_handoff"] = True
    else:
        runtime = clerk_standalone.runtime
    monkeypatch.setattr(model_work.team, "runtime_settings", runtime)
    claimed = model_work.ModelClaim("invented-admission", "invented-box", "invented-owner", "invented-workspace",
                                   "invented-dispatch", model_work.digest(envelope), envelope)
    transport = httpx.MockTransport(lambda _: pytest.fail("unadmitted model attempted HTTP"))
    with pytest.raises(ModelCallFailure) as failure:
        model_work.dispatch_claim(claimed, transport=transport)
    assert failure.value.dispatch == "not_dispatched"
