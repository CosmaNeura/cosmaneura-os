"""EHR backend auth: 2-legged OAuth client-credentials (client secret).

Access tokens stay in process memory only. They are never written to disk, the
database, logs, HTTP responses, or any device. Client id and client secret are
read only through ``COSMAS_MANAGED_SECRET_*`` reference names. Live connectors
are not wired here.

Signed-key / JWT client-assertion auth is deferred to a later ticket so this
module stays small.
"""

from cosmas_os.adapters.ehr_auth.client_credentials import (
    AUTH_KIND_CLIENT_CREDENTIALS,
    ClientCredentialsAuthError,
    ClientCredentialsAuthProvider,
    ClientCredentialsConfig,
    ClientCredentialsTokenClient,
    normalize_system_read_scopes,
)
from cosmas_os.adapters.ehr_auth.managed_secret_env import (
    ATHENA_FHIR_CLIENT_ID_REF,
    ATHENA_FHIR_CLIENT_SECRET_REF,
    ManagedSecretEnvResolver,
    validate_managed_secret_reference_name,
)

__all__ = [
    "ATHENA_FHIR_CLIENT_ID_REF",
    "ATHENA_FHIR_CLIENT_SECRET_REF",
    "AUTH_KIND_CLIENT_CREDENTIALS",
    "ClientCredentialsAuthError",
    "ClientCredentialsAuthProvider",
    "ClientCredentialsConfig",
    "ClientCredentialsTokenClient",
    "ManagedSecretEnvResolver",
    "normalize_system_read_scopes",
    "validate_managed_secret_reference_name",
]
