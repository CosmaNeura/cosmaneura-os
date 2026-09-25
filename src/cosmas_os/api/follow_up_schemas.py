from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cosmas_os.api.note_schemas import Digest
from cosmas_os.api.workspace_schemas import IdempotencyKey


class FollowUpPropose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    idempotency_key: IdempotencyKey
    note_id: UUID
    body: str = Field(min_length=1, max_length=4000)
    due_date: date
    expected_outcome: str = Field(min_length=1, max_length=500)
    share: bool = Field(strict=True)


class FollowUpDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: UUID
    payload_hash: Digest
    choice: Literal["approve", "reject"]


class FollowUpComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: UUID
    payload_hash: Digest
    idempotency_key: IdempotencyKey
    evidence: str = Field(min_length=1, max_length=2000)
    expected_version: int | None = Field(default=None, ge=1, strict=True)
