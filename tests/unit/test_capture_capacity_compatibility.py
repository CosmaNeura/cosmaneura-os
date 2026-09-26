"""Protocol compatibility with Core 1b74a1c / Scribe 6a55bf7 and legacy sessions."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.unit.test_core_capture_operations import exercise

from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.capture_continuity import CaptureContinuity
from cosmas_os.ports.capture_protocol import ReservePayload
from cosmas_os.ports.capture_recovery import CaptureRecoveryRequest


def test_current_capabilities_cross_the_authenticated_core_adapter():
    def current(envelope):
        envelope["receipt"].update(max_chunks=2048, remaining_aggregate_plaintext_bytes=402653184)

    assert exercise("capabilities", current).max_chunks == 2048
    assert exercise("capabilities").max_chunks == 1000


@pytest.mark.parametrize("chunks,capacity", [
    (1000, 67108865), (2048, 402653185), (2049, 402653184), (720, 268435456),
])
def test_unknown_or_mismatched_capability_budget_is_not_released(chunks, capacity):
    def forged(envelope):
        envelope["receipt"].update(max_chunks=chunks, remaining_aggregate_plaintext_bytes=capacity)

    with pytest.raises(ConnectorUnavailable):
        exercise("capabilities", forged)


def test_reservation_and_recovery_receive_current_last_chunk_without_extending_lease():
    reserve = dict(capture_lease_id=uuid4(), capture_lease_generation=1,
                   channel="microphone", first_sequence_number=1980, count=68)
    assert ReservePayload(**reserve).first_sequence_number == 1980
    with pytest.raises(ValidationError):
        ReservePayload(**{**reserve, "count": 69})
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/capture_recovery.json").read_text())
    request = {**fixture["request"], "first_sequence_number": 1000, "next_sequence_number": 1080}
    assert CaptureRecoveryRequest(**request).decision == "resume_capture"
    with pytest.raises(ValidationError):
        CaptureRecoveryRequest(**{**request, "next_sequence_number": 2048})
    assert CaptureRecoveryRequest(**{**request, "next_sequence_number": 2048,
                                     "decision": "finish_capture"}).next_sequence_number == 2048


def test_review_receives_restart_after_one_thousand_chunks_with_gap_warning():
    continuity = dict(schema_version="1.0", continuity="interrupted_or_unconfirmed",
                      missing_audio="unknown", starts=[
                          dict(source_start_id=uuid4(), first_sequence_number=0),
                          dict(source_start_id=uuid4(), first_sequence_number=1080),
                      ])
    assert CaptureContinuity(**continuity).missing_audio == "unknown"
    continuity["starts"][1]["first_sequence_number"] = 2048
    with pytest.raises(ValidationError):
        CaptureContinuity(**continuity)
