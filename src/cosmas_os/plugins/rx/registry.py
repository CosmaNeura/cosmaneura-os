"""Registry for the prescription sandbox scaffold (no vendor pick)."""

from __future__ import annotations

from cosmas_os.plugins.rx.connector import DeclaredRxConnector, RxConnector
from cosmas_os.plugins.rx.manifest import CapabilityManifest, VendorId
from cosmas_os.plugins.rx.refusals import RxCapabilityError

DEFAULT_MANIFEST = CapabilityManifest(
    vendor_id="unspecified",
    display_name="Prescription sandbox (no vendor)",
    readable_resources=frozenset({"formulary_status", "pharmacy_directory", "draft_status"}),
    unsupported_actions=frozenset({
        "send",
        "transmit",
        "prescribe",
        "refill",
        "renew",
        "cancel",
        "submit",
        "sign",
        "production_target",
        "hosted_target",
    }),
    sandbox_supported=True,
    production_supported=False,
    hosted_supported=False,
    sends_supported=False,
    notes=(
        "Mock placeholder only. No prescribing vendor is selected. "
        "Send and non-sandbox reads stay refused."
    ),
)


class VendorRegistry:
    """In-process map of connector id → connector. No network, no secrets."""

    def __init__(self) -> None:
        self._connectors: dict[VendorId, RxConnector] = {}

    def register(self, connector: RxConnector) -> None:
        vendor_id = connector.vendor_id
        manifest = connector.capability_manifest()
        if manifest.vendor_id != vendor_id:
            raise RxCapabilityError("vendor_id_mismatch")
        if vendor_id in self._connectors:
            raise RxCapabilityError("vendor_already_registered")
        self._connectors[vendor_id] = connector

    def get(self, vendor_id: VendorId) -> RxConnector | None:
        return self._connectors.get(vendor_id)

    def require(self, vendor_id: VendorId) -> RxConnector:
        connector = self.get(vendor_id)
        if connector is None:
            raise RxCapabilityError("vendor_not_registered")
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


def build_default_registry() -> VendorRegistry:
    """Register the single unspecified prescription sandbox connector."""
    registry = VendorRegistry()
    registry.register(DeclaredRxConnector(DEFAULT_MANIFEST))
    return registry
