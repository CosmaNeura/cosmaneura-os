import json
from pathlib import Path
from uuid import uuid4

import pytest
from tests.unit.test_core_capture_operations import exercise

from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.capture_source import CaptureSourceEnvelope


def test_source_contract_agrees_with_actual_scribe_fixture():
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/capture_source.json").read_text())
    for name in ("base", "second"):
        assert (
            CaptureSourceEnvelope.model_validate(fixture[name]).model_dump(mode="json")
            == fixture[name]
        )


@pytest.mark.parametrize("kind", ["capture_source", "correct_capture_source"])
@pytest.mark.parametrize(
    "fault", ["session", "gap_hash", "source_hash", "raw", "incomplete", "extra"]
)
def test_changed_source_projection_is_not_released(kind, fault):
    def mutate(envelope):
        value = envelope["receipt"]
        if fault == "session":
            value["session_id"] = str(uuid4())
        elif fault == "gap_hash":
            value["recovery_sha256"] = "a" * 64
        elif fault == "source_hash":
            value["source_sha256"] = "b" * 64
        elif fault == "raw":
            value["raw_transcript"]["segments"][0]["content"] = "private_sentinel"
        elif fault == "incomplete":
            value["capture_incomplete"] = False
        else:
            value["review_approved"] = True

    with pytest.raises(ConnectorUnavailable) as failure:
        exercise(kind, mutate)
    assert "private_sentinel" not in str(failure.value)
