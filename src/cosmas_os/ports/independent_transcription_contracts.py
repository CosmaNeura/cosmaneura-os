"""Pydantic request bodies for CosmaBot independent transcription routes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

MAX_LEASE = 24 * 60 * 60  # seconds
MAX_DURATION_MS = 4 * 60 * 60 * 1000
MAX_AUDIO_BASE64_CHARS = 2_097_152


class IndependentTranscriptionConsent(BaseModel):
    modality: Literal["in_person", "phone", "video"]
    participant_regions: tuple[
        str,
        ...,
    ] = Field(default_factory=tuple, max_length=20)
    method: Literal["pre_visit_form", "verbal_attestation", "phone_ivr"]
    all_parties_consented: Literal[True]
    granted_at: datetime

    @field_validator("all_parties_consented", mode="before")
    @classmethod
    def explicit_true(cls, value):
        if value is not True:
            raise ValueError("explicit consent required")
        return value

    @field_validator("granted_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("consent time needs an offset")
        return value

    @field_validator("participant_regions")
    @classmethod
    def region_shape(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for region in value:
            if not region or len(region) > 16:
                raise ValueError("invalid consent region")
        if len(set(value)) != len(value):
            raise ValueError("duplicate consent region")
        return tuple(sorted(value))


class UploadIndependentAudio(BaseModel):
    operation_id: UUID
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duration_ms: int = Field(ge=1, le=MAX_DURATION_MS)
    language: str = Field(min_length=2, max_length=32)
    recording_class: Literal["synthetic", "demo", "real"] | None = None
    lease_expires_at: datetime
    consent: IndependentTranscriptionConsent
    audio_base64: str = Field(min_length=1, max_length=MAX_AUDIO_BASE64_CHARS)

    @field_validator("lease_expires_at")
    @classmethod
    def aware_lease(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("lease needs an offset")
        return value


class StartIndependentTranscription(BaseModel):
    operation_id: UUID


class RevokeIndependentTranscription(BaseModel):
    operation_id: UUID
