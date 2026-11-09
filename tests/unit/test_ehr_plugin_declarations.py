"""Existing EHR plugins declare capabilities without changing tool behavior."""

from __future__ import annotations

from cosmas_os.plugins import athena, atlas_md, elation, tebra
from cosmas_os.plugins.ehr import build_default_registry


def test_plugin_capability_constants_match_registry():
    registry = build_default_registry()
    assert registry.require("athena").capability_manifest() is athena.EHR_CAPABILITY
    assert registry.require("elation").capability_manifest() is elation.EHR_CAPABILITY
    assert registry.require("tebra").capability_manifest() is tebra.EHR_CAPABILITY
    assert registry.require("atlas_md").capability_manifest() is atlas_md.EHR_CAPABILITY


def test_plugin_tool_surfaces_unchanged_by_capability_declaration():
    assert athena.NAMES == (
        "athena_read_appointments",
        "athena_read_medications",
        "athena_read_allergies",
        "athena_read_authorized_patients",
        "athena_read_fhir_medications",
        "athena_read_visit_link_status",
    )
    assert elation.NAMES == (
        "elation_read_appointments",
        "elation_read_problems",
        "elation_read_medications",
        "elation_read_labs",
    )
    assert tebra.NAMES == (
        "tebra_read_appointments",
        "tebra_read_visit",
        "tebra_read_authorized_patients",
        "tebra_read_medications",
    )
    assert atlas_md.NAMES == (
        "atlas_md_read_appointments",
        "atlas_md_read_patients",
    )
    for module in (athena, elation, tebra, atlas_md):
        tools = module.tool_definitions()
        assert len(tools) == len(module.NAMES)
        for tool in tools:
            assert tool["annotations"]["readOnlyHint"] is True
            assert tool["annotations"]["destructiveHint"] is False
            assert tool["_meta"]["ai.cosmas/operation"]["read_only"] is True
            assert tool["_meta"]["ai.cosmas/operation"]["external_send"] is False
