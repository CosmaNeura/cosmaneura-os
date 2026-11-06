"""Capability manifest for the eFax / fax sandbox scaffold.

Existing vendor_connectors (efax, srfax, documo, spruce) remain the real
adapters. This scaffold only declares fail-closed gates and does not activate
outbound send or non-sandbox read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# Existing fax providers already in this repository. Declared for labels only.
ProviderId = Literal["efax", "srfax", "documo", "spruce"]
ResourceType = Literal["delivery_status", "inbound_metadata", "sandbox_receipt"]
TargetEnvironment = Literal["sandbox", "production", "hosted"]

_PROVIDER_IDS = frozenset({"efax", "srfax", "documo", "spruce"})
_RESOURCE_TYPES = frozenset({"delivery_status", "inbound_metadata", "sandbox_receipt"})
_ACTION_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    """Closed description of one declared fax provider scaffold."""

    provider_id: ProviderId
    display_name: str
    readable_resources: frozenset[ResourceType]
    unsupported_actions: frozenset[str]
    sandbox_supported: bool
    production_supported: bool = False
    hosted_supported: bool = False
    sends_supported: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if self.provider_id not in _PROVIDER_IDS:
            raise ValueError("unknown_provider_id")
        if not isinstance(self.display_name, str) or not (1 <= len(self.display_name) <= 80):
            raise ValueError("display_name_required")
        if any(ord(c) < 32 or ord(c) == 127 for c in self.display_name):
            raise ValueError("display_name_required")
        if type(self.readable_resources) is not frozenset:
            raise ValueError("readable_resources_required")
        if not self.readable_resources <= _RESOURCE_TYPES:
            raise ValueError("unknown_resource_type")
        if type(self.unsupported_actions) is not frozenset or not self.unsupported_actions:
            raise ValueError("unsupported_actions_required")
        if any(
            type(action) is not str or _ACTION_NAME.fullmatch(action) is None
            for action in self.unsupported_actions
        ):
            raise ValueError("unsupported_action_name_invalid")
        if type(self.sandbox_supported) is not bool:
            raise ValueError("sandbox_supported_required")
        if type(self.production_supported) is not bool:
            raise ValueError("production_supported_required")
        if type(self.hosted_supported) is not bool:
            raise ValueError("hosted_supported_required")
        if type(self.sends_supported) is not bool:
            raise ValueError("sends_supported_required")
        if self.production_supported or self.hosted_supported or self.sends_supported:
            raise ValueError("live_fax_not_part_of_this_scaffold")
        if type(self.notes) is not str or len(self.notes) > 500:
            raise ValueError("notes_too_long")
        if any(ord(c) < 32 and c not in "\n\t" for c in self.notes):
            raise ValueError("notes_control_chars")

    def supports_read(self, resource: ResourceType) -> bool:
        return resource in self.readable_resources

    def lists_unsupported(self, action: str) -> bool:
        return action in self.unsupported_actions
