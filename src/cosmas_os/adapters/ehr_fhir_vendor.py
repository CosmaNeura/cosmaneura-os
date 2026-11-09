"""Vendor-aware FHIR connection pins for the shared custody path (C5).

Tebra digests stay byte-identical. athena Preview (practice 195900) uses the
same EhrFhirPatientGrant / source-review tables with distinct contract names and
FHIR base. No route wiring here — that is C8.
"""

from __future__ import annotations

from typing import Literal

from cosmas_os.adapters.athena_fhir_r4 import (
    ATHENA_FHIR_R4_BASE_URL,
    ATHENA_PRACTICE_VALUE,
    ATHENA_PREVIEW_PRACTICE_ID,
)

FhirVendor = Literal["tebra", "athena"]

# Keep this literal identical to adapters.tebra_fhir_read.FHIR_BASE — do not import
# that module here (circular import with medication history helpers).
TEBRA_FHIR_BASE = "https://fhir.prd.cloud.tebra.com/fhir-request"
TEBRA_FHIR_ENVIRONMENT = "synthetic"
ATHENA_FHIR_ENVIRONMENT = "preview"

FHIR_CONNECTION_CONTRACT = {
    "tebra": "tebra-fhir-connection-scope.v1",
    "athena": "athena-fhir-connection-scope.v1",
}
FHIR_PATIENT_SCOPE_CONTRACT = {
    "tebra": "tebra-fhir-patient-scope.v1",
    "athena": "athena-fhir-patient-scope.v1",
}
FHIR_PATIENT_GRANT_CONTRACT = {
    "tebra": "tebra-fhir-patient-grant.v1",
    "athena": "athena-fhir-patient-grant.v1",
}
FHIR_MEDICATION_HISTORY_CONTRACT = {
    "tebra": "tebra-fhir-medication-history.v1",
    "athena": "athena-fhir-medication-history.v1",
}
FHIR_REVIEW_SNAPSHOT_CONTRACT = {
    "tebra": "tebra-fhir-review-snapshot.v1",
    "athena": "athena-fhir-review-snapshot.v1",
}
FHIR_MEDICATIONS_ITEM_KIND = {
    "tebra": "ehr_tebra_fhir_medications_item.v1",
    "athena": "ehr_athena_fhir_medications_item.v1",
}

FHIR_BASE_BY_VENDOR = {
    "tebra": TEBRA_FHIR_BASE,
    "athena": ATHENA_FHIR_R4_BASE_URL,
}

FHIR_ENVIRONMENT_BY_VENDOR = {
    "tebra": TEBRA_FHIR_ENVIRONMENT,
    "athena": ATHENA_FHIR_ENVIRONMENT,
}

VENDOR_DISPLAY = {
    "tebra": "Tebra",
    "athena": "Athena",
}


def require_fhir_vendor(vendor: str) -> FhirVendor:
    if vendor not in FHIR_BASE_BY_VENDOR:
        raise ValueError("unsupported_fhir_vendor")
    return vendor  # type: ignore[return-value]


def fhir_base(vendor: str) -> str:
    return FHIR_BASE_BY_VENDOR[require_fhir_vendor(vendor)]


def fhir_environment(vendor: str) -> str:
    return FHIR_ENVIRONMENT_BY_VENDOR[require_fhir_vendor(vendor)]


def connection_scope_payload(
    vendor: str,
    *,
    box_id: str,
    owner_id: str,
    account_id: str,
    connection_id: str,
    credential_generation: str,
    display_label: str,
) -> dict:
    """Exact connection digest payload; tebra keys stay unchanged."""
    vendor = require_fhir_vendor(vendor)
    body = {
        "contract": FHIR_CONNECTION_CONTRACT[vendor],
        "fhir_base": FHIR_BASE_BY_VENDOR[vendor],
        "box_id": box_id,
        "owner_id": owner_id,
        "account_id": account_id,
        "connection_id": connection_id,
        "credential_generation": credential_generation,
        "display_label": display_label,
    }
    if vendor == "athena":
        body["ah_practice"] = ATHENA_PRACTICE_VALUE
        body["practice_id"] = ATHENA_PREVIEW_PRACTICE_ID
    return body


def patient_scope_payload(vendor: str, scope_fields: dict) -> dict:
    vendor = require_fhir_vendor(vendor)
    return {
        "contract": FHIR_PATIENT_SCOPE_CONTRACT[vendor],
        "fhir_base": FHIR_BASE_BY_VENDOR[vendor],
        **scope_fields,
    }


def patient_grant_payload(vendor: str, fields: dict) -> dict:
    vendor = require_fhir_vendor(vendor)
    return {"contract": FHIR_PATIENT_GRANT_CONTRACT[vendor], **fields}


def medication_history_contract(vendor: str) -> str:
    return FHIR_MEDICATION_HISTORY_CONTRACT[require_fhir_vendor(vendor)]


def review_snapshot_contract(vendor: str) -> str:
    return FHIR_REVIEW_SNAPSHOT_CONTRACT[require_fhir_vendor(vendor)]


def medications_item_kind(vendor: str) -> str:
    return FHIR_MEDICATIONS_ITEM_KIND[require_fhir_vendor(vendor)]


def medication_source_title(vendor: str) -> str:
    return f"{VENDOR_DISPLAY[require_fhir_vendor(vendor)]} medication records (bounded synthetic snapshot)"


def reviewed_medications_label(vendor: str) -> str:
    return f"{VENDOR_DISPLAY[require_fhir_vendor(vendor)]}: reviewed medication records"
