"""Copy-to-EHR mapping: both profiles, hash, expiry, extras, audit scrub."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from cosmas_os.application.ehr_export import (
    ABSOLUTE_EXPIRY_SECONDS,
    AUDIT_EVENTS,
    IDLE_EXPIRY_SECONDS,
    audit_contains_note_text,
    build_audit_event,
    build_export_package,
    compute_expires_at,
    payload_hash_for,
    refresh_package_activity,
    render_full_note,
    render_section,
)
from cosmas_os.application.ehr_export.types import ExportDraft


def _draft() -> ExportDraft:
    return ExportDraft(
        draft_id="visit_note_01hgeneric0123456789abcdef",
        draft_revision="a" * 64,
        field_order=("subjective", "assessment", "patient_instructions", "orders"),
        fields={
            "subjective": "# Opening line\n* drink fluids\n1. rest tonight",
            "assessment": "Viral pharyngitis (invented Taylor Morgan visit).",
            "patient_instructions": "Call if worse.",
            "orders": "No labs today.",
        },
        review_state="reviewed",
        visit_copy_to_ehr_status="not_sent_copy_instead",
    )


@pytest.mark.parametrize("profile_id", ["generic", "atlas_md"])
def test_both_profiles_map_the_same_field_order(profile_id: str):
    pkg = build_export_package(_draft(), profile_id)
    assert pkg.profile_id == profile_id
    assert [section.key for section in pkg.sections] == ["subjective", "assessment"]
    assert [section.key for section in pkg.extras] == ["patient_instructions", "orders"]
    full = render_full_note(pkg)
    assert "Call if worse" not in full
    assert "No labs today" not in full
    assert not full.lstrip().startswith("#")
    assert "Opening line" in full
    assert "drink fluids" in full
    assert "* drink" not in full
    assert "1. rest" not in full
    assert "rest tonight" in full
    subjective = render_section(pkg, "subjective")
    assert subjective.startswith("Subjective\n")
    assert not subjective.split("\n", 1)[1].lstrip().startswith("#")


def test_payload_hash_is_sha256_of_ordered_key_text():
    draft = _draft()
    expected = hashlib.sha256(
        json.dumps(
            [[key, draft.fields[key]] for key in draft.field_order],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert payload_hash_for(draft.field_order, draft.fields) == expected
    assert build_export_package(draft, "generic").payload_hash == expected


def test_expiry_idle_fifteen_absolute_sixty():
    created = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    assert compute_expires_at(created) == created + timedelta(seconds=IDLE_EXPIRY_SECONDS)
    later = created + timedelta(minutes=50)
    # Idle from activity would be +15, but absolute caps at created+60.
    assert compute_expires_at(created, last_activity_at=later) == created + timedelta(
        seconds=ABSOLUTE_EXPIRY_SECONDS
    )
    pkg = build_export_package(_draft(), "atlas_md")
    refreshed = refresh_package_activity(pkg, at=pkg.created_at + timedelta(minutes=10))
    assert refreshed.expires_at == pkg.created_at + timedelta(minutes=25)
    capped = refresh_package_activity(pkg, at=pkg.created_at + timedelta(minutes=55))
    assert capped.expires_at == pkg.created_at + timedelta(seconds=ABSOLUTE_EXPIRY_SECONDS)


@pytest.mark.parametrize("event", sorted(AUDIT_EVENTS))
def test_every_audit_event_name_is_metadata_only(event: str):
    note = "Viral pharyngitis (invented Taylor Morgan visit)."
    built = build_audit_event(
        event,
        profile_id="atlas_md",
        outcome="ok",
        duration_ms=3,
        detail={"draft_id": "visit_note_01hgeneric0123456789abcdef"},
    )
    assert built.event == event
    assert built.correlation_id
    assert not audit_contains_note_text(
        {"event": built.event, "detail": built.detail, "outcome": built.outcome},
        [note, "Taylor Morgan", "pharyngitis", "Call if worse"],
    )


def test_audit_rejects_clipboard_and_section_text_keys():
    with pytest.raises(ValueError, match="note_text_forbidden_in_audit"):
        build_audit_event("copy_to_ehr.done", detail={"clipboard": "secret note"})
    with pytest.raises(ValueError, match="note_text_forbidden_in_audit"):
        build_audit_event("copy_to_ehr.copied", detail={"section_text": "Assessment body"})
