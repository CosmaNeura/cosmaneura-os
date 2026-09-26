"""Explicit selected-context publication; no message, grant or endpoint authority input."""

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
    Goal,
    Key,
    Message,
    Output,
    Positive,
    Timestamp,
)

Kind = Literal["propose", "decide", "handoff", "result", "verify"]


class Propose(Closed):
    idempotency_key: Key
    item_id: ID
    source_id: ID
    source_sha256: Digest
    review_receipt_id: ID
    review_receipt_sha256: Digest
    expected_workspace_revision: Positive
    instructions: Message
    selected_context: Evidence | None = None
    due_date: Day
    expected_outcome: Goal
    reviewed_minimum_context: Confirmed


class Bound(Closed):
    idempotency_key: Key
    ticket_id: ID
    expected_version: Positive
    revision_id: ID
    payload_hash: Digest


class Decide(Bound):
    choice: Literal["approve", "reject"]
    publish_selected_context: Confirmed


class Handoff(Bound):
    kind: Literal["offer", "accept", "decline", "recall", "reclaim"]
    recipient_id: ID | None = None
    offer_id: ID | None = None

    @model_validator(mode="after")
    def shape(self):
        if (self.kind == "offer") != (self.recipient_id is not None):
            raise ValueError("Only offer names a recipient")
        if (self.kind in {"accept", "decline", "recall"}) != (self.offer_id is not None):
            raise ValueError("A response names the exact offer")
        return self


class Result(Bound):
    evidence: Evidence
    no_external_action_claimed: Confirmed


class Verify(Bound):
    result_receipt_id: ID
    result_request_sha256: Digest
    reviewed_current_source: Confirmed
    reviewed_result: Confirmed
    local_handoff_only: Confirmed


class Resolve(Closed):
    command_kind: Kind
    idempotency_key: Key
    request_sha256: Digest


COMMANDS = {
    "propose": Propose,
    "decide": Decide,
    "handoff": Handoff,
    "result": Result,
    "verify": Verify,
}

Reason = Literal[
    "feature_disabled",
    "source_changed",
    "review_changed",
    "authority_changed",
    "work_changed",
    "publication_required",
    "result_already_recorded",
    "responsibility_required",
    "responsibility_changed",
    "result_changed",
]


class Scope(Output):
    box_id: ID
    owner_id: ID
    actor_id: ID
    kind: Literal["workspace", "ticket"]
    id: ID


class Effect(Output):
    ticket_id: ID
    version: Positive
    revision_id: ID
    payload_hash: Digest
    effect_id: ID
    state: Literal["pending_approval", "approved", "closed", "rejected"]


class Response(Output):
    contract_version: ContractVersion
    scope: Scope
    command_kind: Kind
    idempotency_key: Key
    request_sha256: Digest
    outcome: Literal["recorded", "rejected"]
    effect: Effect | None
    rejection: Reason | None
    receipt_id: ID
    recorded_at: Timestamp
    receipt_sha256: Digest

    @model_validator(mode="after")
    def consistent(self):
        if (self.outcome == "recorded") != (self.effect is not None and self.rejection is None):
            raise ValueError("Recorded effects and rejected requests remain distinct")
        if self.outcome == "rejected" and (self.effect is not None or self.rejection is None):
            raise ValueError("Rejected requests have no effect")
        return self


class Responsibility(Output):
    id: ID
    kind: Literal["offer", "accept", "decline", "recall", "reclaim"]
    from_id: ID
    to_id: ID
    offer_id: ID | None


class SavedResult(Output):
    receipt_id: ID
    request_sha256: Digest
    actor_id: ID
    evidence: Evidence


class PrivateSource(Output):
    item_id: ID
    source_id: ID
    source_sha256: Digest
    review_receipt_id: ID
    review_receipt_sha256: Digest
    unavailability: Reason | None


class Summary(Output):
    contract_version: ContractVersion
    work_kind: Literal["incoming_message"]
    ticket_id: ID
    version: Positive
    revision_id: ID
    payload_hash: Digest
    state: Literal["pending_approval", "approved", "closed", "rejected", "source_unavailable"]
    publication_active: bool
    requires_owner_attention: bool
    originator_id: ID
    originator_available: bool
    responsible_id: ID
    publication_receipt_id: ID | None
    verified_current: bool
    external_action_performed: Literal[False]


class Detail(Summary):
    instructions: Message | None
    selected_context: Evidence | None
    due_date: Day | None
    expected_outcome: Goal | None
    result: SavedResult | None
    handoffs: list[Responsibility] = Field(max_length=201)
    private_source: PrivateSource | None = None


class Catalog(Output):
    contract_version: ContractVersion
    items: list[Summary] = Field(max_length=100)
