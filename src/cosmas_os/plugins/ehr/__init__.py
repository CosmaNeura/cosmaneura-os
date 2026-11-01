"""Shared EHR connector contract: manifest, fail-closed gates, vendor registry.

This package is the stable surface for SMART backend-services auth (C2 /
backend_jwt via ``adapters.ehr_auth``), Key Vault secret resolution (C3), and a
FHIR R4 read client (C4). It does not perform vendor HTTP itself. Existing
CosmaBot plugin tools keep their current behavior; they only declare a
capability manifest here.

Writes and production targets are refused by default (fail closed). Optional
hook points exist for a later production gate (C14) and PHI-free read audit /
per-practice scope (C6); those modules are not implemented here.
"""

from cosmas_os.plugins.ehr.connector import DeclaredEhrConnector, EhrConnector
from cosmas_os.plugins.ehr.hooks import (
    BackendAuthProvider,
    FhirReadClient,
    PhiFreeReadAudit,
    PracticeScopeConfig,
    ProductionGate,
    SecretResolver,
)
from cosmas_os.plugins.ehr.manifest import (
    AuthStyle,
    CapabilityManifest,
    ResourceType,
    TargetEnvironment,
    VendorId,
)
from cosmas_os.plugins.ehr.refusals import (
    EhrCapabilityError,
    EhrReadRefused,
    EhrTargetRefused,
    EhrWriteRefused,
)
from cosmas_os.plugins.ehr.registry import VendorRegistry, build_default_registry

__all__ = [
    "AuthStyle",
    "BackendAuthProvider",
    "CapabilityManifest",
    "DeclaredEhrConnector",
    "EhrCapabilityError",
    "EhrConnector",
    "EhrReadRefused",
    "EhrTargetRefused",
    "EhrWriteRefused",
    "FhirReadClient",
    "PhiFreeReadAudit",
    "PracticeScopeConfig",
    "ProductionGate",
    "ResourceType",
    "SecretResolver",
    "TargetEnvironment",
    "VendorId",
    "VendorRegistry",
    "build_default_registry",
]
