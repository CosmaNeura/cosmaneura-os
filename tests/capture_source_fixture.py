"""Bind the actual Scribe fixture to one invented test session."""

import json
from pathlib import Path

from cosmas_os.ports.capture_protocol import SourceTranscript
from cosmas_os.ports.capture_recovery import CaptureRecoveryHistory
from cosmas_os.ports.capture_source import CaptureSourceEnvelope
from cosmas_os.ports.capture_working import WorkingSource, canonical_hash


def source_packet(kind, session_id):
    fixture = json.loads((Path(__file__).parent / "fixtures/capture_source.json").read_text())
    for name in ("base", "second"):
        value = fixture[name]
        value["session_id"] = value["raw_transcript"]["session_id"] = str(session_id)
        raw_hash = canonical_hash(SourceTranscript.model_validate(value["raw_transcript"]))
        working = value["working_transcript"]
        working["session_id"] = str(session_id)
        working["raw_transcript_sha256"] = raw_hash
        working["working_sha256"] = canonical_hash(
            {
                "raw_transcript_sha256": raw_hash,
                "working_source": WorkingSource.model_validate(working["working_source"]),
            }
        )
        if name == "second":
            working["previous_working_sha256"] = fixture["base"]["working_transcript"][
                "working_sha256"
            ]
        history = value["recovery_history"]
        history["session_id"] = str(session_id)
        for receipt in history["recoveries"]:
            receipt["session_id"] = receipt["lease"]["session_id"] = str(session_id)
        value["recovery_sha256"] = canonical_hash(CaptureRecoveryHistory.model_validate(history))
        value["source_sha256"] = canonical_hash(
            {
                "raw_transcript_sha256": raw_hash,
                "working_sha256": working["working_sha256"],
                "recovery_sha256": value["recovery_sha256"],
            }
        )
        fixture[name] = CaptureSourceEnvelope.model_validate(value).model_dump(mode="json")
    operation = {"kind": kind}
    if kind == "correct_capture_source":
        payload = fixture["correction"]
        payload["raw_transcript_sha256"] = fixture["base"]["working_transcript"][
            "raw_transcript_sha256"
        ]
        payload["expected_working_sha256"] = fixture["base"]["working_transcript"]["working_sha256"]
        operation["payload"] = payload
    return operation, fixture["base" if kind == "capture_source" else "second"]
