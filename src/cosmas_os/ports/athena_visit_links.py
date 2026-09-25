"""Exact reviewed pairing of an Athena observation and an existing Core visit."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from cosmas_os.ports.athena_schedule import AthenaAppointment, AthenaScheduleAccount, VendorID
from cosmas_os.ports.core_encounters import (
    AppointmentRef,
    Closed,
    ConnectedRequest,
    ConnectionSnapshot,
    Digest,
    EncounterSnapshot,
    TypeSuffix,
    digest,
)

VisitLinkRef = Annotated[str, Field(pattern=r"^athena_visit_link" + TypeSuffix, strict=True)]
MAX_RESPONSE_BYTES = 16_384


class AthenaSourceSelection(Closed):
    start_date: date
    end_date: date
    offset: int = Field(ge=0, le=10_000, strict=True)
    appointment_ref: VendorID
    source_sha256: Digest

    @model_validator(mode="after")
    def window(self):
        if not 0 <= (self.end_date - self.start_date).days < 31:
            raise ValueError("invalid_athena_visit_window")
        return self


class AthenaVisitLinkRequest(ConnectedRequest):
    action: Literal["lookup", "preview", "link", "status", "unlink_preview", "unlink"]
    account_sha256: Digest
    source: AthenaSourceSelection | None = None
    appointment_ref: AppointmentRef | None = None
    core_source_sha256: Digest | None = None
    link_ref: VisitLinkRef | None = None
    plan_sha256: Digest | None = None
    command_key: UUID | None = None
    command_sha256: Digest | None = None
    confirmed: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def fields_for_action(self):
        required = {
            "lookup": {"source"},
            "preview": {
                "source",
                "appointment_ref",
                "core_source_sha256",
                "command_key",
            },
            "link": {
                "source",
                "appointment_ref",
                "core_source_sha256",
                "command_key",
                "plan_sha256",
                "confirmed",
            },
            "status": {"command_key", "command_sha256"},
            "unlink_preview": {"link_ref", "command_key"},
            "unlink": {"link_ref", "command_key", "plan_sha256", "confirmed"},
        }[self.action]
        optional = {
            "source",
            "appointment_ref",
            "core_source_sha256",
            "link_ref",
            "plan_sha256",
            "command_key",
            "command_sha256",
            "confirmed",
        }
        if (
            {name for name in optional if getattr(self, name) is not None} != required
            or self.confirmed is not None
            and self.confirmed is not True
        ):
            raise ValueError("invalid_athena_visit_link_fields")
        return self


class AthenaVisitLinkResponse(Closed):
    contract_version: Literal["1"] = "1"
    action: Literal["lookup", "preview", "link", "status", "unlink_preview", "unlink"]
    request_nonce: UUID
    checked_at: AwareDatetime
    connection: ConnectionSnapshot
    account: AthenaScheduleAccount
    state: Literal["not_linked", "ready", "linked", "removed", "review_required", "not_found"]
    source: AthenaAppointment | None = None
    encounter: EncounterSnapshot | None = None
    link_ref: VisitLinkRef | None = None
    plan_sha256: Digest | None = None
    command_key: UUID | None = None
    command_sha256: Digest | None = None
    operation: Literal["link", "unlink"] | None = None
    applied: bool = Field(default=False, strict=True)


def command_digest(request: AthenaVisitLinkRequest) -> str:
    return digest(request.model_dump(mode="json", exclude_none=True, exclude={"request_nonce"}))


class AthenaVisitLinkCommand(Closed):
    request_nonce: UUID
    connection_sha256: Digest
    action: Literal[
        "athena_visit_lookup",
        "athena_visit_preview",
        "athena_visit_link",
        "athena_visit_status",
        "athena_visit_unlink_preview",
        "athena_visit_unlink",
    ]
    account_sha256: Digest
    source: AthenaSourceSelection | None = None
    appointment_ref: AppointmentRef | None = None
    core_source_sha256: Digest | None = None
    link_ref: VisitLinkRef | None = None
    plan_sha256: Digest | None = None
    command_key: UUID | None = None
    command_sha256: Digest | None = None
    confirmed: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def fields_for_action(self):
        required = {
            "athena_visit_lookup": {"source"},
            "athena_visit_preview": {
                "source",
                "appointment_ref",
                "core_source_sha256",
                "command_key",
            },
            "athena_visit_link": {
                "source",
                "appointment_ref",
                "core_source_sha256",
                "command_key",
                "plan_sha256",
                "confirmed",
            },
            "athena_visit_status": {"command_key", "command_sha256"},
            "athena_visit_unlink_preview": {"link_ref", "command_key"},
            "athena_visit_unlink": {"link_ref", "command_key", "plan_sha256", "confirmed"},
        }[self.action]
        optional = {
            "source",
            "appointment_ref",
            "core_source_sha256",
            "link_ref",
            "plan_sha256",
            "command_key",
            "command_sha256",
            "confirmed",
        }
        if (
            {name for name in optional if getattr(self, name) is not None} != required
            or self.confirmed is not None
            and self.confirmed is not True
        ):
            raise ValueError("invalid_athena_visit_link_fields")
        return self

    def as_core(self, tenant_ref, actor_ref):
        return AthenaVisitLinkRequest.model_validate(
            {
                **self.model_dump(mode="json", exclude_none=True),
                "action": self.action.removeprefix("athena_visit_"),
                "expected_tenant_ref": tenant_ref,
                "expected_actor_ref": actor_ref,
            }
        )
