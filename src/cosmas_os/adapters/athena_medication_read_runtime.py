"""Independent synthetic medication grants; no Core or schedule authority is inferred."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal
from uuid import UUID

import httpx

from cosmas_os.adapters.athena_medication_read import (
    ORIGINS,
    AthenaMedicationError,
    AthenaMedicationReader,
    AthenaMedicationScope,
    _id,
    _text,
    clinical_loads,
    patient_identity,
)
from cosmas_os.application.athena_medication_snapshot import (
    AthenaMedicationReviewSnapshot,
    prepare_medication_review,
)
from cosmas_os.domain.hashing import payload_hash


@dataclass(frozen=True, repr=False)
class AthenaMedicationConnectionScope:
    box_id: UUID
    owner_id: UUID
    account_id: UUID
    connection_id: UUID
    credential_generation: UUID
    practice_id: str
    practice_label: str
    environment: Literal["preview", "production"] = "preview"
    clinical_scope: Literal["medications"] = "medications"

    def validate(self):
        if (any(type(v) is not UUID for v in (self.box_id, self.owner_id, self.account_id,
                self.connection_id, self.credential_generation)) or self.environment not in ORIGINS or self.clinical_scope != "medications"):
            raise ValueError("invalid_athena_medication_connection")
        _id(self.practice_id)
        if not _text(self.practice_label, 200).strip():
            raise ValueError("invalid_athena_medication_connection")

    def commitment(self):
        self.validate()
        return payload_hash({"contract": "athena-medication-connection-scope.v1", "origin": ORIGINS[self.environment],
            **{k: str(v) if type(v) is UUID else v for k, v in asdict(self).items()}})


@dataclass(frozen=True, repr=False)
class AthenaMedicationAuthorizedPatient:
    grant_id: UUID
    connection_scope: AthenaMedicationConnectionScope
    workspace_id: UUID
    patient_link_id: UUID
    department_id: str
    department_label: str
    patient_id: str
    authorization_sha256: str
    identity_json: str
    identity_sha256: str

    def read_scope(self):
        if type(self.connection_scope) is not AthenaMedicationConnectionScope:
            raise ValueError("invalid_athena_medication_grant")
        self.connection_scope.validate()
        c = self.connection_scope
        return AthenaMedicationScope(c.box_id, c.owner_id, c.account_id, c.connection_id, c.credential_generation,
            self.workspace_id, self.patient_link_id, c.practice_id, self.department_id, self.patient_id,
            c.practice_label, self.department_label, self.authorization_sha256, c.environment)

    def validate(self):
        if (any(type(v) is not UUID for v in (self.grant_id, self.workspace_id, self.patient_link_id))
                or type(self.identity_json) is not str or len(self.identity_json.encode()) > 16384):
            raise ValueError("invalid_athena_medication_grant")
        patient = patient_identity([clinical_loads(self.identity_json)], self.read_scope())
        if patient.identity_json != self.identity_json or patient.identity_sha256 != self.identity_sha256:
            raise ValueError("invalid_athena_medication_grant")

    def commitment(self):
        self.validate()
        return payload_hash({"contract": "athena-medication-patient-grant.v1", "grant_id": str(self.grant_id),
            "scope_sha256": self.read_scope().commitment(), "patient_identity_sha256": self.identity_sha256})


class SyntheticAthenaMedicationReads:
    transport_mode = "mock"
    protocol = "core"
    clinical_scope = "medications"

    def __init__(self, scopes: tuple[AthenaMedicationConnectionScope, ...], patients: tuple[AthenaMedicationAuthorizedPatient, ...],
            transport: httpx.MockTransport, *, enabled: Callable[[], bool]):
        if (type(scopes) is not tuple or not 1 <= len(scopes) <= 20
                or any(type(scope) is not AthenaMedicationConnectionScope for scope in scopes)
                or type(patients) is not tuple or len(patients) > 500
                or any(type(patient) is not AthenaMedicationAuthorizedPatient for patient in patients)
                or type(transport) is not httpx.MockTransport or not callable(enabled)):
            raise ValueError("explicit_synthetic_athena_medication_installation_required")
        try:
            if len({scope.commitment() for scope in scopes}) != len(scopes):
                raise ValueError
            seen, contexts = set(), {}
            for patient in patients:
                patient.validate()
                if patient.connection_scope not in scopes or patient.grant_id in seen:
                    raise ValueError
                seen.add(patient.grant_id)
                context = (patient.connection_scope.commitment(), patient.workspace_id, patient.patient_link_id)
                ids = contexts.setdefault(context, set())
                identity = (patient.department_id, patient.patient_id)
                if identity in ids or len(ids) >= 25:
                    raise ValueError
                ids.add(identity)
        except Exception:
            raise ValueError("explicit_synthetic_athena_medication_installation_required") from None
        self._scopes, self._patients, self._transport, self._enabled = scopes, patients, transport, enabled

    def current(self, scope):
        try:
            return type(scope) is AthenaMedicationConnectionScope and self._enabled() is True and scope in self._scopes
        except Exception:
            return False

    def current_patient(self, patient):
        return (type(patient) is AthenaMedicationAuthorizedPatient and self.current(patient.connection_scope)
            and patient in self._patients)

    def patient_candidates(self, scope, workspace_id, patient_link_id, *, authorize):
        if type(workspace_id) is not UUID or type(patient_link_id) is not UUID or not callable(authorize):
            raise AthenaMedicationError("invalid_scope")
        if not self.current(scope) or authorize() is not True or not self.current(scope):
            raise AthenaMedicationError("access_denied")
        selected = tuple(patient for patient in self._patients if patient.connection_scope == scope
            and patient.workspace_id == workspace_id and patient.patient_link_id == patient_link_id)
        if authorize() is not True or not self.current(scope):
            raise AthenaMedicationError("access_denied")
        return selected

    def medications(self, scope, patient, *, authorize) -> AthenaMedicationReviewSnapshot:
        if not callable(authorize):
            raise AthenaMedicationError("invalid_scope")
        def current():
            return (self.current(scope) and self.current_patient(patient) and patient.connection_scope == scope
                and authorize() is True and self.current(scope) and self.current_patient(patient))
        if not current():
            raise AthenaMedicationError("access_denied")
        read_scope = patient.read_scope()
        observation = AthenaMedicationReader(read_scope, self._transport,
            expected_identity_sha256=patient.identity_sha256, enabled=lambda: self.current(scope),
            authorize=lambda selected: selected == read_scope and current()).read()
        review = prepare_medication_review(observation, expected_scope=read_scope,
            expected_source_sha256=observation.source_sha256, expected_patient_identity_sha256=patient.identity_sha256,
            authorize_read=lambda selected: selected == read_scope and current())
        if not current():
            raise AthenaMedicationError("access_denied")
        return review
