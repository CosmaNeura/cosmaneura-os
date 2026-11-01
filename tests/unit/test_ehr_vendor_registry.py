"""Vendor registry loads the four EHR plugin capability declarations."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from cosmas_os.plugins.ehr import (
    DeclaredEhrConnector,
    EhrCapabilityError,
    EhrTargetRefused,
    EhrWriteRefused,
    VendorRegistry,
    build_default_registry,
)
from cosmas_os.plugins.ehr.manifest import CapabilityManifest


def _manifest(vendor_id: str, display_name: str) -> CapabilityManifest:
    return CapabilityManifest(
        vendor_id=vendor_id,  # type: ignore[arg-type]
        display_name=display_name,
        auth_styles=frozenset({"cosmas_session"}),
        readable_resources=frozenset({"appointments"}),
        unsupported_actions=frozenset({"write_chart", "production_target"}),
        sandbox_supported=True,
    )


def test_registry_register_get_require_and_list():
    registry = VendorRegistry()
    first = DeclaredEhrConnector(_manifest("athena", "athenaOne"))
    second = DeclaredEhrConnector(
        CapabilityManifest(
            vendor_id="elation",
            display_name="Elation",
            auth_styles=frozenset({"oauth2_client_credentials"}),
            readable_resources=frozenset({"appointments"}),
            unsupported_actions=frozenset({"write_chart", "production_target"}),
            sandbox_supported=True,
        )
    )
    registry.register(first)
    registry.register(second)
    assert len(registry) == 2
    assert "athena" in registry
    assert registry.get("athena") is first
    assert registry.require("elation") is second
    assert registry.vendor_ids() == ("athena", "elation")
    assert [row.vendor_id for row in registry.list_manifests()] == ["athena", "elation"]


def test_registry_rejects_duplicate_and_missing():
    registry = VendorRegistry()
    registry.register(DeclaredEhrConnector(_manifest("tebra", "Tebra")))
    with pytest.raises(EhrCapabilityError, match="vendor_already_registered"):
        registry.register(DeclaredEhrConnector(_manifest("tebra", "Tebra")))
    with pytest.raises(EhrCapabilityError, match="vendor_not_registered"):
        registry.require("atlas_md")
    assert registry.get("atlas_md") is None


def test_default_registry_includes_all_four_vendors_fail_closed():
    registry = build_default_registry()
    assert registry.vendor_ids() == ("athena", "atlas_md", "elation", "tebra")
    for vendor_id in registry.vendor_ids():
        connector = registry.require(vendor_id)
        assert isinstance(connector, DeclaredEhrConnector)
        with pytest.raises(EhrWriteRefused):
            connector.refuse_write("prescribe")
        with pytest.raises(EhrTargetRefused):
            connector.allow_target("production")
        manifest = connector.capability_manifest()
        assert manifest.vendor_id == vendor_id
        assert manifest.writes_supported is False
        assert manifest.production_supported is False


def test_default_registry_sandbox_policy_matches_manifests():
    registry = build_default_registry()
    registry.require("athena").allow_target("sandbox")
    registry.require("elation").allow_target("sandbox")
    registry.require("tebra").allow_target("sandbox")
    with pytest.raises(EhrTargetRefused):
        registry.require("atlas_md").allow_target("sandbox")


def test_default_registry_makes_no_network_calls():
    def block_socket(*_args, **_kwargs):
        raise AssertionError("EHR registry must not open network sockets")

    with patch.object(socket.socket, "connect", block_socket):
        with patch("socket.create_connection", block_socket):
            registry = build_default_registry()
            assert len(registry) == 4
            registry.require("elation").allow_read("appointments", target="sandbox")
