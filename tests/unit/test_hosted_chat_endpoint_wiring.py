"""T-PROD-1 (b) wiring: hosted chat HTTP uses the configured reviewed endpoint."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from tests.unit.test_provider_team_contract import context

from cosmas_os.adapters.gpt41 import ENDPOINT, GPT41Connector
from cosmas_os.adapters.gpt41_tools import GPT41ToolsConnector
from cosmas_os.application import agent_tools, model_work
from cosmas_os.config import COSMASCODE_LLM_ENDPOINT, hosted_chat_completions_url
from cosmas_os.ports.bot_capabilities import ModelCallFailure

PROD_BASE = "https://oai-cbot-prd-abcd1234.openai.azure.com/openai/v1"
PROD_CHAT = PROD_BASE + "/chat/completions"


def _text_envelope():
    return GPT41Connector(lambda: "").prepare(context(role="visit_prep"))


def _tool_selection(ctx):
    return agent_tools._selection(
        [
            {
                "entry_id": source.entry_id,
                "revision": source.revision,
                "sha256": agent_tools._content_hash(source.content),
                "label": source.label,
                "kind": source.kind,
            }
            for source in ctx.sources
        ],
        [],
        [],
    )


def _runtime(endpoint: str):
    return SimpleNamespace(
        cosmas_env="early_adopter_beta",
        workspace_llm_api_key=SecretStr("invented-hosted-key"),
        workspace_llm_endpoint=endpoint,
        workspace_enrollment_managed=False,
        workspace_llm_available=True,
    )


def _ok_response(envelope):
    sources = envelope.get("sources") or []
    source_id = sources[0]["source_id"] if sources else "invented-source"
    return httpx.Response(
        200,
        json={
            "model": "gpt-4.1",
            "usage": {"prompt_tokens": 11, "completion_tokens": 5},
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {"answer": "Invented hosted reply.", "source_ids": [source_id]}
                        )
                    },
                }
            ],
        },
    )


def test_helper_cosmascode_keeps_default_path_sentinel():
    assert hosted_chat_completions_url(COSMASCODE_LLM_ENDPOINT) is None
    assert hosted_chat_completions_url(PROD_BASE) == PROD_CHAT
    with pytest.raises(ValueError, match="hosted_chat_endpoint_refused"):
        hosted_chat_completions_url("https://other.openai.azure.com/openai/v1")
    with pytest.raises(ValueError, match="hosted_chat_endpoint_refused"):
        hosted_chat_completions_url("")


def test_hosted_text_dispatch_posts_to_configured_prod_endpoint(monkeypatch):
    envelope = _text_envelope()
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert str(request.url) == PROD_CHAT
        assert request.headers["Authorization"] == "Bearer invented-hosted-key"
        assert request.headers["Content-Type"] == "application/json"
        body = json.loads(request.content)
        assert body["model"] == "gpt-4.1"
        assert "api-version" not in str(request.url)
        return _ok_response(envelope)

    monkeypatch.setattr(model_work.team, "runtime_settings", _runtime(PROD_BASE))
    claim = model_work.ModelClaim(
        "invented-admission",
        "invented-box",
        "invented-owner",
        "invented-workspace",
        "invented-dispatch",
        model_work.digest(envelope),
        envelope,
    )
    result = model_work.dispatch_claim(claim, transport=httpx.MockTransport(respond))
    assert result.content == "Invented hosted reply."
    assert len(calls) == 1
    assert str(calls[0].url) != ENDPOINT


def test_hosted_text_dispatch_cosmascode_keeps_today_url_headers_and_path(monkeypatch):
    envelope = _text_envelope()
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert str(request.url) == ENDPOINT
        assert request.headers["Authorization"] == "Bearer invented-hosted-key"
        assert request.headers["Content-Type"] == "application/json"
        body = json.loads(request.content)
        assert body["model"] == "gpt-4.1"
        assert "api-version" not in str(request.url)
        return _ok_response(envelope)

    monkeypatch.setattr(model_work.team, "runtime_settings", _runtime(COSMASCODE_LLM_ENDPOINT))
    claim = model_work.ModelClaim(
        "invented-admission",
        "invented-box",
        "invented-owner",
        "invented-workspace",
        "invented-dispatch",
        model_work.digest(envelope),
        envelope,
    )
    seen: dict[str, object] = {}
    real = GPT41Connector

    def capturing(credential, **kwargs):
        seen["kwargs"] = dict(kwargs)
        return real(credential, **kwargs)

    monkeypatch.setattr(model_work, "GPT41Connector", capturing)
    result = model_work.dispatch_claim(claim, transport=httpx.MockTransport(respond))
    assert result.content == "Invented hosted reply."
    assert "endpoint" not in seen["kwargs"]
    assert str(calls[0].url) == ENDPOINT


def test_hosted_unusable_endpoint_fails_closed_without_http(monkeypatch):
    envelope = _text_envelope()
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        pytest.fail(f"must not call provider; got {request.url}")

    monkeypatch.setattr(
        model_work.team,
        "runtime_settings",
        _runtime("https://other.openai.azure.com/openai/v1"),
    )
    claim = model_work.ModelClaim(
        "invented-admission",
        "invented-box",
        "invented-owner",
        "invented-workspace",
        "invented-dispatch",
        model_work.digest(envelope),
        envelope,
    )
    with pytest.raises(ModelCallFailure) as failure:
        model_work.dispatch_claim(claim, transport=httpx.MockTransport(respond))
    assert failure.value.dispatch == "not_dispatched"
    assert calls == []


def test_tools_connector_default_endpoint_stays_cosmascode():
    connector = GPT41ToolsConnector(lambda: "invented")
    assert connector.endpoint == ENDPOINT


def test_tools_connector_posts_to_explicit_prod_endpoint():
    ctx = context(role="visit_prep")
    selection = _tool_selection(ctx)
    envelope = GPT41ToolsConnector(lambda: "").prepare(ctx, selection)
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert str(request.url) == PROD_CHAT
        assert "api-version" not in str(request.url)
        body = json.loads(request.content)
        assert body["model"] == "gpt-4.1"
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1",
                "usage": {"prompt_tokens": 9, "completion_tokens": 4},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer": "Invented tools reply.",
                                    "source_ids": [ctx.sources[0].entry_id],
                                }
                            )
                        },
                    }
                ],
            },
        )

    reply = GPT41ToolsConnector(
        lambda: "invented-hosted-key",
        transport=httpx.MockTransport(respond),
        endpoint=PROD_CHAT,
    ).review_prepared(envelope, execute=lambda _: pytest.fail("no tools expected"))
    assert "Invented tools reply." in reply.content
    assert len(calls) == 1


def test_hosted_tools_dispatch_posts_to_prod_endpoint(monkeypatch):
    ctx = context(role="visit_prep")
    selection = _tool_selection(ctx)
    envelope = GPT41ToolsConnector(lambda: "").prepare(ctx, selection)
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert str(request.url) == PROD_CHAT
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1",
                "usage": {"prompt_tokens": 9, "completion_tokens": 4},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer": "Invented tools dispatch reply.",
                                    "source_ids": [ctx.sources[0].entry_id],
                                }
                            )
                        },
                    }
                ],
            },
        )

    monkeypatch.setattr(model_work.team, "runtime_settings", _runtime(PROD_BASE))
    claim = model_work.ModelClaim(
        str(uuid4()),
        "invented-box",
        "invented-owner",
        "invented-workspace",
        "invented-dispatch",
        model_work.digest(envelope),
        envelope,
    )
    result = model_work.dispatch_claim(claim, transport=httpx.MockTransport(respond))
    assert "Invented tools dispatch reply." in result.content
    assert len(calls) == 1
    assert str(calls[0].url) == PROD_CHAT


def test_model_deployment_and_api_surface_unchanged_in_both_modes():
    assert ENDPOINT == COSMASCODE_LLM_ENDPOINT + "/chat/completions"
    cosmas = GPT41Connector(lambda: "")
    prod = GPT41Connector(lambda: "", endpoint=PROD_CHAT)
    assert cosmas.deployment == "gpt-4.1"
    assert prod.deployment == "gpt-4.1"
    assert cosmas.endpoint == ENDPOINT
    assert prod.endpoint == PROD_CHAT
    assert cosmas.endpoint.endswith("/openai/v1/chat/completions")
    assert prod.endpoint.endswith("/openai/v1/chat/completions")
    assert "api-version=" not in cosmas.endpoint
    assert "api-version=" not in prod.endpoint
