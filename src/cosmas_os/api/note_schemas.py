from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cosmas_os.api.workspace_schemas import IdempotencyKey
from cosmas_os.ports.capture_gap_review import GapAcknowledgment
from cosmas_os.ports.core_notes import CoreDraftReference
from cosmas_os.ports.scribe_capture import ProtectedModel

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class CoreNoteLink(ProtectedModel):
    expected_revision: int = Field(ge=1, strict=True)
    idempotency_key: IdempotencyKey
    base_note_id: UUID | None = None
    source: CoreDraftReference


class NoteSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    idempotency_key: IdempotencyKey
    base_note_id: UUID | None = None
    source_reply_id: UUID | None = None
    content: str = Field(min_length=1, max_length=20000)
    sources_reconciled: bool = Field(default=False, strict=True)


class NoteReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    idempotency_key: IdempotencyKey
    content_hash: Digest
    source_fingerprint: Digest
    gap_acknowledgment: GapAcknowledgment | None = None
