"""Closed synthetic FHIR selection/review payloads, separate from SOAP visits."""

import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cosmas_os.adapters.tebra_fhir_read import _json
from cosmas_os.domain.hashing import canonical_json

Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]


class Protected(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    def __repr__(self):
        return f"{type(self).__name__}(<protected>)"

    __str__ = __repr__


def identity_json(value):
    parsed = _json(value)
    if parsed.get("resourceType") != "Patient" or canonical_json(parsed) != value:
        raise ValueError("invalid_fhir_identity")
    return value


def reader_object(value):
    def invalid_constant(_):
        raise ValueError("invalid_fhir_reader_json")
    parsed = json.loads(value, parse_constant=invalid_constant)
    if type(parsed) is not dict or canonical_json(parsed) != value:
        raise ValueError("invalid_fhir_reader_json")
    return parsed


class FhirPatientItem(Protected):
    handle: UUID
    sha256: Digest
    patient_identity_json: str = Field(strict=True, min_length=2, max_length=20000)

    _identity = field_validator("patient_identity_json")(identity_json)


class FhirMedicationRecord(Protected):
    status: Literal["active", "on-hold", "cancelled", "completed", "entered-in-error", "stopped", "draft", "unknown"]
    intent: Literal["order", "plan"]
    authored_on: str = Field(strict=True, min_length=4, max_length=64)
    do_not_perform: bool | None = Field(strict=True)
    reported_json: str | None = Field(strict=True, max_length=20000)
    request_medication_json: str = Field(strict=True, min_length=2, max_length=20000)
    medication_name: str | None = Field(strict=True, max_length=1000)
    medication_json: str = Field(strict=True, min_length=2, max_length=40000)
    dosage_instructions_json: str | None = Field(strict=True, max_length=40000)
    context_json: str = Field(strict=True, min_length=2, max_length=40000)


class FhirMedicationItem(FhirPatientItem):
    coverage: Literal["returned_page_only", "more_rows_available"]
    reported_total: int | None = Field(strict=True, ge=0, le=2147483647)
    warnings: tuple[str, ...] = Field(max_length=1500)
    records: tuple[FhirMedicationRecord, ...] = Field(max_length=25)
    source_content: str = Field(strict=True, min_length=1, max_length=5000)
    content_sha256: Digest


class FhirCommonObservation(Protected):
    provider: Literal["tebra"]
    protocol: Literal["fhir"]
    mode: Literal["synthetic"]
    workspace_id: UUID
    display_label: str = Field(strict=True, min_length=1, max_length=200)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None:
            raise ValueError("aware_fhir_time_required")
        return value


class FhirPatientsObservation(FhirCommonObservation):
    kind: Literal["fhir_patients"]
    coverage: Literal["authorized_candidates_only"]
    items: tuple[FhirPatientItem, ...] = Field(max_length=25)


class FhirParent(Protected):
    observation_id: UUID
    source_sha256: Digest
    item_sha256: Digest


class FhirMedicationsObservation(FhirCommonObservation):
    kind: Literal["fhir_medications"]
    parent: FhirParent
    item: FhirMedicationItem


class FhirPrivateItem(Protected):
    handle: UUID
    grant_id: UUID
    grant_sha256: Digest
    patient_identity_json: str = Field(strict=True, min_length=2, max_length=20000)

    _identity = field_validator("patient_identity_json")(identity_json)


class FhirPrivateSnapshot(Protected):
    protocol: Literal["fhir"]
    transport: Literal["mock"] = "mock"
    binding_sha256: Digest
    request_sha256: Digest
    workspace_id: UUID
    patient_link_id: UUID
    items: tuple[FhirPrivateItem, ...] = Field(max_length=25)
    reader_snapshot_json: str | None = Field(strict=True, max_length=65536)
    review_sha256: Digest | None

    @model_validator(mode="after")
    def exact_read_pair(self):
        if (self.reader_snapshot_json is None) != (self.review_sha256 is None):
            raise ValueError("incomplete_fhir_read")
        if self.reader_snapshot_json is not None:
            parsed = reader_object(self.reader_snapshot_json)
            if canonical_json(parsed) != self.reader_snapshot_json or len(self.items) != 1:
                raise ValueError("invalid_fhir_read")
        return self
