"""T-PROD-1 (b) wiring: hosted chat HTTP uses the configured reviewed endpoint."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from tests.unit.test_gpt41_tools import answer as tool_answer
from tests.unit.test_gpt41_tools import executor as tool_executor
from tests.unit.test_gpt41_tools import request_tools, tool
from tests.unit.test_hosted_llm_endpoint_allow import LOOKALIKE_ENDPOINTS
from tests.unit.test_provider_team_contract import context
from tests.unit.test_workspace_llm_deployment import _v7_selection, _v8_selection

from cosmas_os.adapters.gpt41 import ENDPOINT, GPT41Connector
from cosmas_os.adapters.gpt41_tools import GPT41ToolsConnector
from cosmas_os.adapters.gpt41_tools_v6 import GPT41CompactToolsConnector
from cosmas_os.adapters.gpt41_tools_v7 import GPT41ConnectorToolsConnector
from cosmas_os.adapters.gpt41_tools_v8 import GPT41DeliveryToolsConnector
from cosmas_os.application import agent_tools, model_work
from cosmas_os.application import provider_team as pt
from cosmas_os.config import (
    COSMASCODE_LLM_ENDPOINT,
    REVIEWED_HOSTED_CHAT_COMPLETIONS_URL_PATTERN,
    hosted_chat_completions_url,
    reviewed_hosted_llm_endpoint,
)
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


def _prepare_tools_envelope(kind: str):
    if kind == "base":
        ctx = context(role="visit_prep")
        return GPT41ToolsConnector(lambda: "").prepare(ctx, _tool_selection(ctx)), ctx
    if kind == "compact":
        ctx = context(role="visit_prep")
        return GPT41CompactToolsConnector(lambda: "").prepare(ctx, _tool_selection(ctx)), ctx
    if kind == "connector":
        ctx = replace(context(role="research"), role="research")
        return (
            GPT41ConnectorToolsConnector(lambda: "").prepare(ctx, _v7_selection(ctx)),
            ctx,
        )
    if kind == "delivery":
        ctx = replace(context(role="follow_up"), role="follow_up")
        return (
            GPT41DeliveryToolsConnector(lambda: "").prepare(ctx, _v8_selection(ctx)),
            ctx,
        )
    raise AssertionError(kind)


def _connector_class(kind: str):
    return {
        "base": GPT41ToolsConnector,
        "compact": GPT41CompactToolsConnector,
        "connector": GPT41ConnectorToolsConnector,
        "delivery": GPT41DeliveryToolsConnector,
    }[kind]


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
    assert re.fullmatch(REVIEWED_HOSTED_CHAT_COMPLETIONS_URL_PATTERN, connector.endpoint)


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


@pytest.mark.parametrize("kind", ["base", "compact", "connector", "delivery"])
def test_hosted_tools_dispatch_posts_to_prod_endpoint(monkeypatch, kind):
    envelope, ctx = _prepare_tools_envelope(kind)
    connector_cls = _connector_class(kind)
    calls: list[httpx.Request] = []
    seen: dict[str, object] = {}
    tool_calls: list[dict] = []

    class Sess:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def add(self, *_a):
            return None

        def commit(self):
            return None

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert str(request.url) == PROD_CHAT
        if len(calls) == 1:
            return httpx.Response(200, json=request_tools(tool()))
        source_id = ctx.sources[0].entry_id
        return httpx.Response(
            200,
            json=tool_answer(
                content={
                    "answer": f"Invented {kind} tools dispatch reply.",
                    "source_ids": [source_id],
                }
            ),
        )

    real = connector_cls

    def capturing(credential, **kwargs):
        instance = real(credential, **kwargs)
        seen["endpoint"] = instance.endpoint
        seen["kwargs"] = dict(kwargs)
        return instance

    def fake_executor(*_a, **_k):
        return SimpleNamespace(
            execute=lambda request: tool_executor(envelope, tool_calls)(request)
        )

    monkeypatch.setattr(model_work, connector_cls.__name__, capturing)
    monkeypatch.setattr(
        "cosmas_os.application.agent_tools.AgentToolExecutor", fake_executor
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
    result = model_work.dispatch_claim(
        claim,
        transport=httpx.MockTransport(respond),
        session_factory=lambda: Sess(),
    )
    assert f"Invented {kind} tools dispatch reply." in result.content
    assert len(calls) == 2
    assert all(str(call.url) == PROD_CHAT for call in calls)
    assert seen["endpoint"] == PROD_CHAT
    assert seen["kwargs"]["endpoint"] == PROD_CHAT
    assert tool_calls == [{"tool": "list_selected_sources"}]


def test_hosted_tools_dispatch_cosmascode_constructor_unchanged(monkeypatch):
    envelope, _ctx = _prepare_tools_envelope("base")
    calls: list[httpx.Request] = []
    seen: dict[str, object] = {}

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert str(request.url) == ENDPOINT
        return httpx.Response(
            200,
            json=tool_answer(
                content={
                    "answer": "Invented CosmasCode tools reply.",
                    "source_ids": ["invented-source"],
                }
            ),
        )

    real = GPT41ToolsConnector

    def capturing(credential, **kwargs):
        seen["kwargs"] = dict(kwargs)
        return real(credential, **kwargs)

    monkeypatch.setattr(model_work, "GPT41ToolsConnector", capturing)
    monkeypatch.setattr(model_work.team, "runtime_settings", _runtime(COSMASCODE_LLM_ENDPOINT))
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
    assert "Invented CosmasCode tools reply." in result.content
    assert "endpoint" not in seen["kwargs"]
    assert str(calls[0].url) == ENDPOINT


def test_hosted_tools_unusable_endpoint_fails_closed_without_http(monkeypatch):
    envelope, _ctx = _prepare_tools_envelope("base")
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
        str(uuid4()),
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


@pytest.mark.parametrize(
    "bad",
    [
        "https://other.openai.azure.com/openai/v1/chat/completions",
        "http://oai-cbot-prd-abcd1234.openai.azure.com/openai/v1/chat/completions",
        PROD_BASE,
        "https://oai-cbot-prd-abcd1234.openai.azure.com/openai/v1/chat/completions/extra",
        *[(endpoint + "/chat/completions") for endpoint in LOOKALIKE_ENDPOINTS[:8]],
    ],
)
def test_tools_connector_refuses_unreviewed_chat_urls(bad):
    with pytest.raises(ValueError, match="Exact Azure OpenAI v1 endpoint required"):
        GPT41ToolsConnector(lambda: "invented", endpoint=bad)


@pytest.mark.parametrize("endpoint", LOOKALIKE_ENDPOINTS)
def test_reviewed_endpoint_and_tools_url_pattern_refuse_lookalikes_together(endpoint):
    assert not reviewed_hosted_llm_endpoint(endpoint)
    with pytest.raises(ValueError, match="hosted_chat_endpoint_refused"):
        hosted_chat_completions_url(endpoint)
    chat = endpoint + "/chat/completions"
    assert not re.fullmatch(REVIEWED_HOSTED_CHAT_COMPLETIONS_URL_PATTERN, chat)
    with pytest.raises(ValueError, match="Exact Azure OpenAI v1 endpoint required"):
        GPT41ToolsConnector(lambda: "invented", endpoint=chat)


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


def _label_runtime(endpoint: str) -> SimpleNamespace:
    return SimpleNamespace(
        workspace_llm_endpoint=endpoint,
        workspace_llm_available=False,
        workspace_llm_chat_deployment="gpt-4.1",
        workspace_capture_available=False,
        workspace_capture_notes_enabled=False,
        workspace_capture_corrections_enabled=False,
        workspace_research_available=False,
        workspace_research_io_enabled=False,
        workspace_prep_enabled=False,
        workspace_prep_work_enabled=False,
        workspace_session_prep_available=False,
        workspace_scheduling_available=False,
        inbox_work_enabled=False,
        membership_work_enabled=False,
        finance_work_enabled=False,
    )


def test_connector_label_neutral_on_production_host(monkeypatch):
    class FakeSession:
        def scalar(self, *_a, **_k):
            return None

        def scalars(self, *_a, **_k):
            return iter([])

    monkeypatch.setattr(pt, "_human", lambda *_a, **_k: None)
    monkeypatch.setattr(pt, "runtime_settings", _label_runtime(PROD_BASE))
    prod = pt.read(FakeSession(), "invented-box", "invented-owner")
    prod_assistant = next(
        cap
        for template in prod["templates"]
        for cap in template["capabilities"]
        if cap["key"] == "assistant.answer"
    )
    assert prod_assistant["connector"] == "GPT-4.1"
    monkeypatch.setattr(pt, "runtime_settings", _label_runtime(COSMASCODE_LLM_ENDPOINT))
    staging = pt.read(FakeSession(), "invented-box", "invented-owner")
    staging_assistant = next(
        cap
        for template in staging["templates"]
        for cap in template["capabilities"]
        if cap["key"] == "assistant.answer"
    )
    assert staging_assistant["connector"] == "CosmasCode · GPT-4.1"
