from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cosmas_os.api.note_schemas import Digest
from cosmas_os.api.workspace_schemas import IdempotencyKey


class WorkHandoffCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1, strict=True)
    revision_id: UUID
    payload_hash: Digest
    idempotency_key: IdempotencyKey
    kind: Literal["offer", "accept", "decline", "recall", "reclaim"]
    recipient_id: UUID | None = None
    offer_id: UUID | None = None

    @model_validator(mode="after")
    def exact_shape(self):
        if (self.kind == "offer") != (self.recipient_id is not None):
            raise ValueError("Only an offer names a recipient")
        if (self.kind in {"accept", "decline", "recall"}) != (self.offer_id is not None):
            raise ValueError("A response identifies its exact offer")
        return self
