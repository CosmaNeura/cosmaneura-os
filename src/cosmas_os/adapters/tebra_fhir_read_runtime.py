"""Explicit FHIR patient grants for the synthetic shared FHIR workflow; never authenticates."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import httpx
from pydantic import SecretStr

from cosmas_os.adapters.athena_fhir_medication_read import read_athena_fhir_medications
from cosmas_os.adapters.athena_fhir_r4 import AthenaFhirR4Adapter
from cosmas_os.adapters.ehr_auth import ClientCredentialsTokenClient
from cosmas_os.adapters.ehr_fhir_vendor import (
    connection_scope_payload,
    patient_grant_payload,
    require_fhir_vendor,
)
from cosmas_os.adapters.tebra_fhir_read import (
    TebraFhirCredential,
    TebraFhirPatient,
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
    vendor: Literal["tebra", "athena"] = "tebra"

    def validate(self):
        require_fhir_vendor(self.vendor)
        if (any(type(value) is not UUID for value in (self.box_id, self.owner_id, self.account_id,
                self.connection_id, self.credential_generation))
                or type(self.display_label) is not str or not self.display_label.strip()
                or self.display_label != self.display_label.strip() or len(self.display_label) > 200
                or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in self.display_label)):
            raise ValueError("invalid_tebra_fhir_connection_scope")

    def commitment(self):
        self.validate()
        return payload_hash(connection_scope_payload(
            self.vendor,
            box_id=str(self.box_id),
            owner_id=str(self.owner_id),
            account_id=str(self.account_id),
            connection_id=str(self.connection_id),
            credential_generation=str(self.credential_generation),
            display_label=self.display_label,
        ))


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
        return payload_hash(patient_grant_payload(self.connection_scope.vendor, {
            "grant_id": str(self.grant_id),
            "connection_sha256": self.connection_scope.commitment(),
            "workspace_id": str(self.workspace_id),
            "patient_link_id": str(self.patient_link_id),
            "read_scope_sha256": self.read_scope().commitment(self.connection_scope.vendor),
            "patient_identity_sha256": self.identity_sha256,
        }))


class SyntheticTebraFhirReads:
    """Closed mock runtime; SQL custody and current owner checks belong to the caller."""

    transport_mode = "mock"
    protocol = "fhir"

    def __init__(self, scopes: tuple[TebraFhirConnectionScope, ...],
                 patients: tuple[TebraFhirAuthorizedPatient, ...], transport: httpx.MockTransport, *,
                 enabled: Callable[[], bool],
                 athena_token_client: ClientCredentialsTokenClient | None = None,
                 athena_sandbox_enabled: bool = False,
                 athena_real_data_enabled: bool = False,
                 athena_practice_baa_recorded: bool = False):
        if (type(scopes) is not tuple or not 1 <= len(scopes) <= 20
                or any(type(scope) is not TebraFhirConnectionScope for scope in scopes)
                or type(patients) is not tuple or len(patients) > 500
                or any(type(patient) is not TebraFhirAuthorizedPatient for patient in patients)
                or type(transport) is not httpx.MockTransport or not callable(enabled)
                or type(athena_sandbox_enabled) is not bool
                or type(athena_real_data_enabled) is not bool
                or type(athena_practice_baa_recorded) is not bool):
            raise ValueError("explicit_synthetic_tebra_fhir_installation_required")
        try:
            vendors = {scope.vendor for scope in scopes}
            if len(vendors) != 1:
                raise ValueError
            self.vendor = next(iter(vendors))
            if self.vendor == "athena":
                if type(athena_token_client) is not ClientCredentialsTokenClient:
                    raise ValueError
            elif athena_token_client is not None:
                raise ValueError
            if len({scope.commitment() for scope in scopes}) != len(scopes):
                raise ValueError
            seen = set()
            contexts = {}
            for patient in patients:
                patient.validate()
                if (patient.connection_scope not in scopes or patient.grant_id in seen
                        or patient.connection_scope.vendor != self.vendor):
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
        self._athena_token_client = athena_token_client
        self._athena_sandbox_enabled = athena_sandbox_enabled
        self._athena_real_data_enabled = athena_real_data_enabled
        self._athena_practice_baa_recorded = athena_practice_baa_recorded

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

    def _athena_adapter(self) -> AthenaFhirR4Adapter:
        if self.vendor != "athena" or type(self._athena_token_client) is not ClientCredentialsTokenClient:
            raise TebraFhirReadError("request_invalid")
        return AthenaFhirR4Adapter(
            token_client=self._athena_token_client,
            transport=self._transport,
            sandbox_enabled=self._athena_sandbox_enabled,
            real_data_enabled=self._athena_real_data_enabled,
            practice_baa_recorded=self._athena_practice_baa_recorded,
        )

    def medications(self, scope, patient, *, authorize) -> TebraMedicationReviewSnapshot:
        if not callable(authorize):
            raise TebraFhirReadError("request_invalid")

        def current():
            return (self.current(scope) and self.current_patient(patient) and patient.connection_scope == scope
                and authorize() is True and self.current(scope) and self.current_patient(patient))

        if not current():
            raise TebraFhirReadError("access_denied")
        read_scope = patient.read_scope()
        vendor = patient.connection_scope.vendor
        if vendor == "athena":
            expected = TebraFhirPatient(
                patient.fhir_patient_id, patient.identity_json, patient.identity_sha256,
            )
            observation = read_athena_fhir_medications(
                self._athena_adapter(),
                read_scope,
                expected_patient=expected,
                authorize=lambda: current() is True,
            )
        else:
            adapter = TebraFhirReadAdapter(enabled=True, transport=self._transport,
                authorize_read=lambda selected: selected == read_scope and current(),
                verify_patient=lambda selected, value: selected == read_scope and current()
                    and value.patient_id == patient.fhir_patient_id and value.identity_json == patient.identity_json
                    and value.identity_sha256 == patient.identity_sha256)
            observation = adapter.medication_history(read_scope,
                TebraFhirCredential(read_scope.commitment(vendor), SecretStr("synthetic-tebra-fhir-token")))
        review = prepare_medication_review(observation, expected_scope=read_scope,
            expected_source_sha256=observation.source_sha256, expected_patient_identity_sha256=patient.identity_sha256,
            authorize_read=lambda selected: selected == read_scope and current(),
            vendor=vendor)
        if not current():
            raise TebraFhirReadError("access_denied")
        return review
