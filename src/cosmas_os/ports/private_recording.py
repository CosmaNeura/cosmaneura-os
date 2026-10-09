"""Device-local recording metadata; never Core admission or upload authority."""
from datetime import UTC
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from cosmas_os.ports.capture_working import Digest, ProtectedContract
from cosmas_os.ports.scribe_capture import ConsentAttestation

MAX_SECONDS = 7200
MAX_FRAMES = MAX_SECONDS * 16000


class SavedRecordingSelection(ProtectedContract):
    recording_id: UUID
    link_receipt_id: UUID
    source_sha256: Digest
    manifest_sha256: Digest
    chunks: int = Field(ge=1, le=360, strict=True)
    frames: int = Field(ge=1, le=57_600_000, strict=True)


class RecordingBot(ProtectedContract):
    address: str = Field(min_length=1, max_length=36)
    team_revision: int = Field(strict=True, ge=1)


class AttachRecording(ProtectedContract):
    idempotency_key: UUID
    local_recording_id: UUID
    expected_workspace_revision: int = Field(strict=True, ge=1)
    bot: RecordingBot
    consent: ConsentAttestation
    started_at: AwareDatetime

    @field_validator("started_at")
    @classmethod
    def utc(cls, value):
        offset = value.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("UTC recording timestamp required")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def consent_precedes_capture(self):
        if self.consent.granted_at > self.started_at:
            raise ValueError("consent must precede local recording")
        return self


class FinishRecording(ProtectedContract):
    idempotency_key: UUID
    capture_state: Literal["finished", "interrupted", "unknown"]
    manifest_sha256: Digest | None = None
    chunks: int | None = Field(default=None, strict=True, ge=1, le=1000)
    frames: int | None = Field(default=None, strict=True, ge=1, le=MAX_FRAMES)
    ended_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def complete_metadata(self):
        fields = (self.manifest_sha256, self.chunks, self.frames, self.ended_at)
        if (self.capture_state == "unknown" and any(v is not None for v in fields)
                or self.capture_state != "unknown" and any(v is None for v in fields)):
            raise ValueError("recording outcome metadata required together")
        if self.ended_at is not None:
            offset = self.ended_at.utcoffset()
            if offset is None or offset.total_seconds() != 0:
                raise ValueError("UTC recording timestamp required")
        return self


class LinkRecording(ProtectedContract):
    idempotency_key: UUID
    expected_workspace_revision: int = Field(strict=True, ge=1)
    workspace_link_receipt_id: UUID
