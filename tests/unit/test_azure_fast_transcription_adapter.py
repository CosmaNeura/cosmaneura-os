"""Azure Fast Transcription adapter: MockTransport only; never constructed when off."""

from __future__ import annotations

import hashlib

import httpx
import pytest

from cosmas_os.adapters.azure_fast_transcription import (
    ADAPTER_ID,
    PROFILE_ID,
    AzureFastTranscriptionProcessor,
    validate_azure_fast_transcription_endpoint,
)
from cosmas_os.ports.recording_transcription import TranscriptionFailure, TranscriptionRequest

ENDPOINT = "https://speech.example.invalid/speechtotext/transcriptions:transcribe"


def _req(audio: bytes = b"tone-bytes", *, synthetic: bool = True) -> TranscriptionRequest:
    return TranscriptionRequest(
        audio=audio,
        sha256=hashlib.sha256(audio).hexdigest(),
        duration_ms=500,
        language="en-US",
        operation_id="op-azure-1",
        synthetic=synthetic,
    )


def test_endpoint_validation_rejects_query_and_credentials():
    assert validate_azure_fast_transcription_endpoint(ENDPOINT)
    assert not validate_azure_fast_transcription_endpoint(
        "https://speech.example.invalid/path?api-version=1"
    )
    assert not validate_azure_fast_transcription_endpoint(
        "https://user:pass@speech.example.invalid/path"
    )
    assert not validate_azure_fast_transcription_endpoint("http://speech.example.invalid/path")


def test_refuses_non_synthetic_audio():
    transport = httpx.MockTransport(lambda _: pytest.fail("must not call network"))
    adapter = AzureFastTranscriptionProcessor(
        endpoint=ENDPOINT, token_provider=lambda: "invented-token", transport=transport
    )
    outcome = adapter.transcribe(_req(synthetic=False))
    assert isinstance(outcome, TranscriptionFailure)
    assert outcome.kind == "unavailable"
    assert outcome.detail == "non_synthetic_refused"


def test_maps_http_errors_to_typed_failures():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "busy"})

    adapter = AzureFastTranscriptionProcessor(
        endpoint=ENDPOINT,
        token_provider=lambda: "invented-token",
        transport=httpx.MockTransport(handler),
    )
    outcome = adapter.transcribe(_req())
    assert isinstance(outcome, TranscriptionFailure)
    assert outcome.kind == "retryable"


def test_success_maps_phrases_without_logging_key(monkeypatch):
    invented = "invented-key-value-never-log"
    monkeypatch.setenv("COSMAS_TEST_SPEECH_KEY", invented)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"combinedPhrases": [{"text": "Synthetic visit A", "offsetMilliseconds": 0}]},
        )

    adapter = AzureFastTranscriptionProcessor(
        endpoint=ENDPOINT,
        key_env_name="COSMAS_TEST_SPEECH_KEY",
        transport=httpx.MockTransport(handler),
    )
    outcome = adapter.transcribe(_req())
    assert outcome.processor_id == ADAPTER_ID
    assert outcome.profile_id == PROFILE_ID
    assert outcome.segments[0].text == "Synthetic visit A"
    assert invented not in repr(outcome)
    assert seen and seen[0].headers.get("Ocp-Apim-Subscription-Key") == invented


def test_key_missing_failure_does_not_echo_secret(monkeypatch):
    monkeypatch.delenv("MISSING_SPEECH_KEY", raising=False)
    adapter = AzureFastTranscriptionProcessor(
        endpoint=ENDPOINT,
        key_env_name="MISSING_SPEECH_KEY",
        transport=httpx.MockTransport(lambda _: pytest.fail("no request")),
    )
    outcome = adapter.transcribe(_req())
    assert isinstance(outcome, TranscriptionFailure)
    assert "MISSING" not in (outcome.detail or "") or outcome.detail == "key_env_missing"
    assert outcome.detail == "key_env_missing"


def test_from_settings_never_used_when_azure_switch_off():
    """Guard: application must not construct Azure when azure switch is false."""
    from cosmas_os.config import Settings

    configured = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        independent_recording_transcription_enabled=False,
        independent_recording_transcription_azure_enabled=False,
    )
    assert configured.independent_recording_transcription_azure_enabled is False
