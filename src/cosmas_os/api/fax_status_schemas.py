"""Minimal saved fax facts; no provider account, destination or clinical content."""

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from cosmas_os.api.vendor_work_schemas import (
    ID,
    Acceptance,
    ContractVersion,
    Digest,
    Dispatch,
    ObservationHead,
    Positive,
    ResultState,
    Timestamp,
    Transport,
    Verification,
    WorkState,
)
from cosmas_os.ports.scribe_capture import ProtectedModel


class Closed(ProtectedModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True, strict=True)

    def public(self):
        return self.model_dump(mode="json")


class FaxScope(Closed):
    box_id: ID
    owner_id: ID
    workspace_id: ID


class FaxStep(Closed):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z_]+$")
    label: str = Field(min_length=1, max_length=240)
    requires_human: bool


class FaxRecordedCheck(Closed):
    id: ID
    sha256: Digest
    sequence: int = Field(strict=True, ge=1, le=2147483647)
    observed_at: Timestamp
    recorded_at: Timestamp


class FaxPages(Closed):
    observation: FaxRecordedCheck
    total: int = Field(strict=True, ge=0, le=1_000_000)
    delivered: int = Field(strict=True, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def paired_counts(self):
        if self.delivered > self.total:
            raise ValueError("invalid reported page counts")
        return self


class FaxStatus(Closed):
    contract_version: ContractVersion
    scope: FaxScope
    ticket_id: ID
    operation_id: ID
    revision_id: ID
    payload_hash: Digest
    provider: Literal["spruce", "srfax", "documo", "efax"]
    state: WorkState
    version: Positive
    acceptance: Acceptance
    dispatch: Dispatch
    transport: Transport
    result: ResultState
    verification: Verification
    conflicting_evidence: bool
    source_current: bool | None
    original_account_available: bool
    responsible_id: ID
    status_label: str = Field(min_length=1, max_length=160)
    next_step: FaxStep
    external_outcome: Literal["not_established", "unconfirmed", "provider_transport_delivered", "provider_transport_failed", "spruce_posted_delivery_unconfirmed"]
    observation_head: ObservationHead
    evidence_sha256: Digest
    last_recorded: FaxRecordedCheck | None
    pages: FaxPages | None
    observed_at: Timestamp
    sha256: Digest

    @model_validator(mode="after")
    def evidence_binding(self):
        if ((self.last_recorded is None) != (self.observation_head.sequence == 0) or
            self.last_recorded and self.last_recorded.sequence != self.observation_head.sequence or
            self.pages and self.pages.observation.sequence > self.observation_head.sequence or
            self.provider == "spruce" and self.external_outcome.startswith("provider_transport_")):
            raise ValueError("invalid saved fax evidence binding")
        return self
