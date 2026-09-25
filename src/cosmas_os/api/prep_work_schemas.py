from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from cosmas_os.api.capture_schemas import CaptureBotSelection
from cosmas_os.api.note_schemas import Digest
from cosmas_os.api.workspace_schemas import IdempotencyKey
from cosmas_os.ports.scribe_capture import ProtectedModel


class PrepWorkPropose(ProtectedModel):
    bot: CaptureBotSelection
    expected_entry_revision: int = Field(ge=1, strict=True)
    snapshot_sha256: Digest
    body: str = Field(min_length=1, max_length=4000)
    due_date: date
    expected_outcome: str = Field(min_length=1, max_length=500)
    share_context: bool = Field(strict=True)
    idempotency_key: IdempotencyKey


class PrepWorkDecision(ProtectedModel):
    expected_version: int = Field(ge=1, strict=True)
    revision_id: UUID
    payload_hash: Digest
    choice: Literal["approve", "reject"]
    bot: CaptureBotSelection | None = None
    expected_snapshot_sha256: Digest | None = None

    @model_validator(mode="after")
    def approval_shape(self):
        if (self.choice == "approve") != (self.bot is not None and self.expected_snapshot_sha256 is not None):
            raise ValueError("invalid_preparation_review")
        if self.choice == "reject" and (self.bot is not None or self.expected_snapshot_sha256 is not None):
            raise ValueError("invalid_preparation_review")
        return self


class PrepWorkVerify(ProtectedModel):
    bot: CaptureBotSelection
    expected_version: int = Field(ge=1, strict=True)
    revision_id: UUID
    payload_hash: Digest
    current_snapshot_sha256: Digest
    reviewed_summary: bool = Field(strict=True)
    idempotency_key: IdempotencyKey
