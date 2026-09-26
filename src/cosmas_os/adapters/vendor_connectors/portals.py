"""A common registry for explicit portal implementations, not universal access.

There are deliberately no production profiles until the practice's portal and
its actual API contract are reviewed. This module performs no network activity.
"""

import ipaddress
import re
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import quote, urlsplit

from pydantic import Field, field_validator, model_validator

from cosmas_os.ports.scribe_capture import ProtectedModel
from cosmas_os.ports.vendor_connectors import (
    ApprovalBinding,
    CapabilityDescription,
    ConnectionSelection,
    Digest,
    EndpointID,
    PortalDocumentIntent,
    PortalIntent,
    PortalObservation,
    PreparedPortalRequest,
    ProviderReference,
    SubmissionObservation,
    VendorCommand,
    VendorError,
    digest,
)

from .transport import checked

PortalCapability = Literal["document.upload", "referral.submit", "referral.read"]
AUTH_HEADERS = {"oauth2_bearer": "Authorization", "bearer_api_key": "Authorization",
    "basic": "Authorization", "x_api_key": "X-API-Key"}
PLACEHOLDERS = {"patient_id", "practice_id", "recipient_id", "reference"}


class PortalRouteBindings(ProtectedModel):
    """Already-resolved bounded IDs; no URL, percent escape or raw path input."""

    patient_id: EndpointID | None = None
    practice_id: EndpointID | None = None
    recipient_id: EndpointID | None = None
    reference: EndpointID | None = None


class PortalRoute(ProtectedModel):
    capability: PortalCapability
    origin_index: int = Field(strict=True, ge=0, le=4)
    method: Literal["GET", "POST"]
    path_template: str = Field(strict=True, min_length=2, max_length=512)
    idempotency: Literal["read_only", "documented_key_replay", "documented_unique_reference", "not_documented"]
    idempotency_header: Literal["Idempotency-Key", "X-Idempotency-Key"] | None = None
    reconciliation: Literal["exact_reference_read", "correlated_event_then_read", "manual_review_only", "not_applicable"]
    request_contract_sha256: Digest
    response_contract_sha256: Digest

    def placeholders(self):
        return {part[1:-1] for part in self.path_template.split("/") if part.startswith("{")}

    @model_validator(mode="after")
    def closed_route(self):
        parts = self.path_template.split("/")
        if parts[0] or not 1 <= len(parts) - 1 <= 16:
            raise ValueError("Portal routes require an exact absolute path")
        for part in parts[1:]:
            if part.startswith("{") and part.endswith("}") and part[1:-1] in PLACEHOLDERS:
                continue
            if part in {".", ".."} or re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}", part) is None:
                raise ValueError("Unknown placeholder or unsafe route segment")
        if self.capability == "referral.read":
            if self.idempotency != "read_only" or self.reconciliation != "not_applicable" or "reference" not in self.placeholders():
                raise ValueError("Read route requires its exact reference and read-only classification")
        elif self.method != "POST" or self.idempotency == "read_only" or self.reconciliation == "not_applicable":
            raise ValueError("Mutation route requires explicit write/recovery classification")
        if (self.idempotency == "documented_key_replay") != (self.idempotency_header is not None):
            raise ValueError("A documented replay key requires its closed header mapping")
        if self.capability == "document.upload" and self.reconciliation != "manual_review_only":
            raise ValueError("No generic portal-document status read is implemented")
        return self

    def render_path(self, bindings: PortalRouteBindings) -> str:
        try:
            route = PortalRoute.model_validate(self.model_dump(mode="python"))
            values = PortalRouteBindings.model_validate(bindings.model_dump(mode="python")).model_dump(exclude_none=True)
            if set(values) != route.placeholders():
                raise ValueError
            path = "/".join(quote(values[part[1:-1]], safe="") if part.startswith("{") else part
                for part in route.path_template.split("/"))
            if len(path) > 4096:
                raise ValueError
            return path
        except (ValueError, TypeError, AttributeError):
            raise VendorError("request_invalid") from None


