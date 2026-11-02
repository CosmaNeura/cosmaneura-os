"""PHI-free EHR read audit and per-practice allowed-resource scope.

Standalone module for the shared EHR read path on main today. It does not
import C1's ``plugins.ehr`` package.

Once draft PR #258 (``grok/ehr-connector-contract``) merges, pass these
adapters into ``DeclaredEhrConnector.allow_read``:

- ``SessionPracticeScopeConfig`` satisfies ``PracticeScopeConfig``
  (``allow_practice``)
- ``SessionPhiFreeReadAudit`` satisfies ``PhiFreeReadAudit``
  (``record_read``)

C1 connector resource names (``appointments``, ``patients``, …) map to the
FHIR allow-list stored here. Audit rows and log lines never carry names, DOB,
MRN, free text, or response bodies. Vendor request IDs are hashed.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.log_scrub import scrub_structure, scrub_text
from cosmas_os.models import AuditEvent

logger = logging.getLogger("cosmas_os.ehr_read_audit")

# Default covers today's live EHR reads (appointments, patients, allergies,
# medications, problems / conditions, and Encounter for visit prep). Labs map
# to Observation and stay off the default; a practice that enables labs must
# allow Observation explicitly.
DEFAULT_ALLOWED_RESOURCES: frozenset[str] = frozenset(
    {
        "Patient",
        "Appointment",
        "Encounter",
        "AllergyIntolerance",
        "MedicationRequest",
        "Condition",
    }
)

KNOWN_RESOURCE_TYPES: frozenset[str] = frozenset(
    {
        *DEFAULT_ALLOWED_RESOURCES,
        "Observation",
        "DocumentReference",
        "DiagnosticReport",
        "Immunization",
        "Coverage",
        "Practitioner",
        "Location",
        "Organization",
        "Medication",
    }
)

# C1 connector ResourceType names → FHIR types used in the practice allow-list.
# Keep this table aligned with plugins/ehr/manifest.py once #258 merges.
CONNECTOR_RESOURCE_TO_FHIR: dict[str, str] = {
    "appointments": "Appointment",
    "patients": "Patient",
    "medications": "MedicationRequest",
    "allergies": "AllergyIntolerance",
    "problems": "Condition",
    "labs": "Observation",
    "visit": "Encounter",
}

FHIR_TO_CONNECTOR_RESOURCE: dict[str, str] = {
    fhir: name for name, fhir in CONNECTOR_RESOURCE_TO_FHIR.items()
}

# Existing custody kinds → FHIR resource types for scope + audit.
KIND_RESOURCE_TYPES: dict[str, str] = {
    "window": "Appointment",
    "verify": "Patient",
    "problems": "Condition",
    "medications": "MedicationRequest",
    "fhir_patients": "Patient",
    "fhir_medications": "MedicationRequest",
    "core_patients": "Patient",
    "core_allergies": "AllergyIntolerance",
    "core_medications": "MedicationRequest",
    "lab_reports": "Observation",
    "lab_report": "Observation",
}

EVENT_TYPE = "workspace.ehr_read"
AGGREGATE_TYPE = "ehr_read_connection"
FORBIDDEN_DETAIL_KEYS = frozenset(
    {
        "name",
        "patient_name",
        "first_name",
        "last_name",
        "full_name",
        "dob",
        "date_of_birth",
        "birth_date",
        "birthdate",
        "mrn",
        "medical_record_number",
        "response",
        "response_body",
        "request_body",
        "body",
        "note",
        "note_text",
        "payload",
        "practice_name",
        "vendor_request_id",
    }
)


def hash_vendor_request_id(value: str | None) -> str | None:
    """Hash a vendor request id. Never store the raw id."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def connector_resource_to_fhir(resource: str) -> str | None:
    """Map a C1 connector resource name to the FHIR allow-list type."""
    name = str(resource).strip()
    if name in KNOWN_RESOURCE_TYPES:
        return name
    return CONNECTOR_RESOURCE_TO_FHIR.get(name)


def resource_type_for_kind(kind: str) -> str:
    try:
        return KIND_RESOURCE_TYPES[kind]
    except KeyError as error:
        raise ws.WorkspaceError("unsupported", 404) from error


def normalize_resources(resources: Iterable[str] | None) -> frozenset[str]:
    if resources is None:
        return DEFAULT_ALLOWED_RESOURCES
    cleaned: set[str] = set()
    for item in resources:
        text = str(item).strip()
        if not text:
            continue
        fhir = connector_resource_to_fhir(text)
        if fhir is None:
            raise ws.WorkspaceError("unsupported", 404)
        cleaned.add(fhir)
    unknown = cleaned - KNOWN_RESOURCE_TYPES
    if unknown:
        raise ws.WorkspaceError("unsupported", 404)
    if not cleaned:
        return DEFAULT_ALLOWED_RESOURCES
    return frozenset(cleaned)


