"""Prescription sandbox stub. Synthetic success only; send always refused.

No prescribing vendor is selected. Hosted and production targets refuse.
"""

from __future__ import annotations

from cosmas_os.plugins.rx import RxConnector, RxSendRefused, build_default_registry
from cosmas_os.plugins.rx.manifest import ResourceType, TargetEnvironment
from cosmas_os.ports.rx import SyntheticRxStatus

_SYNTHETIC_LABELS = {
    "formulary_status": "Invented formulary status (sandbox)",
    "pharmacy_directory": "Invented pharmacy directory row (sandbox)",
    "draft_status": "Invented draft prescription status (sandbox)",
}


class RxSandboxAdapter:
    """Local fake adapter for the unspecified prescription scaffold."""

    def __init__(
        self,
        *,
        sandbox_enabled: bool = False,
        hosted: bool = False,
    ) -> None:
        if type(sandbox_enabled) is not bool or type(hosted) is not bool:
            raise ValueError("invalid_rx_sandbox_flags")
        self.sandbox_enabled = sandbox_enabled
        self.hosted = hosted
        self._connector: RxConnector = build_default_registry().require("unspecified")

    def observe(
        self,
        resource: ResourceType,
        *,
        target: TargetEnvironment = "sandbox",
    ) -> SyntheticRxStatus:
        self._connector.allow_read(
            resource,
            target=target,
            sandbox_enabled=self.sandbox_enabled,
            hosted=self.hosted,
        )
        return SyntheticRxStatus(
            resource=resource,
            label=_SYNTHETIC_LABELS[resource],
        )

    def send(self, action: str = "send") -> None:
        self._connector.refuse_send(action)
        raise RxSendRefused(action)  # pragma: no cover - refuse_send always raises
