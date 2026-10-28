"""Private, bounded Tebra review preparation; no human approval or source admission.

This consumes the synthetic reader's exact projection and its server-pinned
commitments. It does not acquire authorization, establish SOAP/FHIR identity,
persist a source, or register a runtime. The reader's pure validators are reused
so this slice does not create a competing FHIR interpretation.
"""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

from cosmas_os.adapters.tebra_fhir_read import (
    MAX_PROJECTION_BYTES,
    MAX_ROWS,
    TebraFhirMedication,
    TebraFhirMedicationRead,
    TebraFhirPatient,
    TebraFhirReadError,
    TebraFhirScope,
    _date,
    _id,
    _json,
    _patient,
    _project,
    _reference,
    _resource,
)
from cosmas_os.domain.hashing import canonical_json, payload_hash

SOURCE_LIMIT = 5000
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_CONTEXT = frozenset(("statusReason", "requester", "encounter", "category", "note", "reasonCode", "reasonReference",
    "courseOfTherapyType", "dispenseRequest", "substitution", "priorPrescription", "basedOn", "groupIdentifier",
    "insurance", "supportingInformation", "detectedIssue", "eventHistory"))
ErrorCode = Literal["snapshot_invalid", "snapshot_mismatch", "snapshot_too_large", "access_denied", "snapshot_unavailable"]


class TebraFhirSnapshotError(Exception):
    def __init__(self, code: ErrorCode):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class TebraRecordedDate:
    state: Literal["recorded", "not_provided"]
    value: str | None


@dataclass(frozen=True, repr=False)
class TebraMedicationReviewRecord:
    """Recorded values for a future review screen, without inferred current use."""

    record: TebraFhirMedication
    authored_date: TebraRecordedDate
    instructions_state: Literal["recorded", "not_provided"]


@dataclass(frozen=True, repr=False)
class TebraMedicationReviewSnapshot:
    """Preparing this value never means a human reviewed or admitted its source."""

    observation: TebraFhirMedicationRead
    completeness: Literal["bounded_recorded_history"]
    patient_birth_date: TebraRecordedDate
    records: tuple[TebraMedicationReviewRecord, ...]
    source_content: str
    source_content_sha256: str
    snapshot_sha256: str


def _digest(value):
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise TebraFhirSnapshotError("snapshot_invalid")
    return value


def _load(raw, kind):
    if type(raw) is not str or len(raw.encode("utf-8")) > MAX_PROJECTION_BYTES:
        raise TebraFhirSnapshotError("snapshot_invalid")
    # The reader parser bounds/validates JSON and refuses all unqualified modifiers.
    value = _json('{"value":'+raw+'}')["value"]
    if type(value) is not kind or canonical_json(value) != raw:
        raise TebraFhirSnapshotError("snapshot_invalid")
    return value


def _validated_record(row, patient_id):
    if type(row) is not TebraFhirMedication or row.patient_id != patient_id:
        raise TebraFhirSnapshotError("snapshot_mismatch")
    _id(row.record_id)
    choice = _load(row.request_medication_json, dict)
    if set(choice) not in ({"medicationCodeableConcept"}, {"medicationReference"}):
        raise TebraFhirSnapshotError("snapshot_invalid")
    medication = _load(row.medication_json, dict)
    if "medicationCodeableConcept" in choice:
        if medication != {"code": choice["medicationCodeableConcept"]}:
            raise TebraFhirSnapshotError("snapshot_mismatch")
    else:
        reference = choice["medicationReference"]
        if type(reference) is not dict or type(reference.get("reference")) is not str:
            raise TebraFhirSnapshotError("snapshot_invalid")
        target = reference["reference"]
        identifier = _id(target[1:]) if target.startswith("#") else _reference(target, "Medication")
        _resource(medication, "Medication", identifier)
    context = _load(row.context_json, dict)
    if not set(context) <= _CONTEXT:
        raise TebraFhirSnapshotError("snapshot_invalid")
    # Reconstitute only the already-projected request. No resource references are followed.
    request = {"id": row.record_id, "status": row.status, "intent": row.intent,
        "authoredOn": row.authored_on, **choice, **context}
    if row.do_not_perform is not None:
        request["doNotPerform"] = row.do_not_perform
    if row.reported_json is not None:
        reported = _load(row.reported_json, dict)
        if set(reported) not in ({"reportedBoolean"}, {"reportedReference"}):
            raise TebraFhirSnapshotError("snapshot_invalid")
        request.update(reported)
    if row.dosage_instructions_json is not None:
        request["dosageInstruction"] = _load(row.dosage_instructions_json, list)
    if _project(request, medication, patient_id) != row:
        raise TebraFhirSnapshotError("snapshot_mismatch")
    return TebraMedicationReviewRecord(row, TebraRecordedDate("recorded", row.authored_on),
        "recorded" if row.dosage_instructions_json is not None else "not_provided")


