import copy
import json
from pathlib import Path
from uuid import UUID, uuid5

import pytest
from pydantic import ValidationError
from starlette.requests import Request
from tests.unit.test_core_capture_operations import exercise

from cosmas_os.api.capture_schemas import CaptureOperationRequest, read_capture_request
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.ports.capture_protocol import SourceTranscript
from cosmas_os.ports.capture_source import CaptureSourceEnvelope
from cosmas_os.ports.capture_working import TranscriptCorrection, WorkingSource, canonical_hash
from cosmas_os.ports.creator_review import CreatorReviewView

FIXTURES = Path(__file__).parents[1] / "fixtures"


def long_source(extra=False):
    source = json.loads((FIXTURES / "capture_source.json").read_text())["base"]
    raw, working = source["raw_transcript"], source["working_transcript"]
    raw_template = raw["segments"][0]
    origin = working["working_source"]["segments"][0]
    projected = working["working_transcript"]["segments"][0]
    raw["segments"] = []
    working["working_source"]["segments"] = []
    working["working_transcript"]["segments"] = []
    for i, size in enumerate([100_000] * 5 + ([1] if extra else [])):
        text = "🩺" * size
        times = {"start_ms": i * 1000, "end_ms": (i + 1) * 1000}
        raw["segments"].append({**raw_template, **times, "content": text})
        segment = {**origin, **times, "source_segment_id": str(uuid5(UUID(raw["id"]), f"segment:{i}")), "content": text}
        working["working_source"]["segments"].append(segment)
        working["working_transcript"]["segments"].append({**projected, **times, "source_segment_id": segment["source_segment_id"], "content": text})
    working["working_source"]["duration_ms"] = len(raw["segments"]) * 1000
    working["raw_transcript_sha256"] = canonical_hash(SourceTranscript.model_validate(raw))
    working["working_sha256"] = canonical_hash({"raw_transcript_sha256": working["raw_transcript_sha256"], "working_source": WorkingSource.model_validate(working["working_source"])})
    source["source_sha256"] = canonical_hash({"raw_transcript_sha256": working["raw_transcript_sha256"], "working_sha256": working["working_sha256"], "recovery_sha256": source["recovery_sha256"]})
    return source


def long_review(session):
    view = json.loads((FIXTURES / "creator_review.json").read_text())["ready"]
    view["session_id"] = view["review_queue"]["session_id"] = session
    source, working = view["source"]["segments"][0], view["working"]["segments"][0]
    view["source"]["segments"], view["working"]["segments"] = [], []
    view["source"]["language_mode"] = "en-US"
    view["source"]["duration_ms"] = 10_000_000
    for i in range(10_000):
        common = {"source_segment_id": str(uuid5(UUID(session), str(i))), "source_locale": "en-US", "start_ms": i * 1000, "end_ms": (i + 1) * 1000, "content": "🩺" * 50}
        view["source"]["segments"].append({**source, **common})
        view["working"]["segments"].append({**working, **common, "resolution": "english_source", "translation_id": None, "translation_version": None, "translation_review_id": None})
    return view


def test_complete_half_million_character_source_retains_provenance_and_limits():
    value = long_source()
    accepted = CaptureSourceEnvelope.model_validate(value)
    assert sum(len(s.content) for s in accepted.raw_transcript.segments) == 500_000
    assert accepted.capture_incomplete is True
    with pytest.raises(ValidationError):
        CaptureSourceEnvelope.model_validate(long_source(extra=True))
    forged = copy.deepcopy(value)
    forged["working_transcript"]["working_transcript"]["segments"][0]["content"] = "changed"
    with pytest.raises(ValidationError):
        CaptureSourceEnvelope.model_validate(forged)


def test_current_core_large_review_crosses_previous_eight_mib_limit():
    def replace(envelope):
        receipt = envelope["receipt"]
        large = long_review(receipt["session_id"])
        assert len(json.dumps(large, ensure_ascii=False).encode()) > 8 * 1024 * 1024
        CreatorReviewView.model_validate(large)
        receipt.clear()
        receipt.update(large)
    result = exercise("creator_review", replace)
    assert len(result.source.segments) == 10_000


@pytest.mark.asyncio
async def test_large_unicode_correction_reaches_the_existing_closed_request_parser():
    source = long_source()["working_transcript"]
    payload = {"raw_transcript_id": source["raw_transcript_id"], "raw_transcript_sha256": source["raw_transcript_sha256"], "expected_working_version": 1, "expected_working_sha256": source["working_sha256"], "corrections": [{"source_segment_id": s["source_segment_id"], "content": s["content"], "speaker_role": s["speaker_role"]} for s in source["working_source"]["segments"]]}
    body = json.dumps({"session_id": source["session_id"], "idempotency_key": "long-synthetic-correction", "operation": {"kind": "correct_transcript", "payload": payload}}, ensure_ascii=False).encode()
    assert 1_048_576 < len(body) < 4_194_304

    async def parse(data):
        sent = False

        async def receive():
            nonlocal sent
            assert not sent
            sent = True
            return {"type": "http.request", "body": data, "more_body": False}
        request = Request({"type": "http", "headers": [(b"content-type", b"application/json"), (b"authorization", b"Bearer synthetic")], "query_string": b""}, receive)
        return await read_capture_request(request, CaptureOperationRequest)

    assert len((await parse(body)).operation.payload.corrections) == 5
    with pytest.raises(WorkspaceError):
        await parse(body + b" " * 4_194_304)
    excessive = copy.deepcopy(payload)
    excessive["corrections"].append({**payload["corrections"][0], "source_segment_id": str(uuid5(UUID(source["raw_transcript_id"]), "extra")), "content": "x"})
    with pytest.raises(ValidationError):
        TranscriptCorrection.model_validate(excessive)
