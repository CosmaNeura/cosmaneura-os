"""Bounded EHR read and explicit human-review commands; no provider IDs or cursors."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, field_validator, model_validator

from cosmas_os.api.workspace_schemas import IdempotencyKey
from cosmas_os.ports.ehr_reads import Digest, Protected, Window


class Status(Protected):
    action: Literal["status"]


class Observe(Protected):
    action: Literal["observe"]
    connection_id: UUID
    binding_sha256: Digest
    starts_at: datetime
    ends_at: datetime
    idempotency_key: IdempotencyKey

    @model_validator(mode="after")
    def bounded(self):
        Window(starts_at=self.starts_at, ends_at=self.ends_at)
        return self


class Verify(Protected):
    action: Literal["verify"]
    connection_id: UUID
    binding_sha256: Digest
    observation_id: UUID
    observation_sha256: Digest
    item_handle: UUID
    item_sha256: Digest
    idempotency_key: IdempotencyKey


class Inspect(Protected):
    action: Literal["inspect"]
    observation_id: UUID


class Resolve(Protected):
    action: Literal["resolve"]
    idempotency_key: IdempotencyKey


EHR_COMMAND = TypeAdapter(Annotated[Status | Observe | Verify | Inspect | Resolve, Field(discriminator="action")])


class ReviewEhr(Protected):
    expected_revision: int = Field(strict=True, ge=1)
    idempotency_key: IdempotencyKey
    observation_id: UUID
    observation_sha256: Digest
    item_handle: UUID
    item_sha256: Digest
    reviewed_visit: Literal[True]
    reviewed_patient_identity: Literal[True]
    reviewed_exact_snapshot: Literal[True]
    reviewed_untrusted_source: Literal[True]

    @field_validator("reviewed_visit", "reviewed_patient_identity", "reviewed_exact_snapshot", "reviewed_untrusted_source", mode="before")
    @classmethod
    def explicit_review(cls, value):
        if value is not True:
            raise ValueError("explicit_ehr_read_review_required")
        return value
