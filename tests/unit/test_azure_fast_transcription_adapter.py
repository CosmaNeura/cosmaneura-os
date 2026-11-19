"""Azure Fast Transcription adapter: MockTransport only; never constructed when off."""

from __future__ import annotations

import hashlib

import httpx
import pytest

from cosmas_os.adapters.azure_fast_transcription import (
    ADAPTER_ID,
    FIXED_KEY_ENV_NAME,
    AzureFastTranscriptionProcessor,
    validate_azure_fast_transcription_endpoint,
)
from cosmas_os.ports.recording_transcription import (
    LABEL_SYNTHETIC,
    TranscriptionFailure,
    TranscriptionRequest,
)

ENDPOINT = "https://eastus.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe"


def _req(audio: bytes = b"tone-bytes", *, synthetic: bool = True, language: str = "en-US") -> TranscriptionRequest:
    return TranscriptionRequest(
        audio=audio,
        sha256=hashlib.sha256(audio).hexdigest(),
        duration_ms=500,
        language=language,
        operation_id="op-azure-1",
        synthetic=synthetic,
    )


def test_endpoint_validation_pins_us_cognitive_host():
    assert validate_azure_fast_transcription_endpoint(ENDPOINT)
    assert validate_azure_fast_transcription_endpoint(
        "https://westus2.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe"
    )
    assert not validate_azure_fast_transcription_endpoint(
        "https://westeurope.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe"
    )
    assert not validate_azure_fast_transcription_endpoint(
        "https://eastus.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe?api-version=1"
    )
    assert not validate_azure_fast_transcription_endpoint(
        "https://user:pass@eastus.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe"
    )
    assert not validate_azure_fast_transcription_endpoint(
        "https://speech.example.invalid/speechtotext/transcriptions:transcribe"
    )


def test_refuses_non_synthetic_audio():
    transport = httpx.MockTransport(lambda _: pytest.fail("must not call network"))
    adapter = AzureFastTranscriptionProcessor(
        endpoint=ENDPOINT, auth="entra", token_provider=lambda: "invented-token", transport=transport
    )
    outcome = adapter.transcribe(_req(synthetic=False))
    assert isinstance(outcome, TranscriptionFailure)
    assert outcome.kind == "unavailable"
    assert outcome.detail == "non_synthetic_refused"


def test_refuses_disallowed_locale():
    adapter = AzureFastTranscriptionProcessor(
        endpoint=ENDPOINT,
        auth="entra",
        token_provider=lambda: "invented-token",
        transport=httpx.MockTransport(lambda _: pytest.fail("no network")),
    )
    outcome = adapter.transcribe(_req(language="fr-FR"))
    assert isinstance(outcome, TranscriptionFailure)
    assert outcome.detail == "locale_not_allowed"


def test_maps_http_errors_to_typed_failures():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "busy"})

    adapter = AzureFastTranscriptionProcessor(
        endpoint=ENDPOINT,
        auth="entra",
        token_provider=lambda: "invented-token",
        transport=httpx.MockTransport(handler),
    )
    outcome = adapter.transcribe(_req())
    assert isinstance(outcome, TranscriptionFailure)
    assert outcome.kind == "retryable"


def test_success_maps_phrases_with_label_and_safe_definition(monkeypatch):
    invented = "invented-key-value-never-log"
    monkeypatch.setenv(FIXED_KEY_ENV_NAME, invented)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "combinedPhrases": [
                    {"text": "Synthetic visit A", "offsetMilliseconds": 0, "durationMilliseconds": 10}
                ]
            },
        )

    adapter = AzureFastTranscriptionProcessor(
        endpoint=ENDPOINT, auth="key", transport=httpx.MockTransport(handler)
    )
    outcome = adapter.transcribe(_req())
    assert not isinstance(outcome, TranscriptionFailure)
    assert outcome.processor_id == ADAPTER_ID
    assert outcome.label == LABEL_SYNTHETIC
    assert outcome.segments[0].text == "Synthetic visit A"
    # Key is sent only as the subscription header; never echoed in body/definition.
    assert seen[0].headers.get("ocp-apim-subscription-key") == invented
    definition = seen[0].read()
    assert invented.encode() not in definition
    assert b"en-US" in definition


def test_key_auth_missing_env_refuses(monkeypatch):
    monkeypatch.delenv(FIXED_KEY_ENV_NAME, raising=False)
    adapter = AzureFastTranscriptionProcessor(
        endpoint=ENDPOINT, auth="key", transport=httpx.MockTransport(lambda _: pytest.fail("no network"))
    )
    outcome = adapter.transcribe(_req())
    assert isinstance(outcome, TranscriptionFailure)
    assert outcome.detail == "key_env_missing"


def test_safe_parsing_rejects_malformed_phrase_offsets():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"combinedPhrases": [{"text": "ok", "offsetMilliseconds": "bad", "durationMilliseconds": 1}]},
        )

    adapter = AzureFastTranscriptionProcessor(
        endpoint=ENDPOINT,
        auth="entra",
        token_provider=lambda: "invented-token",
        transport=httpx.MockTransport(handler),
    )
    outcome = adapter.transcribe(_req())
    assert isinstance(outcome, TranscriptionFailure)
    assert outcome.detail == "empty_transcript"


def test_reused_credential_factory():
    class Cred:
        def __init__(self):
            self.calls = 0

        def get_token(self, scope):
            self.calls += 1
            assert scope
            return type("T", (), {"token": "invented-token"})()

    cred = Cred()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        return httpx.Response(
            200,
            json={"combinedPhrases": [{"text": "hi", "offsetMilliseconds": 0, "durationMilliseconds": 1}]},
        )

    adapter = AzureFastTranscriptionProcessor.from_settings(
        endpoint=ENDPOINT, auth="entra", transport=httpx.MockTransport(handler), credential=cred
    )
    assert not isinstance(adapter.transcribe(_req()), TranscriptionFailure)
    assert not isinstance(adapter.transcribe(_req()), TranscriptionFailure)
    assert cred.calls == 2
    assert seen == ["Bearer invented-token", "Bearer invented-token"]
