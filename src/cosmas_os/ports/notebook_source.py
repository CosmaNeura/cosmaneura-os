"""Exact private notebook provenance, distinct from a recorded transcript."""

import hashlib
from typing import Literal
from uuid import UUID

from pydantic import Field, model_serializer, model_validator

from cosmas_os.ports.capture_gap_review import Digest, GapReviewBound
from cosmas_os.ports.reviewed_source import ReviewedSourceReference
from cosmas_os.ports.scribe_capture import ProtectedModel


class NotebookSource(ProtectedModel):
    kind: Literal["clinician_scratch_notes"] = "clinician_scratch_notes"
    workspace_id: UUID
    entry_id: UUID
    revision: int = Field(ge=1, le=500, strict=True)
    content_sha256: Digest


class ScratchNotes(NotebookSource):
    content: str = Field(min_length=1, max_length=20000, repr=False)

    @model_validator(mode="after")
    def saved_content(self):
        if "\0" in self.content or hashlib.sha256(self.content.encode("utf-8")).hexdigest() != self.content_sha256:
            raise ValueError("invalid_notebook_source")
        return self


class NotebookBound(GapReviewBound):
    reviewed_source: ReviewedSourceReference | None = None
    notebook_source: NotebookSource | None = None

    @model_serializer(mode="wrap")
    def compatible_reference(self, handler):
        result = handler(self)
        for key in ("capture_gap_review", "notebook_source", "reviewed_source"):
            if getattr(self, key) is None:
                result.pop(key, None)
        return result
