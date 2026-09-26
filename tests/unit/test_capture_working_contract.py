import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.unit.test_core_capture_operations import exercise

from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.capture_protocol import OPERATION_ADAPTER, SourceTranscript
from cosmas_os.ports.capture_working import CaptureWorkingTranscript

GOLDEN = json.loads((Path(__file__).parents[1] / "fixtures/capture_working.json").read_text())


def test_independent_scribe_projection_preserves_raw_provenance():
    raw = SourceTranscript.model_validate(GOLDEN["raw"])
    for name in ("base", "second", "third"):
        receipt = CaptureWorkingTranscript.model_validate(GOLDEN[name])
        receipt.validate_raw(raw, "doctor_" + "0" * 25 + "1")


@pytest.mark.parametrize("fault", ["hash", "raw", "projection", "blocker", "actor", "scope", "later_receipt"])
def test_working_adapter_rejects_misbound_or_malformed_receipt(fault):
    def mutate(body):
        receipt = body["receipt"]
        if fault == "hash":
            receipt["working_sha256"] = "0" * 64
        elif fault == "raw":
            receipt["raw_transcript_id"] = "00000000-0000-4000-8000-000000000009"
        elif fault == "projection":
            receipt["working_transcript"]["segments"][0]["content"] = "private_sentinel"
        elif fault == "blocker":
            receipt["working_transcript"]["note_ready"] = False
        elif fault == "actor":
            receipt["corrected_by_practitioner_id"] = None
        elif fault == "scope":
            body["workspace_id"] = "00000000-0000-4000-8000-000000000009"
        else:
            body["receipt"] = GOLDEN["third"]
    with pytest.raises(ConnectorUnavailable):
        exercise("correct_transcript", mutate)


@pytest.mark.parametrize("content", ["", "  ", "private_sentinel\0", "private_sentinel\ud800"])
def test_invalid_text_never_reaches_transport(content):
    payload = json.loads(json.dumps(GOLDEN["correction"]))
    payload["corrections"][0]["content"] = content
    with pytest.raises(ValidationError) as failure:
        OPERATION_ADAPTER.validate_python({"kind": "correct_transcript", "payload": payload})
    assert "private_sentinel" not in str(failure.value)
