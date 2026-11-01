"""SMART Backend Services / athena 2-legged JWT client-assertion auth (C2).

Access tokens stay in process memory only. They are never written to disk, the
database, logs, HTTP responses, or any device. Private keys for production use
stay in Azure Key Vault and are referenced only by ``COSMAS_MANAGED_SECRET_*``
names. Live connectors are not wired here.
"""

from cosmas_os.adapters.ehr_auth.backend_jwt import (
    AUTH_KIND_BACKEND_JWT,
    BackendJwtAuthError,
    BackendJwtConfig,
    BackendJwtTokenClient,
    SmartBackendJwtAuthProvider,
    normalize_system_read_scopes,
)
from cosmas_os.adapters.ehr_auth.key_vault_signer import (
    KeyVaultRemoteKeySigner,
    ManagedSecretKeyReference,
    RemoteDigestSigner,
    validate_managed_secret_reference_name,
)
from cosmas_os.adapters.ehr_auth.local_test_signer import LocalTestKeySigner

__all__ = [
    "AUTH_KIND_BACKEND_JWT",
    "BackendJwtAuthError",
    "BackendJwtConfig",
    "BackendJwtTokenClient",
    "KeyVaultRemoteKeySigner",
    "LocalTestKeySigner",
    "ManagedSecretKeyReference",
    "RemoteDigestSigner",
    "SmartBackendJwtAuthProvider",
    "normalize_system_read_scopes",
    "validate_managed_secret_reference_name",
]
