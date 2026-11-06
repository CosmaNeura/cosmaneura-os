"""Fax / eFax sandbox stub over existing provider ids.

Reuses spruce/srfax/documo/efax identifiers already present in
``adapters.vendor_connectors``. Does not call those connectors, invent a new
fax stack, or flip live inbound/outbound flags. Synthetic success only when
the sandbox scaffold flag is on and the target is sandbox.
"""

from __future__ import annotations

from cosmas_os.plugins.efax import (
    EFaxConnector,
    EFaxSendRefused,
    build_default_registry,
)
from cosmas_os.plugins.efax.manifest import ProviderId, ResourceType, TargetEnvironment
from cosmas_os.ports.efax_sandbox import SyntheticFaxStatus

_SYNTHETIC_LABELS = {
    "delivery_status": "Invented fax delivery status (sandbox)",
    "inbound_metadata": "Invented inbound fax metadata (sandbox)",
    "sandbox_receipt": "Invented fax sandbox receipt",
}


class EFaxSandboxAdapter:
    """Local fake adapter for fax scaffold observe/send gates."""

    def __init__(
        self,
        *,
        sandbox_enabled: bool = False,
        hosted: bool = False,
    ) -> None:
        if type(sandbox_enabled) is not bool or type(hosted) is not bool:
            raise ValueError("invalid_efax_sandbox_flags")
        self.sandbox_enabled = sandbox_enabled
        self.hosted = hosted
        self._registry = build_default_registry()

    def _connector(self, provider_id: ProviderId) -> EFaxConnector:
        return self._registry.require(provider_id)

    def observe(
        self,
        provider_id: ProviderId,
        resource: ResourceType,
        *,
        target: TargetEnvironment = "sandbox",
    ) -> SyntheticFaxStatus:
        connector = self._connector(provider_id)
        connector.allow_read(
            resource,
            target=target,
            sandbox_enabled=self.sandbox_enabled,
            hosted=self.hosted,
        )
        return SyntheticFaxStatus(
            provider_id=provider_id,
            resource=resource,
            label=_SYNTHETIC_LABELS[resource],
        )

    def send(self, action: str = "send") -> None:
        # Any registered provider refuses send the same way.
        self._connector("efax").refuse_send(action)
        raise EFaxSendRefused(action)  # pragma: no cover - refuse_send always raises
