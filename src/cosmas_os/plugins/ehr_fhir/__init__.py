"""Shared FHIR R4 / US Core read client for CosmaBot EHR connectors.

Self-contained package. A separate ticket owns ``plugins/ehr`` and the
``EhrConnector`` interface; this client stays independent so the two PRs do not
conflict, and can plug into that interface later.
"""

from cosmas_os.plugins.ehr_fhir.client import (
    FhirR4ReadClient,
    FhirReadResult,
    production_base_refused,
)
from cosmas_os.plugins.ehr_fhir.errors import (
    ERROR_STATES,
    READY,
    FhirReadError,
    error_result,
    map_http_status,
    map_operation_outcome,
    map_operation_outcome_code,
    messages_for,
)
from cosmas_os.plugins.ehr_fhir.resources import (
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_RESPONSE_BYTES,
    READABLE_RESOURCES,
    WRITE_HTTP_METHODS,
    ReadableResource,
)
from cosmas_os.plugins.ehr_fhir.urls import (
    assert_allowed_base_url,
    is_production_base_url,
    is_sandbox_base_url,
)

__all__ = [
    "DEFAULT_MAX_PAGES",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "ERROR_STATES",
    "FhirR4ReadClient",
    "FhirReadError",
    "FhirReadResult",
    "READABLE_RESOURCES",
    "READY",
    "ReadableResource",
    "WRITE_HTTP_METHODS",
    "assert_allowed_base_url",
    "error_result",
    "is_production_base_url",
    "is_sandbox_base_url",
    "map_http_status",
    "map_operation_outcome",
    "map_operation_outcome_code",
    "messages_for",
    "production_base_refused",
]
