"""Fake transcription processor: deterministic, injectable crash/failure, no I/O."""

from __future__ import annotations

import hashlib

import pytest

from cosmas_os.ports.recording_transcription import (
    LABEL_SYNTHETIC,
    FakeTranscriptionProcessor,
    TranscriptionFailure,
    TranscriptionRequest,
    TranscriptionResult,
)


def _request(op: str, audio: bytes = b"tone", **changes) -> TranscriptionRequest:
    base = dict(
        audio=audio,
        sha256=hashlib.sha256(audio).hexdigest(),
        duration_ms=1000,
        language="en-US",
        operation_id=op,
        synthetic=True,
    )
    base.update(changes)
    return TranscriptionRequest(**base)


def test_fake_transcript_starts_with_synthetic_label():
    result = FakeTranscriptionProcessor().transcribe(_request("op-a"))
    assert isinstance(result, TranscriptionResult)
    assert result.label == LABEL_SYNTHETIC
    assert result.segments[0].text.startswith("SYNTHETIC TRANSCRIPT")
    assert result.synthetic is True
    assert result.processor_id == "fake_transcription"


def test_fake_refuses_non_synthetic():
    outcome = FakeTranscriptionProcessor().transcribe(_request("real-op", synthetic=False))
    assert isinstance(outcome, TranscriptionFailure)
    assert outcome.kind == "unavailable"
    assert outcome.detail == "fake_non_synthetic_refused"


def test_fake_corrupt_and_truncated():
    fake = FakeTranscriptionProcessor()
    assert fake.transcribe(_request("empty", audio=b"")).kind == "corrupt"
    assert fake.transcribe(_request("short", audio=b"ab")).kind == "truncated"


def test_fake_injectable_failure_and_crash():
    fake = FakeTranscriptionProcessor(
        fail_operations={"fail-op": "unavailable"},
        crash_operations=frozenset({"crash-op"}),
    )
    failure = fake.transcribe(_request("fail-op"))
    assert isinstance(failure, TranscriptionFailure) and failure.kind == "unavailable"
    with pytest.raises(RuntimeError, match="injected processor crash"):
        fake.transcribe(_request("crash-op"))


def test_fake_guard_mutation_empty_audio_must_refuse():
    """Proving test: deleting the empty-audio guard would return a result."""
    result = FakeTranscriptionProcessor().transcribe(_request("empty", audio=b""))
    assert isinstance(result, TranscriptionFailure)
    assert result.kind == "corrupt"
