"""Build and render copy-to-EHR export packages from a reviewed draft."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from cosmas_os.application.ehr_export.profiles import get_profile
from cosmas_os.application.ehr_export.text import normalise_section_text, words_label
from cosmas_os.application.ehr_export.types import (
    ABSOLUTE_EXPIRY_SECONDS,
    EXTRA_KEYS,
    IDLE_EXPIRY_SECONDS,
    EhrExportProfileId,
    ExportDraft,
    ExportPackage,
    ExportSection,
)


def _ordered_pairs(field_order: Sequence[str], fields: Mapping[str, str]) -> list[list[str]]:
    if not field_order:
        raise ValueError("empty_field_order")
    if len(set(field_order)) != len(field_order):
        raise ValueError("duplicate_field_order")
    if set(field_order) != set(fields):
        raise ValueError("field_order_mismatch")
    return [[key, fields[key]] for key in field_order]


def payload_hash_for(field_order: Sequence[str], fields: Mapping[str, str]) -> str:
    """sha256 of ordered key+text (same ordering contract as capture field_order/fields)."""
    ordered = _ordered_pairs(field_order, fields)
    canonical = json.dumps(ordered, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _section(key: str, text: str, *, forbid_leading_hash: bool) -> ExportSection:
    return ExportSection(
        key=key,
        label=words_label(key),
        text=normalise_section_text(text, forbid_leading_hash=forbid_leading_hash),
    )


def build_export_package(draft: ExportDraft, profile_id: EhrExportProfileId | str) -> ExportPackage:
    """Map a reviewed draft into an ``ExportPackage`` for the given profile."""
    profile = get_profile(profile_id)
    field_order = list(draft.field_order)
    fields = dict(draft.fields)
    _ordered_pairs(field_order, fields)

    sections: list[ExportSection] = []
    extras: list[ExportSection] = []
    for key in field_order:
        section = _section(key, fields[key], forbid_leading_hash=profile.forbid_leading_hash)
        if profile.extras_separate and key in EXTRA_KEYS:
            extras.append(section)
        else:
            sections.append(section)

    now = datetime.now(UTC)
    idle = now + timedelta(seconds=IDLE_EXPIRY_SECONDS)
    absolute = now + timedelta(seconds=ABSOLUTE_EXPIRY_SECONDS)
    expires_at = idle if idle <= absolute else absolute

    return ExportPackage(
        profile_id=profile.id,
        draft_id=draft.draft_id,
        draft_revision=draft.draft_revision,
        payload_hash=payload_hash_for(field_order, fields),
        sections=tuple(sections),
        extras=tuple(extras),
        created_at=now,
        expires_at=expires_at,
        review_state=draft.review_state,
        visit_copy_to_ehr_status=draft.visit_copy_to_ehr_status,
    )


def render_section(pkg: ExportPackage, key: str) -> str:
    """Render one section (or extra) as plain text for clipboard paste."""
    profile = get_profile(pkg.profile_id)
    for section in (*pkg.sections, *pkg.extras):
        if section.key != key:
            continue
        if profile.label_line_then_text:
            body = f"{section.label}\n{section.text}".rstrip()
        else:
            body = section.text
        if profile.forbid_leading_hash and body.lstrip().startswith("#"):
            body = body.lstrip()[1:].lstrip()
        return body
    raise KeyError("unknown_export_section")


def render_full_note(pkg: ExportPackage) -> str:
    """Render the full note. Extras are never included."""
    profile = get_profile(pkg.profile_id)
    parts: list[str] = []
    for section in pkg.sections:
        parts.append(render_section(pkg, section.key))
    text = profile.full_note_section_separator.join(parts).strip()
    if profile.forbid_leading_hash and text.lstrip().startswith("#"):
        text = text.lstrip()[1:].lstrip()
    return text
