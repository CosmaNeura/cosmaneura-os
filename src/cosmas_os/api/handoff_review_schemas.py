"""Closed human feedback contract for an exact saved private handoff result."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cosmas_os.api.workspace_schemas import IdempotencyKey


class HandoffReview(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    expected_revision: int = Field(strict=True, ge=1)
    idempotency_key: IdempotencyKey
    attempt_id: UUID
    result_entry_id: UUID
    result_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    decision: Literal["accepted", "changes_requested"]
    feedback: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def actionable_feedback(self):
        if "\0" in self.feedback or (
            self.decision == "changes_requested" and not self.feedback.strip()
        ):
            raise ValueError("handoff_review_feedback_required")
        return self


class HandoffRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    expected_revision: int = Field(strict=True, ge=1)
    idempotency_key: IdempotencyKey
    review_id: UUID
