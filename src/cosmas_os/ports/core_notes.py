"""Closed source/template/draft references for the capture review workflow."""

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from cosmas_os.ports.notebook_source import NotebookBound, ScratchNotes
from cosmas_os.ports.scribe_capture import ProtectedModel

SchemaRef = Annotated[str, Field(pattern=r"^doctor_note_schema_[0-7][0-9a-hjkmnp-tv-z]{25}$")]
NoteRef = Annotated[str, Field(pattern=r"^visit_note_[0-7][0-9a-hjkmnp-tv-z]{25}$")]
TranscriptRef = Annotated[str, Field(pattern=r"^ai_visit_transcript_[0-7][0-9a-hjkmnp-tv-z]{25}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
NoteAction = Literal["templates", "read", "prepare", "save", "resolve"]


class CoreNoteEdit(ProtectedModel):
    client_key: UUID
    expected_note_ref: NoteRef
    expected_note_sha256: Digest
    expected_source_sha256: Digest
    fields: dict[str, str] = Field(min_length=1, max_length=100)

    @field_validator("fields")
    @classmethod
    def bounded_fields(cls, fields):
        try:
            if any(not key or len(key) > 200 or "\0" in key or "\0" in value for key, value in fields.items()):
                raise ValueError
            if len(json.dumps(fields, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 262_144:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("invalid_note_edit") from None
        return fields


class CoreNoteSelection(ProtectedModel):
    action: NoteAction
    schema_ref: SchemaRef | None = None
    edit: CoreNoteEdit | None = None
    scratch_notes: ScratchNotes | None = None

    @model_validator(mode="after")
    def selected_template(self):
        if (self.action == "templates") != (self.schema_ref is None):
            raise ValueError("invalid_template_selection")
        if (self.action in {"save", "resolve"}) != (self.edit is not None):
            raise ValueError("invalid_note_edit_selection")
        if self.scratch_notes is not None and self.action not in {"read", "prepare"}:
            raise ValueError("invalid_notebook_selection")
        return self


def core_note_edit_hash(edit: CoreNoteEdit, schema_ref: str, session_id: UUID, workspace_id: UUID) -> str:
    value = {"edit": edit.model_dump(mode="json"), "schema": schema_ref,
             "session": str(session_id), "workspace": str(workspace_id)}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class CoreSaveResolution(ProtectedModel):
    session_id: UUID
    schema_ref: SchemaRef
    client_key: UUID
    request_sha256: Digest
    status: Literal["saved", "closed"]
    result_note_ref: NoteRef | None = None
    result_sha256: Digest | None = None

    @model_validator(mode="after")
    def consistent_result(self):
        if (self.result_note_ref is not None) != (self.status == "saved") or (self.result_sha256 is not None) != (self.status == "saved"):
            raise ValueError("invalid_note_save_resolution")
        return self


class CoreNoteTemplate(ProtectedModel):
    schema_ref: SchemaRef
    note_type: str = Field(min_length=1, max_length=160)
    field_names: tuple[Annotated[str, Field(min_length=1, max_length=200)], ...] = Field(min_length=1, max_length=100)

    @field_validator("field_names")
    @classmethod
    def distinct_fields(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("duplicate_template_field")
        return value


class CoreTemplateReceipt(ProtectedModel):
    session_id: UUID
    templates: tuple[CoreNoteTemplate, ...] = Field(max_length=100)

    @field_validator("templates")
    @classmethod
    def distinct_templates(cls, value):
        if len({item.schema_ref for item in value}) != len(value):
            raise ValueError("duplicate_template")
        return value


def note_content_hash(fields: dict[str, str], field_order: tuple[str, ...] | None = None) -> str:
    # Field order is part of the template and of Core's receipt digest.
    canonical = json.dumps([[key, fields[key]] for key in (field_order or tuple(fields))], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class CoreDraftReceipt(NotebookBound):
    session_id: UUID
    scribe_source_id: UUID
    source_sha256: Digest
    schema_ref: SchemaRef
    transcript_ref: TranscriptRef | None
    note_ref: NoteRef | None
    status: Literal["not_prepared", "draft"]
    note_type: str = Field(min_length=1, max_length=160)
    fields: dict[str, str] | None
    field_order: tuple[str, ...] | None
    note_sha256: Digest | None
    created_at: AwareDatetime | None
    review_required: Literal[True]

    @field_validator("review_required", mode="before")
    @classmethod
    def unreviewed_output(cls, value):
        if value is not True:
            raise ValueError("invalid_review_state")
        return value

    @model_validator(mode="after")
    def consistent_draft(self):
        if self.reviewed_source is not None and self.reviewed_source.working_transcript_id != self.scribe_source_id:
            raise ValueError("invalid_reviewed_source")
        values = (self.fields, self.field_order, self.note_ref, self.note_sha256, self.created_at)
        if self.status == "not_prepared":
            if any(value is not None for value in values):
                raise ValueError("inconsistent_draft")
        else:
            if any(value is None for value in values) or self.transcript_ref is None:
                raise ValueError("inconsistent_draft")
            assert self.fields is not None
            assert self.field_order is not None
            if len(set(self.field_order)) != len(self.field_order) or set(self.field_order) != set(self.fields):
                raise ValueError("invalid_field_order")
            if not 1 <= len(self.fields) <= 100 or any(not key or "\x00" in key or "\x00" in text for key, text in self.fields.items()):
                raise ValueError("invalid_note_fields")
            if note_content_hash(self.fields, self.field_order) != self.note_sha256:
                raise ValueError("note_content_changed")
        if len(self.model_dump_json().encode("utf-8")) > 1_048_576:
            raise ValueError("note_receipt_too_large")
        return self


class CoreDraftReference(NotebookBound):
    """Exact clinical/source version; never a bearer capability."""

    session_id: UUID
    scribe_source_id: UUID
    source_sha256: Digest
    schema_ref: SchemaRef
    transcript_ref: TranscriptRef
    note_ref: NoteRef
    note_sha256: Digest

    @model_validator(mode="after")
    def bound_reviewed_source(self):
        if self.reviewed_source is not None and self.reviewed_source.working_transcript_id != self.scribe_source_id:
            raise ValueError("invalid_reviewed_source")
        return self

    @classmethod
    def from_draft(cls, draft: CoreDraftReceipt):
        if draft.status != "draft":
            raise ValueError("core_draft_required")
        return cls.model_validate({key: getattr(draft, key) for key in cls.model_fields})
