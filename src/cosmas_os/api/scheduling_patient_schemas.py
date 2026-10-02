"""Explicit human patient search/confirmation; opaque choices are not grants."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, TypeAdapter, field_validator

from cosmas_os.ports.scheduling_patient_setup import Digest, SearchPatientSelector
from cosmas_os.ports.scribe_capture import ProtectedModel


class Command(ProtectedModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Status(Command):
    action: Literal["status"]


class Preview(Command):
    action: Literal["preview"]
    expected_revision: int = Field(strict=True, ge=1)
    idempotency_key: UUID
    search: SearchPatientSelector


class Confirm(Command):
    action: Literal["confirm"]
    expected_revision: int = Field(strict=True, ge=1)
    idempotency_key: UUID
    preview_id: UUID
    preview_sha256: Digest
    choice_ref: UUID
    identity_sha256: Digest
    reviewed_same_patient: Literal[True]
    reviewed_exact_identity: Literal[True]

    @field_validator("reviewed_same_patient", "reviewed_exact_identity", mode="before")
    @classmethod
    def explicit_human_review(cls, value):
        if value is not True:
            raise ValueError("explicit_patient_identity_review_required")
        return value


class Inspect(Command):
    action: Literal["inspect"]
    request_id: UUID


class Resolve(Command):
    action: Literal["resolve"]
    kind: Literal["preview", "confirm"]
    idempotency_key: UUID


PATIENT_SETUP_COMMAND = TypeAdapter(Annotated[Status | Preview | Confirm | Inspect | Resolve, Field(discriminator="action")])
