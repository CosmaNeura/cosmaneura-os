"""Closed synthetic Athena allergy observations; clinical authority stays private."""

import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cosmas_os.adapters.athena_allergy_read import _id, _json, _text, allergy_records
from cosmas_os.domain.hashing import canonical_json

Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
IDENTITY_KEYS = {"firstname", "middlename", "lastname", "dob", "status", "deceaseddate"}
PRIVATE_IDENTITY_KEYS = IDENTITY_KEYS | {"patientid", "departmentid", "primarydepartmentid"}


class Protected(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    def __repr__(self):
        return f"{type(self).__name__}(<protected>)"

    __str__ = __repr__


def identity_json(value, *, private=False):
    parsed = _json(value)
    allowed = PRIVATE_IDENTITY_KEYS if private else IDENTITY_KEYS
    if type(parsed) is not dict or set(parsed) - allowed or canonical_json(parsed) != value:
        raise ValueError("invalid_athena_identity")
    for key in ("firstname", "lastname"):
        if not _text(parsed.get(key), 300).strip():
            raise ValueError("invalid_athena_identity")
    for item in parsed.values():
        _text(item, 300)
    if private:
        _id(parsed.get("patientid"))
    if parsed.get("dob"):
        import re

        if not re.fullmatch(r"[0-9]{2}/[0-9]{2}/[0-9]{4}", parsed["dob"]):
            raise ValueError("invalid_athena_identity")
        datetime.strptime(parsed["dob"], "%m/%d/%Y")
    return value


def private_identity_json(value):
    return identity_json(value, private=True)


def public_identity_json(value):
    private_identity_json(value)
    return canonical_json({key: item for key, item in _json(value).items() if key in IDENTITY_KEYS})


def valid_section_json(value):
    parsed = _json(value)
    if canonical_json(parsed) != value:
        raise ValueError("invalid_athena_section")
    allergy_records(parsed)
    return value


def reader_object(value):
    def invalid_constant(_):
        raise ValueError("invalid_athena_reader_json")

    parsed = json.loads(value, parse_constant=invalid_constant)
    if type(parsed) is not dict or canonical_json(parsed) != value:
        raise ValueError("invalid_athena_reader_json")
    return parsed


class AthenaPatientItem(Protected):
    handle: UUID
    sha256: Digest
    patient_identity_json: str = Field(strict=True, min_length=2, max_length=16384)
    department_label: str = Field(strict=True, min_length=1, max_length=200)

    _identity = field_validator("patient_identity_json")(identity_json)


class AthenaAllergyItem(AthenaPatientItem):
    coverage: Literal["returned_section_only"]
    includes_inactive: Literal[True]
    section_json: str = Field(strict=True, min_length=2, max_length=65536)
    source_content: str = Field(strict=True, min_length=1, max_length=5000)
    content_sha256: Digest

    _section = field_validator("section_json")(valid_section_json)

    @field_validator("includes_inactive", mode="before")
    @classmethod
    def exact_inactive(cls, value):
        if value is not True:
            raise ValueError("invalid_athena_coverage")
        return value


class AthenaCommonObservation(Protected):
    provider: Literal["athena"]
    protocol: Literal["core"]
    mode: Literal["synthetic"]
    workspace_id: UUID
    practice_label: str = Field(strict=True, min_length=1, max_length=200)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None:
            raise ValueError("aware_athena_time_required")
        return value


class AthenaPatientsObservation(AthenaCommonObservation):
    kind: Literal["core_patients"]
    coverage: Literal["authorized_candidates_only"]
    items: tuple[AthenaPatientItem, ...] = Field(max_length=25)


class AthenaParent(Protected):
    observation_id: UUID
    source_sha256: Digest
    item_sha256: Digest


class AthenaAllergiesObservation(AthenaCommonObservation):
    kind: Literal["core_allergies"]
    parent: AthenaParent
    item: AthenaAllergyItem


class AthenaPrivateItem(Protected):
    handle: UUID
    grant_id: UUID
    grant_sha256: Digest
    patient_identity_json: str = Field(strict=True, min_length=2, max_length=16384)

    _identity = field_validator("patient_identity_json")(private_identity_json)


class AthenaPrivateSnapshot(Protected):
    protocol: Literal["core"]
    transport: Literal["mock"] = "mock"
    binding_sha256: Digest
    request_sha256: Digest
    workspace_id: UUID
    patient_link_id: UUID
    items: tuple[AthenaPrivateItem, ...] = Field(max_length=25)
    reader_snapshot_json: str | None = Field(strict=True, max_length=65536)
    review_sha256: Digest | None

    @model_validator(mode="after")
    def exact_read_pair(self):
        if (self.reader_snapshot_json is None) != (self.review_sha256 is None):
            raise ValueError("incomplete_athena_read")
        if self.reader_snapshot_json is not None:
            reader_object(self.reader_snapshot_json)
            if len(self.items) != 1:
                raise ValueError("invalid_athena_read")
        return self
