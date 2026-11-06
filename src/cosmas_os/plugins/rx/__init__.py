"""Prescription connector scaffold: fail-closed gates, no vendor pick.

This package is a mock-placeholder surface only. It does not contact any
prescribing network, mint credentials, or enable live send/read paths.
"""

from cosmas_os.plugins.rx.connector import DeclaredRxConnector, RxConnector
from cosmas_os.plugins.rx.manifest import (
    CapabilityManifest,
    ResourceType,
    TargetEnvironment,
    VendorId,
)
from cosmas_os.plugins.rx.refusals import (
    RxCapabilityError,
    RxReadRefused,
    RxSendRefused,
    RxTargetRefused,
)
from cosmas_os.plugins.rx.registry import DEFAULT_MANIFEST, VendorRegistry, build_default_registry

__all__ = [
    "DEFAULT_MANIFEST",
    "CapabilityManifest",
    "DeclaredRxConnector",
    "ResourceType",
    "RxCapabilityError",
    "RxConnector",
    "RxReadRefused",
    "RxSendRefused",
    "RxTargetRefused",
    "TargetEnvironment",
    "VendorId",
    "VendorRegistry",
    "build_default_registry",
]
