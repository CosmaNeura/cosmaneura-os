"""eFax / fax connector scaffold: fail-closed gates over existing providers.

Reuses provider ids from ``adapters.vendor_connectors``. Does not invent a new
fax stack, flip live inbound flags, or enable outbound send.
"""

from cosmas_os.plugins.efax.connector import DeclaredEFaxConnector, EFaxConnector
from cosmas_os.plugins.efax.manifest import (
    CapabilityManifest,
    ProviderId,
    ResourceType,
    TargetEnvironment,
)
from cosmas_os.plugins.efax.refusals import (
    EFaxCapabilityError,
    EFaxReadRefused,
    EFaxSendRefused,
    EFaxTargetRefused,
)
from cosmas_os.plugins.efax.registry import ProviderRegistry, build_default_registry

__all__ = [
    "CapabilityManifest",
    "DeclaredEFaxConnector",
    "EFaxCapabilityError",
    "EFaxConnector",
    "EFaxReadRefused",
    "EFaxSendRefused",
    "EFaxTargetRefused",
    "ProviderId",
    "ProviderRegistry",
    "ResourceType",
    "TargetEnvironment",
    "build_default_registry",
]
