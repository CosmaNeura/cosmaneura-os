"""Private membership review, with manual source evidence explicitly classified."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from cosmas_os.api.vendor_work_schemas import (
    ID,
    Closed,
    Confirmed,
    ContractVersion,
    Day,
    Digest,
    Document,
    Evidence,
    Goal,
    Key,
    Label,
    Output,
    Positive,
    ReviewedSource,
    Timestamp,
    public_digest,
)

Purpose = Literal["enrollment_assistance", "membership_status_review", "failed_payment_follow_up"]
Kind = Literal["propose", "decide", "result", "verify", "withdraw"]
Reference = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9:_-]{1,120}$")]
Classification = Literal[
    "local_unreconciled", "manual_ledger_record", "manual_ledger_and_finance_review"
]
MembershipState = Literal[
    "unknown", "not_enrolled", "pending_enrollment", "active", "paused", "ended"
]
BillingState = Literal["unknown", "current", "past_due", "payment_failed"]


class Proposal(Closed):
    expected_workspace_revision: Positive
    idempotency_key: Key
    source: ReviewedSource
    patient_link_id: ID
    purpose: Purpose
    due_date: Day
    expected_outcome: Goal
    instructions: Evidence


class Bound(Closed):
    ticket_id: ID
    expected_version: Positive = Field(le=100)
    revision_id: ID
    payload_hash: Digest
    idempotency_key: Key


class Decision(Bound):
    review_sha256: Digest
    choice: Literal["approve", "reject"]
    reviewed_patient: Confirmed
    reviewed_local_only_authority: Confirmed


class FinanceProof(Closed):
    ticket_id: ID
    verification_receipt_id: ID
    verification_receipt_sha256: Digest
    evidence_sha256: Digest


class LedgerProof(Closed):
    source_label: Label
    system_kind: Literal["hint", "atlas_md", "practice_owned_ledger", "other"]
    record_reference: Reference
    observed_at: Timestamp
    document: Document
    observed_membership_state: MembershipState
    observed_billing_state: BillingState
    reviewed_record_matches_patient: Confirmed
    reviewed_document: Confirmed
    finance: FinanceProof | None = None


class Result(Bound):
    disposition: Literal["local_preparation_ready", "record_reviewed", "needs_human"]
    evidence: Evidence
    ledger: LedgerProof | None = None

    @model_validator(mode="after")
    def classified_source(self):
        if (self.disposition == "record_reviewed") != (self.ledger is not None):
            raise ValueError("Only a reviewed record may carry ledger evidence")
        return self


class Verify(Bound):
    result_receipt_id: ID
    result_receipt_sha256: Digest
    evidence_classification: Classification
    reviewed_patient: Confirmed
    reviewed_result: Confirmed
    reviewed_evidence_limits: Confirmed
    confirm_review_completion: Confirmed


class Withdraw(Bound):
    confirm_withdraw: Confirmed


class Resolve(Closed):
    command_kind: Kind
    idempotency_key: Key
    request_sha256: Digest


COMMANDS = {
    "propose": Proposal,
    "decide": Decision,
    "result": Result,
    "verify": Verify,
    "withdraw": Withdraw,
}


class Scope(Closed):
    box_id: ID
    owner_id: ID
    workspace_id: ID


def request_digest(kind, scope, request):
    return public_digest(
        "cosmas-membership-request.v1",
        {"scope": scope, "command_kind": kind, "request": request.public()},
    )


class Review(Closed):
    ticket_id: ID
    revision_id: ID
    patient_link_id: ID
    proposal: Proposal
    authority: Literal["local_human_review_only"]
    automatic_membership_changes: Literal[False]
    automatic_messages_or_money_movement: Literal[False]


class Effect(Closed):
    ticket_id: ID
    revision_id: ID
    payload_hash: Digest
    version: Positive = Field(le=100)
    receipt_id: ID
    recorded_at: Timestamp
    effect: Literal[
        "proposed", "approved", "rejected", "result_recorded", "review_verified", "withdrawn"
    ]
    state: Literal["pending_approval", "approved", "rejected", "closed", "withdrawn"]
    evidence_classification: Classification
    external_service_verified: Literal[False]


class Response(Output):
    contract_version: ContractVersion
    scope: Scope
    command_kind: Kind
    idempotency_key: Key
    request_sha256: Digest
    outcome: Literal["recorded", "not_found"]
    effect: Effect | None
    receipt_sha256: Digest | None

    @model_validator(mode="after")
    def coherent(self):
        if (self.effect is not None) != (self.outcome == "recorded") or (
            self.receipt_sha256 is not None
        ) != (self.outcome == "recorded"):
            raise ValueError("Receipt outcome mismatch")
        return self


class Summary(Closed):
    ticket_id: ID
    version: Positive
    revision_id: ID
    payload_hash: Digest
    purpose: Purpose
    due_date: Day
    state: Literal["pending_approval", "approved", "rejected", "closed", "withdrawn"]
    evidence_classification: Classification
    evidence_current: Literal["none", "available", "changed"]
    result: Literal["none", "local_preparation_ready", "record_reviewed", "needs_human"]
    verification: Literal["pending", "review_verified"]
    external_service_verified: Literal[False]
    membership_authority: Literal["not_established"]
    source_current: bool
    can_verify: bool


class ResultView(Closed):
    receipt_id: ID
    receipt_sha256: Digest
    request: Result


class Detail(Output):
    contract_version: ContractVersion
    scope: Scope
    summary: Summary
    review: Review
    review_sha256: Digest
    latest_result: ResultView | None


class Options(Output):
    contract_version: ContractVersion
    scope: Scope
    patient_link_id: ID
    expected_workspace_revision: Positive
    source: ReviewedSource | None
    enabled: bool
    installed_membership_service: Literal["not_selected"]


class Catalog(Output):
    contract_version: ContractVersion
    scope: Scope
    items: list[Summary] = Field(max_length=100)


class HistoryItem(Closed):
    request: Proposal | Decision | Result | Verify | Withdraw
    receipt: Response


class History(Output):
    contract_version: ContractVersion
    scope: Scope
    ticket_id: ID
    items: list[HistoryItem] = Field(max_length=100)
