"""Exact review evidence accompanying a Core draft from interrupted capture."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_serializer, model_validator

from cosmas_os.ports.capture_recovery import GapReason
from cosmas_os.ports.scribe_capture import ProtectedModel

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class GapObservation(ProtectedModel):
    gap_id: UUID
    reason_code: GapReason
    observed_at: AwareDatetime
    acknowledged_at: AwareDatetime
    decision: Literal["resume_capture", "finish_capture"]

    @model_validator(mode="after")
    def ordered_observation(self):
        if self.observed_at > self.acknowledged_at:
            raise ValueError("invalid_gap_observation")
        return self


class CaptureGapReview(ProtectedModel):
    recovery_sha256: Digest
    observations: tuple[GapObservation, ...] = Field(min_length=1, max_length=1000)
    review_required: Literal[True] = True

    @field_validator("review_required", mode="before")
    @classmethod
    def explicit_required(cls, value):
        if value is not True:
            raise ValueError("invalid_gap_review_state")
        return value

    @model_validator(mode="after")
    def distinct_ordered_gaps(self):
        if len({item.gap_id for item in self.observations}) != len(self.observations):
            raise ValueError("duplicate_gap_observation")
        if any(
            right.observed_at < left.acknowledged_at
            for left, right in zip(self.observations, self.observations[1:], strict=False)
        ):
            raise ValueError("invalid_gap_observation_order")
        return self


class GapReviewBound(ProtectedModel):
    capture_gap_review: CaptureGapReview | None = None

    @model_serializer(mode="wrap")
    def compatible_reference(self, handler):
        result = handler(self)
        if self.capture_gap_review is None:
            result.pop("capture_gap_review", None)
        return result


class GapAcknowledgment(ProtectedModel):
    recovery_sha256: Digest
    acknowledged: Literal[True]

    @field_validator("acknowledged", mode="before")
    @classmethod
    def explicit_acknowledgment(cls, value):
        if value is not True:
            raise ValueError("gap_acknowledgment_required")
        return value
