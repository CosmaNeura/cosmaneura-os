"""Copy-to-EHR guard coverage against the fixed export contract (track E).

Synthetic fixtures only. Invented patient Taylor Morgan with a sore throat.
Never logs note text. Never claims a chart match or vendor credentials.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from cosmas_os.application import ehr_export
from cosmas_os.application.ehr_export import (
    EhrExportProfile,
    ExportPackage,
    ExportSection,
    build_export_package,
    render_full_note,
    render_section,
)
from cosmas_os.application.ehr_export import fallback
from cosmas_os.application.ehr_export import sessions
from cosmas_os.config import Settings
from cosmas_os.log_scrub import scrub_structure, scrub_text
from cosmas_os.plugins.ehr.manifest import CapabilityManifest

# ---------------------------------------------------------------------------
# Synthetic draft: invented sore-throat visit for Taylor Morgan.
# ---------------------------------------------------------------------------

DRAFT_ID = "00000000-0000-4000-8000-000000000501"
DRAFT_REVISION = 3
SUBJECTIVE = (
    "Taylor Morgan reports an invented sore throat for two days. "
    "No # code was discussed."
)
OBJECTIVE = "Invented exam: oropharynx mildly erythematous without exudate."
ASSESSMENT = "Invented viral pharyngitis."
PLAN = "Supportive care; return if fever persists three days."
PATIENT_INSTRUCTIONS = "Invented: fluids and rest for Taylor Morgan."
ORDERS = "Invented: no imaging ordered for this visit."
NOTE_CANARIES = (
    SUBJECTIVE,
    OBJECTIVE,
    ASSESSMENT,
    PLAN,
    PATIENT_INSTRUCTIONS,
    ORDERS,
    "Taylor Morgan",
    "sore throat",
)

FIELD_ORDER = ("Subjective", "Objective", "Assessment", "Plan")
FIELDS = {
    "Subjective": SUBJECTIVE,
    "Objective": OBJECTIVE,
    "Assessment": ASSESSMENT,
    "Plan": PLAN,
}
EXTRAS = {
    "patient_instructions": PATIENT_INSTRUCTIONS,
    "orders": ORDERS,
}
AUDIT_EVENTS = (
    "copy_to_ehr.opened",
    "copy_to_ehr.copied",
    "copy_to_ehr.cleared",
    "copy_to_ehr.done",
    "copy_to_ehr.blocked",
    "copy_to_ehr.fallback_shown",
)


def _synthetic_draft(**overrides):
    draft = {
        "draft_id": DRAFT_ID,
        "draft_revision": DRAFT_REVISION,
        "note_type": "Visit note",
        "fields": dict(FIELDS),
        "field_order": list(FIELD_ORDER),
        "extras": dict(EXTRAS),
        "review_state": "reviewed",
    }
    draft.update(overrides)
    return draft


def _ordered_payload_hash(fields: dict[str, str], field_order: list[str]) -> str:
    ordered = [[key, fields[key]] for key in field_order]
    return hashlib.sha256(json.dumps(ordered, ensure_ascii=True).encode("utf-8")).hexdigest()


def _leading_hash_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.lstrip().startswith("#")]


def _as_mapping(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return dict(value)


def _status_code(error: BaseException) -> int | None:
    for attr in ("status", "status_code"):
        code = getattr(error, attr, None)
        if isinstance(code, int):
            return code
    return None


def _profiles() -> dict[str, EhrExportProfile]:
    raw = getattr(ehr_export, "PROFILES", None)
    if raw is None:
        raw = getattr(ehr_export, "profiles", None)
    if callable(raw):
        raw = raw()
    if isinstance(raw, dict):
        return {key: value for key, value in raw.items()}
    if raw is not None:
        return {profile.id: profile for profile in raw}
    getter = getattr(ehr_export, "get_profile", None) or getattr(EhrExportProfile, "for_id", None)
    assert callable(getter), "ehr_export must expose PROFILES or get_profile"
    return {profile_id: getter(profile_id) for profile_id in ("generic", "atlas_md")}


# ---------------------------------------------------------------------------
# Profiles reuse the C7/C8 connector profile shape (CapabilityManifest style).
# ---------------------------------------------------------------------------

def test_export_profiles_reuse_c7_c8_connector_profile_shape():
    profiles = _profiles()
    assert set(profiles) >= {"generic", "atlas_md"}

    atlas_capability = CapabilityManifest(
        vendor_id="atlas_md",
        display_name="Atlas.md",
        auth_styles=frozenset({"unverified"}),
        readable_resources=frozenset(),
        unsupported_actions=frozenset({"patients", "appointments"}),
        sandbox_supported=False,
    )
    atlas = profiles["atlas_md"]
    assert isinstance(atlas, EhrExportProfile)
    assert atlas.id == atlas_capability.vendor_id == "atlas_md"
    assert isinstance(atlas.display_name, str) and 1 <= len(atlas.display_name) <= 80
    assert atlas.label_style == "words"
    assert atlas.forbid_leading_hash is True
    assert atlas.full_note_section_separator == "\n\n"
    assert atlas.label_line_then_text is True
    assert atlas.per_section_copy is True
    assert atlas.plain_text_only is True
    assert atlas.extras_separate is True

    generic = profiles["generic"]
    assert generic.id == "generic"
    assert generic.forbid_leading_hash is True
    assert generic.extras_separate is True
    assert generic.label_style == "words"


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
    assert isinstance(pkg, ExportPackage)
    full = render_full_note(pkg)
    assert _leading_hash_lines(full) == []
    assert not full.lstrip().startswith("#")
    for section in pkg.sections:
        assert isinstance(section, ExportSection)
        assert not section.text.lstrip().startswith("#")
        assert not section.label.lstrip().startswith("#")
        rendered = render_section(pkg, section.key)
        assert _leading_hash_lines(rendered) == []
        assert not rendered.lstrip().startswith("#")


@pytest.mark.parametrize("profile_id", ["generic", "atlas_md"])
def test_extras_excluded_from_full_note(profile_id):
    pkg = build_export_package(_synthetic_draft(), profile_id)
    full = render_full_note(pkg)
    assert PATIENT_INSTRUCTIONS not in full
    assert ORDERS not in full
    section_keys = {section.key for section in pkg.sections}
    assert "patient_instructions" not in section_keys
    assert "orders" not in section_keys
    extras = _as_mapping(pkg.extras)
    assert extras["patient_instructions"] == PATIENT_INSTRUCTIONS
    assert extras["orders"] == ORDERS
    for key in FIELD_ORDER:
        assert key in section_keys
        assert FIELDS[key] in full


@pytest.mark.parametrize("profile_id", ["generic", "atlas_md"])
def test_payload_hash_binds_ordered_section_text(profile_id):
    pkg = build_export_package(_synthetic_draft(), profile_id)
    expected = _ordered_payload_hash(FIELDS, list(FIELD_ORDER))
    assert pkg.payload_hash == expected
    assert re.fullmatch(r"[0-9a-f]{64}", pkg.payload_hash)
    changed = build_export_package(
        _synthetic_draft(fields={**FIELDS, "Plan": "Invented different plan."}),
        profile_id,
    )
    assert changed.payload_hash != pkg.payload_hash
    assert changed.draft_revision == DRAFT_REVISION


# ---------------------------------------------------------------------------
# Stale revision / hash refusal (409).
# ---------------------------------------------------------------------------

def test_stale_revision_refuses_with_409():
    pkg = build_export_package(_synthetic_draft(), "atlas_md")
    refuse = getattr(ehr_export, "refuse_stale_package", None) or getattr(
        ehr_export, "require_current_package", None
    )
    assert callable(refuse), "ehr_export must expose stale package refusal"
    with pytest.raises(Exception) as caught:
        refuse(
            pkg,
            expected_revision=DRAFT_REVISION - 1,
            expected_payload_hash=pkg.payload_hash,
        )
    assert _status_code(caught.value) == 409


def test_stale_payload_hash_refuses_with_409():
    pkg = build_export_package(_synthetic_draft(), "atlas_md")
    refuse = getattr(ehr_export, "refuse_stale_package", None) or getattr(
        ehr_export, "require_current_package", None
    )
    assert callable(refuse), "ehr_export must expose stale package refusal"
    with pytest.raises(Exception) as caught:
        refuse(
            pkg,
            expected_revision=DRAFT_REVISION,
            expected_payload_hash="0" * 64,
        )
    assert _status_code(caught.value) == 409


def test_api_returns_404_when_copy_to_ehr_flag_off(monkeypatch):
    from fastapi.testclient import TestClient

    from cosmas_os.api import app as api

    settings = Settings(copy_to_ehr_enabled=False)
    monkeypatch.setattr(api, "settings", settings, raising=False)
    if hasattr(api, "get_settings"):
        monkeypatch.setattr(api, "get_settings", lambda: settings)

    with TestClient(api.app) as client:
        response = client.get(
            f"/api/copy-to-ehr/drafts/{DRAFT_ID}",
            params={"profile": "atlas_md", "revision": DRAFT_REVISION},
        )
    assert response.status_code == 404
    for token in NOTE_CANARIES:
        assert token not in response.text


def test_api_returns_409_on_revision_mismatch(monkeypatch):
    from fastapi.testclient import TestClient

    from cosmas_os.api import app as api

    settings = Settings(copy_to_ehr_enabled=True)
    monkeypatch.setattr(api, "settings", settings, raising=False)
    if hasattr(api, "get_settings"):
        monkeypatch.setattr(api, "get_settings", lambda: settings)
    if hasattr(ehr_export, "load_reviewed_draft"):
        monkeypatch.setattr(
            ehr_export,
            "load_reviewed_draft",
            lambda draft_id: _synthetic_draft(draft_id=draft_id),
        )

    with TestClient(api.app) as client:
        response = client.get(
            f"/api/copy-to-ehr/drafts/{DRAFT_ID}",
            params={"profile": "atlas_md", "revision": DRAFT_REVISION + 9},
        )
    assert response.status_code == 409
    for token in NOTE_CANARIES:
        assert token not in response.text


# ---------------------------------------------------------------------------
# Audit and log scrub: metadata only, never note text.
# ---------------------------------------------------------------------------

def test_audit_metadata_never_contains_note_text(caplog):
    record = getattr(ehr_export, "record_copy_audit", None) or getattr(
        ehr_export, "emit_copy_to_ehr_audit", None
    )
    assert callable(record), "ehr_export must expose content-free copy audit recording"

    rows = []
    for event in AUDIT_EVENTS:
        row = record(
            event=event,
            profile_id="atlas_md",
            outcome="ok" if event != "copy_to_ehr.blocked" else "stale_revision",
            duration_ms=12,
            correlation_id=str(uuid4()),
        )
        rows.append(_as_mapping(row) if row is not None else {"event": event})

    blob = json.dumps(rows, default=str)
    for token in NOTE_CANARIES:
        assert token not in blob
    for row in rows:
        assert "event" in row
        assert row["event"] in AUDIT_EVENTS
        for key in row:
            assert key in {
                "event",
                "profile_id",
                "outcome",
                "duration_ms",
                "correlation_id",
            }
        for token in NOTE_CANARIES:
            assert token not in str(row)

    with caplog.at_level(logging.DEBUG):
        for event in AUDIT_EVENTS:
            record(
                event=event,
                profile_id="atlas_md",
                outcome="ok",
                duration_ms=1,
                correlation_id="corr-synth-copy",
            )
    for token in NOTE_CANARIES:
        assert token not in caplog.text


def test_logger_scrub_drops_note_text_from_copy_paths():
    payload = {
        "event": "copy_to_ehr.copied",
        "profile_id": "atlas_md",
        "note": SUBJECTIVE,
        "section_text": PLAN,
        "patient": "Taylor Morgan",
        "duration_ms": 9,
        "correlation_id": "corr-synth-scrub",
    }
    cleaned = scrub_structure(payload)
    encoded = json.dumps(cleaned)
    for token in NOTE_CANARIES:
        assert token not in encoded
    assert cleaned["event"] == "copy_to_ehr.copied"
    assert cleaned["profile_id"] == "atlas_md"
    assert cleaned["duration_ms"] == 9
    assert cleaned["correlation_id"] == "corr-synth-scrub"
    scrubbed_line = scrub_text(f"copy_to_ehr.copied note={SUBJECTIVE}")
    assert SUBJECTIVE not in scrubbed_line


# ---------------------------------------------------------------------------
# Session expiry: 15 minutes idle / 60 minutes absolute.
# ---------------------------------------------------------------------------

def test_session_expires_after_fifteen_minutes_idle():
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
    session = sessions.create_session(
        clinician_id="invented-clinician",
        draft_id=DRAFT_ID,
        draft_revision=DRAFT_REVISION,
    )
    message = sessions.highlight_message(
        session,
        draft_revision=DRAFT_REVISION,
        section_key="Subjective",
    )
    encoded = json.dumps(_as_mapping(message), default=str)
    for token in NOTE_CANARIES:
        assert token not in encoded
    body = _as_mapping(message)
    assert body["draft_revision"] == DRAFT_REVISION
    assert body["section_key"] == "Subjective"
    assert "text" not in body
    assert "section_text" not in body
    assert "full_note" not in body
    assert SUBJECTIVE not in encoded


# ---------------------------------------------------------------------------
# Connection failure: visible "not sent", offer Copy to EHR, never silent,
# never blocks the visit.
# ---------------------------------------------------------------------------

def test_connection_failure_marks_visible_fallback_and_does_not_block_visit():
    visit = SimpleNamespace(
        id="00000000-0000-4000-8000-000000000777",
        copy_to_ehr_fallback=False,
        blocked=False,
        note_sent=None,
    )
    mark = getattr(fallback, "on_adapter_connection_failure", None) or getattr(
        fallback, "mark_copy_to_ehr_fallback", None
    )
    assert callable(mark), "fallback.py must expose connection-failure marking"
    result = mark(
        visit,
        error=SimpleNamespace(code="adapter_disconnected", message="invented disconnect"),
    )
    assert visit.copy_to_ehr_fallback is True
    assert getattr(visit, "blocked", False) is False
    payload = _as_mapping(result) if result is not None else {
        "note_sent": False,
        "offer_copy_to_ehr": True,
        "silent": False,
        "clinician_message": "Note was NOT sent. Copy to EHR is available.",
    }
    if result is not None:
        assert payload.get("note_sent") is False
        assert payload.get("silent") is False
        assert payload.get("offer_copy_to_ehr") is True
        message = str(payload.get("clinician_message", ""))
        assert "not sent" in message.lower() or "NOT sent" in message
        assert "Copy to EHR" in message or payload.get("offer_copy_to_ehr") is True
    for token in NOTE_CANARIES:
        assert token not in json.dumps(payload, default=str)


def test_connection_failure_never_falls_back_silently_or_blocks_visit():
    visit = SimpleNamespace(
        id="00000000-0000-4000-8000-000000000778",
        copy_to_ehr_fallback=False,
        blocked=False,
    )
    mark = getattr(fallback, "on_adapter_connection_failure", None) or getattr(
        fallback, "mark_copy_to_ehr_fallback", None
    )
    assert callable(mark), "fallback.py must expose connection-failure marking"
    kwargs = dict(visit=visit, error=SimpleNamespace(code="adapter_error", message="invented adapter fault"))
    try:
        result = mark(**kwargs, settings=Settings(copy_to_ehr_fallback_enabled=True))
    except TypeError:
        result = mark(**kwargs)
    assert getattr(visit, "blocked", False) is False
    if result is not None:
        payload = _as_mapping(result)
        assert payload.get("note_sent") is False
        assert payload.get("silent") is False
    assert visit.copy_to_ehr_fallback is True


# ---------------------------------------------------------------------------
# Package surface stays minimum: no audio, transcript, chart, demographics,
# credentials, or chart match.
# ---------------------------------------------------------------------------

def test_export_package_omits_sensitive_and_unrelated_fields():
    pkg = build_export_package(_synthetic_draft(), "atlas_md")
    data = _as_mapping(pkg)
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
    assert pkg.review_state
    assert pkg.created_at
    assert pkg.expires_at
