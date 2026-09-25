"""Closed owner activity projection; navigation is never execution authority."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, NaiveDatetime, model_validator

from cosmas_os.api.model_work_schemas import AdmissionObservation, AdmittedBot

MAX_RESPONSE_BYTES = 65536
PAGE_SIZE = 20
View = Literal["attention", "recent"]
Cursor = Annotated[str, Field(pattern=r"^a1[0-9a-f]{128}$")]
Count = Annotated[int, Field(strict=True, ge=0, le=999999999999)]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Policy(Closed):
    version: Literal[1]
    max_attempts_per_24h: Annotated[int, Field(strict=True, ge=0, le=1000)]


class Usage(Closed):
    contract_version: Literal[1]
    policy: Policy | None
    team_revision: Count
    as_of: AwareDatetime
    window_start: AwareDatetime
    admitted_units: Count
    occupied_units: Count
    remaining_units: Count | None
    pending_units: Count
    unknown_units: Count
    verified_input_tokens: Count | None
    verified_output_tokens: Count | None
    usage_complete: bool
    coverage: Literal["new_admissions_and_retained_legacy_records"]


class Encounter(Closed):
    workspace_id: UUID
    appointment_id: UUID
    label: str = Field(min_length=1, max_length=200)
    starts_at: AwareDatetime | None
    source_local_start: NaiveDatetime | None = None
    entry_id: UUID

    @model_validator(mode="after")
    def source_time(self):
        if (self.starts_at is None) == (self.source_local_start is None):
            raise ValueError("one source time required")
        return self


class ActivityRow(Closed):
    kind: Literal["conversation", "private_handoff"]
    bot: AdmittedBot
    encounter: Encounter
    admission: AdmissionObservation


class Coverage(Closed):
    rows: Literal["durable_admissions_only"]
    paging: Literal["live_current_access"]
    attention_total: Count
    recent_total: Count
    withheld_total: Count
    legacy_rows_included: Literal[False]


class Page(Closed):
    limit: Literal[20]
    cursor: Cursor | None
    next_cursor: Cursor | None
    has_more: bool

    @model_validator(mode="after")
    def consistent(self):
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("invalid activity pagination")
        return self


class ActivityResponse(Closed):
    contract_version: Literal[1, 2]
    box_id: UUID
    owner_id: UUID
    recovery_scope: str = Field(pattern=r"^[a-f0-9]{64}$")
    view: View
    as_of: AwareDatetime
    page: Page
    coverage: Coverage
    usage: Usage
    rows: list[ActivityRow] = Field(max_length=PAGE_SIZE)

    @model_validator(mode="after")
    def consistent(self):
        ids = [row.admission.id for row in self.rows]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate activity row")
        for row in self.rows:
            if self.contract_version == 1 and row.encounter.starts_at is None:
                raise ValueError("legacy activity requires known instant")
            pending = row.admission.state in {"reserved", "running", "unknown"}
            if pending != (self.view == "attention") or row.admission.admitted_at > self.as_of:
                raise ValueError("invalid activity view")
        if self.page.has_more and len(self.rows) != PAGE_SIZE:
            raise ValueError("incomplete activity page")
        return self
