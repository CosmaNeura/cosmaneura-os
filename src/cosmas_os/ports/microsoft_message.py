"""One explicitly selected Outlook message and private, refresh-stable custody."""

import hashlib
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MessageId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_+/=-]{1,2048}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ClosedMessageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class MicrosoftMessageSelection(ClosedMessageModel):
    message_id: MessageId
    thread_id: MessageId | None = None


class MicrosoftMessageBinding(ClosedMessageModel):
    account_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
    binding_digest: Digest
    connected_at: datetime
    grant_sha256: Digest

    @model_validator(mode="after")
    def aware_connection(self):
        if self.connected_at.tzinfo is None or self.connected_at.utcoffset() is None:
            raise ValueError("microsoft_message_binding_invalid")
        return self


class MicrosoftMessageRead(ClosedMessageModel):
    message_id: MessageId
    thread_id: MessageId
    change_key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_+/=-]{1,2048}$")] | None = None
    subject: str = Field(max_length=998)
    sender: str = Field(max_length=320)
    received_at: datetime
    is_read: bool
    observed_at: datetime
    status: Literal["complete", "needs_human"]
    content: str | None = Field(default=None, max_length=5000)
    reason: Literal["attachment", "html_only", "unsupported_mime", "oversize", "ambiguous", "invalid_encoding"] | None = None
    raw_sha256: Digest
    content_sha256: Digest | None = None
    custody: MicrosoftMessageBinding

    @model_validator(mode="after")
    def exact_completion(self):
        if any(t.tzinfo is None or t.utcoffset() is None for t in (self.received_at, self.observed_at)):
            raise ValueError("microsoft_message_time_invalid")
        if self.status == "complete":
            if self.content is None or self.reason is not None or self.content_sha256 is None:
                raise ValueError("microsoft_message_completion_invalid")
            if hashlib.sha256(self.content.encode()).hexdigest() != self.content_sha256:
                raise ValueError("microsoft_message_completion_invalid")
        elif self.content is not None or self.content_sha256 is not None or self.reason is None:
            raise ValueError("microsoft_message_completion_invalid")
        return self
