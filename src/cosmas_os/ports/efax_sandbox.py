"""Closed fax sandbox scaffold port over existing provider ids.

Live fax send/inbound stay on the existing vendor_connectors and application
paths. This port only describes the fail-closed scaffold used for Track 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from cosmas_os.plugins.efax.manifest import ProviderId, ResourceType, TargetEnvironment


@dataclass(frozen=True, slots=True)
class SyntheticFaxStatus:
    """Invented sandbox receipt. Never a live fax or PHI."""

    provider_id: ProviderId
    resource: ResourceType
    label: str
    synthetic: Literal[True] = True


@runtime_checkable
class EFaxSandboxPort(Protocol):
    """Fail-closed fax scaffold surface used by adapters and tests."""

    def observe(
        self,
        provider_id: ProviderId,
        resource: ResourceType,
        *,
        target: TargetEnvironment = "sandbox",
    ) -> SyntheticFaxStatus: ...

    def send(self, action: str = "send") -> None: ...
