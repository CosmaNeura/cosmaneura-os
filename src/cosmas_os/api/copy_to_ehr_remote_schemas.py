"""Request bodies for Copy to EHR phone-remote highlight sessions."""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator

SectionKey = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{0,63}$", min_length=1, max_length=64),
]
VisitKey = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[A-Za-z0-9:_-]{1,100}$", min_length=1, max_length=100),
]
EndReason = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^(end|logout|visit_change)$"),
]


class CreateRemoteSession(BaseModel):
    model_config = {"extra": "forbid"}

    draft_id: UUID
    draft_revision: int = Field(strict=True, ge=1, le=1_000_000)
    section_keys: list[SectionKey] = Field(min_length=1, max_length=32)
    visit_key: VisitKey

    @field_validator("section_keys")
    @classmethod
    def unique_keys(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate_section_key")
        return value


class HighlightRemoteSection(BaseModel):
    model_config = {"extra": "forbid"}

    draft_revision: int = Field(strict=True, ge=1, le=1_000_000)
    section_key: SectionKey


class EndRemoteSession(BaseModel):
    model_config = {"extra": "forbid"}

    reason: EndReason = "end"
