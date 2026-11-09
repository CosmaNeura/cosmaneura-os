"""Closed surface for the Elation FHIR R4 sandbox adapter (C11 / C20 / T4).

No CosmaBot route wiring here. Appointments stay on the existing REST read
path (``adapters.elation_read``). This port re-exports the FHIR adapter
constants and result type so application code can depend on a stable import
path without reaching into adapter internals.
"""

from cosmas_os.adapters.elation_fhir_r4 import (
    ELATION_FHIR_EXTRA_SANDBOX_HOSTS,
    ELATION_FHIR_R4_BASE_URL,
    ELATION_FHIR_RESOURCES,
    ELATION_FHIR_SYSTEM_READ_SCOPES,
    ELATION_FHIR_TOKEN_URL,
    ELATION_REST_APPOINTMENT_SURFACE,
    FORBIDDEN_FHIR_RESOURCES,
    ElationFhirR4Adapter,
    ElationFhirR4Error,
    ElationFhirR4SearchRequest,
    elation_fhir_sandbox_client_credentials_config,
)
from cosmas_os.plugins.ehr_fhir import FhirReadResult

__all__ = [
    "ELATION_FHIR_EXTRA_SANDBOX_HOSTS",
    "ELATION_FHIR_R4_BASE_URL",
    "ELATION_FHIR_RESOURCES",
    "ELATION_FHIR_SYSTEM_READ_SCOPES",
    "ELATION_FHIR_TOKEN_URL",
    "ELATION_REST_APPOINTMENT_SURFACE",
    "FORBIDDEN_FHIR_RESOURCES",
    "ElationFhirR4Adapter",
    "ElationFhirR4Error",
    "ElationFhirR4SearchRequest",
    "FhirReadResult",
    "elation_fhir_sandbox_client_credentials_config",
]
