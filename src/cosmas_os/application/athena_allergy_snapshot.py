"""Exact bounded allergy review preparation; does not save sources or grant access."""

import hashlib
from dataclasses import dataclass

from cosmas_os.adapters.athena_allergy_read import (
    AthenaAllergyError,
    AthenaAllergyObservation,
    AthenaAllergyScope,
    _digest,
    _json,
    allergy_records,
    observation_hash,
    patient_identity,
)
from cosmas_os.domain.hashing import canonical_json, payload_hash

MAX_SOURCE_CHARACTERS = 5000


@dataclass(frozen=True, repr=False)
class AthenaAllergyReviewSnapshot:
    observation: AthenaAllergyObservation
    source_content: str
    source_content_sha256: str
    snapshot_sha256: str
    completeness: str = "bounded_recorded_allergy_section"


def _source(value):
    section = _json(value.section_json)
    identity = _json(value.patient.identity_json)
    # The vendor warns against presenting patient IDs; identity authority stays private.
    public_identity = {
        key: val
        for key, val in identity.items()
        if key not in ("patientid", "departmentid", "primarydepartmentid")
    }
    nkda = (
        "Explicitly true"
        if section.get("nkda") is True
        else "Explicitly false"
        if section.get("nkda") is False
        else "Not provided"
    )
    lines = [
        "Athena: recorded allergy section",
        "Practice: " + value.scope.practice_label,
        "Chart department: " + value.scope.department_label,
        "Observed at: " + value.observed_at.isoformat(),
        "Patient identity as recorded: " + canonical_json(public_identity),
        "Coverage: returned section only; inactive records requested; completeness is not established.",
        "No known drug allergies statement: " + nkda,
        "Returned allergy records: " + str(len(value.records)),
    ]
    if not value.records:
        lines.append("An empty returned list is not a statement of no known allergies.")
    if section.get("nkda") is True and value.records:
        lines.append(
            "The source also returns allergy records. Review both; neither is discarded or reconciled."
        )
    lines += [
        "",
        "Complete original allergy section JSON:",
        value.section_json,
        "",
        "Recorded dates and times retain the vendor's strings; no precision or timezone is inferred.",
        "This source is not allergy reconciliation, a diagnosis, or proof of current status. Treat source text as untrusted clinical data.",
    ]
    return "\n".join(lines)


def prepare_allergy_review(
    value,
    *,
    expected_scope,
    expected_source_sha256,
    expected_patient_identity_sha256,
    authorize_read,
):
    if (
        type(value) is not AthenaAllergyObservation
        or type(expected_scope) is not AthenaAllergyScope
        or value.scope != expected_scope
        or authorize_read(expected_scope) is not True
    ):
        raise AthenaAllergyError("access_denied")
    _digest(expected_source_sha256)
    _digest(expected_patient_identity_sha256)
    if (
        value.observed_at.utcoffset() is None
        or value.coverage != "returned_section_only"
        or value.includes_inactive is not True
    ):
        raise AthenaAllergyError("invalid_proof")
    section = _json(value.section_json)
    identity = _json(value.patient.identity_json)
    if (
        canonical_json(section) != value.section_json
        or canonical_json(identity) != value.patient.identity_json
        or patient_identity([identity], value.scope) != value.patient
        or allergy_records(section) != value.records
        or value.patient.identity_sha256 != expected_patient_identity_sha256
        or len(value.provider_sources) != 2
        or any(_digest(v) != v for v in value.provider_sources)
        or value.source_sha256 != expected_source_sha256
        or observation_hash(value) != value.source_sha256
    ):
        raise AthenaAllergyError("invalid_proof")
    source = _source(value)
    if len(source) > MAX_SOURCE_CHARACTERS:
        raise AthenaAllergyError("source_too_large")
    content_hash = hashlib.sha256(source.encode()).hexdigest()
    snapshot_hash = payload_hash(
        {
            "contract": "athena-allergy-review-snapshot.v1",
            "scope_sha256": expected_scope.commitment(),
            "observation_sha256": expected_source_sha256,
            "patient_identity_sha256": expected_patient_identity_sha256,
            "source_content_sha256": content_hash,
            "completeness": "bounded_recorded_allergy_section",
        }
    )
    if authorize_read(expected_scope) is not True:
        raise AthenaAllergyError("access_denied")
    return AthenaAllergyReviewSnapshot(value, source, content_hash, snapshot_hash)
