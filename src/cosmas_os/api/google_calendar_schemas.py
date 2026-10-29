"""Closed bounded summary commands; the server owns account and time range."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, TypeAdapter, field_validator, model_validator

from cosmas_os.api.workspace_schemas import IdempotencyKey
from cosmas_os.ports.google_calendar import Digest, EventId
from cosmas_os.ports.scribe_capture import ProtectedModel


class Command(ProtectedModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Status(Command):
    action: Literal["status"]
    include_private_notebook: Literal[True] | None = None

    @field_validator("include_private_notebook", mode="before")
    @classmethod
    def explicit_capability(cls, value):
        if value is not True:
            raise ValueError("invalid_google_calendar_request")
        return value


class Observe(Command):
    action: Literal["observe"]
    idempotency_key: IdempotencyKey


class Inspect(Command):
    action: Literal["inspect"]
    observation_id: UUID


class Resolve(Command):
    action: Literal["resolve"]
    idempotency_key: IdempotencyKey


CALENDAR_COMMAND = TypeAdapter(Annotated[Status | Observe | Inspect | Resolve, Field(discriminator="action")])


class ReviewCalendar(Command):
    expected_revision: int = Field(strict=True, ge=1)
    idempotency_key: IdempotencyKey
    observation_id: UUID
    observation_sha256: Digest
    event_id: EventId
    event_sha256: Digest
    reviewed_visit: Literal[True] | None = None
    reviewed_private_notebook: Literal[True] | None = None
    reviewed_exact_summary: Literal[True]
    reviewed_untrusted_source: Literal[True]

    @field_validator("reviewed_visit", "reviewed_private_notebook", "reviewed_exact_summary", "reviewed_untrusted_source", mode="before")
    @classmethod
    def explicit_review(cls, value):
        if value is not True:
            raise ValueError("explicit_google_calendar_review_required")
        return value

    @model_validator(mode="after")
    def one_review_context(self):
        if (self.reviewed_visit is True) == (self.reviewed_private_notebook is True):
            raise ValueError("one_google_calendar_review_context_required")
        return self
