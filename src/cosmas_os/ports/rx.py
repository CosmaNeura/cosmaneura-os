"""Closed prescription sandbox port. No vendor; send stays refused by default."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from cosmas_os.plugins.rx.manifest import ResourceType, TargetEnvironment

RxAction = Literal["read", "send"]


@dataclass(frozen=True, slots=True)
class SyntheticRxStatus:
    """Invented sandbox receipt. Never a live prescription or PHI."""

    resource: ResourceType
    label: str
    synthetic: Literal[True] = True
    vendor: Literal["unspecified"] = "unspecified"


@runtime_checkable
class RxSandboxPort(Protocol):
    """Fail-closed prescription surface used by adapters and tests."""

    def observe(
        self,
        resource: ResourceType,
        *,
        target: TargetEnvironment = "sandbox",
    ) -> SyntheticRxStatus: ...

    def send(self, action: str = "send") -> None: ...
