"""Copy-to-EHR export types. Clipboard paste only; no vendor credentials."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from cosmas_os.plugins.ehr.manifest import VendorId

# Profile id: existing EHR VendorId, or the extra literal "generic".
EhrExportProfileId = VendorId | Literal["generic"]

# Visit-level status Track D sets when a note was not sent and the clinician
# should copy instead. Visible to the clinician; never silent; never blocks a visit.
VisitCopyToEhrStatus = Literal[
    "unset",
    "not_sent_copy_instead",
]

EXTRA_KEYS = frozenset({"patient_instructions", "orders"})

AUDIT_EVENTS = frozenset({
    "copy_to_ehr.opened",
    "copy_to_ehr.copied",
    "copy_to_ehr.cleared",
    "copy_to_ehr.done",
    "copy_to_ehr.blocked",
    "copy_to_ehr.fallback_shown",
})

IDLE_EXPIRY_SECONDS = 15 * 60
ABSOLUTE_EXPIRY_SECONDS = 60 * 60


@dataclass(frozen=True, slots=True)
class EhrExportProfile:
    """Paste formatting for one copy destination.

    ``id`` is the profile id (contract field name). Typed as an existing
    ``VendorId`` or the single extra literal ``generic``. Copy profiles are
    not registered in ``VendorRegistry``.
    """

    id: EhrExportProfileId
    display_name: str
    label_style: Literal["words"] = "words"
    forbid_leading_hash: bool = True
    full_note_section_separator: str = "\n\n"
    label_line_then_text: bool = True
    per_section_copy: bool = True
    plain_text_only: bool = True
    extras_separate: bool = True


@dataclass(frozen=True, slots=True)
class ExportSection:
    key: str
    label: str
    text: str  # plain text, no leading '#', bullets normalised to plain lines


@dataclass(frozen=True, slots=True)
class ExportPackage:
    profile_id: EhrExportProfileId
    draft_id: str
    draft_revision: str
    payload_hash: str  # sha256 of ordered key+text
    sections: tuple[ExportSection, ...]  # draft field_order, extras excluded
    extras: tuple[ExportSection, ...]  # patient_instructions, orders; never in full note
    created_at: datetime
    expires_at: datetime  # 15 min idle / 60 min absolute
    review_state: str
    # Visit-level hint for Track D fallback UI. Default unset; never blocks.
    visit_copy_to_ehr_status: VisitCopyToEhrStatus = "unset"


@dataclass(frozen=True, slots=True)
class ExportDraft:
    """Minimal draft shape for ``build_export_package`` (field_order/fields contract)."""

    draft_id: str
    draft_revision: str
    field_order: Sequence[str]
    fields: Mapping[str, str]
    review_state: str = "reviewed"
    visit_copy_to_ehr_status: VisitCopyToEhrStatus = "unset"


@dataclass(frozen=True, slots=True)
class CopyToEhrAuditEvent:
    """Metadata-only audit row. Never carries note text or clinic-supplied labels."""

    event: str
    profile_id: EhrExportProfileId | None
    outcome: str
    duration_ms: int | None = None
    correlation_id: str = ""
    detail: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.event not in AUDIT_EVENTS:
            raise ValueError("unknown_copy_to_ehr_audit_event")
        # Refuse accidental note-text keys in metadata.
        forbidden = {
            "text", "note", "note_text", "full_note", "section_text", "label",
            "body", "content", "fields", "sections", "extras",
        }
        if any(key in forbidden for key in self.detail):
            raise ValueError("note_text_forbidden_in_audit")
