"""Closed financial work protocol; a PaymentIntent creation is never a payment."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from cosmas_os.api.vendor_work_schemas import (
    ID,
    BoundCommand,
    Closed,
    Day,
    Digest,
    Evidence,
    Goal,
    Key,
    Label,
    ObservationHead,
    Positive,
    ProviderError,
    ReviewedSource,
    Revision,
    Selection,
    Timestamp,
    VendorVerify,
    public_digest,
)

Amount = Annotated[int, Field(strict=True, ge=50, le=99_999_999)]
PaymentState = Literal[
    "not_observed",
    "requires_payment_method",
    "requires_confirmation",
    "requires_action",
    "processing",
    "requires_capture",
    "canceled",
    "succeeded",
    "unknown",
]
CommandKind = Literal["propose", "decide", "withdraw", "submit", "reconcile", "result", "verify"]


class FinanceProposal(Closed):
    expected_workspace_revision: Positive
    idempotency_key: Key
    proposed_operation_id: ID
    source: ReviewedSource
    connection: Selection
    customer: Selection
    amount: Amount
    currency: Literal["usd"]
    due_date: Day
    expected_outcome: Goal
    revises: Revision | None = None


class FinanceDecision(BoundCommand):
    review_sha256: Digest
    choice: Literal["approve", "reject"]


class FinanceResult(BoundCommand):
    observation_head: ObservationHead
    evidence_sha256: Digest
    disposition: Literal[
        "reported_paid", "reported_unpaid", "verified_in_processor", "unable_to_establish"
    ]
    evidence: Evidence


class FinanceVerify(VendorVerify):
    """Exact owner attestation fields; no payment confirm/capture instruction."""


class FinanceResolve(Closed):
    command_kind: CommandKind
    idempotency_key: Key
    request_sha256: Digest


class FinanceConnectionView(Closed):
    id: ID
    revision: Positive
    environment: Literal["production", "sandbox"]
    label: Label
    availability: Literal["enabled", "read_only", "unavailable"]
    public_sha256: Digest


class FinanceCustomerView(Closed):
    id: ID
    revision: Positive
    connection_id: ID
    label: Label
    availability: Literal["reviewed", "unavailable"]
    public_sha256: Digest


def request_digest(kind, scope, request):
    return public_digest(
        "cosmas-finance-public-request.v1",
        {"command_kind": kind, "scope": scope, "request": request.public()},
    )


class FinanceReview(Closed):
    ticket_id: ID
    revision_id: ID
    operation_id: ID
    connection: FinanceConnectionView
    customer: FinanceCustomerView
    source: ReviewedSource
    amount: Amount
    currency: Literal["usd"]
    due_date: Day
    expected_outcome: Goal
    expires_at: Timestamp
    processor_confirmation: Literal["not_requested"]


from cosmas_os.api.vendor_work_schemas import (  # noqa: E402
    ContractVersion,
    Output,
    WorkState,
)


class FinanceEffect(Closed):
    ticket_id: ID
    revision_id: ID
    operation_id: ID
    payload_hash: Digest
    receipt_id: ID
    effect_version: Positive
    recorded_at: Timestamp
    effect: Literal[
        "proposed",
        "approved",
        "rejected",
        "withdrawn",
        "submit_claimed",
        "read_claimed",
        "result_recorded",
        "verified",
    ]


class FinanceScope(Closed):
    kind: Literal["workspace"]
    id: ID


class FinanceResponse(Output):
    contract_version: ContractVersion
    scope: FinanceScope
    command_kind: CommandKind
    idempotency_key: Key
    request_sha256: Digest
    outcome: Literal["recorded", "not_found"]
    effect: FinanceEffect | None
    receipt_sha256: Digest | None
    observed_at: Timestamp

    @model_validator(mode="after")
    def coherent_receipt(self):
        if (self.effect is not None) != (self.outcome == "recorded") or (
            self.receipt_sha256 is not None
        ) != (self.outcome == "recorded"):
            raise ValueError("receipt outcome mismatch")
        if self.effect is not None:
            expected = {
                "propose": {"proposed"},
                "decide": {"approved", "rejected"},
                "withdraw": {"withdrawn"},
                "submit": {"submit_claimed"},
                "reconcile": {"read_claimed"},
                "result": {"result_recorded"},
                "verify": {"verified"},
            }
            if self.effect.effect not in expected[self.command_kind]:
                raise ValueError("receipt command mismatch")
        return self


class FinanceSummary(Closed):
    ticket_id: ID
    version: Positive
    revision_id: ID
    operation_id: ID
    payload_hash: Digest
    state: WorkState
    amount: Amount
    currency: Literal["usd"]
    creation: Literal["not_observed", "accepted", "rejected", "unconfirmed"]
    payment_state: PaymentState
    amount_received: Annotated[int, Field(strict=True, ge=0, le=99_999_999)]
    submit_claimed: bool
    conflicting_evidence: bool
    result: Literal[
        "none", "reported_paid", "reported_unpaid", "verified_in_processor", "unable_to_establish"
    ]
    verification: Literal["pending", "verified"]
    observation_head: ObservationHead
    evidence_sha256: Digest


class FinanceHumanResult(Closed):
    receipt_id: ID
    receipt_sha256: Digest
    disposition: Literal[
        "reported_paid", "reported_unpaid", "verified_in_processor", "unable_to_establish"
    ]
    evidence: Evidence
    observation_head: ObservationHead
    recorded_at: Timestamp


class FinanceDetail(Output):
    contract_version: ContractVersion
    workspace_id: ID
    summary: FinanceSummary
    review: FinanceReview
    review_sha256: Digest
    latest_result: FinanceHumanResult | None


class FinanceOptions(Output):
    contract_version: ContractVersion
    workspace_id: ID
    expected_workspace_revision: Positive
    source: ReviewedSource | None
    enabled: bool
    connections: Annotated[list[FinanceConnectionView], Field(max_length=50)]
    customers: Annotated[list[FinanceCustomerView], Field(max_length=50)]


FinanceCursor = Annotated[
    str, Field(strict=True, min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+\.[a-f0-9]{64}$")
]


class FinanceCatalog(Output):
    contract_version: ContractVersion
    workspace_id: ID
    items: Annotated[list[FinanceSummary], Field(max_length=25)]
    next_cursor: FinanceCursor | None


class FinanceObservationBase(Closed):
    id: ID
    sequence: Positive
    operation_id: ID
    recorded_at: Timestamp
    sha256: Digest


class FinanceDispatch(FinanceObservationBase):
    kind: Literal["dispatch"]
    dispatch: Literal["invocation_started", "proved_not_dispatched", "unconfirmed"]
    safe_error: ProviderError | None = None


class FinanceCreation(FinanceObservationBase):
    kind: Literal["creation"]
    acceptance: Literal["accepted", "rejected", "unconfirmed"]
    safe_error: ProviderError | None = None


class FinancePayment(FinanceObservationBase):
    kind: Literal["payment"]
    payment_state: PaymentState
    amount: Amount
    currency: Literal["usd"]
    amount_received: Annotated[int, Field(strict=True, ge=0, le=99_999_999)]
    livemode: bool | None = None
    safe_error: ProviderError | None = None

    @model_validator(mode="after")
    def coherent_amount(self):
        if self.amount_received > self.amount or (
            self.payment_state == "succeeded" and self.amount_received != self.amount
        ):
            raise ValueError("payment amount mismatch")
        return self


class FinanceObservations(Output):
    contract_version: ContractVersion
    workspace_id: ID
    ticket_id: ID
    operation_id: ID
    observations: Annotated[
        list[
            Annotated[
                FinanceDispatch | FinanceCreation | FinancePayment, Field(discriminator="kind")
            ]
        ],
        Field(max_length=20),
    ]
    observation_head: ObservationHead
    next_cursor: FinanceCursor | None
