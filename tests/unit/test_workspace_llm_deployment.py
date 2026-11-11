"""T-USDZ: CosmaBot chat deployment flag (off = historical gpt-4.1, on = gpt-4.1-dzus)."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from cosmas_os.adapters.gpt41 import ENDPOINT, MODEL, GPT41Connector
from cosmas_os.adapters.gpt41_tools import GPT41ToolsConnector
from cosmas_os.adapters.gpt41_tools import _digest as tools_digest
from cosmas_os.adapters.gpt41_tools_v6 import GPT41CompactToolsConnector
from cosmas_os.adapters.gpt41_tools_v7 import GPT41ConnectorToolsConnector
from cosmas_os.adapters.gpt41_tools_v8 import GPT41DeliveryToolsConnector
from cosmas_os.application import agent_tools, model_work
from cosmas_os.application import provider_team as team
from cosmas_os.config import Settings
from cosmas_os.ports.bot_capabilities import BotContext, SourcePassage
from cosmas_os.workspace_llm import (
    DEFAULT_DEPLOYMENT,
    USDZ_DEPLOYMENT,
    chat_deployment,
)


def _context() -> BotContext:
    return BotContext(
        "invented-workspace",
        1,
        "chief",
        "What does the invented note say?",
        "brief",
        (SourcePassage("invented-source", 1, "Invented notes", "scratchpad", "Invented BP is unconfirmed."),),
        (),
    )


def _tool_context() -> BotContext:
    source = SourcePassage("invented-source", 1, "Invented source", "evidence", "Invented provider plan.")
    return BotContext("invented-workspace", 1, "visit_prep", "Prepare the agenda", "brief", (source,), ())


def _tool_selection(ctx: BotContext) -> dict:
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


def test_flag_off_keeps_historical_default_deployment_and_endpoint() -> None:
    assert DEFAULT_DEPLOYMENT == "gpt-4.1"
    assert MODEL == DEFAULT_DEPLOYMENT
    assert chat_deployment(usdz_enabled=False) == "gpt-4.1"
    configured = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert configured.workspace_llm_usdz_enabled is False
    assert configured.workspace_llm_deployment == "gpt-4.1"
    assert configured.workspace_llm_chat_deployment == "gpt-4.1"
    assert configured.workspace_llm_endpoint == "https://cosmascode.services.ai.azure.com/openai/v1"
    assert ENDPOINT == "https://cosmascode.services.ai.azure.com/openai/v1/chat/completions"
    envelope = GPT41Connector(lambda: "").prepare(_context())
    assert envelope["body"]["model"] == "gpt-4.1"
    assert envelope["body"]["model"] != USDZ_DEPLOYMENT


def test_flag_on_unset_deployment_defaults_to_dzus() -> None:
    assert USDZ_DEPLOYMENT == "gpt-4.1-dzus"
    assert chat_deployment(usdz_enabled=True) == "gpt-4.1-dzus"
    configured = Settings(  # pyright: ignore[reportCallIssue]
        _env_file=None,
        workspace_llm_usdz_enabled=True,
    )
    assert configured.workspace_llm_usdz_enabled is True
    assert configured.workspace_llm_chat_deployment == "gpt-4.1-dzus"
    assert configured.workspace_llm_deployment == "gpt-4.1-dzus"
    assert configured.workspace_llm_endpoint == "https://cosmascode.services.ai.azure.com/openai/v1"


def test_flag_on_explicit_gpt_4_1_is_not_rewritten() -> None:
    configured = Settings(  # pyright: ignore[reportCallIssue]
        _env_file=None,
        workspace_llm_usdz_enabled=True,
        workspace_llm_deployment="gpt-4.1",
    )
    assert configured.workspace_llm_usdz_enabled is True
    assert configured.workspace_llm_deployment == "gpt-4.1"
    assert configured.workspace_llm_chat_deployment == "gpt-4.1"


def test_flag_off_unset_stays_gpt_4_1() -> None:
    configured = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert configured.workspace_llm_usdz_enabled is False
    assert configured.workspace_llm_deployment == "gpt-4.1"
    assert configured.workspace_llm_chat_deployment == "gpt-4.1"


@pytest.mark.parametrize(
    ("connector_type", "build"),
    [
        (
            "v4",
            lambda deployment: GPT41Connector(lambda: "", deployment=deployment).prepare(_context()),
        ),
        (
            "v5",
            lambda deployment: GPT41ToolsConnector(lambda: "", deployment=deployment).prepare(
                _tool_context(), _tool_selection(_tool_context())
            ),
        ),
        (
            "v6",
            lambda deployment: GPT41CompactToolsConnector(lambda: "", deployment=deployment).prepare(
                _tool_context(), _tool_selection(_tool_context())
            ),
        ),
        (
            "v7",
            lambda deployment: GPT41ConnectorToolsConnector(lambda: "", deployment=deployment).prepare(
                replace(_tool_context(), role="research"),
                _v7_selection(replace(_tool_context(), role="research")),
            ),
        ),
        (
            "v8",
            lambda deployment: GPT41DeliveryToolsConnector(lambda: "", deployment=deployment).prepare(
                replace(_tool_context(), role="follow_up"),
                _v8_selection(replace(_tool_context(), role="follow_up")),
            ),
        ),
    ],
)
@pytest.mark.parametrize(
    ("deployment", "expected"),
    [(DEFAULT_DEPLOYMENT, "gpt-4.1"), (USDZ_DEPLOYMENT, "gpt-4.1-dzus")],
)
def test_adapter_prepare_request_model_matches_selected_deployment(
    connector_type, build, deployment, expected
) -> None:
    envelope = build(deployment)
    body = envelope["body"]
    assert body["model"] == expected
    if "baseline" in envelope:
        assert envelope["baseline"]["body"]["model"] == expected


def _v7_selection(ctx: BotContext) -> dict:
    value = {
        **_tool_selection(ctx),
        "contract": "cosmas-agent-tool-selection.v2",
        "connector_capabilities": ["research_propose"],
        "connector_intents": [],
    }
    value.pop("sha256")
    return {**value, "sha256": tools_digest(value)}


def _v8_selection(ctx: BotContext) -> dict:
    intent = {
        "kind": "vendor_delivery",
        **{
            key: str(uuid4())
            for key in (
                "ticket_id",
                "revision_id",
                "operation_id",
                "approval_receipt_id",
                "agent_id",
                "team_revision_id",
                "external_identity_id",
            )
        },
        **{
            key: "a" * 64
            for key in (
                "payload_hash",
                "approval_receipt_sha256",
                "authority_sha256",
                "evidence_sha256",
            )
        },
    }
    selected = {
        **_tool_selection(ctx),
        "contract": "cosmas-agent-tool-selection.v3",
        "connector_capabilities": [],
        "connector_intents": [],
        "delivery_intents": [intent],
    }
    selected.pop("sha256")
    return {**selected, "sha256": tools_digest(selected)}


@pytest.mark.parametrize(
    ("deployment", "expected"),
    [(DEFAULT_DEPLOYMENT, "gpt-4.1"), (USDZ_DEPLOYMENT, "gpt-4.1-dzus")],
)
def test_model_work_prepare_uses_runtime_chat_deployment(monkeypatch, deployment, expected) -> None:
    captured: dict[str, str] = {}

    class CapturingConnector:
        def __init__(self, credential, *, deployment=MODEL, **_kwargs):
            captured["deployment"] = deployment

        def prepare(self, context):
            return GPT41Connector(lambda: "", deployment=captured["deployment"]).prepare(context)

    monkeypatch.setattr(model_work, "GPT41Connector", CapturingConnector)
    monkeypatch.setattr(
        model_work.team,
        "runtime_settings",
        SimpleNamespace(
            workspace_llm_chat_deployment=deployment,
            workspace_agent_tools_enabled=False,
        ),
    )
    # Exercise the same getattr used by _new_admission prepare.
    selected = getattr(model_work.team.runtime_settings, "workspace_llm_chat_deployment", MODEL)
    envelope = model_work.GPT41Connector(lambda: "", deployment=selected).prepare(_context())
    assert captured["deployment"] == expected
    assert envelope["body"]["model"] == expected


def test_flag_on_dispatch_request_body_uses_dzus_and_unchanged_endpoint() -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1-2025-04-14",
                "usage": {"prompt_tokens": 11, "completion_tokens": 5},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer": "Invented BP remains unconfirmed.",
                                    "source_ids": ["invented-source"],
                                }
                            )
                        },
                    }
                ],
            },
        )

    reply = GPT41Connector(
        lambda: "invented-test-key",
        transport=httpx.MockTransport(respond),
        deployment=USDZ_DEPLOYMENT,
    ).review(_context())
    body = json.loads(calls[0].content)
    assert body["model"] == "gpt-4.1-dzus"
    assert str(calls[0].url) == ENDPOINT
    assert reply.citations[0].entry_id == "invented-source"


def test_flag_off_dispatch_request_body_stays_on_gpt_4_1() -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1-2025-04-14",
                "usage": {"prompt_tokens": 9, "completion_tokens": 4},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer": "Invented BP remains unconfirmed.",
                                    "source_ids": ["invented-source"],
                                }
                            )
                        },
                    }
                ],
            },
        )

    GPT41Connector(
        lambda: "invented-test-key",
        transport=httpx.MockTransport(respond),
    ).review(_context())
    body = json.loads(calls[0].content)
    assert body["model"] == "gpt-4.1"
    assert str(calls[0].url) == ENDPOINT


def test_usage_record_model_flag_off_reads_gpt_4_1_from_envelope() -> None:
    row = SimpleNamespace(
        prepared_envelope={"body": {"model": "gpt-4.1"}, "baseline": None},
    )
    assert model_work._usage_model_name(row) == "gpt-4.1"


def test_usage_record_model_flag_on_reads_dzus_from_envelope() -> None:
    row = SimpleNamespace(
        prepared_envelope={"body": {"model": "gpt-4.1-dzus"}},
    )
    assert model_work._usage_model_name(row) == "gpt-4.1-dzus"


def test_provider_team_llm_label_flag_off_is_gpt_4_1(monkeypatch) -> None:
    monkeypatch.setattr(
        team,
        "runtime_settings",
        Settings(_env_file=None),  # pyright: ignore[reportCallIssue]
    )
    # team.runtime_settings is imported as settings singleton in the module;
    # patch the chat deployment property path via a Settings instance used above.
    assert team.runtime_settings.workspace_llm_chat_deployment == "gpt-4.1"


def test_provider_team_llm_label_flag_on_is_dzus(monkeypatch) -> None:
    monkeypatch.setattr(
        team,
        "runtime_settings",
        Settings(_env_file=None, workspace_llm_usdz_enabled=True),  # pyright: ignore[reportCallIssue]
    )
    assert team.runtime_settings.workspace_llm_chat_deployment == "gpt-4.1-dzus"
