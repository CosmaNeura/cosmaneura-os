"""Registry for fax / eFax sandbox scaffolds over existing provider ids."""

from __future__ import annotations

from cosmas_os.plugins.efax.connector import DeclaredEFaxConnector, EFaxConnector
from cosmas_os.plugins.efax.manifest import CapabilityManifest, ProviderId
from cosmas_os.plugins.efax.refusals import EFaxCapabilityError

_UNSUPPORTED = frozenset({
    "send",
    "transmit",
    "submit",
    "external_send",
    "fax_send",
    "deliver",
    "production_target",
    "hosted_target",
})

_PROVIDER_DISPLAY = {
    "efax": "eFax Corporate (sandbox scaffold)",
    "srfax": "SRFax (sandbox scaffold)",
    "documo": "Documo (sandbox scaffold)",
    "spruce": "Spruce fax (sandbox scaffold)",
}


def _manifest(provider_id: ProviderId) -> CapabilityManifest:
    return CapabilityManifest(
        provider_id=provider_id,
        display_name=_PROVIDER_DISPLAY[provider_id],
        readable_resources=frozenset({
            "delivery_status",
            "inbound_metadata",
            "sandbox_receipt",
        }),
        unsupported_actions=_UNSUPPORTED,
        sandbox_supported=True,
        production_supported=False,
        hosted_supported=False,
        sends_supported=False,
        notes=(
            "Mock placeholder only. Reuses existing vendor_connectors ids. "
            "Does not activate live fax send or non-sandbox read."
        ),
    )


class ProviderRegistry:
    """In-process map of provider id → scaffold connector. No network."""

    def __init__(self) -> None:
        self._connectors: dict[ProviderId, EFaxConnector] = {}

    def register(self, connector: EFaxConnector) -> None:
        provider_id = connector.provider_id
        manifest = connector.capability_manifest()
        if manifest.provider_id != provider_id:
            raise EFaxCapabilityError("provider_id_mismatch")
        if provider_id in self._connectors:
            raise EFaxCapabilityError("provider_already_registered")
        self._connectors[provider_id] = connector

    def get(self, provider_id: ProviderId) -> EFaxConnector | None:
        return self._connectors.get(provider_id)

    def require(self, provider_id: ProviderId) -> EFaxConnector:
        connector = self.get(provider_id)
        if connector is None:
            raise EFaxCapabilityError("provider_not_registered")
        return connector

    def provider_ids(self) -> tuple[ProviderId, ...]:
        return tuple(sorted(self._connectors))

    def list_manifests(self) -> tuple[CapabilityManifest, ...]:
        return tuple(
            self._connectors[provider_id].capability_manifest()
            for provider_id in self.provider_ids()
        )

    def __contains__(self, provider_id: object) -> bool:
        return provider_id in self._connectors

    def __len__(self) -> int:
        return len(self._connectors)


def build_default_registry() -> ProviderRegistry:
    """Register scaffolds for the four existing fax provider ids."""
    registry = ProviderRegistry()
    for provider_id in ("documo", "efax", "spruce", "srfax"):
        registry.register(DeclaredEFaxConnector(_manifest(provider_id)))
    return registry
