"""athena Preview FHIR medication history for the shared custody path (C8).

Uses the C7 ``AthenaFhirR4Adapter`` (mock transport + vault secret refs only) and
projects into the existing ``TebraFhirMedicationRead`` shape with athena vendor
contracts from C5. Refusals run before token mint or FHIR HTTP.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from cosmas_os.adapters.athena_fhir_r4 import (
    ATHENA_FHIR_R4_BASE_URL,
    AthenaFhirR4Adapter,
    AthenaFhirR4Error,
)
from cosmas_os.adapters.ehr_fhir_vendor import medication_history_contract
from cosmas_os.adapters.tebra_fhir_read import (
    MAX_PROJECTION_BYTES,
    MAX_ROWS,
    TebraFhirMedicationRead,
    TebraFhirPatient,
    TebraFhirReadError,
    TebraFhirScope,
    _concept,
    _id,
    _json,
    _patient,
    _project,
    _reference,
    _resource,
)
from cosmas_os.domain.hashing import canonical_json, payload_hash

_GATE_CODES = frozenset({
    "sandbox_flag_required",
    "real_data_required",
    "access_denied",
    "request_invalid",
    "scope_changed",
    "patient_changed",
    "response_invalid",
    "response_too_large",
    "too_many_results",
    "unsupported_record",
    "provider_rejected",
    "provider_throttled",
    "transport_unconfirmed",
    "connector_disabled",
})


def _map_adapter_error(exc: AthenaFhirR4Error) -> TebraFhirReadError:
    if exc.code in {"sandbox_flag_required", "real_data_required"}:
        return TebraFhirReadError(exc.code)  # type: ignore[arg-type]
    if exc.code in {"resource_unsupported", "unsupported_scope", "action_refused", "practice_override_refused"}:
        return TebraFhirReadError("unsupported_record")
    if exc.code in {"not_configured", "auth_unavailable", "synthetic_transport_required"}:
        return TebraFhirReadError("connector_disabled")
    if exc.code in {"off_origin_refused", "unknown_ehr_origin", "invalid_ehr_origin", "invalid_ehr_gate_flags"}:
        return TebraFhirReadError("request_invalid")
    return TebraFhirReadError("transport_unconfirmed")


def _require_ready(result, *, patient_changed: bool = False) -> tuple[Any, ...]:
    if getattr(result, "ok", False) is not True or getattr(result, "state", None) != "ready":
        state = getattr(result, "state", None)
        if state in {"timeout", "not_connected"}:
            raise TebraFhirReadError("transport_unconfirmed")
        if state == "throttled":
            raise TebraFhirReadError("provider_throttled")
        if state in {"expired", "wrong_practice"}:
            raise TebraFhirReadError("access_denied")
        if patient_changed or state in {"stale", "empty"}:
            raise TebraFhirReadError("patient_changed" if patient_changed else "response_invalid")
        raise TebraFhirReadError("provider_rejected")
    resources = getattr(result, "resources", ())
    if type(resources) is not tuple:
        raise TebraFhirReadError("response_invalid")
    return resources


def _resolve_medication(adapter: AthenaFhirR4Adapter, row: dict[str, Any], proofs: list[str]) -> dict[str, Any]:
    variants = [key for key in ("medicationCodeableConcept", "medicationReference") if key in row]
    if len(variants) != 1:
        raise TebraFhirReadError("response_invalid")
    if variants[0] == "medicationCodeableConcept":
        return {"code": row[variants[0]]}
    reference = row[variants[0]]
    if type(reference) is not dict or type(reference.get("reference")) is not str:
        raise TebraFhirReadError("response_invalid")
    target = reference["reference"]
    if target.startswith("#"):
        identifier = _id(target[1:])
        contained = row.get("contained", [])
        if type(contained) is not list or len(contained) > 25:
            raise TebraFhirReadError("response_invalid")
        matches = [item for item in contained if type(item) is dict and item.get("id") == identifier]
        if len(matches) != 1:
            raise TebraFhirReadError("response_invalid")
        return _resource(matches[0], "Medication", identifier)
    identifier = _reference(target, "Medication")
    med = adapter.read("Medication", identifier)
    resources = _require_ready(med)
    if len(resources) != 1:
        raise TebraFhirReadError("response_invalid")
    medication = _resource(resources[0], "Medication", identifier)
    proofs.append(payload_hash({
        "url": f"{ATHENA_FHIR_R4_BASE_URL}/Medication/{identifier}",
        "body": medication,
    }))
    return medication


def read_athena_fhir_medications(
    adapter: AthenaFhirR4Adapter,
    scope: TebraFhirScope,
    *,
    expected_patient: TebraFhirPatient,
    authorize: Callable[[], bool],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> TebraFhirMedicationRead:
    """One authorized patient medication page via C7; refuse before auth when gated."""

    if type(adapter) is not AthenaFhirR4Adapter or type(scope) is not TebraFhirScope:
        raise TebraFhirReadError("request_invalid")
    if type(expected_patient) is not TebraFhirPatient or not callable(authorize):
        raise TebraFhirReadError("request_invalid")
    scope.validate()
    if expected_patient.patient_id != scope.patient_id:
        raise TebraFhirReadError("patient_changed")

    def current() -> None:
        if authorize() is not True:
            raise TebraFhirReadError("access_denied")

    try:
        current()
        # Adapter guards origin/sandbox before minting a token or calling FHIR.
        patient_result = adapter.read("Patient", scope.patient_id)
        current()
        patient_rows = _require_ready(patient_result, patient_changed=True)
        if len(patient_rows) != 1:
            raise TebraFhirReadError("response_invalid")
        patient = _patient(patient_rows[0], scope)
        if (patient.patient_id != expected_patient.patient_id
                or patient.identity_json != expected_patient.identity_json
                or patient.identity_sha256 != expected_patient.identity_sha256):
            raise TebraFhirReadError("patient_changed")
        proofs = [payload_hash({
            "url": f"{ATHENA_FHIR_R4_BASE_URL}/Patient/{scope.patient_id}",
            "body": _json(patient.identity_json.encode("utf-8")),
        })]
        current()
        search = adapter.search(
            "MedicationRequest",
            {
                "patient": scope.patient_id,
                "intent": "order,plan",
                "_count": "25",
            },
            follow_paging=False,
        )
        current()
        rows = list(_require_ready(search))
        if len(rows) > MAX_ROWS:
            raise TebraFhirReadError("too_many_results")
        more = bool(getattr(search, "more_available", False))
        projected = []
        for row in rows:
            _resource(row, "MedicationRequest")
            subject = row.get("subject")
            if type(subject) is not dict:
                raise TebraFhirReadError("response_invalid")
            if _reference(subject.get("reference"), "Patient") != scope.patient_id:
                raise TebraFhirReadError("scope_changed")
            # Touch concept helper so malformed codes refuse early.
            if "medicationCodeableConcept" in row:
                _concept(row["medicationCodeableConcept"])
            medication = _resolve_medication(adapter, row, proofs)
            projected.append(_project(row, medication, scope.patient_id))
            proofs.append(payload_hash({
                "url": f"{ATHENA_FHIR_R4_BASE_URL}/MedicationRequest/{row['id']}",
                "body": row,
            }))
            current()
        observed = now()
        if type(observed) is not datetime or observed.utcoffset() is None:
            raise TebraFhirReadError("response_invalid")
        total = getattr(search, "reported_total", None)
        if total is None and hasattr(search, "resources"):
            total = len(rows) if not more else None
        if total is not None and (type(total) is not int or not len(projected) <= total <= 2147483647):
            raise TebraFhirReadError("response_invalid")
        coverage = "more_rows_available" if more else "returned_page_only"
        content = {
            "scope_sha256": scope.commitment("athena"),
            "patient": asdict(patient),
            "rows": [asdict(item) for item in projected],
            "observed_at": observed.isoformat(),
            "coverage": coverage,
            "reported_total": total,
            "warnings": (),
            "provider_sources": tuple(proofs),
        }
        if len(canonical_json(content).encode()) > MAX_PROJECTION_BYTES:
            raise TebraFhirReadError("response_too_large")
        current()
        return TebraFhirMedicationRead(
            scope,
            patient,
            observed,
            tuple(projected),
            coverage,
            total,
            (),
            payload_hash({"contract": medication_history_contract("athena"), **content}),
            tuple(proofs),
        )
    except TebraFhirReadError:
        raise
    except AthenaFhirR4Error as exc:
        raise _map_adapter_error(exc) from None
    except Exception:
        raise TebraFhirReadError("transport_unconfirmed") from None