def _validate_observation(observation, scope, source_sha256, identity_sha256):
    if type(observation) is not TebraFhirMedicationRead or observation.scope != scope:
        raise TebraFhirSnapshotError("snapshot_mismatch")
    if (type(observation.patient) is not TebraFhirPatient or observation.patient.patient_id != scope.patient_id
            or observation.source_sha256 != source_sha256 or observation.patient.identity_sha256 != identity_sha256):
        raise TebraFhirSnapshotError("snapshot_mismatch")
    identity = _load(observation.patient.identity_json, dict)
    if _patient(identity, scope) != observation.patient:
        raise TebraFhirSnapshotError("snapshot_mismatch")
    if (type(observation.rows) is not tuple or len(observation.rows) > MAX_ROWS
            or type(observation.observed_at) is not datetime or observation.observed_at.utcoffset() is None
            or observation.coverage not in ("more_rows_available", "returned_page_only")):
        raise TebraFhirSnapshotError("snapshot_invalid")
    total = observation.reported_total
    if total is not None and (type(total) is not int or not len(observation.rows) <= total <= 2147483647):
        raise TebraFhirSnapshotError("snapshot_invalid")
    if (type(observation.warnings) is not tuple or len(observation.warnings) > 1500
            or any(type(code) is not str or not 1 <= len(code) <= 64
                or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in code) for code in observation.warnings)):
        raise TebraFhirSnapshotError("snapshot_invalid")
    if type(observation.provider_sources) is not tuple or not 2 <= len(observation.provider_sources) <= MAX_ROWS+2:
        raise TebraFhirSnapshotError("snapshot_invalid")
    for proof in observation.provider_sources:
        _digest(proof)
    records = tuple(_validated_record(row, scope.patient_id) for row in observation.rows)
    if len({item.record.record_id for item in records}) != len(records):
        raise TebraFhirSnapshotError("snapshot_invalid")
    content = {"scope_sha256": scope.commitment(), "patient": asdict(observation.patient),
        "rows": [asdict(row) for row in observation.rows], "observed_at": observation.observed_at.isoformat(),
        "coverage": observation.coverage, "reported_total": total, "warnings": observation.warnings,
        "provider_sources": observation.provider_sources}
    if len(canonical_json(content).encode("utf-8")) > MAX_PROJECTION_BYTES:
        raise TebraFhirSnapshotError("snapshot_too_large")
    if payload_hash({"contract": "tebra-fhir-medication-history.v1", **content}) != source_sha256:
        raise TebraFhirSnapshotError("snapshot_mismatch")
    birth = TebraRecordedDate("recorded", _date(identity["birthDate"])) if "birthDate" in identity else TebraRecordedDate("not_provided", None)
    return records, birth


