"""Current-member connection choices; no membership or scheduling mutation."""

import hashlib
import json
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

MAX_CATALOG_BYTES = 65_536


def catalog_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Choice(Closed):
    id: UUID
    label: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def safe_label(self):
        if "\0" in self.label:
            raise ValueError("invalid_connection_label")
        return self


class ZonedChoice(Choice):
    timezone: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def valid_zone(self):
        ZoneInfo(self.timezone)
        return self


class VisitChoice(Choice):
    duration_minutes: int = Field(ge=5, le=480, strict=True)


class ConnectionContent(Closed):
    contract_version: Literal["1"] = "1"
    practice: Choice
    actor_id: UUID
    role: Literal["owner", "admin", "staff"]
    practitioner: ZonedChoice | None
    locations: tuple[ZonedChoice, ...] = Field(max_length=50)
    appointment_types: tuple[VisitChoice, ...] = Field(max_length=50)

    @model_validator(mode="after")
    def unique_choices(self):
        if len({v.id for v in self.locations}) != len(self.locations) or len(
            {v.id for v in self.appointment_types}
        ) != len(self.appointment_types):
            raise ValueError("duplicate_connection_choice")
        return self


class ConnectionCatalog(ConnectionContent):
    observed_at: AwareDatetime
    catalog_sha256: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)

    @model_validator(mode="after")
    def exact_catalog(self):
        if (
            catalog_digest(self.model_dump(mode="json", exclude={"observed_at", "catalog_sha256"}))
            != self.catalog_sha256
        ):
            raise ValueError("invalid_connection_catalog")
        return self


class EnrollmentCommand(Closed):
    action: Literal[
        "enrollment_status",
        "enrollment_start",
        "enrollment_cancel",
        "enrollment_review",
        "enrollment_confirm",
        "enrollment_result",
    ]
    attempt_ref: UUID | None = None
    catalog_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$", strict=True)
    location_id: UUID | None = None
    appointment_type_id: UUID | None = None
    command_key: UUID | None = None
    command_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$", strict=True)
    plan_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$", strict=True)
    confirmed: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def exact_fields(self):
        fields = {
            "enrollment_status": set(),
            "enrollment_start": set(),
            "enrollment_cancel": set(),
            "enrollment_review": {
                "attempt_ref",
                "catalog_sha256",
                "location_id",
                "appointment_type_id",
                "command_key",
            },
            "enrollment_confirm": {
                "attempt_ref",
                "catalog_sha256",
                "location_id",
                "appointment_type_id",
                "command_key",
                "plan_sha256",
                "confirmed",
            },
            "enrollment_result": {"attempt_ref", "command_key", "command_sha256"},
        }[self.action]
        optional = {
            "attempt_ref",
            "catalog_sha256",
            "location_id",
            "appointment_type_id",
            "command_key",
            "command_sha256",
            "plan_sha256",
            "confirmed",
        }
        if (
            {name for name in optional if getattr(self, name) is not None} != fields
            or self.confirmed is not None
            and self.confirmed is not True
        ):
            raise ValueError("invalid_scheduling_enrollment_request")
        return self


def enrollment_command_digest(command: EnrollmentCommand) -> str:
    return catalog_digest(command.model_dump(mode="json", exclude_none=True))