def allowed_resources(session, box_id: str, connection_id: str) -> frozenset[str]:
    """Return the practice allow-list, or the product default when unset."""
    from cosmas_os.ehr_read_models import EhrPracticeResourceScope

    row = session.scalar(
        select(EhrPracticeResourceScope).where(
            EhrPracticeResourceScope.box_id == str(box_id),
            EhrPracticeResourceScope.connection_id == str(connection_id),
        )
    )
    if row is None:
        return DEFAULT_ALLOWED_RESOURCES
    return normalize_resources(row.allowed_resources)


def upsert_allowed_resources(
    session,
    *,
    box_id: str,
    connection_id: str,
    resources: Iterable[str],
) -> frozenset[str]:
    """Persist a practice allow-list. Additive config only; never stores PHI."""
    from cosmas_os.ehr_read_models import EhrPracticeResourceScope

    allowed = normalize_resources(resources)
    row = session.scalar(
        select(EhrPracticeResourceScope).where(
            EhrPracticeResourceScope.box_id == str(box_id),
            EhrPracticeResourceScope.connection_id == str(connection_id),
        )
    )
    values = sorted(allowed)
    if row is None:
        session.add(
            EhrPracticeResourceScope(
                id=str(uuid4()),
                box_id=str(box_id),
                connection_id=str(connection_id),
                allowed_resources=values,
            )
        )
    else:
        row.allowed_resources = values
    session.flush()
    return allowed


def ensure_resource_allowed(
    session,
    *,
    box_id: str,
    connection_id: str,
    resource_type: str,
    actor_principal_id: str,
    vendor: str,
    practice_id: str | None = None,
    request_hash: str | None = None,
    vendor_request_id: str | None = None,
    audit: bool = True,
) -> str:
    """Refuse a resource outside the practice allow-list with plain `unsupported`."""
    resource = connector_resource_to_fhir(str(resource_type).strip()) or ""
    allowed = (
        allowed_resources(session, box_id, connection_id)
        if resource in KNOWN_RESOURCE_TYPES
        else frozenset()
    )
    if resource not in KNOWN_RESOURCE_TYPES or resource not in allowed:
        if audit:
            record_ehr_read_audit(
                session,
                box_id=box_id,
                actor_principal_id=actor_principal_id,
                connection_id=connection_id,
                practice_id=practice_id,
                vendor=vendor,
                resource_type=resource or str(resource_type).strip() or "unknown",
                result_count=0,
                outcome="unsupported",
                request_hash=request_hash,
                vendor_request_id=vendor_request_id,
            )
            session.commit()
        raise ws.WorkspaceError("unsupported", 404)
    return resource


def result_count_from_payload(payload: Mapping[str, Any] | None) -> int:
    """Count returned items without reading clinical content."""
    if not isinstance(payload, Mapping):
        return 0
    public = payload.get("public")
    if not isinstance(public, Mapping):
        return 0
    for key in ("items", "patients", "allergies", "medications", "problems", "reports"):
        value = public.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return len(value)
    item = public.get("item")
    if isinstance(item, Mapping):
        for key in ("allergies", "medications", "problems", "reports"):
            nested = item.get(key)
            if isinstance(nested, Mapping):
                rows = nested.get("items")
                if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)):
                    return len(rows)
            if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes, bytearray)):
                return len(nested)
    return 0


