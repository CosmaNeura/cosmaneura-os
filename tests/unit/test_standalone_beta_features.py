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


@pytest.mark.parametrize("features", [model_values(), google_values(), model_values() | google_values()])
def test_explicit_optional_features_preserve_independent_profile(clerk_standalone, features):
    runtime = clerk_standalone.runtime.model_copy(update=features)
    runtime.validate_runtime_configuration()
    assert runtime.workspace_llm_available == ("workspace_llm_backend" in features)
    assert runtime.workspace_google_message_available == ("workspace_google_connection_enabled" in features)
    assert runtime.workspace_google_calendar_available == ("workspace_google_connection_enabled" in features)
    assert not runtime.workspace_core_connection_available
    assert not runtime.workspace_agent_tools_enabled
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
    {"workspace_llm_backend": "disabled"}, {"workspace_agent_tools_enabled": True},
    {"workspace_routines_enabled": True}, {"core_capture_origin": "https://core.example.invalid"},
])
def test_model_incomplete_or_broadened_configuration_fails(clerk_standalone, change):
    runtime = clerk_standalone.runtime.model_copy(update=model_values() | change)
    assert runtime.runtime_configuration_errors()


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
    for values in (model_values(), google_values()):
        assert clerk_standalone.offline.model_copy(update=values).runtime_configuration_errors()


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
        def __init__(self, selected, _sessions):
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
