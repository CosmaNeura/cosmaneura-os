"""Explicit selected Microsoft reads and human source custody; no mailbox writes."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, TypeAdapter, field_validator

from cosmas_os.api.workspace_schemas import IdempotencyKey
from cosmas_os.ports.microsoft_message import Digest, MessageId
from cosmas_os.ports.scribe_capture import ProtectedModel


class Command(ProtectedModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Status(Command):
    action: Literal["status"]


class ListMessages(Command):
    action: Literal["list"]
    idempotency_key: IdempotencyKey


class ReadMessage(Command):
    action: Literal["read"]
    idempotency_key: IdempotencyKey
    observation_id: UUID
    observation_sha256: Digest
    message_id: MessageId
    thread_id: MessageId | None = None


class InspectMessage(Command):
    action: Literal["inspect"]
    read_id: UUID


class ResolveMessage(Command):
    action: Literal["resolve"]
    idempotency_key: IdempotencyKey
    kind: Literal["list", "message"]


MESSAGE_COMMAND = TypeAdapter(Annotated[Status | ListMessages | ReadMessage | InspectMessage | ResolveMessage,
                                       Field(discriminator="action")])


class ReviewMessage(Command):
    expected_revision: int = Field(strict=True, ge=1)
    idempotency_key: IdempotencyKey
    read_id: UUID
    source_sha256: Digest
    reviewed_patient: Literal[True]
    reviewed_exact_message: Literal[True]
    reviewed_untrusted_source: Literal[True]

    @field_validator("reviewed_patient", "reviewed_exact_message", "reviewed_untrusted_source", mode="before")
    @classmethod
    def explicit_review(cls, value):
        if value is not True:
            raise ValueError("explicit_microsoft_message_review_required")
        return value
