"""Human selection of an exact saved note; no client-supplied clinical text."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cosmas_os.api.note_schemas import Digest
from cosmas_os.api.workspace_schemas import IdempotencyKey


class ShareSavedNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    idempotency_key: IdempotencyKey
    note_id: UUID
    note_version: int = Field(ge=1, le=50, strict=True)
    content_hash: Digest
    source_fingerprint: Digest
    share_with_team: Literal[True]

    @field_validator("share_with_team", mode="before")
    @classmethod
    def explicit_human_share(cls, value):
        if value is not True:
            raise ValueError("explicit human sharing required")
        return value
