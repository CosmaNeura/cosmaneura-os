"""CosmaBot Azure OpenAI deployment name pin (T-USDZ). Synthetic config only."""

from __future__ import annotations

import json

import httpx

from cosmas_os.adapters.gpt41 import ENDPOINT, MODEL, GPT41Connector
from cosmas_os.config import Settings
from cosmas_os.ports.bot_capabilities import BotContext, SourcePassage
from cosmas_os.workspace_llm import DEPLOYMENT


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


def test_deployment_constant_is_data_zone_us() -> None:
    assert DEPLOYMENT == "gpt-4.1-dzus"
    assert MODEL == DEPLOYMENT


def test_settings_default_deployment_and_unchanged_endpoint() -> None:
    configured = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert configured.workspace_llm_deployment == "gpt-4.1-dzus"
    assert configured.workspace_llm_deployment == DEPLOYMENT
    # Endpoint default stays on the historical CosmasCode Services AI host.
    assert configured.workspace_llm_endpoint == "https://cosmascode.services.ai.azure.com/openai/v1"
    assert ENDPOINT == "https://cosmascode.services.ai.azure.com/openai/v1/chat/completions"


def test_chief_prepare_request_uses_dzus_deployment_not_global_name() -> None:
    envelope = GPT41Connector(lambda: "").prepare(_context())
    assert envelope["body"]["model"] == "gpt-4.1-dzus"
    assert envelope["body"]["model"] != "gpt-4.1"


def test_dispatch_request_body_uses_dzus_deployment() -> None:
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
                                {"answer": "Invented BP remains unconfirmed.", "source_ids": ["invented-source"]}
                            )
                        },
                    }
                ],
            },
        )

    reply = GPT41Connector(
        lambda: "invented-test-key", transport=httpx.MockTransport(respond)
    ).review(_context())
    body = json.loads(calls[0].content)
    assert body["model"] == "gpt-4.1-dzus"
    assert str(calls[0].url) == ENDPOINT
    assert reply.citations[0].entry_id == "invented-source"
