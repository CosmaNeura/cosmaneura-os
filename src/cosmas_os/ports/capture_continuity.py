"""Closed continuity evidence from Scribe; no inferred missing speech."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_serializer, model_validator

from cosmas_os.ports.capture_limits import MAX_CAPTURE_CHUNKS
from cosmas_os.ports.capture_recovery import GapReason
from cosmas_os.ports.capture_working import ProtectedContract


class NativeIntervalStart(ProtectedContract):
    source_start_id: UUID
    first_sequence_number: int = Field(strict=True, ge=0, lt=MAX_CAPTURE_CHUNKS)


class AcknowledgedCaptureInterruption(ProtectedContract):
    receipt_id: UUID
    gap_id: UUID
    next_sequence_number: int = Field(strict=True, ge=0, le=MAX_CAPTURE_CHUNKS)
    reason_code: GapReason
    decision: Literal["resume_capture", "finish_capture"]


class CaptureRecoveryEvidence(ProtectedContract):
    history_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    interruptions: tuple[AcknowledgedCaptureInterruption, ...] = Field(
        min_length=1, max_length=1000
    )

    @model_validator(mode="after")
    def ordered_interruptions(self) -> "CaptureRecoveryEvidence":
        rows = self.interruptions
        positions = [row.next_sequence_number for row in rows]
        if (
            positions != sorted(positions)
            or len({row.receipt_id for row in rows}) != len(rows)
            or len({row.gap_id for row in rows}) != len(rows)
            or any(row.decision == "finish_capture" for row in rows[:-1])
            or any(
                row.decision == "finish_capture" and row.next_sequence_number == 0
                for row in rows
            )
        ):
            raise ValueError("capture_continuity_invalid")
        return self


class CaptureContinuity(ProtectedContract):
    schema_version: Literal["1.0", "1.1"]
    continuity: Literal["interrupted_or_unconfirmed"]
    missing_audio: Literal["unknown"]
    starts: tuple[NativeIntervalStart, ...] = Field(max_length=1000)
    recovery: CaptureRecoveryEvidence | None = None

    @model_serializer(mode="wrap")
    def compatible_evidence(self, handler):
        value = handler(self)
        if self.recovery is None:
            value.pop("recovery", None)
        return value

    @model_validator(mode="after")
    def ordered_starts(self) -> "CaptureContinuity":
        positions = [item.first_sequence_number for item in self.starts]
        if (
            (
                self.schema_version == "1.0"
                and (len(self.starts) < 2 or self.recovery is not None)
            )
            or (self.schema_version == "1.1" and self.recovery is None)
            or (positions and positions[0] != 0)
            or positions != sorted(positions)
            or len({item.source_start_id for item in self.starts}) != len(self.starts)
        ):
            raise ValueError("capture_continuity_invalid")
        return self


def continuity_grounding(evidence: CaptureContinuity | None) -> str:
    if evidence is None:
        return ""
    return (
        "\nCAPTURE LIMITATION: This source has recorded interruption or native restart evidence. "
        "Continuous capture is unconfirmed. Do not infer missing speech, gap "
        "duration, findings, or completed actions. Transcript offsets describe "
        "retained audio, not total encounter duration. Use only the supplied "
        "reviewed source. The clinician must review possible recording gaps.\n"
    )
