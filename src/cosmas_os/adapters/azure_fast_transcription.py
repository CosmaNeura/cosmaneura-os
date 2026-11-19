"""Azure AI Speech Fast Transcription adapter. Default-off; MockTransport in tests."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from cosmas_os.ports.recording_transcription import (
    LABEL_SYNTHETIC,
    TranscriptionFailure,
    TranscriptionRequest,
    TranscriptionResult,
    TranscriptionSegment,
)

ADAPTER_ID = "azure_ai_speech"
PROFILE_ID = "azure_fast_transcription_en_es_v1"
API_VERSION = "2024-11-15"
TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"
# Fixed env name only; settings never hold a key value.
FIXED_KEY_ENV_NAME = "COSMAS_AZURE_SPEECH_KEY"
AuthMode = Literal["entra", "key"]
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_DURATION_MS = 4 * 60 * 60 * 1000
MAX_ATTEMPTS = 3
BASE_TIMEOUT_SECONDS = 15.0
TIMEOUT_PER_MINUTE = 10.0
ALLOWED_LOCALES = frozenset({"en-US", "es-US", "en-ES", "es-ES"})
# Pinned Cognitive Services host shape; US regions only.
_US_REGIONS = frozenset(
    {
        "eastus",
        "eastus2",
        "westus",
        "westus2",
        "westus3",
        "centralus",
        "northcentralus",
        "southcentralus",
        "westcentralus",
    }
)
_HOST_RE = re.compile(
    r"^(?P<region>[a-z0-9]+)\.api\.cognitive\.microsoft\.com$"
)
_PATH = "/speechtotext/transcriptions:transcribe"


def validate_azure_fast_transcription_endpoint(value: str) -> bool:
    parsed = urlparse(value)
    if not (
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and not parsed.params
        and parsed.path.rstrip("/") == _PATH.rstrip("/")
    ):
        return False
    match = _HOST_RE.fullmatch(parsed.hostname.lower())
    return bool(match and match.group("region") in _US_REGIONS)


def _scaled_timeout(duration_ms: int) -> float:
    minutes = max(duration_ms, 1) / 60_000
    return BASE_TIMEOUT_SECONDS + TIMEOUT_PER_MINUTE * minutes


class AzureFastTranscriptionProcessor:
    """Implements TranscriptionProcessor against Azure Fast Transcription REST."""

    def __init__(
        self,
        *,
        endpoint: str,
        auth: AuthMode,
        token_provider: Callable[[], str] | None = None,
        transport: httpx.BaseTransport | None = None,
        credential: Any | None = None,
    ) -> None:
        if not validate_azure_fast_transcription_endpoint(endpoint):
            raise ValueError("invalid azure fast transcription endpoint")
        if auth == "entra" and token_provider is None and credential is None:
            raise ValueError("azure fast transcription entra auth required")
        self._endpoint = endpoint.rstrip("/")
        self._auth = auth
        self._token_provider = token_provider
        self._transport = transport
        self._credential = credential

    @classmethod
    def from_settings(
        cls,
        *,
        endpoint: str,
        auth: AuthMode = "entra",
        transport: httpx.BaseTransport | None = None,
        credential: Any | None = None,
    ) -> AzureFastTranscriptionProcessor:
        if auth == "key":
            return cls(endpoint=endpoint, auth="key", transport=transport)
        reused = credential
        if reused is None:
            from azure.identity import DefaultAzureCredential

            reused = DefaultAzureCredential(exclude_interactive_browser_credential=True)

        def token_provider() -> str:
            return reused.get_token(TOKEN_SCOPE).token

        return cls(
            endpoint=endpoint,
            auth="entra",
            token_provider=token_provider,
            transport=transport,
            credential=reused,
        )

    def transcribe(self, request: TranscriptionRequest) -> TranscriptionResult | TranscriptionFailure:
        if not request.synthetic:
            return TranscriptionFailure(kind="unavailable", detail="non_synthetic_refused")
        if len(request.audio) > MAX_AUDIO_BYTES:
            return TranscriptionFailure(kind="truncated", detail="audio_too_large")
        if request.duration_ms > MAX_DURATION_MS or request.duration_ms < 1:
            return TranscriptionFailure(kind="corrupt", detail="duration_out_of_bounds")
        digest = hashlib.sha256(request.audio).hexdigest()
        if digest != request.sha256:
            return TranscriptionFailure(kind="corrupt", detail="sha256_mismatch")
        if not request.audio:
            return TranscriptionFailure(kind="corrupt", detail="empty_audio")
        locale = request.language if request.language in ALLOWED_LOCALES else None
        if locale is None:
            return TranscriptionFailure(kind="corrupt", detail="locale_not_allowed")
        headers = self._auth_headers()
        if isinstance(headers, TranscriptionFailure):
            return headers
        url = f"{self._endpoint}?api-version={API_VERSION}"
        definition = json.dumps({"locales": [locale]}, ensure_ascii=True, separators=(",", ":"))
        files = {
            "audio": ("audio.wav", request.audio, "application/octet-stream"),
            "definition": (None, definition, "application/json"),
        }
        timeout = _scaled_timeout(request.duration_ms)
        last: TranscriptionFailure | None = None
        for _ in range(MAX_ATTEMPTS):
            try:
                with httpx.Client(
                    transport=self._transport, timeout=timeout, follow_redirects=False
                ) as client:
                    response = client.post(url, headers=headers, files=files)
            except httpx.TimeoutException:
                last = TranscriptionFailure(kind="retryable", detail="timeout")
                continue
            except httpx.HTTPError:
                return TranscriptionFailure(kind="unavailable", detail="transport_error")
            outcome = self._map_response(response)
            if isinstance(outcome, TranscriptionFailure) and outcome.kind == "retryable":
                last = outcome
                continue
            return outcome
        return last or TranscriptionFailure(kind="retryable", detail="attempts_exhausted")

    def _auth_headers(self) -> dict[str, str] | TranscriptionFailure:
        if self._auth == "key":
            value = os.environ.get(FIXED_KEY_ENV_NAME)
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
        if not isinstance(body, dict):
            return TranscriptionFailure(kind="unavailable", detail="invalid_body")
        phrases = body.get("combinedPhrases") or body.get("phrases") or []
        if not isinstance(phrases, list):
            return TranscriptionFailure(kind="unavailable", detail="invalid_phrases")
        segments: list[TranscriptionSegment] = []
        for item in phrases:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if not isinstance(text, str) or not text:
                continue
            offset = item.get("offsetMilliseconds") or 0
            duration = item.get("durationMilliseconds") or 0
            if not isinstance(offset, int) or not isinstance(duration, int):
                continue
            if offset < 0 or duration < 0:
                continue
            segments.append(TranscriptionSegment(text=text, offset_ms=offset, duration_ms=duration))
        if not segments:
            return TranscriptionFailure(kind="unavailable", detail="empty_transcript")
        return TranscriptionResult(
            segments=tuple(segments),
            processor_id=ADAPTER_ID,
            profile_id=PROFILE_ID,
            synthetic=True,
            label=LABEL_SYNTHETIC,
        )