class PortalProfile(ProtectedModel):
    portal_id: str = Field(strict=True, pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    contract_version: str = Field(strict=True, pattern=r"^[a-zA-Z0-9._-]{1,64}$")
    documentation_sha256: Digest
    origins: tuple[str, ...] = Field(min_length=1, max_length=5)
    capabilities: tuple[CapabilityDescription, ...] = Field(max_length=10)
    auth_scheme: Literal["oauth2_bearer", "bearer_api_key", "basic", "x_api_key"]
    correspondence: tuple[Literal["patient", "practice", "recipient"], ...] = Field(min_length=2, max_length=3)
    receipt_parser_version: str = Field(strict=True, pattern=r"^[a-zA-Z0-9._-]{1,64}$")
    routes: tuple[PortalRoute, ...] = Field(max_length=3)

    @field_validator("origins")
    @classmethod
    def exact_origins(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Duplicate portal origin")
        for value in values:
            parts = urlsplit(value)
            host = parts.hostname or ""
            if (value != "https://" + host or parts.port is not None or parts.username or parts.password
                    or parts.path or parts.query or parts.fragment or len(host) > 253
                    or host.endswith((".local", ".localhost", ".internal", ".lan", ".home"))
                    or re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host) is None):
                raise ValueError("Portal origin must be a fixed HTTPS hostname")
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                raise ValueError("Portal IP origins are unsupported")
        return values

    @model_validator(mode="after")
    def unique_capabilities(self):
        if len({entry.capability for entry in self.capabilities}) != len(self.capabilities):
            raise ValueError("Duplicate portal capability")
        if any(entry.capability not in {"document.upload", "referral.submit", "referral.read"} for entry in self.capabilities):
            raise ValueError("Unsupported common portal capability")
        if len(set(self.correspondence)) != len(self.correspondence) or not {"patient", "practice"}.issubset(self.correspondence):
            raise ValueError("Exact patient/practice correspondence is required")
        documented = {entry.capability for entry in self.capabilities if entry.evidence == "documented"}
        if len({route.capability for route in self.routes}) != len(self.routes) or {route.capability for route in self.routes} != documented:
            raise ValueError("Each documented capability requires exactly one route")
        for route in self.routes:
            if route.origin_index >= len(self.origins):
                raise ValueError("Route origin is not in the exact profile allowlist")
            if route.capability != "referral.read" and "recipient" not in self.correspondence:
                raise ValueError("A write requires exact recipient correspondence")
            if route.reconciliation in {"exact_reference_read", "correlated_event_then_read"} and "referral.read" not in documented:
                raise ValueError("Declared reconciliation requires a documented exact read")
        return self

    def commitment(self):
        return digest("cosmas-portal-profile.v1", self.model_dump(mode="json"))

    @property
    def auth_header(self):
        return AUTH_HEADERS[self.auth_scheme]


class PortalImplementation(Protocol):
    """A named adapter supplies its own closed request/receipt and authorization.

    Implementations must not derive a live endpoint from arbitrary portal input.
    Preparation is pure. Submit must default off, verify current application
    authority before I/O, use its own approved typed encoder and retain uncertain
    dispatch/received evidence. Observe requires current read authority and exact
    reference correlation. Registry lookup/preparation grants no such authority.
    """

    profile: PortalProfile

    def prepare(self, command: VendorCommand, document: bytes | None = None) -> PreparedPortalRequest: ...

    async def submit(self, prepared: PreparedPortalRequest, approval: ApprovalBinding) -> SubmissionObservation: ...

    async def observe(self, command: VendorCommand, reference: ProviderReference) -> PortalObservation: ...


@dataclass(frozen=True)
class PortalBinding:
    profile: PortalProfile
    adapter: PortalImplementation


class PortalRegistry:
    def __init__(self, bindings: tuple[PortalBinding, ...] = ()):
        self._bindings = {}
        for binding in bindings:
            profile = PortalProfile.model_validate(binding.profile.model_dump(mode="python"))
            if (binding.adapter.profile != profile or profile.portal_id in self._bindings
                    or not all(callable(getattr(binding.adapter, method, None)) for method in ("prepare", "submit", "observe"))):
                raise VendorError("request_invalid")
            self._bindings[profile.portal_id] = PortalBinding(profile, binding.adapter)

    def capabilities(self, portal_id: str) -> tuple[CapabilityDescription, ...]:
        binding = self._bindings.get(portal_id)
        if binding is None:
            raise VendorError("capability_unavailable")
        return binding.profile.capabilities

    def resolve(self, selection: ConnectionSelection, portal_id: str, capability: str) -> PortalImplementation:
        selection = ConnectionSelection.model_validate(selection.model_dump(mode="python"))
        binding = self._bindings.get(portal_id)
        if selection.vendor != "portal" or binding is None or binding.adapter.profile != binding.profile or not any(
                item.capability == capability and item.evidence == "documented" for item in binding.profile.capabilities):
            raise VendorError("capability_unavailable")
        return binding.adapter

    def prepare(self, command: VendorCommand, document: bytes | None = None) -> PreparedPortalRequest:
        command = checked(command)
        if not isinstance(command.intent, PortalIntent):
            raise VendorError("capability_unavailable")
        intent = command.intent
        adapter = self.resolve(command.selection, intent.portal_id, intent.kind)
        profile = self._bindings[intent.portal_id].profile
        if intent.profile_sha256 != profile.commitment():
            raise VendorError("connection_changed")
        # Validate exact data before even entering an implementation's pure
        # preparer. A referral never receives bytes for an implicit upload.
        if isinstance(intent, PortalDocumentIntent):
            if document is None:
                raise VendorError("artifact_changed")
            intent.document.require_bytes(document)
        elif document is not None:
            raise VendorError("request_invalid")
        try:
            result = adapter.prepare(command, document)
            result = PreparedPortalRequest.model_validate(result.model_dump(mode="python"))
            if result.command.commitment() != command.commitment() or result.profile_sha256 != profile.commitment():
                raise ValueError
            return result
        except (ValueError, TypeError, AttributeError):
            raise VendorError("request_invalid") from None


PRODUCTION_PORTALS = PortalRegistry()
