"""Shared ``EhrConnector`` interface with fail-closed write and target gates.

Implementations declare a ``CapabilityManifest`` and may attach later modules
via optional hook slots (C2 auth, C3 secrets, C4 FHIR read). Gate methods call
optional C14 / C6 hooks when provided; without them, production and writes are
refused and reads are limited to sandbox-supported declared resources.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from cosmas_os.plugins.ehr.hooks import (
    BackendAuthProvider,
    FhirReadClient,
    PhiFreeReadAudit,
    PracticeScopeConfig,
    ProductionGate,
    SecretResolver,
)
from cosmas_os.plugins.ehr.manifest import (
    CapabilityManifest,
    ResourceType,
    TargetEnvironment,
    VendorId,
)
from cosmas_os.plugins.ehr.refusals import EhrReadRefused, EhrTargetRefused, EhrWriteRefused

# Closed allowlist of read action names. Anything else is refused as a write.
READ_ACTIONS = frozenset({
    "appointments",
    "patients",
    "medications",
    "allergies",
    "problems",
    "labs",
    "visit",
    "visit_link_status",
    "status",
    "observe",
    "verify",
    "read",
})

# Historical mutation names kept for tests and docs; the gate uses READ_ACTIONS.
WRITE_ACTIONS = frozenset({
    "write",
    "write_chart",
    "create",
    "update",
    "delete",
    "prescribe",
    "sign",
    "sign_note",
    "book",
    "book_appointment",
    "cancel_appointment",
    "link_visit",
    "unlink_visit",
    "submit",
    "send_message",
    "external_send",
})


def normalize_action_name(action: str) -> str:
    """Strip surrounding whitespace and casefold for closed comparisons."""
    return action.strip().casefold()


@runtime_checkable
class EhrConnector(Protocol):
    """Stable connector surface for vendor capability declaration and gates."""

    @property
    def vendor_id(self) -> VendorId: ...

    def capability_manifest(self) -> CapabilityManifest: ...

    def refuse_write(self, action: str = "write") -> None: ...

    def allow_target(
        self,
        target: TargetEnvironment,
        *,
        production_gate: ProductionGate | None = None,
    ) -> None: ...

    def allow_read(
        self,
        resource: ResourceType,
        *,
        target: TargetEnvironment = "sandbox",
        practice_ref: str | None = None,
        production_gate: ProductionGate | None = None,
        practice_scope: PracticeScopeConfig | None = None,
        read_audit: PhiFreeReadAudit | None = None,
    ) -> None: ...


@dataclass(slots=True)
class DeclaredEhrConnector:
    """Default connector built from a plugin's capability manifest.

    Hook slots stay ``None`` until C2–C4 / C6 / C14 attach implementations.
    This class never opens a network connection.
    """

    manifest: CapabilityManifest
    auth_provider: BackendAuthProvider | None = None
    secret_resolver: SecretResolver | None = None
    fhir_read_client: FhirReadClient | None = None
    _read_actions: frozenset[str] = field(default=READ_ACTIONS, repr=False)

    def __post_init__(self) -> None:
        if type(self.manifest) is not CapabilityManifest:
            raise ValueError("capability_manifest_required")

    @property
    def vendor_id(self) -> VendorId:
        return self.manifest.vendor_id

    def capability_manifest(self) -> CapabilityManifest:
        return self.manifest

    def refuse_write(self, action: str = "write") -> None:
        raise EhrWriteRefused(action)

    def allow_target(
        self,
        target: TargetEnvironment,
        *,
        production_gate: ProductionGate | None = None,
    ) -> None:
        if target not in {"sandbox", "production"}:
            raise EhrTargetRefused(str(target))
        if target == "sandbox":
            if not self.manifest.sandbox_supported:
                raise EhrTargetRefused("sandbox")
            return
        # production: fail closed unless C14 gate explicitly allows and the
        # manifest claims production support.
        if not self.manifest.production_supported:
            raise EhrTargetRefused("production")
        if production_gate is None:
            raise EhrTargetRefused("production")
        if not production_gate.allow_production(
            vendor_id=self.vendor_id,
            target=target,
        ):
            raise EhrTargetRefused("production")

    def allow_read(
        self,
        resource: ResourceType,
        *,
        target: TargetEnvironment = "sandbox",
        practice_ref: str | None = None,
        production_gate: ProductionGate | None = None,
        practice_scope: PracticeScopeConfig | None = None,
        read_audit: PhiFreeReadAudit | None = None,
    ) -> None:
        outcome = "refused"
        try:
            self.allow_target(target, production_gate=production_gate)
            if not self.manifest.supports_read(resource):
                raise EhrReadRefused("ehr_resource_unsupported")
            if practice_scope is not None:
                if practice_ref is None or not practice_ref:
                    raise EhrReadRefused("ehr_practice_scope_required")
                if not practice_scope.allow_practice(
                    vendor_id=self.vendor_id,
                    practice_ref=practice_ref,
                    resource=resource,
                ):
                    raise EhrReadRefused("ehr_practice_scope_refused")
            outcome = "allowed"
        finally:
            if read_audit is not None:
                read_audit.record_read(
                    vendor_id=self.vendor_id,
                    resource=resource,
                    target=target,
                    practice_ref=practice_ref,
                    outcome=outcome,
                )

    def assert_not_write_action(self, action: str) -> None:
        """Refuse any action that is not an explicit allowlisted read name."""
        if type(action) is not str:
            raise EhrWriteRefused("write")
        normalized = normalize_action_name(action)
        if not normalized or normalized not in self._read_actions:
            self.refuse_write(action if action.strip() else "write")
