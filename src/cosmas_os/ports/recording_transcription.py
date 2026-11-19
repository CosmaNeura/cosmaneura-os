"""CosmaBot-owned transcription processor port (Oracle model slot later)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

TranscriptionFailureKind = Literal["corrupt", "truncated", "unavailable", "retryable"]
PROCESSOR_FAKE = "fake_transcription"
PROFILE_FAKE = "fake_synthetic_v1"


@dataclass(frozen=True, slots=True)
class TranscriptionRequest:
    audio: bytes
    sha256: str
    duration_ms: int
    language: str
    operation_id: str
    synthetic: bool


@dataclass(frozen=True, slots=True)
class TranscriptionSegment:
    text: str
    offset_ms: int = 0
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    segments: tuple[TranscriptionSegment, ...]
    processor_id: str
    profile_id: str
    synthetic: bool


@dataclass(frozen=True, slots=True)
class TranscriptionFailure:
    kind: TranscriptionFailureKind
    detail: str


class TranscriptionProcessor(Protocol):
    def transcribe(self, request: TranscriptionRequest) -> TranscriptionResult | TranscriptionFailure:
        """Process audio into an immutable transcript or a typed failure."""


class FakeTranscriptionProcessor:
    """Deterministic in-process fake. Default and only processor in tests/CI."""

    def __init__(
        self,
        *,
        crash_operations: frozenset[str] | None = None,
        fail_operations: dict[str, TranscriptionFailureKind] | None = None,
    ) -> None:
        self.crash_operations = crash_operations or frozenset()
        self.fail_operations = fail_operations or {}
        self.calls: list[str] = []

    def transcribe(self, request: TranscriptionRequest) -> TranscriptionResult | TranscriptionFailure:
        self.calls.append(request.operation_id)
        if request.operation_id in self.crash_operations:
            raise RuntimeError("injected processor crash")
        failure = self.fail_operations.get(request.operation_id)
        if failure is not None:
            return TranscriptionFailure(kind=failure, detail="injected failure")
        if not request.audio:
            return TranscriptionFailure(kind="corrupt", detail="empty audio")
        if len(request.audio) < 4:
            return TranscriptionFailure(kind="truncated", detail="audio too short")
        text = f"SYNTHETIC TRANSCRIPT operation={request.operation_id} language={request.language}"
        return TranscriptionResult(
            segments=(TranscriptionSegment(text=text, offset_ms=0, duration_ms=request.duration_ms),),
            processor_id=PROCESSOR_FAKE,
            profile_id=PROFILE_FAKE,
            synthetic=True,
        )
