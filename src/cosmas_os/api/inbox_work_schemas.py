"""Private owner Inbox contract. External source text is never a command input."""

from typing import Literal

from pydantic import Field, model_validator

from cosmas_os.api.vendor_work_schemas import (
    ID,
    Closed,
    Confirmed,
    ContractVersion,
    Day,
    Digest,
    Evidence,
    Key,
    Output,
    Positive,
    Timestamp,
    public_digest,
)
from cosmas_os.ports.vendor_inbox import AttachmentKind

Kind = Literal["review", "triage", "result", "verify"]
State = Literal[
    "needs_review", "reviewed", "triaged", "result_recorded", "closed_local_review", "needs_human"
]
Reason = Literal[
    "inbox_version_changed",
    "inbox_source_changed",
    "inbox_binding_unavailable",
    "inbox_workspace_changed",
    "inbox_review_required",
    "inbox_triage_required",
    "inbox_result_changed",
    "inbox_exception_unresolved",
    "inbox_feature_disabled",
    "inbox_history_limit",
]
Classification = Literal[
    "administrative_review", "clinical_human_review", "urgent_human_review", "source_exception"
]
ReadError = Literal[
    "authority_required",
    "reference_unavailable",
    "response_invalid",
    "response_too_large",
    "provider_throttled",
    "provider_unavailable",
    "request_timeout",
    "source_scope_changed",
]


class Scope(Output):
    box_id: ID
    owner_id: ID


class Bound(Closed):
    item_id: ID
    expected_version: Positive
    source_id: ID | None = None
    source_sha256: Digest | None = None
    idempotency_key: Key

    @model_validator(mode="after")
    def complete_source_binding(self):
        if (self.source_id is None) != (self.source_sha256 is None):
            raise ValueError("Both exact source fields are required together")
        return self


class Review(Bound):
    workspace_id: ID
    expected_workspace_revision: Positive
    patient_link_id: ID
    reviewed_patient: Confirmed
    reviewed_exact_thread: Confirmed
    reviewed_untrusted_source: Confirmed


class Triage(Bound):
    classification: Classification
    due_date: Day
    instructions: Evidence
    human_disposition_required: Confirmed


class Result(Bound):
    triage_receipt_id: ID
    triage_receipt_sha256: Digest
    disposition: Literal["local_review_complete", "needs_human"]
    evidence: Evidence
    no_external_action_claimed: Confirmed


class Verify(Bound):
    result_receipt_id: ID
    result_receipt_sha256: Digest
    reviewed_patient: Confirmed
    reviewed_exact_source: Confirmed
    reviewed_human_result: Confirmed
    confirm_local_review_only: Confirmed


class Resolve(Closed):
    item_id: ID
    command_kind: Kind
    idempotency_key: Key
    request_sha256: Digest


class Effect(Output):
    item_id: ID
    version: Positive
    source_id: ID | None
    source_sha256: Digest | None
    state: State


class Receipt(Output):
    contract_version: ContractVersion
    scope: Scope
    command_kind: Kind
    idempotency_key: Key
    request_sha256: Digest
    outcome: Literal["recorded", "rejected", "not_found"]
    effect: Effect | None
    rejection: Reason | None
    receipt_id: ID | None
    recorded_at: Timestamp | None
    receipt_sha256: Digest | None

    @model_validator(mode="after")
    def coherent_outcome(self):
        durable = self.outcome != "not_found"
        if durable != all(
            x is not None for x in (self.receipt_id, self.recorded_at, self.receipt_sha256)
        ):
            raise ValueError("Exact durable receipt required")
        if self.outcome == "recorded" and (self.effect is None or self.rejection is not None):
            raise ValueError("Recorded effect required")
        if self.outcome == "rejected" and (self.effect is not None or self.rejection is None):
            raise ValueError("Permanent rejection proof required")
        if self.outcome == "not_found" and any(
            x is not None
            for x in (
                self.effect,
                self.rejection,
                self.receipt_id,
                self.recorded_at,
                self.receipt_sha256,
            )
        ):
            raise ValueError("Missing receipt has no effect or proof")
        return self


class SourceMetadata(Output):
    source_id: ID
    sequence: Positive
    source_sha256: Digest
    created_at: Timestamp
    modified_at: Timestamp
    observed_at: Timestamp
    incomplete_content: bool


class Source(SourceMetadata):
    vendor: Literal["spruce"]
    conversation_id: str = Field(max_length=255)
    item_reference: str = Field(max_length=255)
    contact_id: str = Field(max_length=255)
    patient_link_id: ID
    correspondence_version_id: ID
    correspondence_public_sha256: Digest
    text: str = Field(max_length=16384)
    attachments: bool
    attachment_types: list[AttachmentKind] = Field(max_length=10)
    pages: bool
    buttons: bool
    event: bool
    conversation_archived: bool
    conversation_read_only: bool
    item_response_sha256: Digest
    conversation_response_sha256: Digest
    trust: Literal["untrusted_external_text"]
    projection_sha256: Digest


class Summary(Output):
    item_id: ID
    version: Positive
    label: str = Field(max_length=80)
    patient_link_id: ID
    source_id: ID | None
    source_sha256: Digest | None
    state: State
    source_conflict: bool
    read_issue: ReadError | None
    binding_current: bool
    incomplete_content: bool
    workspace_id: ID | None
    workspace_current: bool
    classification: Classification | None
    human_review_required: Literal[True]
    vendor_latest_state_verified: Literal[False]
    external_action_performed: Literal[False]
    handoff_available: Literal[False]


class Availability(Output):
    review: bool
    triage: bool
    result: bool
    verify: bool
    history_capacity_remaining: int = Field(ge=0, le=100)


class Detail(Output):
    contract_version: ContractVersion
    scope: Scope
    summary: Summary
    source: Source | None
    latest_review: Receipt | None
    latest_triage: Receipt | None
    latest_result: Receipt | None
    latest_verification: Receipt | None
    availability: Availability


class Catalog(Output):
    contract_version: ContractVersion
    scope: Scope
    enabled: bool
    items: list[Summary] = Field(max_length=100)


class HistoryItem(Output):
    request: Review | Triage | Result | Verify
    receipt: Receipt


class ReadHistory(Output):
    id: ID
    item_id: ID
    version: Positive
    outcome: Literal["new", "newer", "older", "same", "conflict", "failure"]
    source_id: ID | None
    source_sha256: Digest | None
    safe_error: ReadError | None
    observed_at: Timestamp | None
    item_response_sha256: Digest | None
    conversation_response_sha256: Digest | None
    request_sha256: Digest
    grant_sha256: Digest
    recorded_at: Timestamp
    receipt_sha256: Digest


class History(Output):
    contract_version: ContractVersion
    scope: Scope
    item_id: ID
    sources: list[SourceMetadata] = Field(max_length=50)
    reads: list[ReadHistory] = Field(max_length=100)
    commands: list[HistoryItem] = Field(max_length=100)


COMMANDS = {"review": Review, "triage": Triage, "result": Result, "verify": Verify}


def request_digest(kind, scope, request):
    return public_digest(
        "cosmas-inbox-request.v1",
        {
            "scope": scope,
            "command_kind": kind,
            "request": request.public(),
        },
    )
