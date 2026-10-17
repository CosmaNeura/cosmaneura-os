"""Closed practice-access requests. No caller-supplied account or organization."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SubmitAccess(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID
    display_name: str = Field(min_length=1, max_length=120, strict=True)

    @field_validator("display_name")
    @classmethod
    def name(cls, value):
        if value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("invalid display name")
        return value


class CompletePracticeSetup(SubmitAccess):
    practice_name: str = Field(min_length=1, max_length=120, strict=True)
    specialty: str | None = Field(default=None, max_length=120, strict=True)
    confirm: bool = Field(strict=True)

    @field_validator("practice_name", "specialty")
    @classmethod
    def setup_text(cls, value):
        if value == "":
            raise ValueError("setup text must not be empty")
        return SubmitAccess.name(value) if value is not None else None

    @field_validator("confirm")
    @classmethod
    def confirm_setup(cls, value):
        if value is not True:
            raise ValueError("confirmation required")
        return value


class ReviewAccess(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    review_sha256: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)
    confirm: bool = Field(strict=True)

    @field_validator("confirm")
    @classmethod
    def confirmed(cls, value):
        if value is not True:
            raise ValueError("confirmation required")
        return value


class DecideAccess(ReviewAccess):
    decision: Literal["approve", "decline"]


class MembersPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after_id: UUID | None


class MemberChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID
    member_id: UUID
    action: Literal["deactivate", "reactivate"]
    review_sha256: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)
    reviewed_at: str = Field(min_length=25, max_length=40, strict=True)
    confirm: bool = Field(strict=True)

    @field_validator("confirm")
    @classmethod
    def confirmed(cls, value):
        return ReviewAccess.confirmed(value)

    @field_validator("reviewed_at")
    @classmethod
    def canonical_time(cls, value):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.astimezone(UTC).isoformat() != value:
            raise ValueError("canonical UTC review timestamp required")
        return value


class CreateInvitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID
    label: str = Field(min_length=1, max_length=120, strict=True)
    token: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)
    expires_in_hours: Literal[24, 72, 168]

    @field_validator("label")
    @classmethod
    def text(cls, value):
        return SubmitAccess.name(value)

    @field_validator("expires_in_hours", mode="before")
    @classmethod
    def exact_hours(cls, value):
        if type(value) is not int:
            raise ValueError("integer expiry required")
        return value


class RevokeInvitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID
    invitation_id: UUID


class JoinInvitation(SubmitAccess):
    token: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)
