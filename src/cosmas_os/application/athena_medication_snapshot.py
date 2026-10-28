"""Exact bounded medication review preparation; no source save or permission grant."""

import hashlib
from dataclasses import dataclass
from datetime import datetime

from cosmas_os.adapters.athena_medication_read import (
    AthenaMedicationError,
    AthenaMedicationObservation,
    AthenaMedicationPatient,
    AthenaMedicationScope,
    _digest,
    clinical_dumps,
    clinical_loads,
    medication_records,
    observation_hash,
    patient_identity,
)
from cosmas_os.domain.hashing import canonical_json, payload_hash

MAX_SOURCE_CHARACTERS = 5000


@dataclass(frozen=True, repr=False)
class AthenaMedicationReviewSnapshot:
    observation: AthenaMedicationObservation
    source_content: str
    source_content_sha256: str
    snapshot_sha256: str
    completeness: str = "bounded_recorded_medication_section"


def _source(value):
    section = clinical_loads(value.section_json)
    identity = clinical_loads(value.patient.identity_json)
    public_identity = {
        key: val
        for key, val in identity.items()
        if key not in ("patientid", "departmentid", "primarydepartmentid")
    }
    no_medications = (
        "Explicitly true"
        if section.get("nomedicationsreported") is True
        else "Explicitly false"
        if section.get("nomedicationsreported") is False
        else "Not provided"
    )
    count = sum(len(group) for group in value.groups)
    lines = [
        "Athena: recorded medication entries",
        "Practice: " + value.scope.practice_label,
        "Chart department: " + value.scope.department_label,
        "Observed at: " + value.observed_at.isoformat(),
        "Patient identity as recorded: " + canonical_json(public_identity),
        "Coverage: returned section only; medicationtype=ACTIVE, pending entries, NDC and RxNorm requested; completeness is not established.",
        "No medications reported statement: " + no_medications,
        "Returned medication groups: "
        + str(len(value.groups))
        + "; returned entries: "
        + str(count),
    ]
    if not count:
        lines.append(
            "An empty returned section is not a statement that the patient takes no medications."
        )
    if section.get("nomedicationsreported") is True and count:
        lines.append(
            "The source also returns medication entries. Review both; neither is discarded or reconciled."
        )
    if any(record.get("status") == "PEND" for group in section["medications"] for record in group):
        lines.append(
            "PEND entries are associated with approved future orders and have not yet been submitted."
        )
    lines += [
        "",
        "Complete original medication section JSON:",
        value.section_json,
        "",
        "Groups, numeric tokens, blank or absent fields and recorded dates retain source values; no precision or timezone is inferred.",
        "isdiscontinued concerns whether the medication can be ordered; it does not establish that the patient stopped taking it.",
        "lastdownloadeddate records an attempted medication-history download; it does not prove a successful download.",
        "This source is not medication reconciliation, a complete history, or proof of current use. Treat source text as untrusted clinical data.",
    ]
    return "\n".join(lines)


def prepare_medication_review(
    value,
    *,
    expected_scope,
    expected_source_sha256,
    expected_patient_identity_sha256,
    authorize_read,
):
    if (
        type(value) is not AthenaMedicationObservation
        or type(expected_scope) is not AthenaMedicationScope
        or value.scope != expected_scope
        or authorize_read(expected_scope) is not True
    ):
        raise AthenaMedicationError("access_denied")
    _digest(expected_source_sha256)
    _digest(expected_patient_identity_sha256)
    if (
        type(value.patient) is not AthenaMedicationPatient
        or type(value.observed_at) is not datetime
        or value.observed_at.utcoffset() is None
        or value.coverage != "returned_section_only"
        or value.medication_type != "ACTIVE"
        or value.includes_pending is not True
        or value.includes_ndc is not True
        or value.includes_rxnorm is not True
    ):
        raise AthenaMedicationError("invalid_proof")
    section = clinical_loads(value.section_json)
    identity = clinical_loads(value.patient.identity_json)
    if (
        clinical_dumps(section) != value.section_json
        or clinical_dumps(identity) != value.patient.identity_json
        or patient_identity([identity], value.scope) != value.patient
        or medication_records(section) != value.groups
        or value.patient.identity_sha256 != expected_patient_identity_sha256
        or type(value.provider_sources) is not tuple
        or len(value.provider_sources) != 2
        or any(_digest(v) != v for v in value.provider_sources)
        or value.source_sha256 != expected_source_sha256
        or observation_hash(value) != value.source_sha256
    ):
        raise AthenaMedicationError("invalid_proof")
    source = _source(value)
    if len(source) > MAX_SOURCE_CHARACTERS:
        raise AthenaMedicationError("source_too_large")
    content_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    snapshot_hash = payload_hash(
        {
            "contract": "athena-medication-review-snapshot.v1",
            "scope_sha256": expected_scope.commitment(),
            "observation_sha256": expected_source_sha256,
            "patient_identity_sha256": expected_patient_identity_sha256,
            "source_content_sha256": content_hash,
            "completeness": "bounded_recorded_medication_section",
        }
    )
    if authorize_read(expected_scope) is not True:
        raise AthenaMedicationError("access_denied")
    return AthenaMedicationReviewSnapshot(value, source, content_hash, snapshot_hash)
