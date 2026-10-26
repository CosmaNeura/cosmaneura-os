"""Bounded EHR read and explicit human-review commands; no provider IDs or cursors."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, field_validator, model_validator

from cosmas_os.api.workspace_schemas import IdempotencyKey
from cosmas_os.ports.ehr_reads import Digest, Protected, Window


class ProviderCommand(Protected):
    provider: Literal["elation", "tebra"] | None = None
    protocol: Literal["fhir"] | None = None

    @field_validator("protocol", mode="before")
    @classmethod
    def explicit_protocol(cls, value):
        if value != "fhir":
            raise ValueError("explicit_protocol_required")
        return value

    @model_validator(mode="after")
    def correct_protocol(self):
        if self.protocol is not None and (self.provider != "tebra" or getattr(self, "action", "review") not in ("status", "inspect", "resolve", "fhir_patients", "fhir_medications", "review")):
            raise ValueError("invalid_ehr_protocol")
        return self

    @field_validator("provider", mode="before")
    @classmethod
    def explicit_provider(cls, value):
        if value not in ("elation", "tebra"):
            raise ValueError("explicit_provider_required")
        return value


class Status(ProviderCommand):
    include_problems: Literal[True] | None = None
    include_medications: Literal[True] | None = None

    @field_validator("include_problems", "include_medications", mode="before")
    @classmethod
    def explicit_capability(cls, value):
        if value is not True:
            raise ValueError("explicit_capability_required")
        return value

    action: Literal["status"]


class Observe(ProviderCommand):
    action: Literal["observe"]
    connection_id: UUID
    binding_sha256: Digest
    starts_at: datetime
    ends_at: datetime
    idempotency_key: IdempotencyKey

    @model_validator(mode="after")
    def bounded(self):
        Window(starts_at=self.starts_at, ends_at=self.ends_at)
        return self


class Verify(ProviderCommand):
    last_name: str | None = Field(default=None, strict=True, min_length=1, max_length=255)
    birth_date: date | None = None

    @model_validator(mode="after")
    def patient_query(self):
        if self.provider == "tebra":
            if (self.last_name is None or self.last_name != self.last_name.strip()
                    or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in self.last_name) or self.birth_date is None
                    or not date(1850, 1, 1) <= self.birth_date <= date.today()):
                raise ValueError("exact_patient_query_required")
        elif {"last_name", "birth_date"} & self.model_fields_set:
            raise ValueError("unexpected_patient_query")
        return self

    @field_validator("birth_date", mode="before")
    @classmethod
    def exact_date(cls, value):
        if value is not None and (type(value) is not str or len(value) != 10 or date.fromisoformat(value).isoformat() != value):
            raise ValueError("exact_date_required")
        return value
    action: Literal["verify"]
    connection_id: UUID
    binding_sha256: Digest
    observation_id: UUID
    observation_sha256: Digest
    item_handle: UUID
    item_sha256: Digest
    idempotency_key: IdempotencyKey


class Problems(ProviderCommand):
    action: Literal["problems"]
    connection_id: UUID
    binding_sha256: Digest
    observation_id: UUID
    observation_sha256: Digest
    item_handle: UUID
    item_sha256: Digest
    idempotency_key: IdempotencyKey

    @model_validator(mode="after")
    def elation_only(self):
        if self.provider not in (None, "elation"):
            raise ValueError("elation_problems_required")
        return self


class Medications(ProviderCommand):
    action: Literal["medications"]
    connection_id: UUID
    binding_sha256: Digest
    observation_id: UUID
    observation_sha256: Digest
    item_handle: UUID
    item_sha256: Digest
    idempotency_key: IdempotencyKey

    @model_validator(mode="after")
    def elation_only(self):
        if self.provider not in (None, "elation"):
            raise ValueError("elation_medications_required")
        return self


class Inspect(ProviderCommand):
    action: Literal["inspect"]
    observation_id: UUID


class FhirContext(ProviderCommand):
    connection_id: UUID
    binding_sha256: Digest
    workspace_id: UUID
    idempotency_key: IdempotencyKey

    @model_validator(mode="after")
    def explicit_fhir(self):
        if self.provider != "tebra" or self.protocol != "fhir":
            raise ValueError("explicit_fhir_required")
        return self


class FhirPatients(FhirContext):
    action: Literal["fhir_patients"]


class FhirMedications(FhirContext):
    action: Literal["fhir_medications"]
    observation_id: UUID
    observation_sha256: Digest
    item_handle: UUID
    item_sha256: Digest


class Resolve(ProviderCommand):
    action: Literal["resolve"]
    idempotency_key: IdempotencyKey


class Install(ProviderCommand):
    @model_validator(mode="after")
    def elation_only(self):
        if self.provider is not None:
            raise ValueError("legacy_elation_install_shape_required")
        return self

    action: Literal["install"]
    installation_id: UUID
    installation_sha256: Digest
    idempotency_key: IdempotencyKey


EHR_COMMAND = TypeAdapter(Annotated[Status | Observe | Verify | Problems | Medications | Inspect | Resolve | Install | FhirPatients | FhirMedications, Field(discriminator="action")])


class ReviewEhr(ProviderCommand):
    expected_revision: int = Field(strict=True, ge=1)
    idempotency_key: IdempotencyKey
    observation_id: UUID
    observation_sha256: Digest
    item_handle: UUID
    item_sha256: Digest
    reviewed_visit: Literal[True] | None = None
    reviewed_patient_identity: Literal[True]
    reviewed_exact_snapshot: Literal[True]
    reviewed_untrusted_source: Literal[True]

    @model_validator(mode="after")
    def review_kind(self):
        if self.protocol == "fhir":
            if "reviewed_visit" in self.model_fields_set:
                raise ValueError("unexpected_visit_review")
        elif self.reviewed_visit is not True:
            raise ValueError("visit_review_required")
        return self

    @field_validator("reviewed_visit", "reviewed_patient_identity", "reviewed_exact_snapshot", "reviewed_untrusted_source", mode="before")
    @classmethod
    def explicit_review(cls, value):
        if value is not True:
            raise ValueError("explicit_ehr_read_review_required")
        return value
