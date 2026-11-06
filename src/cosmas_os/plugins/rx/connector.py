"""Shared ``RxConnector`` interface with fail-closed send and target gates.

This scaffold never opens a network connection and never selects a vendor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from cosmas_os.plugins.rx.manifest import (
    CapabilityManifest,
    ResourceType,
    TargetEnvironment,
    VendorId,
)
from cosmas_os.plugins.rx.refusals import (
    SANDBOX_FLAG_MESSAGE,
    RxReadRefused,
    RxSendRefused,
    RxTargetRefused,
)

READ_ACTIONS = frozenset({
    "status",
    "observe",
    "verify",
    "read",
    "formulary_status",
    "pharmacy_directory",
    "draft_status",
})

SEND_ACTIONS = frozenset({
    "send",
    "transmit",
    "prescribe",
    "refill",
    "renew",
    "cancel",
    "submit",
    "sign",
    "external_send",
})


def normalize_action_name(action: str) -> str:
    return action.strip().casefold()


@runtime_checkable
class RxConnector(Protocol):
    """Stable connector surface for prescription capability declaration and gates."""

    @property
    def vendor_id(self) -> VendorId: ...

    def capability_manifest(self) -> CapabilityManifest: ...

    def refuse_send(self, action: str = "send") -> None: ...

    def allow_target(
        self,
        target: TargetEnvironment,
        *,
        sandbox_enabled: bool = False,
        hosted: bool = False,
    ) -> None: ...

    def allow_read(
        self,
        resource: ResourceType,
        *,
        target: TargetEnvironment = "sandbox",
        sandbox_enabled: bool = False,
        hosted: bool = False,
    ) -> None: ...


@dataclass(slots=True)
class DeclaredRxConnector:
    """Default connector built from the prescription scaffold manifest."""

    manifest: CapabilityManifest
    _read_actions: frozenset[str] = field(default=READ_ACTIONS, repr=False)

    def __post_init__(self) -> None:
        if type(self.manifest) is not CapabilityManifest:
            raise ValueError("capability_manifest_required")

    @property
    def vendor_id(self) -> VendorId:
        return self.manifest.vendor_id

    def capability_manifest(self) -> CapabilityManifest:
        return self.manifest

    def refuse_send(self, action: str = "send") -> None:
        raise RxSendRefused(action)

    def allow_target(
        self,
        target: TargetEnvironment,
        *,
        sandbox_enabled: bool = False,
        hosted: bool = False,
    ) -> None:
        if type(sandbox_enabled) is not bool or type(hosted) is not bool:
            raise RxTargetRefused("invalid")
        if hosted or target == "hosted":
            raise RxTargetRefused("hosted")
        if target == "production":
            raise RxTargetRefused("production")
        if target != "sandbox":
            raise RxTargetRefused(str(target))
        if not self.manifest.sandbox_supported:
            raise RxTargetRefused("sandbox")
        if not sandbox_enabled:
            raise RxTargetRefused("sandbox", message=SANDBOX_FLAG_MESSAGE)

    def allow_read(
        self,
        resource: ResourceType,
        *,
        target: TargetEnvironment = "sandbox",
        sandbox_enabled: bool = False,
        hosted: bool = False,
    ) -> None:
        if type(resource) is not str:
            raise RxReadRefused("rx_resource_unsupported")
        self.allow_target(target, sandbox_enabled=sandbox_enabled, hosted=hosted)
        if not self.manifest.supports_read(resource):
            raise RxReadRefused("rx_resource_unsupported")

    def assert_not_send_action(self, action: str) -> None:
        """Refuse any action that is not an explicit allowlisted read name."""
        if type(action) is not str:
            raise RxSendRefused("send")
        normalized = normalize_action_name(action)
        if not normalized or normalized not in self._read_actions:
            self.refuse_send(action if action.strip() else "send")