def _source(observation, records):
    coverage = ("More rows are available; only this page was read." if observation.coverage == "more_rows_available"
        else "Returned page only; completeness is not established.")
    lines = ["Tebra medication records (bounded synthetic snapshot)",
        "Patient identity: "+observation.patient.identity_json,
        "Observed: "+observation.observed_at.isoformat(), "Coverage: "+coverage,
        f"Returned records: {len(records)}; reported total: {observation.reported_total if observation.reported_total is not None else 'not provided'}.",
        "Unlisted optional fields were not provided. Dates keep their recorded precision; no timezone or current use is inferred.",
        "JSON sections preserve codes, qualifiers and decoded instruction/string contents; request details do not establish dispensing."]
    if observation.warnings:
        lines.append("Provider warning codes: "+canonical_json(list(observation.warnings)))
    for index, review in enumerate(records, 1):
        row = review.record
        name = json.dumps(row.medication_name, ensure_ascii=False) if row.medication_name is not None else "No unambiguous recorded medication name"
        lines.extend(["", f"Record {index}: {name}",
            "Record ID: "+row.record_id, "Recorded status: "+row.status, "Recorded intent: "+row.intent,
            "Authored date/time: "+row.authored_on,
            "Do-not-perform flag: "+("not provided" if row.do_not_perform is None else str(row.do_not_perform).lower()),
            "Reported information: "+(row.reported_json if row.reported_json is not None else "not provided"),
            "Original medication choice: "+row.request_medication_json,
            "Resolved medication: "+row.medication_json,
            "Dose instructions: "+(row.dosage_instructions_json if row.dosage_instructions_json is not None else "not provided"),
            "Other recorded request details: "+row.context_json])
    if not records:
        lines.extend(["", "No medication records returned; this does not establish absence of medications."])
    lines.extend(["", "These are recorded medication requests/history, not a reconciled current list or proof of transmission, dispensing or use.",
        "This snapshot does not prescribe or update the EHR. Preparing it does not establish human approval or source admission."])
    return "\n".join(lines)


def prepare_medication_review(observation: TebraFhirMedicationRead, *, expected_scope: TebraFhirScope,
        expected_source_sha256: str, expected_patient_identity_sha256: str,
        authorize_read: Callable[[TebraFhirScope], bool]) -> TebraMedicationReviewSnapshot:
    """Prepare exact review content against trusted server pins; never grants access.

    The application must obtain the expected scope/hashes from current server-owned
    custody, not from a client asserting its own authorization or selected patient.
    Actual review, SQL custody, recovery and Chief admission remain separate work.
    """
    try:
        if type(expected_scope) is not TebraFhirScope or not callable(authorize_read):
            raise TebraFhirSnapshotError("snapshot_invalid")
        expected_scope.validate()
        if authorize_read(expected_scope) is not True:
            raise TebraFhirSnapshotError("access_denied")
        _digest(expected_source_sha256)
        _digest(expected_patient_identity_sha256)
        records, birth = _validate_observation(observation, expected_scope, expected_source_sha256, expected_patient_identity_sha256)
        source = _source(observation, records)
        if len(source) > SOURCE_LIMIT:
            raise TebraFhirSnapshotError("snapshot_too_large")
        content_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
        review_sha256 = payload_hash({"contract": "tebra-fhir-review-snapshot.v1", "scope_sha256": expected_scope.commitment(),
            "observation_sha256": expected_source_sha256, "patient_identity_sha256": expected_patient_identity_sha256,
            "source_content_sha256": content_sha256, "completeness": "bounded_recorded_history"})
        if authorize_read(expected_scope) is not True:
            raise TebraFhirSnapshotError("access_denied")
        return TebraMedicationReviewSnapshot(observation, "bounded_recorded_history", birth, records, source, content_sha256, review_sha256)
    except TebraFhirSnapshotError:
        raise
    except TebraFhirReadError as error:
        raise TebraFhirSnapshotError("snapshot_too_large" if error.code in ("response_too_large", "too_many_results") else "snapshot_invalid") from None
    except Exception:
        raise TebraFhirSnapshotError("snapshot_unavailable") from None
