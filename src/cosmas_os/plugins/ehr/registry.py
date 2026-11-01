"""Vendor registry for declared EHR connectors."""

from __future__ import annotations

from cosmas_os.plugins.ehr.connector import DeclaredEhrConnector, EhrConnector
from cosmas_os.plugins.ehr.manifest import CapabilityManifest, VendorId
from cosmas_os.plugins.ehr.refusals import EhrCapabilityError


class VendorRegistry:
    """In-process map of vendor id → connector. No network, no secrets."""

    def __init__(self) -> None:
        self._connectors: dict[VendorId, EhrConnector] = {}

    def register(self, connector: EhrConnector) -> None:
        vendor_id = connector.vendor_id
        manifest = connector.capability_manifest()
        if manifest.vendor_id != vendor_id:
            raise EhrCapabilityError("vendor_id_mismatch")
        if vendor_id in self._connectors:
            raise EhrCapabilityError("vendor_already_registered")
        self._connectors[vendor_id] = connector

    def get(self, vendor_id: VendorId) -> EhrConnector | None:
        return self._connectors.get(vendor_id)

    def require(self, vendor_id: VendorId) -> EhrConnector:
        connector = self.get(vendor_id)
        if connector is None:
            raise EhrCapabilityError("vendor_not_registered")
        return connector

    def vendor_ids(self) -> tuple[VendorId, ...]:
        return tuple(sorted(self._connectors))

    def list_manifests(self) -> tuple[CapabilityManifest, ...]:
        return tuple(
            self._connectors[vendor_id].capability_manifest()
            for vendor_id in self.vendor_ids()
        )

    def __contains__(self, vendor_id: object) -> bool:
        return vendor_id in self._connectors

    def __len__(self) -> int:
        return len(self._connectors)


def _manifest_from_plugin(module_name: str) -> CapabilityManifest:
    import importlib

    module = importlib.import_module(module_name)
    manifest = getattr(module, "EHR_CAPABILITY", None)
    if type(manifest) is not CapabilityManifest:
        raise EhrCapabilityError("plugin_capability_missing")
    return manifest


def build_default_registry() -> VendorRegistry:
    """Register athena, Elation, Tebra, and Atlas.md from their plugin modules."""
    registry = VendorRegistry()
    for module_name in (
        "cosmas_os.plugins.athena",
        "cosmas_os.plugins.elation",
        "cosmas_os.plugins.tebra",
        "cosmas_os.plugins.atlas_md",
    ):
        manifest = _manifest_from_plugin(module_name)
        registry.register(DeclaredEhrConnector(manifest))
    return registry
