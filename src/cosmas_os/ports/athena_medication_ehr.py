"""Medication-only public snapshots; clinical numbers stay in exact JSON strings."""

import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cosmas_os.adapters.athena_medication_read import (
    AthenaMedicationError,
    clinical_dumps,
    clinical_loads,
    medication_records,
)
from cosmas_os.domain.hashing import canonical_json
from cosmas_os.ports.athena_allergy_ehr import identity_json, private_identity_json
from cosmas_os.ports.athena_allergy_ehr import public_identity_json as public_identity_json

Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]


class Protected(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    def __repr__(self):
        return f"{type(self).__name__}(<protected>)"

    __str__ = __repr__


def valid_section_json(value):
    try:
        parsed = clinical_loads(value)
        if clinical_dumps(parsed) != value:
            raise ValueError("invalid_athena_medication_section")
        medication_records(parsed)
    except AthenaMedicationError:
        # Shared snapshot unions also inspect existing allergy alternatives.
        # A provider refusal is a field-validation failure, not an exception
        # that may abort validation of an otherwise valid sibling protocol.
        raise ValueError("invalid_athena_medication_section") from None
    return value


def reader_object(value):
    def invalid_constant(_):
        raise ValueError("invalid_athena_medication_reader_json")

    # The outer proof contains only strings, booleans, lists and objects.
    # Clinical JSON remains inside strings and is validated losslessly above.
    parsed = json.loads(value, parse_constant=invalid_constant)
    if type(parsed) is not dict or canonical_json(parsed) != value:
        raise ValueError("invalid_athena_medication_reader_json")
    return parsed


class AthenaMedicationPatientItem(Protected):
    handle: UUID
    sha256: Digest
    patient_identity_json: str = Field(strict=True, min_length=2, max_length=16384)
    department_label: str = Field(strict=True, min_length=1, max_length=200)

    # Only the previously qualified identity field format is shared. Grant,
    # binding, request and source authority have medication-only commitments.
    _identity = field_validator("patient_identity_json")(identity_json)


class AthenaMedicationItem(AthenaMedicationPatientItem):
    coverage: Literal["returned_section_only"]
    medication_type: Literal["ACTIVE"]
    includes_pending: Literal[True]
    includes_ndc: Literal[True]
    includes_rxnorm: Literal[True]
    section_json: str = Field(strict=True, min_length=2, max_length=65536)
    source_content: str = Field(strict=True, min_length=1, max_length=5000)
    content_sha256: Digest

    _section = field_validator("section_json")(valid_section_json)

    @field_validator("includes_pending", "includes_ndc", "includes_rxnorm", mode="before")
    @classmethod
    def exact_true(cls, value):
        if value is not True:
            raise ValueError("invalid_athena_medication_coverage")
        return value


class AthenaMedicationCommonObservation(Protected):
    provider: Literal["athena"]
    protocol: Literal["core"]
    clinical_scope: Literal["medications"]
    mode: Literal["synthetic"]
    workspace_id: UUID
    practice_label: str = Field(strict=True, min_length=1, max_length=200)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None:
            raise ValueError("aware_athena_medication_time_required")
        return value


class AthenaMedicationPatientsObservation(AthenaMedicationCommonObservation):
    kind: Literal["core_patients"]
    coverage: Literal["authorized_candidates_only"]
    items: tuple[AthenaMedicationPatientItem, ...] = Field(max_length=25)


class AthenaMedicationParent(Protected):
    observation_id: UUID
    source_sha256: Digest
    item_sha256: Digest


class AthenaMedicationsObservation(AthenaMedicationCommonObservation):
    kind: Literal["core_medications"]
    parent: AthenaMedicationParent
    item: AthenaMedicationItem


class AthenaMedicationPrivateItem(Protected):
    handle: UUID
    grant_id: UUID
    grant_sha256: Digest
    patient_identity_json: str = Field(strict=True, min_length=2, max_length=16384)

    _identity = field_validator("patient_identity_json")(private_identity_json)


class AthenaMedicationPrivateSnapshot(Protected):
    protocol: Literal["core"]
    clinical_scope: Literal["medications"]
    transport: Literal["mock"] = "mock"
    binding_sha256: Digest
    request_sha256: Digest
    workspace_id: UUID
    patient_link_id: UUID
    items: tuple[AthenaMedicationPrivateItem, ...] = Field(max_length=25)
    reader_snapshot_json: str | None = Field(strict=True, max_length=65536)
    review_sha256: Digest | None

    @model_validator(mode="after")
    def exact_read_pair(self):
        if (self.reader_snapshot_json is None) != (self.review_sha256 is None):
            raise ValueError("incomplete_athena_medication_read")
        if self.reader_snapshot_json is not None:
            reader_object(self.reader_snapshot_json)
            if len(self.items) != 1:
                raise ValueError("invalid_athena_medication_read")
        return self
