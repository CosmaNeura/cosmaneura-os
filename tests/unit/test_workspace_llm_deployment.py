"""T-USDZ: CosmaBot chat deployment flag (off = historical gpt-4.1, on = gpt-4.1-dzus)."""

from __future__ import annotations

import json

import httpx

from cosmas_os.adapters.gpt41 import ENDPOINT, MODEL, GPT41Connector
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


def test_flag_on_selects_us_data_zone_deployment_without_endpoint_change() -> None:
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
    envelope = GPT41Connector(lambda: "", deployment=configured.workspace_llm_chat_deployment).prepare(
        _context()
    )
    assert envelope["body"]["model"] == "gpt-4.1-dzus"
    assert envelope["body"]["model"] != "gpt-4.1"


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
