"""Closed private EHR snapshot shapes and their deliberately smaller display projection."""

import re
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cosmas_os.ports.athena_allergy_ehr import (
    AthenaAllergiesObservation,
    AthenaPatientsObservation,
    AthenaPrivateSnapshot,
)
from cosmas_os.ports.athena_medication_ehr import (
    AthenaMedicationPatientsObservation,
    AthenaMedicationPrivateSnapshot,
    AthenaMedicationsObservation,
)
from cosmas_os.ports.elation_lab_ehr import (
    LabPrivateSnapshot,
    LabReportObservation,
    LabReportsObservation,
)
from cosmas_os.ports.tebra_fhir_ehr import (
    FhirMedicationsObservation,
    FhirPatientsObservation,
    FhirPrivateSnapshot,
)

Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
ProviderId = Annotated[str, Field(strict=True, pattern=r"^[1-9][0-9]{0,18}$")]
Status = Literal["Scheduled", "Confirmed", "Checked Out", "Cancelled", "With Doctor",
                 "In Room", "Checked In", "In Room - Vitals Taken", "Not Seen", "Billed"]
Coverage = Literal["end_of_results", "more_rows_available"]


class Protected(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    def __repr__(self):
        return f"{type(self).__name__}(<protected>)"

    __str__ = __repr__


class Window(Protected):
    starts_at: datetime
    ends_at: datetime

    @field_validator("starts_at", "ends_at")
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None:
            raise ValueError("aware_time_required")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bounded(self):
        if not timedelta(0) < self.ends_at - self.starts_at <= timedelta(days=7):
            raise ValueError("bounded_window_required")
        return self


class Practice(Protected):
    label: str = Field(strict=True, min_length=1, max_length=200)
    timezone: str = Field(strict=True, min_length=1, max_length=100)

    @field_validator("timezone")
    @classmethod
    def timezone_known(cls, value):
        ZoneInfo(value)
        return value


class PatientDisplay(Protected):
    first_name: str = Field(strict=True, min_length=1, max_length=70)
    last_name: str = Field(strict=True, min_length=1, max_length=70)
    birth_date: date


class WindowItem(Protected):
    handle: UUID
    sha256: Digest
    starts_at: datetime
    ends_at: datetime
    status: Status | None
    selectable: bool = Field(strict=True)


class VerifiedItem(Protected):
    handle: UUID
    sha256: Digest
    starts_at: datetime
    ends_at: datetime
    status: Status | None
    patient: PatientDisplay


class CommonObservation(Protected):
    provider: Literal["elation"] = "elation"
    mode: Literal["synthetic"] = "synthetic"
    practice: Practice
    observed_at: datetime
    window: Window
    coverage: Coverage


class WindowObservation(CommonObservation):
    kind: Literal["window"]
    items: tuple[WindowItem, ...] = Field(max_length=25)


class VerifiedObservation(CommonObservation):
    kind: Literal["verified_visit"]
    item: VerifiedItem


class ProblemDisplay(Protected):
    description: str = Field(strict=True, min_length=1, max_length=200)
    status: Literal["Active", "Controlled", "Resolved"]
    start_date: date
    resolved_date: date | None
    verification_status: Literal["confirmed", "differential", "entered_in_error", "provisional", "refuted", "unconfirmed", ""] | None

    @field_validator("description")
    @classmethod
    def safe_text(cls, value):
        if not value.strip() or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("invalid_problem_description")
        return value


    @model_validator(mode="after")
    def resolved_status(self):
        if self.resolved_date is not None and self.status != "Resolved":
            raise ValueError("invalid_problem_resolution")
        return self


class ProblemList(Protected):
    coverage: Literal["end_of_results", "more_rows_available", "unknown"]
    total_count: int | None = Field(strict=True, ge=0, le=2147483647)
    items: tuple[ProblemDisplay, ...] = Field(max_length=25)

    @model_validator(mode="after")
    def consistent_count(self):
        count = len(self.items)
        if (self.total_count is not None and self.total_count < count
                or self.coverage == "end_of_results" and self.total_count is not None and self.total_count != count
                or self.coverage == "more_rows_available" and (not count or self.total_count is not None and self.total_count <= count)):
            raise ValueError("invalid_problem_coverage")
        return self


class ProblemsItem(VerifiedItem):
    problems: ProblemList


class VerifiedParent(Protected):
    observation_id: UUID
    source_sha256: Digest
    item_sha256: Digest


class ProblemsObservation(CommonObservation):
    kind: Literal["verified_problems"]
    parent: VerifiedParent
    item: ProblemsItem


_MEDICATION_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?\Z")
DatePresence = Literal["date_recorded", "no_date_recorded", "unknown"]


class MedicationDisplay(Protected):
    medication_name: str = Field(strict=True, min_length=1, max_length=300)
    strength: str | None = Field(strict=True, max_length=255)
    route: str | None = Field(strict=True, max_length=100)
    form: str | None = Field(strict=True, max_length=100)
    directions: str | None = Field(strict=True, max_length=1000)
    medication_type: str | None = Field(strict=True, max_length=40)
    order_type: str | None = Field(strict=True, max_length=40)
    is_doc_med: bool | None = Field(strict=True)
    is_permanent: bool | None = Field(strict=True)
    start_date: str | None = Field(strict=True, max_length=10)
    document_date: str | None = Field(strict=True, max_length=40)
    signed_date: str | None = Field(strict=True, max_length=40)
    deleted_date: str | None = Field(strict=True, max_length=40)
    discontinue_date: str | None = Field(strict=True, max_length=40)
    signature_state: DatePresence
    discontinuation_state: DatePresence
    deletion_state: DatePresence

    @field_validator("medication_name", "strength", "route", "form", "directions", "medication_type", "order_type")
    @classmethod
    def safe_record_text(cls, value, info):
        allowed = "\t\n\r" if info.field_name == "directions" else ""
        if value is not None and (info.field_name == "medication_name" and not value.strip()
                or any((ord(c) < 32 and c not in allowed) or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
            raise ValueError("invalid_medication_text")
        return value

    @field_validator("start_date", "document_date", "signed_date", "deleted_date", "discontinue_date")
    @classmethod
    def recorded_date(cls, value, info):
        if value is None:
            return value
        if info.field_name in ("start_date", "discontinue_date") and len(value) == 10:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("invalid_medication_date")
        elif info.field_name == "start_date" or not _MEDICATION_TIME.fullmatch(value):
            raise ValueError("invalid_medication_date")
        else:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @model_validator(mode="after")
    def date_presence(self):
        for value, state in ((self.signed_date, self.signature_state), (self.discontinue_date, self.discontinuation_state),
                             (self.deleted_date, self.deletion_state)):
            if (value is not None) != (state == "date_recorded"):
                raise ValueError("invalid_medication_date_presence")
        return self


class MedicationList(Protected):
    coverage: Literal["end_of_results", "more_rows_available", "unknown"]
    total_count: int | None = Field(strict=True, ge=0, le=2147483647)
    items: tuple[MedicationDisplay, ...] = Field(max_length=25)

    @model_validator(mode="after")
    def consistent_count(self):
        count = len(self.items)
        if (self.total_count is not None and self.total_count < count
                or self.coverage == "end_of_results" and self.total_count is not None and self.total_count != count
                or self.coverage == "more_rows_available" and (not count or self.total_count is not None and self.total_count <= count)):
            raise ValueError("invalid_medication_coverage")
        return self


class MedicationsItem(VerifiedItem):
    medications: MedicationList


class MedicationsObservation(CommonObservation):
    kind: Literal["verified_medications"]
    parent: VerifiedParent
    item: MedicationsItem


class PrivateAppointment(Protected):
    appointment_id: ProviderId
    patient_id: ProviderId | None
    physician_id: ProviderId
    starts_at: datetime
    ends_at: datetime
    status: Status | None
    scheduled_date_raw: str = Field(strict=True, min_length=1, max_length=40)
    deleted_at: datetime | None


class PrivatePatient(PatientDisplay):
    patient_id: ProviderId
    primary_physician_id: ProviderId
    deleted_at: datetime | None


class PrivateItem(Protected):
    handle: UUID
    appointment: PrivateAppointment
    patient: PrivatePatient | None


class PrivateSnapshot(Protected):
    transport: Literal["mock", "vendor_sandbox"] = "mock"
    binding_sha256: Digest
    request_sha256: Digest
    items: tuple[PrivateItem, ...] = Field(max_length=25)
    provider_sources: tuple[Digest, ...] = Field(min_length=1, max_length=2)


class PrivateProblem(ProblemDisplay):
    problem_id: ProviderId
    patient_id: ProviderId
    practice_id: ProviderId


class ProblemsPrivateSnapshot(PrivateSnapshot):
    provider_sources: tuple[Digest, ...] = Field(min_length=3, max_length=3)
    problems: tuple[PrivateProblem, ...] = Field(max_length=25)


class PrivateMedication(MedicationDisplay):
    medication_id: ProviderId
    patient_id: ProviderId
    practice_id: ProviderId


class MedicationsPrivateSnapshot(PrivateSnapshot):
    provider_sources: tuple[Digest, ...] = Field(min_length=3, max_length=3)
    medications: tuple[PrivateMedication, ...] = Field(max_length=25)


TebraStatus = Literal["Confirmed", "Check-in", "No-show", "Check-out", "Rescheduled", "Scheduled", "Cancelled"]


class TebraPatientDisplay(Protected):
    full_name: str = Field(strict=True, min_length=1, max_length=255)
    birth_date: date


class TebraWindowItem(WindowItem):
    status: TebraStatus


class TebraVerifiedItem(Protected):
    handle: UUID
    sha256: Digest
    starts_at: datetime
    ends_at: datetime
    status: TebraStatus
    patient: TebraPatientDisplay


class TebraCommonObservation(Protected):
    provider: Literal["tebra"]
    mode: Literal["synthetic"]
    practice: Practice
    observed_at: datetime
    window: Window
    coverage: Literal["returned_rows_only"]


class TebraWindowObservation(TebraCommonObservation):
    kind: Literal["window"]
    items: tuple[TebraWindowItem, ...] = Field(max_length=25)


class TebraVerifiedObservation(TebraCommonObservation):
    kind: Literal["verified_visit"]
    item: TebraVerifiedItem


class TebraPrivateAppointment(Protected):
    appointment_id: ProviderId
    patient_id: ProviderId
    starts_at: datetime
    ends_at: datetime
    status: TebraStatus


class TebraPrivatePatient(TebraPatientDisplay):
    patient_id: ProviderId


class TebraPrivateItem(Protected):
    handle: UUID
    appointment: TebraPrivateAppointment
    patient: TebraPrivatePatient | None


class TebraPrivateSnapshot(Protected):
    transport: Literal["mock"]
    binding_sha256: Digest
    request_sha256: Digest
    items: tuple[TebraPrivateItem, ...] = Field(max_length=25)
    provider_sources: tuple[Digest, ...] = Field(min_length=1, max_length=2)


class SnapshotPayload(Protected):
    public: WindowObservation | VerifiedObservation | ProblemsObservation | MedicationsObservation | TebraWindowObservation | TebraVerifiedObservation | FhirPatientsObservation | FhirMedicationsObservation | AthenaPatientsObservation | AthenaAllergiesObservation | LabReportsObservation | LabReportObservation | AthenaMedicationPatientsObservation | AthenaMedicationsObservation
    private: MedicationsPrivateSnapshot | ProblemsPrivateSnapshot | PrivateSnapshot | TebraPrivateSnapshot | FhirPrivateSnapshot | AthenaPrivateSnapshot | LabPrivateSnapshot | AthenaMedicationPrivateSnapshot

    @model_validator(mode="before")
    @classmethod
    def private_provider(cls, value):
        if isinstance(value, dict) and isinstance(value.get("public"), dict) and value["public"].get("clinical_scope") == "medications":
            return {**value, "private": AthenaMedicationPrivateSnapshot.model_validate(value["private"])}
        if isinstance(value, dict) and isinstance(value.get("public"), dict) and value["public"].get("kind") in ("lab_reports", "verified_lab_report"):
            return {**value, "private": LabPrivateSnapshot.model_validate(value["private"])}
        if isinstance(value, dict) and isinstance(value.get("public"), dict) and value["public"].get("protocol") == "core":
            return {**value, "private": AthenaPrivateSnapshot.model_validate(value["private"])}
        if isinstance(value, dict) and isinstance(value.get("public"), dict) and value["public"].get("protocol") == "fhir":
            return {**value, "private": FhirPrivateSnapshot.model_validate(value["private"])}
        if isinstance(value, dict) and isinstance(value.get("public"), dict) and value["public"].get("kind") == "verified_medications":
            return {**value, "private": MedicationsPrivateSnapshot.model_validate(value["private"])}
        if isinstance(value, dict) and isinstance(value.get("public"), dict) and value["public"].get("kind") == "verified_problems":
            return {**value, "private": ProblemsPrivateSnapshot.model_validate(value["private"])}
        if isinstance(value, dict) and isinstance(value.get("public"), dict) and value["public"].get("provider") == "tebra":
            return {**value, "private": TebraPrivateSnapshot.model_validate(value["private"])}
        return value

    @model_validator(mode="after")
    def same_provider(self):
        if isinstance(self.public, (AthenaMedicationPatientsObservation, AthenaMedicationsObservation)):
            if not isinstance(self.private, AthenaMedicationPrivateSnapshot):
                raise ValueError("athena_medication_payload_mismatch")
            return self
        if isinstance(self.private, AthenaMedicationPrivateSnapshot):
            raise ValueError("athena_medication_payload_mismatch")
        if isinstance(self.public, (LabReportsObservation, LabReportObservation)):
            if not isinstance(self.private, LabPrivateSnapshot):
                raise ValueError("lab_payload_mismatch")
            return self
        if isinstance(self.private, LabPrivateSnapshot):
            raise ValueError("lab_payload_mismatch")
        if isinstance(self.public, (AthenaPatientsObservation, AthenaAllergiesObservation)):
            if not isinstance(self.private, AthenaPrivateSnapshot):
                raise ValueError("athena_payload_mismatch")
            return self
        if isinstance(self.private, AthenaPrivateSnapshot):
            raise ValueError("athena_payload_mismatch")
        if isinstance(self.public, (FhirPatientsObservation, FhirMedicationsObservation)):
            if not isinstance(self.private, FhirPrivateSnapshot):
                raise ValueError("fhir_payload_mismatch")
            return self
        if isinstance(self.private, FhirPrivateSnapshot):
            raise ValueError("fhir_payload_mismatch")
        if isinstance(self.public, MedicationsObservation) != isinstance(self.private, MedicationsPrivateSnapshot):
            raise ValueError("medication_payload_mismatch")
        if isinstance(self.public, ProblemsObservation) != isinstance(self.private, ProblemsPrivateSnapshot):
            raise ValueError("problem_payload_mismatch")
        if (self.public.provider == "tebra") != isinstance(self.private, TebraPrivateSnapshot):
            raise ValueError("provider_payload_mismatch")
        return self