def _safe_detail(detail: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in detail.items():
        if key in FORBIDDEN_DETAIL_KEYS:
            continue
        if value is None:
            continue
        if isinstance(value, str) and key.endswith("_hash"):
            cleaned[key] = value
        elif isinstance(value, str | int | bool):
            cleaned[key] = value
    # Defense in depth: run the shared scrubber over the structured detail.
    scrubbed = scrub_structure(cleaned)
    if not isinstance(scrubbed, dict):
        return {}
    return {key: value for key, value in scrubbed.items() if key not in FORBIDDEN_DETAIL_KEYS}


def record_ehr_read_audit(
    session,
    *,
    box_id: str,
    actor_principal_id: str,
    connection_id: str,
    vendor: str,
    resource_type: str,
    result_count: int,
    outcome: str,
    practice_id: str | None = None,
    request_hash: str | None = None,
    vendor_request_id: str | None = None,
    request_body: Mapping[str, Any] | None = None,
    target: str | None = None,
    connector_resource: str | None = None,
) -> AuditEvent:
    """Write one PHI-free AuditEvent for an EHR read attempt."""
    digest = request_hash
    if digest is None and request_body is not None:
        digest = payload_hash(dict(request_body))
    detail = _safe_detail(
        {
            "connection_id": str(connection_id),
            "practice_id": str(practice_id) if practice_id is not None else None,
            "vendor": str(vendor),
            "resource_type": str(resource_type),
            "connector_resource": connector_resource,
            "target": target,
            "result_count": int(result_count),
            "request_hash": digest,
            "vendor_request_id_hash": hash_vendor_request_id(vendor_request_id),
        }
    )
    event = AuditEvent(
        box_id=str(box_id),
        aggregate_type=AGGREGATE_TYPE,
        aggregate_id=str(connection_id),
        event_type=EVENT_TYPE,
        actor_principal_id=str(actor_principal_id),
        outcome=str(outcome),
        payload_hash=digest,
        detail=detail,
    )
    session.add(event)
    logger.info(
        scrub_text(
            f"ehr_read audit vendor={vendor} resource_type={resource_type} "
            f"outcome={outcome} result_count={int(result_count)} connection_id={connection_id}"
        )
    )
    return event


def audit_stored_read(session, read, payload: Mapping[str, Any], *, outcome: str = "ok") -> AuditEvent:
    """Audit a successful custody store for any vendor that uses ehr_reads._store."""
    from cosmas_os.ehr_read_models import EhrReadBinding

    kind = getattr(read, "kind", None) or (read.request_json or {}).get("action")
    resource = resource_type_for_kind(str(kind))
    request = getattr(read, "request_json", None) or {}
    vendor_name = request.get("provider") or "elation"
    binding = session.get(EhrReadBinding, read.binding_id)
    if binding is not None:
        vendor_name = binding.vendor
    return record_ehr_read_audit(
        session,
        box_id=read.box_id,
        actor_principal_id=read.owner_id,
        connection_id=read.connection_id,
        practice_id=read.practice_id,
        vendor=vendor_name,
        resource_type=resource,
        connector_resource=FHIR_TO_CONNECTOR_RESOURCE.get(resource),
        result_count=result_count_from_payload(payload),
        outcome=outcome,
        request_hash=read.request_hash,
    )


@dataclass(slots=True)
class SessionPracticeScopeConfig:
    """C6 practice scope adapter shaped for C1's ``PracticeScopeConfig`` hook.

    ``practice_ref`` is the EHR connection id for this practice. ``resource``
    may be a C1 connector name (``appointments``) or a FHIR type (``Appointment``).
    """

    session: Any
    box_id: str

    def allow_practice(
        self,
        *,
        vendor_id: str,
        practice_ref: str,
        resource: str,
    ) -> bool:
        del vendor_id  # Vendor is authenticated separately; scope is per practice/connection.
        if type(practice_ref) is not str or not practice_ref.strip():
            return False
        fhir = connector_resource_to_fhir(resource)
        if fhir is None:
            return False
        return fhir in allowed_resources(self.session, self.box_id, practice_ref.strip())


@dataclass(slots=True)
class SessionPhiFreeReadAudit:
    """C6 audit adapter shaped for C1's ``PhiFreeReadAudit`` hook.

    Bound to one box and actor. Never accepts chart payload bodies — only the
    keyword fields from the C1 hook (plus optional result_count on this class
    via ``default_result_count`` for gate-time audits, which is always 0).
    """

    session: Any
    box_id: str
    actor_principal_id: str
    commit: bool = False
    default_result_count: int = 0

    def record_read(
        self,
        *,
        vendor_id: str,
        resource: str,
        target: str,
        practice_ref: str | None,
        outcome: str,
    ) -> None:
        connection_id = (practice_ref or "").strip() or str(uuid4())
        fhir = connector_resource_to_fhir(resource) or str(resource)
        connector_name = resource if resource in CONNECTOR_RESOURCE_TO_FHIR else FHIR_TO_CONNECTOR_RESOURCE.get(fhir)
        record_ehr_read_audit(
            self.session,
            box_id=self.box_id,
            actor_principal_id=self.actor_principal_id,
            connection_id=connection_id,
            practice_id=None,
            vendor=str(vendor_id),
            resource_type=fhir,
            connector_resource=connector_name,
            target=str(target),
            result_count=int(self.default_result_count),
            outcome=str(outcome),
        )
        if self.commit:
            self.session.commit()
