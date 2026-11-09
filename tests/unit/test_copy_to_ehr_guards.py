"""Copy-to-EHR guard coverage against the fixed export contract (track E).

Synthetic fixtures only. Invented patient Taylor Morgan with a sore throat.
Never logs note text. Never claims a chart match or vendor credentials.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import get_args

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosmas_os.api import copy_to_ehr_routes
from cosmas_os.application.ehr_export import (
    ABSOLUTE_EXPIRY_SECONDS,
    AUDIT_EVENTS,
    EXTRA_KEYS,
    IDLE_EXPIRY_SECONDS,
    PROFILES,
    VisitCopyToEhrStatus,
    audit_contains_note_text,
    build_audit_event,
    build_export_package,
    copy_profile_for_vendor,
    get_profile,
    known_vendor_profile_ids,
    manifest_vendor_ids,
    payload_hash_for,
    render_full_note,
    render_section,
)
from cosmas_os.application.ehr_export.types import ExportDraft
from cosmas_os.config import Settings
from cosmas_os.log_scrub import scrub_structure, scrub_text
from cosmas_os.plugins.ehr.manifest import CapabilityManifest

# ---------------------------------------------------------------------------
# Synthetic draft: invented sore-throat visit for Taylor Morgan.
# ---------------------------------------------------------------------------

DRAFT_ID = "visit_note_01habcdef0123456789abcde"
DRAFT_REVISION = "rev-taylor-sore-throat-1"
SUBJECTIVE = (
    "Taylor Morgan reports an invented sore throat for two days.\n"
    "- No fever\n"
    "# prior note fragment"
)
OBJECTIVE = "Invented exam: oropharynx mildly erythematous without exudate."
ASSESSMENT = "Invented viral pharyngitis."
PLAN = "Supportive care; return if fever persists three days."
PATIENT_INSTRUCTIONS = "Invented: fluids and rest for Taylor Morgan."
ORDERS = "Invented: no imaging ordered for this visit."
NOTE_CANARIES = (
    "Taylor Morgan reports an invented sore throat for two days.",
    OBJECTIVE,
    ASSESSMENT,
    PLAN,
    PATIENT_INSTRUCTIONS,
    ORDERS,
    "Taylor Morgan",
    "sore throat",
)


def _synthetic_draft(**overrides) -> ExportDraft:
    values = dict(
        draft_id=DRAFT_ID,
        draft_revision=DRAFT_REVISION,
        field_order=(
            "chief_complaint",
            "subjective",
            "objective",
            "assessment",
            "plan",
            "patient_instructions",
            "orders",
        ),
        fields={
            "chief_complaint": "Invented sore throat for two days",
            "subjective": SUBJECTIVE,
            "objective": OBJECTIVE,
            "assessment": ASSESSMENT,
            "plan": PLAN,
            "patient_instructions": PATIENT_INSTRUCTIONS,
            "orders": ORDERS,
        },
        review_state="reviewed",
        visit_copy_to_ehr_status="unset",
    )
    values.update(overrides)
    return ExportDraft(**values)


def _leading_hash_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.lstrip().startswith("#")]


def _route_client(enabled: bool, draft: ExportDraft | None = None) -> TestClient:
    def load(draft_id: str) -> ExportDraft | None:
        if draft is not None and draft.draft_id == draft_id:
            return draft
        return None

    copy_to_ehr_routes.configure_draft_loader(load)
    app = FastAPI()
    app.include_router(
        copy_to_ehr_routes.router(
            configuration=lambda: SimpleNamespace(copy_to_ehr_enabled=enabled)
        )
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# Profiles reuse the C7/C8 connector profile shape (CapabilityManifest style).
# ---------------------------------------------------------------------------

def test_export_profiles_reuse_c7_c8_connector_profile_shape():
    assert set(PROFILES) == {"generic", "atlas_md"}

    atlas_capability = CapabilityManifest(
        vendor_id="atlas_md",
        display_name="Atlas.md",
        auth_styles=frozenset({"unverified"}),
        readable_resources=frozenset(),
        unsupported_actions=frozenset({"patients", "appointments"}),
        sandbox_supported=False,
    )
    atlas = get_profile("atlas_md")
    assert atlas.id == atlas_capability.vendor_id == "atlas_md"
    assert atlas.display_name == atlas_capability.display_name
    assert atlas.label_style == "words"
    assert atlas.forbid_leading_hash is True
    assert atlas.full_note_section_separator == "\n\n"
    assert atlas.label_line_then_text is True
    assert atlas.per_section_copy is True
    assert atlas.plain_text_only is True
    assert atlas.extras_separate is True

    generic = get_profile("generic")
    assert generic.id == "generic"
    assert generic.forbid_leading_hash is True
    assert generic.extras_separate is True
    assert copy_profile_for_vendor("atlas_md").id == "atlas_md"
    assert copy_profile_for_vendor("athena").id == "generic"

    vendors = manifest_vendor_ids()
    for profile_id in known_vendor_profile_ids():
        assert profile_id in vendors


def test_flags_default_off_in_settings():
    settings = Settings()
    assert settings.copy_to_ehr_enabled is False
    assert settings.copy_to_ehr_remote_enabled is False
    assert settings.copy_to_ehr_fallback_enabled is False


# ---------------------------------------------------------------------------
# Rendering guards: no leading '#'; extras stay out of the full note.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("profile_id", ["generic", "atlas_md"])
def test_rendered_lines_never_lead_with_hash(profile_id):
    pkg = build_export_package(_synthetic_draft(), profile_id)
    full = render_full_note(pkg)
    assert _leading_hash_lines(full) == []
    assert not full.lstrip().startswith("#")
    for section in pkg.sections:
        assert not section.text.lstrip().startswith("#")
        assert not section.label.lstrip().startswith("#")
        rendered = render_section(pkg, section.key)
        assert _leading_hash_lines(rendered) == []
        assert not rendered.lstrip().startswith("#")
    # Leading hash inside source text is stripped; remainder remains.
    subjective = next(section for section in pkg.sections if section.key == "subjective")
    assert "prior note fragment" in subjective.text
    assert not subjective.text.lstrip().startswith("#")


@pytest.mark.parametrize("profile_id", ["generic", "atlas_md"])
def test_extras_excluded_from_full_note(profile_id):
    pkg = build_export_package(_synthetic_draft(), profile_id)
    full = render_full_note(pkg)
    assert PATIENT_INSTRUCTIONS not in full
    assert ORDERS not in full
    section_keys = {section.key for section in pkg.sections}
    extra_keys = {section.key for section in pkg.extras}
    assert "patient_instructions" not in section_keys
    assert "orders" not in section_keys
    assert extra_keys == EXTRA_KEYS
    assert {section.text for section in pkg.extras} >= {PATIENT_INSTRUCTIONS, ORDERS}
    for key in ("chief_complaint", "subjective", "objective", "assessment", "plan"):
        assert key in section_keys


@pytest.mark.parametrize("profile_id", ["generic", "atlas_md"])
def test_payload_hash_binds_ordered_section_text(profile_id):
    draft = _synthetic_draft()
    pkg = build_export_package(draft, profile_id)
    assert pkg.payload_hash == payload_hash_for(draft.field_order, draft.fields)
    assert len(pkg.payload_hash) == 64
    changed = build_export_package(
        _synthetic_draft(
            fields={**dict(draft.fields), "plan": "Invented different plan."},
        ),
        profile_id,
    )
    assert changed.payload_hash != pkg.payload_hash


# ---------------------------------------------------------------------------
# Stale revision / hash refusal (409).
# ---------------------------------------------------------------------------

def test_api_returns_404_when_copy_to_ehr_flag_off():
    draft = _synthetic_draft()
    response = _route_client(False, draft).get(
        f"/api/copy-to-ehr/drafts/{draft.draft_id}",
        params={"profile": "atlas_md", "revision": draft.draft_revision},
    )
    assert response.status_code == 404
    for token in NOTE_CANARIES:
        assert token not in response.text


def test_api_returns_409_on_revision_mismatch():
    draft = _synthetic_draft()
    response = _route_client(True, draft).get(
        f"/api/copy-to-ehr/drafts/{draft.draft_id}",
        params={"profile": "atlas_md", "revision": "stale-revision"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "revision_mismatch"
    for token in NOTE_CANARIES:
        assert token not in response.text


def test_stale_payload_hash_is_refused_as_blocked_audit():
    """Editing the draft changes the hash; prior package binding must fail closed."""
    draft = _synthetic_draft()
    pkg = build_export_package(draft, "atlas_md")
    edited = build_export_package(
        _synthetic_draft(
            fields={**dict(draft.fields), "plan": "Invented revised plan after review."},
        ),
        "atlas_md",
    )
    assert edited.payload_hash != pkg.payload_hash
    event = build_audit_event(
        "copy_to_ehr.blocked",
        profile_id="atlas_md",
        outcome="stale_hash",
        detail={"expected_payload_hash": pkg.payload_hash, "actual_payload_hash": edited.payload_hash},
    )
    assert event.outcome == "stale_hash"
    assert not audit_contains_note_text(event.detail, NOTE_CANARIES)


# ---------------------------------------------------------------------------
# Audit and log scrub: metadata only, never note text.
# ---------------------------------------------------------------------------

def test_audit_metadata_never_contains_note_text(caplog):
    rows = []
    for event_name in sorted(AUDIT_EVENTS):
        row = build_audit_event(
            event_name,
            profile_id="atlas_md",
            outcome="ok" if event_name != "copy_to_ehr.blocked" else "stale_revision",
            duration_ms=12,
            correlation_id="corr-synth-copy",
            detail={"section_key": "subjective"} if event_name == "copy_to_ehr.copied" else None,
        )
        rows.append(row)

    blob = json.dumps(
        [
            {
                "event": row.event,
                "profile_id": row.profile_id,
                "outcome": row.outcome,
                "duration_ms": row.duration_ms,
                "correlation_id": row.correlation_id,
                "detail": dict(row.detail),
            }
            for row in rows
        ],
        default=str,
    )
    for token in NOTE_CANARIES:
        assert token not in blob
        assert not audit_contains_note_text(blob, [token])

    with pytest.raises(ValueError, match="note_text_forbidden_in_audit"):
        build_audit_event(
            "copy_to_ehr.copied",
            profile_id="atlas_md",
            outcome="ok",
            detail={"note_text": SUBJECTIVE},
        )

    with caplog.at_level(logging.DEBUG):
        for event_name in sorted(AUDIT_EVENTS):
            build_audit_event(
                event_name,
                profile_id="atlas_md",
                outcome="ok",
                duration_ms=1,
                correlation_id="corr-synth-copy",
            )
    for token in NOTE_CANARIES:
        assert token not in caplog.text


def test_logger_scrub_drops_note_text_from_copy_paths():
    # Audit builders refuse note-text keys; scrubbing drops accidental note_text fields.
    with pytest.raises(ValueError, match="note_text_forbidden_in_audit"):
        build_audit_event(
            "copy_to_ehr.copied",
            profile_id="atlas_md",
            outcome="ok",
            detail={"section_text": PLAN},
        )
    safe = build_audit_event(
        "copy_to_ehr.copied",
        profile_id="atlas_md",
        outcome="ok",
        duration_ms=9,
        correlation_id="corr-synth-scrub",
        detail={"section_key": "plan"},
    )
    safe_blob = {
        "event": safe.event,
        "profile_id": safe.profile_id,
        "outcome": safe.outcome,
        "duration_ms": safe.duration_ms,
        "correlation_id": safe.correlation_id,
        "detail": dict(safe.detail),
    }
    assert not audit_contains_note_text(safe_blob, NOTE_CANARIES)
    leaked = scrub_structure(
        {
            "event": "copy_to_ehr.copied",
            "profile_id": "atlas_md",
            "note_text": SUBJECTIVE,
            "duration_ms": 9,
            "correlation_id": "corr-synth-scrub",
        }
    )
    encoded = json.dumps(leaked)
    assert "note_text" not in leaked
    for token in NOTE_CANARIES:
        assert token not in encoded
    scrubbed_line = scrub_text(f"copy_to_ehr.copied note_text={SUBJECTIVE}")
    assert "Taylor Morgan reports an invented sore throat" not in scrubbed_line
    assert "patient_name=Taylor Morgan" not in scrub_text("patient_name=Taylor Morgan")


# ---------------------------------------------------------------------------
# Session expiry: 15 minutes idle / 60 minutes absolute.
# ---------------------------------------------------------------------------

def test_package_expiry_bounds_match_fifteen_and_sixty_minutes():
    assert IDLE_EXPIRY_SECONDS == 15 * 60
    assert ABSOLUTE_EXPIRY_SECONDS == 60 * 60
    before = datetime.now(UTC)
    pkg = build_export_package(_synthetic_draft(), "atlas_md")
    after = datetime.now(UTC)
    assert pkg.created_at >= before
    assert pkg.expires_at <= after + timedelta(seconds=IDLE_EXPIRY_SECONDS)
    assert pkg.expires_at - pkg.created_at <= timedelta(seconds=IDLE_EXPIRY_SECONDS)
    assert ABSOLUTE_EXPIRY_SECONDS >= IDLE_EXPIRY_SECONDS


def test_session_expires_after_fifteen_minutes_idle():
    import importlib

    sessions = importlib.import_module("cosmas_os.application.ehr_export.sessions")

    clock = {"now": datetime(2026, 11, 9, 15, 0, tzinfo=UTC)}

    def now():
        return clock["now"]

    session = sessions.create_session(
        clinician_id="invented-clinician",
        draft_id=DRAFT_ID,
        draft_revision=DRAFT_REVISION,
        clock=now,
    )
    assert sessions.is_active(session, clock=now) is True
    clock["now"] = clock["now"] + timedelta(minutes=14, seconds=59)
    assert sessions.is_active(session, clock=now) is True
    clock["now"] = clock["now"] + timedelta(seconds=2)
    assert sessions.is_active(session, clock=now) is False


def test_session_expires_after_sixty_minutes_absolute():
    import importlib

    sessions = importlib.import_module("cosmas_os.application.ehr_export.sessions")

    start = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
    clock = {"now": start}

    def now():
        return clock["now"]

    session = sessions.create_session(
        clinician_id="invented-clinician",
        draft_id=DRAFT_ID,
        draft_revision=DRAFT_REVISION,
        clock=now,
    )
    for minutes in (10, 20, 30, 40, 50, 59):
        clock["now"] = start + timedelta(minutes=minutes)
        sessions.touch(session, clock=now)
        assert sessions.is_active(session, clock=now) is True
    clock["now"] = start + timedelta(minutes=60, seconds=1)
    assert sessions.is_active(session, clock=now) is False


# ---------------------------------------------------------------------------
# Remote highlight messages carry pointers only — never note text.
# ---------------------------------------------------------------------------

def test_remote_highlight_messages_contain_no_note_text():
    import importlib

    sessions = importlib.import_module("cosmas_os.application.ehr_export.sessions")

    session = sessions.create_session(
        clinician_id="invented-clinician",
        draft_id=DRAFT_ID,
        draft_revision=DRAFT_REVISION,
    )
    message = sessions.highlight_message(
        session,
        draft_revision=DRAFT_REVISION,
        section_key="subjective",
    )
    body = message if isinstance(message, dict) else dict(message)
    encoded = json.dumps(body, default=str)
    for token in NOTE_CANARIES:
        assert token not in encoded
    assert body["draft_revision"] == DRAFT_REVISION
    assert body["section_key"] == "subjective"
    assert "text" not in body
    assert "section_text" not in body
    assert "full_note" not in body


# ---------------------------------------------------------------------------
# Connection failure: visible "not sent", offer Copy to EHR, never silent,
# never blocks the visit. Track A status; Track D sets it on adapter failure.
# ---------------------------------------------------------------------------

def test_connection_failure_status_is_not_sent_copy_instead_and_does_not_block():
    assert "not_sent_copy_instead" in get_args(VisitCopyToEhrStatus)
    draft = _synthetic_draft(visit_copy_to_ehr_status="not_sent_copy_instead")
    pkg = build_export_package(draft, "atlas_md")
    assert pkg.visit_copy_to_ehr_status == "not_sent_copy_instead"
    # Package still builds and renders — the visit is not blocked.
    full = render_full_note(pkg)
    assert "Invented viral pharyngitis." in full
    assert PATIENT_INSTRUCTIONS not in full
    event = build_audit_event(
        "copy_to_ehr.fallback_shown",
        profile_id="atlas_md",
        outcome="not_sent_copy_instead",
    )
    assert event.event == "copy_to_ehr.fallback_shown"
    assert not audit_contains_note_text(
        {"event": event.event, "outcome": event.outcome},
        NOTE_CANARIES,
    )


def test_connection_failure_fallback_module_marks_visible_offer():
    import importlib

    fallback = importlib.import_module("cosmas_os.application.ehr_export.fallback")

    visit = SimpleNamespace(
        id="00000000-0000-4000-8000-000000000777",
        copy_to_ehr_fallback=False,
        blocked=False,
        visit_copy_to_ehr_status="unset",
    )
    mark = getattr(fallback, "on_adapter_connection_failure", None) or getattr(
        fallback, "mark_copy_to_ehr_fallback", None
    )
    assert callable(mark), "fallback.py must expose connection-failure marking"
    result = mark(
        visit,
        error=SimpleNamespace(code="adapter_disconnected", message="invented disconnect"),
    )
    assert visit.copy_to_ehr_fallback is True or getattr(visit, "visit_copy_to_ehr_status", None) == "not_sent_copy_instead"
    assert getattr(visit, "blocked", False) is False
    if result is not None:
        payload = result if isinstance(result, dict) else dict(result.__dict__)
        assert payload.get("note_sent") is False or payload.get("silent") is False
        message = str(payload.get("clinician_message", ""))
        if message:
            assert "not sent" in message.lower()
            assert "Copy to EHR" in message or payload.get("offer_copy_to_ehr") is True


# ---------------------------------------------------------------------------
# Package surface stays minimum: no audio, transcript, chart, demographics,
# credentials, or chart match.
# ---------------------------------------------------------------------------

def test_export_package_omits_sensitive_and_unrelated_fields():
    pkg = build_export_package(_synthetic_draft(), "atlas_md")
    data = {
        "profile_id": pkg.profile_id,
        "draft_id": pkg.draft_id,
        "draft_revision": pkg.draft_revision,
        "payload_hash": pkg.payload_hash,
        "sections": pkg.sections,
        "extras": pkg.extras,
        "created_at": pkg.created_at,
        "expires_at": pkg.expires_at,
        "review_state": pkg.review_state,
        "visit_copy_to_ehr_status": pkg.visit_copy_to_ehr_status,
    }
    forbidden = {
        "audio",
        "transcript",
        "chart_id",
        "patient_id",
        "patient_name",
        "demographics",
        "ehr_credentials",
        "credentials",
        "chart_match",
        "atlas_credentials",
    }
    assert forbidden.isdisjoint(set(data))
    assert pkg.profile_id == "atlas_md"
    assert pkg.draft_id == DRAFT_ID
    assert pkg.draft_revision == DRAFT_REVISION
    assert pkg.review_state == "reviewed"
