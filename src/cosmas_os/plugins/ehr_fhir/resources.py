"""FHIR R4 / US Core resource types this shared read client may request."""

from __future__ import annotations

from typing import Final, Literal

ReadableResource = Literal[
    "Patient",
    "Encounter",
    "Appointment",
    "AllergyIntolerance",
    "MedicationRequest",
    "Medication",
    "Condition",
    "Observation",
    "DocumentReference",
    "Practitioner",
    "Organization",
]

# Default shared allowlist. Vendor adapters that need additional certified
# types (for example athena's DiagnosticReport / Binary) must pass an explicit
# ``allowed_resources`` override on ``FhirR4ReadClient``; they must not widen
# this default for other vendors.
READABLE_RESOURCES: Final[frozenset[str]] = frozenset(
    {
        "Patient",
        "Encounter",
        "Appointment",
        "AllergyIntolerance",
        "MedicationRequest",
        "Medication",
        "Condition",
        "Observation",
        "DocumentReference",
        "Practitioner",
        "Organization",
    }
)

# Closed universe of resource types the shared client may ever be configured to
# read. Overrides must be a non-empty subset of this set.
EXTENDED_READABLE_RESOURCES: Final[frozenset[str]] = frozenset(
    {
        *READABLE_RESOURCES,
        "DiagnosticReport",
        "Binary",
    }
)

WRITE_HTTP_METHODS: Final[frozenset[str]] = frozenset(
    {"POST", "PUT", "PATCH", "DELETE", "CONNECT", "TRACE"}
)

# Hard caps for Bundle paging. Cumulative across followed pages.
DEFAULT_MAX_PAGES: Final[int] = 5
DEFAULT_MAX_RESPONSE_BYTES: Final[int] = 262_144
DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
