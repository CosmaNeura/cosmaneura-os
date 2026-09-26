"""Closed qualified source projection, including immutable interruption evidence."""

from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool, model_validator

from cosmas_os.ports.capture_protocol import SourceTranscript
from cosmas_os.ports.capture_recovery import CaptureRecoveryHistory
from cosmas_os.ports.capture_working import (
    CaptureWorkingTranscript,
    Digest,
    ProtectedContract,
    canonical_hash,
)

MAX_CAPTURE_SOURCE_BYTES = 24 * 1024 * 1024


class CaptureSourceEnvelope(ProtectedContract):
    protocol_version: Literal["1.0"] = "1.0"
    session_id: UUID
    raw_transcript: SourceTranscript = Field(repr=False)
    working_transcript: CaptureWorkingTranscript = Field(repr=False)
    recovery_history: CaptureRecoveryHistory = Field(repr=False)
    recovery_sha256: Digest
    source_sha256: Digest
    capture_incomplete: StrictBool

    @model_validator(mode="after")
    def bound_source(self):
        raw = self.raw_transcript
        working = self.working_transcript
        if (
            raw.session_id != self.session_id
            or working.session_id != self.session_id
            or self.recovery_history.session_id != self.session_id
            or self.recovery_sha256 != canonical_hash(self.recovery_history)
            or self.source_sha256
            != canonical_hash(
                {
                    "raw_transcript_sha256": working.raw_transcript_sha256,
                    "working_sha256": working.working_sha256,
                    "recovery_sha256": self.recovery_sha256,
                }
            )
            or self.capture_incomplete != bool(self.recovery_history.recoveries)
        ):
            raise ValueError("capture_source_projection_invalid")
        # This proves recorded origin. The gateway separately supplies the
        # currently admitted practitioner, rather than trusting this assertion.
        working.validate_raw(raw, working.corrected_by_practitioner_id or "unmodified")
        return self

    def validate_practitioner(self, practitioner_id: str) -> None:
        self.working_transcript.validate_raw(
            self.raw_transcript, practitioner_id
        )
        if any(
            row.acknowledged_by_practitioner_id != practitioner_id
            for row in self.recovery_history.recoveries
        ):
            raise ValueError("capture_source_practitioner_invalid")
