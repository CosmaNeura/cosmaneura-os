"""Map synthetic US Core / FHIR R4 resources into CosmaBot review provenance (C5).

Produces PatientLink-ready identity pins and human source-review projections with
provenance (vendor, resource type, resource id hash, read time). Reuses the
shared FHIR custody shape; does not wire routes or plugin tools (C8).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from cosmas_os.adapters.ehr_fhir_vendor import (
    VENDOR_DISPLAY,
    require_fhir_vendor,
)
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.plugins.ehr_fhir.resources import READABLE_RESOURCES

# Resources C8 will read through the shared FHIR path into source-review.
# Appointment stays vendor-specific (Tebra SOAP / parked athena C15) — not mapped here.
MAPPED_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "Patient",
        "MedicationRequest",
        "Encounter",
        "AllergyIntolerance",
        "Condition",
        "Observation",
        "DocumentReference",
    }
)

# Keep identity projection aligned with SQL ehr_fhir grant identity allow-list.
_PATIENT_IDENTITY_KEYS = (
    "resourceType",
    "id",
    "name",
    "birthDate",
    "gender",
    "identifier",
    "active",
    "deceasedBoolean",
    "deceasedDateTime",
    "link",
    "managingOrganization",
)

_SUMMARY_KEYS: dict[str, tuple[str, ...]] = {
    "MedicationRequest": ("status", "intent", "authoredOn", "medicationCodeableConcept", "medicationReference", "dosageInstruction"),
    "Encounter": ("status", "class", "type", "period"),
    "AllergyIntolerance": ("clinicalStatus", "verificationStatus", "code", "recordedDate"),
    "Condition": ("clinicalStatus", "verificationStatus", "category", "code", "onsetDateTime", "recordedDate"),
    "Observation": ("status", "category", "code", "effectiveDateTime", "valueQuantity", "valueCodeableConcept", "valueString"),
    "DocumentReference": ("status", "type", "category", "date", "description", "content"),
}


@dataclass(frozen=True, repr=False)
class FhirSourceProvenance:
    """PHI-free provenance for a mapped US Core source row."""

    vendor: Literal["tebra", "athena"]
    resource_type: str
    resource_id_hash: str
    read_time: datetime

    def as_dict(self) -> dict[str, str]:
        if self.read_time.utcoffset() is None:
            raise ValueError("aware_fhir_read_time_required")
        return {
            "vendor": self.vendor,
            "resource_type": self.resource_type,
            "resource_id_hash": self.resource_id_hash,
            "read_time": self.read_time.isoformat(),
        }


@dataclass(frozen=True, repr=False)
class MappedPatientLinkIdentity:
    """Exact Patient identity JSON for EhrFhirPatientGrant / PatientLink selection."""

    vendor: Literal["tebra", "athena"]
    fhir_patient_id: str
    identity_json: str
    identity_sha256: str
    provenance: FhirSourceProvenance


@dataclass(frozen=True, repr=False)
class MappedReviewSource:
    """Reviewable source projection that fits the existing human source-review flow."""

    vendor: Literal["tebra", "athena"]
    resource_type: str
    resource_id: str
    provenance: FhirSourceProvenance
    display_label: str
    source_content: str
    content_sha256: str
    summary_json: str


def resource_id_hash(resource_id: str) -> str:
    if type(resource_id) is not str or not 1 <= len(resource_id) <= 64:
        raise ValueError("invalid_fhir_resource_id")
    if resource_id in {".", ".."} or any(c in resource_id for c in "/?#\\"):
        raise ValueError("invalid_fhir_resource_id")
    return hashlib.sha256(resource_id.encode("utf-8")).hexdigest()


def _require_resource(resource: dict[str, Any], expected: str | None = None) -> tuple[str, str]:
    if type(resource) is not dict:
        raise ValueError("invalid_fhir_resource")
    kind = resource.get("resourceType")
    identifier = resource.get("id")
    if type(kind) is not str or kind not in READABLE_RESOURCES:
        raise ValueError("unsupported_fhir_resource_type")
    if expected is not None and kind != expected:
        raise ValueError("unexpected_fhir_resource_type")
    if type(identifier) is not str or not 1 <= len(identifier) <= 64:
        raise ValueError("invalid_fhir_resource_id")
    if identifier in {".", ".."} or any(c in identifier for c in "/?#\\"):
        raise ValueError("invalid_fhir_resource_id")
    return kind, identifier


def _aware(read_time: datetime) -> datetime:
    if type(read_time) is not datetime or read_time.utcoffset() is None:
        raise ValueError("aware_fhir_read_time_required")
    return read_time


def _provenance(vendor: str, resource_type: str, resource_id: str, read_time: datetime) -> FhirSourceProvenance:
    return FhirSourceProvenance(
        vendor=require_fhir_vendor(vendor),
        resource_type=resource_type,
        resource_id_hash=resource_id_hash(resource_id),
        read_time=_aware(read_time),
    )


def map_patient_identity(resource: dict[str, Any], *, vendor: str, read_time: datetime) -> MappedPatientLinkIdentity:
    """Project a US Core Patient into the existing FHIR grant identity pin."""
    kind, identifier = _require_resource(resource, "Patient")
    vendor = require_fhir_vendor(vendor)
    identity = {key: resource[key] for key in _PATIENT_IDENTITY_KEYS if key in resource}
    if identity.get("resourceType") != "Patient" or identity.get("id") != identifier:
        raise ValueError("invalid_fhir_patient_identity")
    identity_json = canonical_json(identity)
    provenance = _provenance(vendor, kind, identifier, read_time)
    return MappedPatientLinkIdentity(
        vendor=vendor,
        fhir_patient_id=identifier,
        identity_json=identity_json,
        identity_sha256=hashlib.sha256(identity_json.encode("utf-8")).hexdigest(),
        provenance=provenance,
    )


def _summary(resource: dict[str, Any], kind: str) -> dict[str, Any]:
    keys = _SUMMARY_KEYS.get(kind, ())
    body = {key: resource[key] for key in keys if key in resource}
    body["resourceType"] = kind
    body["id"] = resource["id"]
    if "subject" in resource:
        body["subject"] = resource["subject"]
    if "patient" in resource:
        body["patient"] = resource["patient"]
    return body


def _source_content(
    *,
    vendor: str,
    kind: str,
    resource_id: str,
    read_time: datetime,
    summary_json: str,
    provenance: FhirSourceProvenance,
) -> str:
    label = VENDOR_DISPLAY[require_fhir_vendor(vendor)]
    lines = [
        f"{label} {kind} (bounded synthetic US Core snapshot)",
        f"Resource id hash: {provenance.resource_id_hash}",
        f"Observed: {read_time.isoformat()}",
        f"Vendor: {vendor}",
        f"Resource type: {kind}",
        f"Recorded resource id: {resource_id}",
        "JSON section preserves codes and qualifiers only; this does not establish current clinical truth.",
        summary_json,
        "Preparing this projection does not establish human approval or source admission.",
    ]
    return "\n".join(lines)


def map_review_source(resource: dict[str, Any], *, vendor: str, read_time: datetime) -> MappedReviewSource:
    """Map one US Core clinical resource into a source-review projection with provenance."""
    kind, identifier = _require_resource(resource)
    if kind not in MAPPED_SOURCE_TYPES or kind == "Patient":
        raise ValueError("unsupported_fhir_review_resource")
    vendor = require_fhir_vendor(vendor)
    read_time = _aware(read_time)
    provenance = _provenance(vendor, kind, identifier, read_time)
    summary = _summary(resource, kind)
    summary_json = canonical_json(summary)
    content = _source_content(
        vendor=vendor,
        kind=kind,
        resource_id=identifier,
        read_time=read_time,
        summary_json=summary_json,
        provenance=provenance,
    )
    if len(content) > 5000:
        raise ValueError("fhir_source_too_large")
    return MappedReviewSource(
        vendor=vendor,
        resource_type=kind,
        resource_id=identifier,
        provenance=provenance,
        display_label=f"{VENDOR_DISPLAY[vendor]}: reviewed {kind}",
        source_content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        summary_json=summary_json,
    )


def map_bundle_entries(
    bundle: dict[str, Any],
    *,
    vendor: str,
    read_time: datetime,
) -> tuple[MappedPatientLinkIdentity | None, tuple[MappedReviewSource, ...]]:
    """Map a synthetic Bundle searchset/collection into grant identity + review sources."""
    if type(bundle) is not dict or bundle.get("resourceType") != "Bundle":
        raise ValueError("invalid_fhir_bundle")
    vendor = require_fhir_vendor(vendor)
    read_time = _aware(read_time)
    patient: MappedPatientLinkIdentity | None = None
    sources: list[MappedReviewSource] = []
    entries = bundle.get("entry") or []
    if type(entries) is not list or len(entries) > 50:
        raise ValueError("invalid_fhir_bundle_entries")
    for entry in entries:
        if type(entry) is not dict:
            raise ValueError("invalid_fhir_bundle_entry")
        resource = entry.get("resource")
        if type(resource) is not dict:
            continue
        kind = resource.get("resourceType")
        if kind == "Patient":
            mapped = map_patient_identity(resource, vendor=vendor, read_time=read_time)
            if patient is not None and patient.fhir_patient_id != mapped.fhir_patient_id:
                raise ValueError("multiple_fhir_patients")
            patient = mapped
        elif kind in MAPPED_SOURCE_TYPES:
            sources.append(map_review_source(resource, vendor=vendor, read_time=read_time))
        elif kind in READABLE_RESOURCES:
            # Included Medication / Practitioner / Organization support rows are not review sources.
            continue
        else:
            raise ValueError("unsupported_fhir_resource_type")
    return patient, tuple(sources)


def provenance_commitment(provenance: FhirSourceProvenance) -> str:
    """Stable hash over the four provenance fields required by C5 done criteria."""
    return payload_hash({"contract": "ehr-fhir-source-provenance.v1", **provenance.as_dict()})
