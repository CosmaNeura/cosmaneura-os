"""Copy-to-EHR contract: profiles, flags, route skeleton, audit metadata."""

from __future__ import annotations

from types import SimpleNamespace
from typing import get_args

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosmas_os.api import copy_to_ehr_routes
from cosmas_os.application.ehr_export import (
    EXTRA_KEYS,
    PROFILES,
    VisitCopyToEhrStatus,
    audit_contains_note_text,
    build_audit_event,
    build_export_package,
    copy_profile_for_vendor,
    get_profile,
    known_vendor_profile_ids,
    manifest_vendor_ids,
    render_full_note,
    render_section,
)
from cosmas_os.application.ehr_export.types import ExportDraft
from cosmas_os.config import Settings


def _sore_throat_draft(**overrides) -> ExportDraft:
    values = dict(
        draft_id="visit_note_01habcdef0123456789abcde",
        draft_revision="rev-taylor-sore-throat-1",
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
            "chief_complaint": "Sore throat for two days",
            "subjective": (
                "Taylor Morgan reports a sore throat for two days.\n"
                "- No fever\n"
                "# prior note fragment"
            ),
            "objective": "Oropharynx mildly erythematous. No exudate.",
            "assessment": "Likely viral pharyngitis.",
            "plan": "Fluids, rest, follow-up if swallowing worsens.",
            "patient_instructions": "Warm fluids. Return if worse.",
            "orders": "None today.",
        },
        review_state="reviewed",
        visit_copy_to_ehr_status="unset",
    )
    values.update(overrides)
    return ExportDraft(**values)


def test_flags_default_false():
    settings = Settings()
    assert settings.copy_to_ehr_enabled is False
    assert settings.copy_to_ehr_remote_enabled is False
    assert settings.copy_to_ehr_fallback_enabled is False


def test_profiles_generic_and_atlas_md():
    assert set(PROFILES) == {"generic", "atlas_md"}
    generic = get_profile("generic")
    atlas = get_profile("atlas_md")
    assert generic.id == "generic"
    assert atlas.id == "atlas_md"
    assert atlas.forbid_leading_hash is True
    assert atlas.label_style == "words"
    assert atlas.plain_text_only is True
    assert atlas.extras_separate is True


def test_non_generic_profile_ids_are_manifest_vendor_ids():
    vendors = manifest_vendor_ids()
    for profile_id in known_vendor_profile_ids():
        assert profile_id in vendors


def test_copy_profile_for_vendor_falls_back_to_generic():
    assert copy_profile_for_vendor("atlas_md").id == "atlas_md"
    assert copy_profile_for_vendor("athena").id == "generic"
    assert copy_profile_for_vendor(None).id == "generic"


def test_visit_copy_to_ehr_status_includes_not_sent_copy_instead():
    assert "not_sent_copy_instead" in get_args(VisitCopyToEhrStatus)
    draft = _sore_throat_draft(visit_copy_to_ehr_status="not_sent_copy_instead")
    pkg = build_export_package(draft, "atlas_md")
    assert pkg.visit_copy_to_ehr_status == "not_sent_copy_instead"


def test_build_and_render_excludes_extras_and_leading_hash():
    pkg = build_export_package(_sore_throat_draft(), "atlas_md")
    assert {section.key for section in pkg.sections} == {
        "chief_complaint", "subjective", "objective", "assessment", "plan",
    }
    assert {section.key for section in pkg.extras} == EXTRA_KEYS
    full = render_full_note(pkg)
    assert "Warm fluids" not in full
    assert "None today" not in full
    assert not full.lstrip().startswith("#")
    for section in pkg.sections:
        assert not section.text.lstrip().startswith("#")
        assert not render_section(pkg, section.key).lstrip().startswith("#")
    assert "prior note fragment" in pkg.sections[1].text
    assert "- No fever" not in pkg.sections[1].text
    assert "No fever" in pkg.sections[1].text


def test_audit_metadata_only_refuses_note_text_keys():
    note = "Taylor Morgan reports a sore throat for two days."
    event = build_audit_event(
        "copy_to_ehr.copied",
        profile_id="atlas_md",
        outcome="ok",
        duration_ms=12,
        detail={"section_key": "subjective"},
    )
    assert event.event == "copy_to_ehr.copied"
    assert not audit_contains_note_text(event.detail, [note, "sore throat"])
    with pytest.raises(ValueError, match="note_text_forbidden_in_audit"):
        build_audit_event(
            "copy_to_ehr.copied",
            profile_id="atlas_md",
            outcome="ok",
            detail={"note_text": note},
        )


def _route_client(enabled: bool, draft: ExportDraft | None = None) -> TestClient:
    def load(draft_id: str) -> ExportDraft | None:
        if draft is not None and draft.draft_id == draft_id:
            return draft
        return None

    copy_to_ehr_routes.configure_draft_loader(load)
    app = FastAPI()
    app.include_router(
        copy_to_ehr_routes.router(configuration=lambda: SimpleNamespace(copy_to_ehr_enabled=enabled))
    )
    return TestClient(app)


def test_route_flag_off_returns_404():
    draft = _sore_throat_draft()
    client = _route_client(False, draft)
    response = client.get(f"/api/copy-to-ehr/drafts/{draft.draft_id}?profile=atlas_md")
    assert response.status_code == 404


def test_route_revision_mismatch_returns_409():
    draft = _sore_throat_draft()
    client = _route_client(True, draft)
    response = client.get(
        f"/api/copy-to-ehr/drafts/{draft.draft_id}",
        params={"profile": "atlas_md", "revision": "stale-revision"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "revision_mismatch"


def test_route_returns_package_when_enabled():
    draft = _sore_throat_draft()
    client = _route_client(True, draft)
    response = client.get(
        f"/api/copy-to-ehr/drafts/{draft.draft_id}",
        params={"profile": "atlas_md", "revision": draft.draft_revision},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["profile_id"] == "atlas_md"
    assert body["draft_revision"] == draft.draft_revision
    assert "full_note" in body
    assert "Warm fluids" not in body["full_note"]
    assert body["visit_copy_to_ehr_status"] == "unset"
