"""Shared ``EFaxConnector`` scaffold with fail-closed send and target gates.

Reuses provider ids already present in ``adapters.vendor_connectors``. This
class never opens a network connection and never flips live fax flags.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from cosmas_os.plugins.efax.manifest import (
    CapabilityManifest,
    ProviderId,
    ResourceType,
    TargetEnvironment,
)
from cosmas_os.plugins.efax.refusals import (
    SANDBOX_FLAG_MESSAGE,
    EFaxReadRefused,
    EFaxSendRefused,
    EFaxTargetRefused,
)

READ_ACTIONS = frozenset({
    "status",
    "observe",
    "verify",
    "read",
    "delivery_status",
    "inbound_metadata",
    "sandbox_receipt",
})

SEND_ACTIONS = frozenset({
    "send",
    "transmit",
    "submit",
    "external_send",
    "fax_send",
    "deliver",
})


def normalize_action_name(action: str) -> str:
    return action.strip().casefold()


@runtime_checkable
class EFaxConnector(Protocol):
    """Stable connector surface for fax scaffold declaration and gates."""

    @property
    def provider_id(self) -> ProviderId: ...

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
class DeclaredEFaxConnector:
    """Default connector built from a fax scaffold manifest."""

    manifest: CapabilityManifest
    _read_actions: frozenset[str] = field(default=READ_ACTIONS, repr=False)

    def __post_init__(self) -> None:
        if type(self.manifest) is not CapabilityManifest:
            raise ValueError("capability_manifest_required")

    @property
    def provider_id(self) -> ProviderId:
        return self.manifest.provider_id

    def capability_manifest(self) -> CapabilityManifest:
        return self.manifest

    def refuse_send(self, action: str = "send") -> None:
        raise EFaxSendRefused(action)

    def allow_target(
        self,
        target: TargetEnvironment,
        *,
        sandbox_enabled: bool = False,
        hosted: bool = False,
    ) -> None:
        if type(sandbox_enabled) is not bool or type(hosted) is not bool:
            raise EFaxTargetRefused("invalid")
        if hosted or target == "hosted":
            raise EFaxTargetRefused("hosted")
        if target == "production":
            raise EFaxTargetRefused("production")
        if target != "sandbox":
            raise EFaxTargetRefused(str(target))
        if not self.manifest.sandbox_supported:
            raise EFaxTargetRefused("sandbox")
        if not sandbox_enabled:
            raise EFaxTargetRefused("sandbox", message=SANDBOX_FLAG_MESSAGE)

    def allow_read(
        self,
        resource: ResourceType,
        *,
        target: TargetEnvironment = "sandbox",
        sandbox_enabled: bool = False,
        hosted: bool = False,
    ) -> None:
        if type(resource) is not str:
            raise EFaxReadRefused("efax_resource_unsupported")
        self.allow_target(target, sandbox_enabled=sandbox_enabled, hosted=hosted)
        if not self.manifest.supports_read(resource):
            raise EFaxReadRefused("efax_resource_unsupported")

    def assert_not_send_action(self, action: str) -> None:
        if type(action) is not str:
            raise EFaxSendRefused("send")
        normalized = normalize_action_name(action)
        if not normalized or normalized not in self._read_actions:
            self.refuse_send(action if action.strip() else "send")
