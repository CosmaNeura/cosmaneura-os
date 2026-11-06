"""Capability manifest for the prescription sandbox scaffold.

No vendor is selected. The only declared connector id is ``unspecified``.
This manifest never grants authority to contact a prescribing network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# Closed placeholder only. Do not add Surescripts, DoseSpot, or other vendors here.
VendorId = Literal["unspecified"]
ResourceType = Literal["formulary_status", "pharmacy_directory", "draft_status"]
TargetEnvironment = Literal["sandbox", "production", "hosted"]

_VENDOR_IDS = frozenset({"unspecified"})
_RESOURCE_TYPES = frozenset({"formulary_status", "pharmacy_directory", "draft_status"})
_ACTION_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    """Closed description of the prescription sandbox scaffold.

    ``production_supported``, ``hosted_supported``, and ``sends_supported``
    default to False and cannot be flipped true on this contract.
    """

    vendor_id: VendorId
    display_name: str
    readable_resources: frozenset[ResourceType]
    unsupported_actions: frozenset[str]
    sandbox_supported: bool
    production_supported: bool = False
    hosted_supported: bool = False
    sends_supported: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if self.vendor_id not in _VENDOR_IDS:
            raise ValueError("unknown_vendor_id")
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
            raise ValueError("live_prescribing_not_part_of_this_contract")
        if type(self.notes) is not str or len(self.notes) > 500:
            raise ValueError("notes_too_long")
        if any(ord(c) < 32 and c not in "\n\t" for c in self.notes):
            raise ValueError("notes_control_chars")

    def supports_read(self, resource: ResourceType) -> bool:
        return resource in self.readable_resources

    def lists_unsupported(self, action: str) -> bool:
        return action in self.unsupported_actions
