"""Capability manifest schema for EHR connectors.

A manifest is declarative only: it names what a vendor connector may read,
how it authenticates, whether sandbox or production is claimed, and which
actions stay explicitly unsupported. It does not grant authority to call a
vendor or to leave the sandbox.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

VendorId = Literal["athena", "elation", "tebra", "atlas_md"]

ResourceType = Literal[
    "appointments",
    "patients",
    "medications",
    "allergies",
    "problems",
    "labs",
    "visit",
    "visit_link_status",
]

AuthStyle = Literal[
    "cosmas_session",
    "oauth2_client_credentials",
    "athena_platform_bearer",
    "tebra_soap_customer_key",
    "tebra_fhir_bearer",
    "unverified",
    "smart_backend_services",
]

TargetEnvironment = Literal["sandbox", "production"]

_VENDOR_IDS = frozenset({"athena", "elation", "tebra", "atlas_md"})
_RESOURCE_TYPES = frozenset({
    "appointments",
    "patients",
    "medications",
    "allergies",
    "problems",
    "labs",
    "visit",
    "visit_link_status",
})
_AUTH_STYLES = frozenset({
    "cosmas_session",
    "oauth2_client_credentials",
    "athena_platform_bearer",
    "tebra_soap_customer_key",
    "tebra_fhir_bearer",
    "unverified",
    "smart_backend_services",
})
_ACTION_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    """Closed description of one vendor connector's declared capabilities.

    ``production_supported`` and ``writes_supported`` default to False. The
    shared connector contract still refuses production and writes unless a
    later gate (C14) and a separate write contract say otherwise.
    """

    vendor_id: VendorId
    display_name: str
    auth_styles: frozenset[AuthStyle]
    readable_resources: frozenset[ResourceType]
    unsupported_actions: frozenset[str]
    sandbox_supported: bool
    production_supported: bool = False
    writes_supported: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if self.vendor_id not in _VENDOR_IDS:
            raise ValueError("unknown_vendor_id")
        if not isinstance(self.display_name, str) or not (1 <= len(self.display_name) <= 80):
            raise ValueError("display_name_required")
        if any(ord(c) < 32 or ord(c) == 127 for c in self.display_name):
            raise ValueError("display_name_required")
        if type(self.auth_styles) is not frozenset or not self.auth_styles:
            raise ValueError("auth_styles_required")
        if not self.auth_styles <= _AUTH_STYLES:
            raise ValueError("unknown_auth_style")
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
        if type(self.writes_supported) is not bool:
            raise ValueError("writes_supported_required")
        if self.writes_supported:
            raise ValueError("writes_not_part_of_this_contract")
        if type(self.notes) is not str or len(self.notes) > 500:
            raise ValueError("notes_too_long")
        if any(ord(c) < 32 and c not in "\n\t" for c in self.notes):
            raise ValueError("notes_control_chars")

    def supports_read(self, resource: ResourceType) -> bool:
        return resource in self.readable_resources

    def lists_unsupported(self, action: str) -> bool:
        return action in self.unsupported_actions
