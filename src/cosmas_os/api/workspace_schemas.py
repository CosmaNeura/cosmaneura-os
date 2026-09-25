from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

IdempotencyKey = Annotated[str, Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9:_-]+$")]


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    appointment_id: UUID
    idempotency_key: IdempotencyKey


class WorkspaceAppend(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1, strict=True)
    idempotency_key: IdempotencyKey
    kind: Literal["scratchpad", "conversation", "evidence"]
    content: str = Field(min_length=1, max_length=20000)
    source_label: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def evidence_label(self):
        if (self.kind == "evidence") != (self.source_label is not None):
            raise ValueError("only evidence requires a source label")
        return self


class WorkspaceWorkLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    idempotency_key: IdempotencyKey
    ticket_id: UUID
