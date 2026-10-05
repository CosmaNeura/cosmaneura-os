"""Existing Core provider-encounter v1 catalog; no creation or matching authority."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from cosmas_os.ports.core_encounters import (
    ActorRef,
    AppointmentRef,
    Closed,
    Label,
    PatientRef,
    TenantRef,
    TypeSuffix,
)


class ScribeCatalogAccount(Closed):
    actor_ref: ActorRef
    tenant_ref: TenantRef
    doctor_ref: Annotated[str, Field(pattern=r"^doctor" + TypeSuffix, strict=True)]
    email: str = Field(min_length=1, max_length=320, strict=True, repr=False)


class ScribeCatalogEncounter(Closed):
    workspace_id: UUID
    appointment_ref: AppointmentRef
    patient_ref: PatientRef
    patient_name: Label = Field(repr=False)
    title: Label = Field(repr=False)
    appointment_at: AwareDatetime
    # Optional display metadata adds no encounter or recording authority.
    date_of_birth: date | None = Field(default=None, repr=False)
    status: Literal["recording_saved", "draft_ready"] | None = None

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def canonical_birth_date(cls, value):
        if value is None or type(value) is date:
            return value
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError("invalid_birth_date")
        return value


class ScribeCatalog(Closed):
    version: Literal["1"]
    action: Literal["list"]
    request_nonce: UUID
    account: ScribeCatalogAccount = Field(repr=False)
    encounters: tuple[ScribeCatalogEncounter, ...] = Field(max_length=1000, repr=False)

    @model_validator(mode="after")
    def unambiguous(self):
        for key in ("workspace_id", "appointment_ref"):
            if len({getattr(row, key) for row in self.encounters}) != len(self.encounters):
                raise ValueError("ambiguous_scribe_catalog")
        return self
