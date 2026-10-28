"""Closed report selection and exact laboratory source projections."""

from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cosmas_os.adapters.elation_lab_read import MAX_ID, parse_json, text
from cosmas_os.domain.hashing import canonical_json

Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
METADATA_KEYS = frozenset("chart_date document_date report_type created_date custom_title deleted_date is_urgent order_status reported_date requisition_number signed_date".split())


class Protected(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    def __repr__(self):
        return f"{type(self).__name__}(<protected>)"

    __str__ = __repr__


def canonical_object(value):
    parsed = parse_json(value)
    if type(parsed) is not dict or canonical_json(parsed) != value:
        raise ValueError("invalid_lab_json")
    return value


def public_identity(value):
    canonical_object(value)
    parsed = parse_json(value)
    if set(parsed) != {"first_name", "last_name", "dob"}:
        raise ValueError("invalid_lab_patient")
    for key in ("first_name", "last_name"):
        text(parsed[key], 70, nonblank=True)
    from datetime import date

    if type(parsed["dob"]) is not str or date.fromisoformat(parsed["dob"]).isoformat() != parsed["dob"]:
        raise ValueError("invalid_lab_patient")
    return value


def valid_metadata_json(value):
    canonical_object(value)
    if set(parse_json(value)) - METADATA_KEYS:
        raise ValueError("invalid_lab_metadata")
    return value


def provider_integer(value):
    if type(value) is not str or not value.isascii() or not value.isdecimal() or value.startswith("0") or not 0 < int(value) <= MAX_ID:
        raise ValueError("invalid_lab_identifier")
    return value


class LabPractice(Protected):
    label: str = Field(strict=True, min_length=1, max_length=200)
    timezone: str = Field(strict=True, min_length=1, max_length=100)


class LabWindow(Protected):
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def bounded(self):
        if self.starts_at.utcoffset() is None or self.ends_at.utcoffset() is None or not timedelta(0) < self.ends_at - self.starts_at <= timedelta(days=7):
            raise ValueError("invalid_lab_window")
        return self


class LabParent(Protected):
    observation_id: UUID
    source_sha256: Digest
    item_sha256: Digest


class LabCandidateItem(Protected):
    handle: UUID
    sha256: Digest
    metadata_json: str = Field(strict=True, min_length=2, max_length=16384)

    _metadata = field_validator("metadata_json")(valid_metadata_json)


class LabReportItem(Protected):
    handle: UUID
    sha256: Digest
    report_json: str = Field(strict=True, min_length=2, max_length=65536)
    changed_since_selection: bool = Field(strict=True)
    warnings: tuple[str, ...] = Field(min_length=2, max_length=5)
    completeness: Literal["selected_report_api_fields_only"]
    source_content: str = Field(strict=True, min_length=1, max_length=5000)
    content_sha256: Digest

    _report = field_validator("report_json")(canonical_object)


class LabCommon(Protected):
    provider: Literal["elation"]
    mode: Literal["synthetic"]
    workspace_id: UUID
    practice: LabPractice
    window: LabWindow
    observed_at: datetime
    patient_identity_json: str = Field(strict=True, min_length=2, max_length=16384)
    parent: LabParent

    _identity = field_validator("patient_identity_json")(public_identity)

    @field_validator("observed_at")
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None:
            raise ValueError("invalid_lab_observed_time")
        return value


class LabReportsObservation(LabCommon):
    kind: Literal["lab_reports"]
    coverage: Literal["returned_page_only", "more_rows_available", "continuation_unknown"]
    returned_report_count: int = Field(strict=True, ge=0, le=25)
    other_report_count: int = Field(strict=True, ge=0, le=25)
    reported_total: str | None = Field(strict=True, max_length=19)
    items: tuple[LabCandidateItem, ...] = Field(max_length=25)

    @model_validator(mode="after")
    def counts(self):
        if self.returned_report_count != len(self.items) + self.other_report_count:
            raise ValueError("invalid_lab_counts")
        if self.reported_total is not None and (not self.reported_total.isascii() or not self.reported_total.isdecimal()
                or str(int(self.reported_total)) != self.reported_total or not self.returned_report_count <= int(self.reported_total) <= MAX_ID):
            raise ValueError("invalid_lab_total")
        return self


class LabReportObservation(LabCommon):
    kind: Literal["verified_lab_report"]
    item: LabReportItem


class LabPrivateItem(Protected):
    handle: UUID
    report_id: str = Field(strict=True, max_length=19)
    report_sha256: Digest

    _identifier = field_validator("report_id")(provider_integer)


class LabPrivateSnapshot(Protected):
    lab_contract: Literal["elation_lab.v1"]
    transport: Literal["mock"] = "mock"
    binding_sha256: Digest
    request_sha256: Digest
    workspace_id: UUID
    patient_link_id: UUID
    items: tuple[LabPrivateItem, ...] = Field(max_length=25)
    page_snapshot_json: str | None = Field(strict=True, max_length=65536)
    reader_snapshot_json: str | None = Field(strict=True, max_length=65536)
    review_sha256: Digest | None
    # Audit observations only. Authority derives from the immutable verified
    # visit plus account/workspace/patient scope; these hashes do not grant it.
    visit_provider_sources: tuple[Digest, Digest]

    @model_validator(mode="after")
    def bounded_pair(self):
        if (self.reader_snapshot_json is None) != (self.review_sha256 is None):
            raise ValueError("invalid_lab_proof_pair")
        if (self.page_snapshot_json is None) == (self.reader_snapshot_json is None):
            raise ValueError("invalid_lab_snapshot_kind")
        for raw in (self.page_snapshot_json, self.reader_snapshot_json):
            if raw is not None:
                canonical_object(raw)
        if self.reader_snapshot_json is not None and len(self.items) != 1:
            raise ValueError("invalid_selected_lab")
        return self
