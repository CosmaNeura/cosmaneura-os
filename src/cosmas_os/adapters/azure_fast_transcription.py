"""Azure AI Speech Fast Transcription adapter. Default-off; MockTransport in tests."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import httpx

from cosmas_os.ports.recording_transcription import (
    TranscriptionFailure,
    TranscriptionRequest,
    TranscriptionResult,
    TranscriptionSegment,
)

ADAPTER_ID = "azure_ai_speech"
PROFILE_ID = "azure_fast_transcription_en_es_v1"
API_VERSION = "2024-11-15"
TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"


def validate_azure_fast_transcription_endpoint(value: str) -> bool:
    parsed = urlparse(value)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and not parsed.params
        and parsed.path not in {"", "/"}
    )


class AzureFastTranscriptionProcessor:
    """Implements TranscriptionProcessor against Azure Fast Transcription REST."""

    def __init__(
        self,
        *,
        endpoint: str,
        token_provider: Callable[[], str] | None = None,
        key_env_name: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not validate_azure_fast_transcription_endpoint(endpoint):
            raise ValueError("invalid azure fast transcription endpoint")
        if token_provider is None and not key_env_name:
            raise ValueError("azure fast transcription auth required")
        self._endpoint = endpoint.rstrip("/")
        self._token_provider = token_provider
        self._key_env_name = key_env_name
        self._transport = transport
        self._timeout = timeout_seconds

    @classmethod
    def from_settings(
        cls,
        *,
        endpoint: str,
        key_env_name: str | None = None,
        transport: httpx.BaseTransport | None = None,
        credential_factory: Callable[[], Any] | None = None,
    ) -> AzureFastTranscriptionProcessor:
        if key_env_name:
            return cls(endpoint=endpoint, key_env_name=key_env_name, transport=transport)

        def token_provider() -> str:
            factory = credential_factory
            if factory is None:
                from azure.identity import DefaultAzureCredential

                def factory():
                    return DefaultAzureCredential(exclude_interactive_browser_credential=True)

            return factory().get_token(TOKEN_SCOPE).token

        return cls(endpoint=endpoint, token_provider=token_provider, transport=transport)

    def transcribe(self, request: TranscriptionRequest) -> TranscriptionResult | TranscriptionFailure:
        if not request.synthetic:
            return TranscriptionFailure(kind="unavailable", detail="non_synthetic_refused")
        digest = hashlib.sha256(request.audio).hexdigest()
        if digest != request.sha256:
            return TranscriptionFailure(kind="corrupt", detail="sha256_mismatch")
        if not request.audio:
            return TranscriptionFailure(kind="corrupt", detail="empty_audio")
        headers = self._auth_headers()
        if isinstance(headers, TranscriptionFailure):
            return headers
        url = f"{self._endpoint}?api-version={API_VERSION}"
        files = {
            "audio": ("audio.wav", request.audio, "application/octet-stream"),
            "definition": (
                None,
                f'{{"locales":["{request.language or "en-US"}"]}}',
                "application/json",
            ),
        }
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout, follow_redirects=False) as client:
                response = client.post(url, headers=headers, files=files)
        except httpx.TimeoutException:
            return TranscriptionFailure(kind="retryable", detail="timeout")
        except httpx.HTTPError:
            return TranscriptionFailure(kind="unavailable", detail="transport_error")
        return self._map_response(response)

    def _auth_headers(self) -> dict[str, str] | TranscriptionFailure:
        if self._key_env_name:
            value = os.environ.get(self._key_env_name)
            if not value:
                return TranscriptionFailure(kind="unavailable", detail="key_env_missing")
            return {"Ocp-Apim-Subscription-Key": value}
        assert self._token_provider is not None
        try:
            token = self._token_provider()
        except Exception:
            return TranscriptionFailure(kind="unavailable", detail="token_unavailable")
        if not token:
            return TranscriptionFailure(kind="unavailable", detail="token_empty")
        return {"Authorization": f"Bearer {token}"}

    def _map_response(self, response: httpx.Response) -> TranscriptionResult | TranscriptionFailure:
        if response.status_code in {408, 429, 500, 502, 503, 504}:
            return TranscriptionFailure(kind="retryable", detail=f"http_{response.status_code}")
        if response.status_code == 400:
            return TranscriptionFailure(kind="corrupt", detail="http_400")
        if response.status_code == 413:
            return TranscriptionFailure(kind="truncated", detail="http_413")
        if response.status_code != 200:
            return TranscriptionFailure(kind="unavailable", detail=f"http_{response.status_code}")
        try:
            body = response.json()
        except ValueError:
            return TranscriptionFailure(kind="unavailable", detail="invalid_json")
        phrases = body.get("combinedPhrases") or body.get("phrases") or []
        segments: list[TranscriptionSegment] = []
        if isinstance(phrases, list):
            for item in phrases:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if not isinstance(text, str) or not text:
                    continue
                segments.append(
                    TranscriptionSegment(
                        text=text,
                        offset_ms=int(item.get("offsetMilliseconds") or 0),
                        duration_ms=int(item.get("durationMilliseconds") or 0),
                    )
                )
        if not segments:
            return TranscriptionFailure(kind="unavailable", detail="empty_transcript")
        return TranscriptionResult(
            segments=tuple(segments),
            processor_id=ADAPTER_ID,
            profile_id=PROFILE_ID,
            synthetic=True,
        )
