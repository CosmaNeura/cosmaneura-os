"""Closed surface for the athena Certified FHIR R4 Preview adapter (C7).

No CosmaBot route wiring here — that is ticket C8. This port re-exports the
adapter constants and result type so application code can depend on a stable
import path without reaching into adapter internals.
"""

from cosmas_os.adapters.athena_fhir_r4 import (
    ATHENA_FHIR_R4_BASE_URL,
    ATHENA_FHIR_RESOURCES,
    ATHENA_FHIR_SYSTEM_READ_SCOPES,
    ATHENA_FHIR_TOKEN_URL,
    ATHENA_PRACTICE_PARAM,
    ATHENA_PRACTICE_VALUE,
    ATHENA_PREVIEW_PRACTICE_ID,
    FORBIDDEN_FHIR_RESOURCES,
    AthenaFhirR4Adapter,
    AthenaFhirR4Error,
    AthenaFhirR4SearchRequest,
    athena_fhir_preview_client_credentials_config,
)
from cosmas_os.plugins.ehr_fhir import FhirReadResult

__all__ = [
    "ATHENA_FHIR_R4_BASE_URL",
    "ATHENA_FHIR_RESOURCES",
    "ATHENA_FHIR_SYSTEM_READ_SCOPES",
    "ATHENA_FHIR_TOKEN_URL",
    "ATHENA_PRACTICE_PARAM",
    "ATHENA_PRACTICE_VALUE",
    "ATHENA_PREVIEW_PRACTICE_ID",
    "FORBIDDEN_FHIR_RESOURCES",
    "AthenaFhirR4Adapter",
    "AthenaFhirR4Error",
    "AthenaFhirR4SearchRequest",
    "FhirReadResult",
    "athena_fhir_preview_client_credentials_config",
]
