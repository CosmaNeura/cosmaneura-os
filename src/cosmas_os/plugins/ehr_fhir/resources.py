"""FHIR R4 / US Core resource types this shared read client may request."""

from __future__ import annotations

from typing import Final, Literal

ReadableResource = Literal[
    "Patient",
    "Encounter",
    "Appointment",
    "AllergyIntolerance",
    "MedicationRequest",
    "Condition",
    "Observation",
    "DocumentReference",
]

READABLE_RESOURCES: Final[frozenset[str]] = frozenset(
    {
        "Patient",
        "Encounter",
        "Appointment",
        "AllergyIntolerance",
        "MedicationRequest",
        "Condition",
        "Observation",
        "DocumentReference",
    }
)

WRITE_HTTP_METHODS: Final[frozenset[str]] = frozenset(
    {"POST", "PUT", "PATCH", "DELETE", "CONNECT", "TRACE"}
)

# Hard caps for Bundle paging. Cumulative across followed pages.
DEFAULT_MAX_PAGES: Final[int] = 5
DEFAULT_MAX_RESPONSE_BYTES: Final[int] = 262_144
DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
