"""Offline wire checks for the optional structured-tool transport policy."""

import json
import time
from types import SimpleNamespace

import httpx
import pytest
from lab.engine import AzureModel, Budget
from lab.store import LabError


@pytest.mark.parametrize("require_tools", [None, False, True])
def test_model_requires_tools_only_when_opted_in(monkeypatch, require_tools):
    import azure.identity

    credentials = []

    class Credential:
        def __init__(self, **kwargs):
            credentials.append(self)
            self.closed = False

        def get_token(self, scope):
            assert scope == "https://cognitiveservices.azure.com/.default"
            return SimpleNamespace(token="invented-offline-token", expires_on=time.time() + 3600)

        def close(self):
            self.closed = True

    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer invented-offline-token"
        return httpx.Response(200, json={"model": "gpt-4.1", "choices": [{"finish_reason": "tool_calls",
            "message": {"role": "assistant", "tool_calls": [{"id": "offline", "type": "function",
                "function": {"name": "submit_draft", "arguments": "{}"}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

    monkeypatch.setattr(azure.identity, "AzureCliCredential", Credential)
    kwargs = {} if require_tools is None else {"require_tools": require_tools}
    model = AzureModel(Budget(), **kwargs)
    model.client.close()
    model.client = httpx.Client(transport=httpx.MockTransport(respond), trust_env=False)
    try:
        message, usage = model.reply([{"role": "user", "content": "Invented test only."}], [
            {"type": "function", "function": {"name": "submit_draft", "parameters": {"type": "object"}}}])
        assert message["tool_calls"][0]["function"]["name"] == "submit_draft"
        assert usage["total_tokens"] == 15
        assert len(requests) == 1 and requests[0]["store"] is False
        assert requests[0]["max_completion_tokens"] == (1800 if require_tools else 1200)
        if require_tools:
            assert requests[0]["tool_choice"] == "required"
        else:
            assert "tool_choice" not in requests[0]
    finally:
        model.close()
    assert credentials[0].closed


@pytest.fixture
def offline_model(monkeypatch):
    import azure.identity

    monkeypatch.setattr(azure.identity, "AzureCliCredential", lambda **kwargs: SimpleNamespace(
        get_token=lambda scope: SimpleNamespace(token="invented-offline-token", expires_on=time.time() + 3600),
        close=lambda: None))
    models = []

    def create(respond, **kwargs):
        model = AzureModel(Budget(), **kwargs)
        model.client.close()
        model.client = httpx.Client(transport=httpx.MockTransport(respond), trust_env=False)
        models.append(model)
        return model

    yield create
    for model in models:
        model.close()


@pytest.mark.parametrize("require_tools", [False, True])
@pytest.mark.parametrize("failure", ["length", "content_filter", "refusal", "unexpected_model"])
def test_rejected_output_still_accounts_for_valid_provider_usage(offline_model, require_tools, failure):
    requests = []
    limit = 1800 if require_tools else 1200

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "different-model" if failure == "unexpected_model" else "gpt-4.1",
            "choices": [{"finish_reason": failure if failure in {"length", "content_filter"} else "stop",
                         "message": {"role": "assistant", "content": "Invented private response content.",
                                     "refusal": "Invented refusal content." if failure == "refusal" else None}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": limit, "total_tokens": limit + 10}})

    model = offline_model(respond, require_tools=require_tools)
    expected = "model_output_limit" if failure == "length" else (
        "unexpected_model" if failure == "unexpected_model" else "incomplete_model_response")
    with pytest.raises(LabError, match="^" + expected + "$"):
        model.reply([{"role": "user", "content": "Invented test only."}], [])
    assert len(requests) == model.budget.calls == 1
    assert requests[0]["max_completion_tokens"] == limit
    assert model.budget.tokens == limit + 10
    assert model.budget.reserved_tokens == 0


@pytest.mark.parametrize("failure", ["missing_usage", "invalid_usage", "timeout"])
def test_unknown_usage_preserves_call_reservation(offline_model, failure):
    messages = [{"role": "user", "content": "Invented test only."}]
    tools = []

    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("Invented network interruption.")
        value = {"model": "gpt-4.1", "choices": [{"finish_reason": "length",
                 "message": {"role": "assistant", "content": "Invented partial output."}}]}
        if failure == "invalid_usage":
            value["usage"] = {"total_tokens": -1}
        return httpx.Response(200, json=value)

    model = offline_model(respond, require_tools=True)
    with pytest.raises(httpx.ReadTimeout if failure == "timeout" else LabError):
        model.reply(messages, tools)
    assert model.budget.calls == 1 and model.budget.tokens == 0
    assert model.budget.reserved_tokens == len(json.dumps([messages, tools]).encode()) + 5000
