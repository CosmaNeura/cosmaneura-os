"""Bounded saved Core context; generated drafts are not finalized clinical notes."""

import hashlib
import json
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from cosmas_os.ports.scribe_capture import ProtectedModel


class PrepSource(ProtectedModel):
    source_ref: str = Field(pattern=r"^(?:visit_note|intake)_[0-7][0-9a-hjkmnp-tv-z]{25}$")
    appointment_ref: str = Field(pattern=r"^appointment_[0-7][0-9a-hjkmnp-tv-z]{25}$")
    kind: Literal["generated_visit_note", "patient_intake_summary"]
    label: str = Field(min_length=1, max_length=200)
    source_at: AwareDatetime
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    content: str = Field(max_length=8000, repr=False)
    truncated: bool = Field(strict=True)


class CorePrepReceipt(ProtectedModel):
    appointment_ref: str = Field(pattern=r"^appointment_[0-7][0-9a-hjkmnp-tv-z]{25}$")
    sources: tuple[PrepSource, ...] = Field(max_length=6)
    additional_notes_available: bool = Field(strict=True)
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def exact_snapshot(self):
        value = self.model_dump(mode="json", exclude={"snapshot_sha256"})
        digest = hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        if digest != self.snapshot_sha256 or len({s.source_ref for s in self.sources}) != len(
            self.sources
        ):
            raise ValueError("invalid_prep_snapshot")
        prior_count = sum(s.kind == "generated_visit_note" for s in self.sources)
        if (
            prior_count > 5
            or len(self.sources) - prior_count > 1
            or self.additional_notes_available
            and prior_count != 5
        ):
            raise ValueError("invalid_prep_source_count")
        for source in self.sources:
            prefix = "intake_" if source.kind == "patient_intake_summary" else "visit_note_"
            if not source.source_ref.startswith(prefix) or "\0" in source.content:
                raise ValueError("invalid_prep_source")
            if (
                source.kind == "patient_intake_summary"
                and source.appointment_ref != self.appointment_ref
            ):
                raise ValueError("invalid_prep_source")
            if (
                source.kind == "generated_visit_note"
                and source.appointment_ref == self.appointment_ref
            ):
                raise ValueError("invalid_prep_source")
        return self
