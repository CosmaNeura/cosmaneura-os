"""Explicit FHIR patient grants for the synthetic Tebra workflow; never authenticates."""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

import httpx
from pydantic import SecretStr

from cosmas_os.adapters.tebra_fhir_read import (
    FHIR_BASE,
    TebraFhirCredential,
    TebraFhirReadAdapter,
    TebraFhirReadError,
    TebraFhirScope,
    _json,
    _patient,
)
from cosmas_os.application.tebra_fhir_snapshot import (
    TebraMedicationReviewSnapshot,
    prepare_medication_review,
)
from cosmas_os.domain.hashing import payload_hash


@dataclass(frozen=True, repr=False)
class TebraFhirConnectionScope:
    box_id: UUID
    owner_id: UUID
    account_id: UUID
    connection_id: UUID
    credential_generation: UUID
    display_label: str

    def validate(self):
        if (any(type(value) is not UUID for value in (self.box_id, self.owner_id, self.account_id,
                self.connection_id, self.credential_generation))
                or type(self.display_label) is not str or not self.display_label.strip()
                or self.display_label != self.display_label.strip() or len(self.display_label) > 200
                or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in self.display_label)):
            raise ValueError("invalid_tebra_fhir_connection_scope")

    def commitment(self):
        self.validate()
        return payload_hash({"contract": "tebra-fhir-connection-scope.v1", "fhir_base": FHIR_BASE,
            "box_id": str(self.box_id), "owner_id": str(self.owner_id), "account_id": str(self.account_id),
            "connection_id": str(self.connection_id), "credential_generation": str(self.credential_generation),
            "display_label": self.display_label})


@dataclass(frozen=True, repr=False)
class TebraFhirAuthorizedPatient:
    """Server-configured grant. A client-supplied copy never creates authority."""

    grant_id: UUID
    connection_scope: TebraFhirConnectionScope
    workspace_id: UUID
    patient_link_id: UUID
    fhir_patient_id: str
    authorization_sha256: str
    identity_json: str
    identity_sha256: str

    def read_scope(self):
        if type(self.connection_scope) is not TebraFhirConnectionScope:
            raise ValueError("invalid_tebra_fhir_patient_grant")
        self.connection_scope.validate()
        scope = TebraFhirScope(self.connection_scope.box_id, self.connection_scope.owner_id,
            self.connection_scope.connection_id, self.connection_scope.credential_generation,
            self.fhir_patient_id, self.authorization_sha256)
        scope.validate()
        return scope

    def validate(self):
        if (any(type(value) is not UUID for value in (self.grant_id, self.workspace_id, self.patient_link_id))
                or type(self.identity_json) is not str or len(self.identity_json.encode("utf-8")) > 16384):
            raise ValueError("invalid_tebra_fhir_patient_grant")
        patient = _patient(_json(self.identity_json.encode("utf-8")), self.read_scope())
        if patient.identity_json != self.identity_json or patient.identity_sha256 != self.identity_sha256:
            raise ValueError("invalid_tebra_fhir_patient_grant")

    def commitment(self):
        self.validate()
        return payload_hash({"contract": "tebra-fhir-patient-grant.v1", "grant_id": str(self.grant_id),
            "connection_sha256": self.connection_scope.commitment(), "workspace_id": str(self.workspace_id),
            "patient_link_id": str(self.patient_link_id), "read_scope_sha256": self.read_scope().commitment(),
            "patient_identity_sha256": self.identity_sha256})


class SyntheticTebraFhirReads:
    """Closed mock runtime; SQL custody and current owner checks belong to the caller."""

    transport_mode = "mock"
    protocol = "fhir"

    def __init__(self, scopes: tuple[TebraFhirConnectionScope, ...],
                 patients: tuple[TebraFhirAuthorizedPatient, ...], transport: httpx.MockTransport, *,
                 enabled: Callable[[], bool]):
        if (type(scopes) is not tuple or not 1 <= len(scopes) <= 20
                or any(type(scope) is not TebraFhirConnectionScope for scope in scopes)
                or type(patients) is not tuple or len(patients) > 500
                or any(type(patient) is not TebraFhirAuthorizedPatient for patient in patients)
                or type(transport) is not httpx.MockTransport or not callable(enabled)):
            raise ValueError("explicit_synthetic_tebra_fhir_installation_required")
        try:
            if len({scope.commitment() for scope in scopes}) != len(scopes):
                raise ValueError
            seen = set()
            contexts = {}
            for patient in patients:
                patient.validate()
                if patient.connection_scope not in scopes or patient.grant_id in seen:
                    raise ValueError
                seen.add(patient.grant_id)
                context = (patient.connection_scope.commitment(), patient.workspace_id, patient.patient_link_id)
                ids = contexts.setdefault(context, set())
                if patient.fhir_patient_id in ids or len(ids) >= 25:
                    raise ValueError
                ids.add(patient.fhir_patient_id)
        except Exception:
            raise ValueError("explicit_synthetic_tebra_fhir_installation_required") from None
        self._scopes, self._patients, self._transport, self._enabled = scopes, patients, transport, enabled

    def current(self, scope):
        try:
            return type(scope) is TebraFhirConnectionScope and self._enabled() is True and scope in self._scopes
        except Exception:
            return False

    def current_patient(self, patient):
        return (type(patient) is TebraFhirAuthorizedPatient and self.current(patient.connection_scope)
            and patient in self._patients)

    def patient_candidates(self, scope, workspace_id, patient_link_id, *, authorize):
        if type(workspace_id) is not UUID or type(patient_link_id) is not UUID or not callable(authorize):
            raise TebraFhirReadError("request_invalid")
        if not self.current(scope) or authorize() is not True or not self.current(scope):
            raise TebraFhirReadError("access_denied")
        selected = tuple(patient for patient in self._patients if patient.connection_scope == scope
            and patient.workspace_id == workspace_id and patient.patient_link_id == patient_link_id)
        if authorize() is not True or not self.current(scope):
            raise TebraFhirReadError("access_denied")
        return selected

    def medications(self, scope, patient, *, authorize) -> TebraMedicationReviewSnapshot:
        if not callable(authorize):
            raise TebraFhirReadError("request_invalid")

        def current():
            return (self.current(scope) and self.current_patient(patient) and patient.connection_scope == scope
                and authorize() is True and self.current(scope) and self.current_patient(patient))

        if not current():
            raise TebraFhirReadError("access_denied")
        read_scope = patient.read_scope()
        adapter = TebraFhirReadAdapter(enabled=True, transport=self._transport,
            authorize_read=lambda selected: selected == read_scope and current(),
            verify_patient=lambda selected, value: selected == read_scope and current()
                and value.patient_id == patient.fhir_patient_id and value.identity_json == patient.identity_json
                and value.identity_sha256 == patient.identity_sha256)
        observation = adapter.medication_history(read_scope,
            TebraFhirCredential(read_scope.commitment(), SecretStr("synthetic-tebra-fhir-token")))
        review = prepare_medication_review(observation, expected_scope=read_scope,
            expected_source_sha256=observation.source_sha256, expected_patient_identity_sha256=patient.identity_sha256,
            authorize_read=lambda selected: selected == read_scope and current())
        if not current():
            raise TebraFhirReadError("access_denied")
        return review
