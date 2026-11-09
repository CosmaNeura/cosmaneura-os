"""Capability manifest schema validation for EHR connectors."""

from __future__ import annotations

import pytest

from cosmas_os.plugins.athena import EHR_CAPABILITY as ATHENA
from cosmas_os.plugins.atlas_md import EHR_CAPABILITY as ATLAS
from cosmas_os.plugins.ehr import CapabilityManifest
from cosmas_os.plugins.elation import EHR_CAPABILITY as ELATION
from cosmas_os.plugins.tebra import EHR_CAPABILITY as TEBRA


def _base(**overrides) -> dict:
    values = dict(
        vendor_id="athena",
        display_name="athenaOne",
        auth_styles=frozenset({"cosmas_session"}),
        readable_resources=frozenset({"appointments"}),
        unsupported_actions=frozenset({"write_chart", "production_target"}),
        sandbox_supported=True,
    )
    values.update(overrides)
    return values


def test_manifest_is_frozen_and_supports_read_helpers():
    manifest = CapabilityManifest(**_base())
    assert manifest.supports_read("appointments")
    assert not manifest.supports_read("labs")
    assert manifest.lists_unsupported("write_chart")
    assert manifest.production_supported is False
    assert manifest.writes_supported is False
    with pytest.raises(AttributeError):
        manifest.display_name = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"vendor_id": "epic"}, "unknown_vendor_id"),
        ({"display_name": ""}, "display_name_required"),
        ({"auth_styles": frozenset()}, "auth_styles_required"),
        ({"auth_styles": frozenset({"mystery"})}, "unknown_auth_style"),
        ({"readable_resources": frozenset({"notes"})}, "unknown_resource_type"),
        ({"unsupported_actions": frozenset()}, "unsupported_actions_required"),
        ({"unsupported_actions": frozenset({"Bad-Action"})}, "unsupported_action_name_invalid"),
        ({"writes_supported": True}, "writes_not_part_of_this_contract"),
        ({"notes": "x" * 501}, "notes_too_long"),
    ],
)
def test_manifest_rejects_invalid_fields(overrides, match):
    with pytest.raises(ValueError, match=match):
        CapabilityManifest(**_base(**overrides))


def test_plugin_manifests_match_expected_vendors():
    by_id = {
        ATHENA.vendor_id: ATHENA,
        ELATION.vendor_id: ELATION,
        TEBRA.vendor_id: TEBRA,
        ATLAS.vendor_id: ATLAS,
    }
    assert set(by_id) == {"athena", "elation", "tebra", "atlas_md"}
    for manifest in by_id.values():
        assert manifest.writes_supported is False
        assert manifest.production_supported is False
        assert "write_chart" in manifest.unsupported_actions
        assert "production_target" in manifest.unsupported_actions


def test_athena_elation_tebra_declare_sandbox_reads():
    assert ATHENA.sandbox_supported is True
    assert ATHENA.readable_resources == frozenset({
        "appointments", "medications", "allergies", "visit_link_status",
    })
    assert "athena_platform_bearer" in ATHENA.auth_styles
    assert ELATION.sandbox_supported is True
    assert ELATION.readable_resources == frozenset({
        "appointments", "patients", "problems", "medications", "allergies", "labs", "visit",
    })
    assert "oauth2_client_credentials" in ELATION.auth_styles
    assert "read_allergies" not in ELATION.unsupported_actions
    assert TEBRA.sandbox_supported is True
    assert TEBRA.readable_resources == frozenset({
        "appointments", "visit", "patients", "medications",
    })
    assert "tebra_fhir_bearer" in TEBRA.auth_styles
    assert "patient_search_without_appointment" in TEBRA.unsupported_actions


def test_atlas_md_declares_no_reads_and_no_sandbox():
    assert ATLAS.sandbox_supported is False
    assert ATLAS.readable_resources == frozenset()
    assert ATLAS.auth_styles == frozenset({"unverified"})
    assert "read_appointments" in ATLAS.unsupported_actions
    assert "sandbox_target" in ATLAS.unsupported_actions
