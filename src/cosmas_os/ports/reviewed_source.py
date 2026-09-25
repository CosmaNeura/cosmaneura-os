"""Core reviewed-English note provenance; no clinical approval is inferred."""
from typing import Literal
from uuid import UUID

from pydantic import SerializerFunctionWrapHandler, model_serializer

from cosmas_os.ports.capture_continuity import CaptureContinuity
from cosmas_os.ports.capture_working import ProtectedContract, Version


class ReviewedSourceReference(ProtectedContract):
    kind: Literal["reviewed_english"] = "reviewed_english"
    source_version: Version
    working_transcript_id: UUID
    working_version: Version
    capture_continuity: CaptureContinuity | None = None

    @model_serializer(mode="wrap")
    def compatible_continuity(self, handler: SerializerFunctionWrapHandler):
        value = handler(self)
        if self.capture_continuity is None:
            value.pop("capture_continuity", None)
        return value


