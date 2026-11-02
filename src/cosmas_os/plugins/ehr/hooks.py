"""Optional hook points for later EHR modules.

These Protocols are intentional extension seams. They are not implemented in
this package:

- ``ProductionGate`` — C14 real-data / production gate
- ``PracticeScopeConfig`` / ``PhiFreeReadAudit`` — C6 per-practice scope and
  PHI-free read audit
- ``BackendAuthProvider`` — C2 2-legged OAuth client-credentials auth
- ``SecretResolver`` — named secret resolution (C2 env binding; C3 Key Vault)
- ``FhirReadClient`` — C4 FHIR R4 read client

Callers pass hook instances into ``EhrConnector`` gate methods when those
modules exist. Until then the connector stays fail closed.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cosmas_os.plugins.ehr.manifest import ResourceType, TargetEnvironment, VendorId


class ProductionGate(Protocol):
    """C14: decide whether a production / real-data target may proceed."""

    def allow_production(
        self,
        *,
        vendor_id: VendorId,
        target: TargetEnvironment,
    ) -> bool:
        """Return True only when production use is explicitly authorized."""
        ...


class PracticeScopeConfig(Protocol):
    """C6: per-practice scope check before a read is attempted."""

    def allow_practice(
        self,
        *,
        vendor_id: VendorId,
        practice_ref: str,
        resource: ResourceType,
    ) -> bool:
        """Return True only when this practice may be read for the resource."""
        ...


class PhiFreeReadAudit(Protocol):
    """C6: record a PHI-free audit row for an attempted or completed read."""

    def record_read(
        self,
        *,
        vendor_id: VendorId,
        resource: ResourceType,
        target: TargetEnvironment,
        practice_ref: str | None,
        outcome: str,
    ) -> None:
        """Persist a non-PHI audit event. Must not accept chart payload bodies."""
        ...


@runtime_checkable
class BackendAuthProvider(Protocol):
    """C2: obtain a 2-legged client-credentials access token for a vendor.

    Concrete implementation:
    ``cosmas_os.adapters.ehr_auth.ClientCredentialsAuthProvider``.
    """

    def access_token(self, *, vendor_id: VendorId, audience: str) -> str:
        """Return a short-lived access token. Must not log the token."""
        ...


@runtime_checkable
class SecretResolver(Protocol):
    """Resolve a named secret without embedding credentials in code.

    C2 provides ``ManagedSecretEnvResolver`` (``COSMAS_MANAGED_SECRET_*`` env
    bindings from Key Vault). C3 may add a richer Key Vault adapter.
    """

    def resolve(self, *, name: str) -> str:
        """Return the secret value for ``name``. Must not log the value."""
        ...


class FhirReadClient(Protocol):
    """C4: bounded FHIR R4 read against an already-authorized base URL."""

    def read_resource(
        self,
        *,
        resource_type: str,
        resource_id: str,
    ) -> dict:
        """Return one FHIR resource document for the authorized scope."""
        ...
