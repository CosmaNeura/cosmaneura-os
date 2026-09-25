"""Closed owner finance settings; no credentials, URLs or processor commands."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from cosmas_os.api.vendor_work_schemas import (
    ID,
    Closed,
    Confirmed,
    Counter,
    Digest,
    Key,
    Label,
    Output,
    Positive,
    Timestamp,
    public_digest,
)

CustomerID = Annotated[str, Field(strict=True, pattern=r"^cus_[A-Za-z0-9]{1,240}$")]
AccountID = Annotated[str, Field(strict=True, pattern=r"^acct_[A-Za-z0-9]{1,240}$")]
Kind = Literal["account", "customer"]
CommandKind = Literal["propose_account", "propose_customer", "activate", "disable", "revoke"]
State = Literal["pending_review", "active", "disabled", "revoked"]


class Scope(Output):
    box_id: ID
    owner_id: ID


class Permissions(Closed):
    read_status: bool = Field(strict=True)
    create_unconfirmed_intents: bool = Field(strict=True)

    @model_validator(mode="after")
    def some_permission(self):
        if not self.read_status and not self.create_unconfirmed_intents:
            raise ValueError("Select at least one local permission")
        return self


class InstalledAccount(Output):
    installation_id: ID
    installation_sha256: Digest
    label: Label
    environment: Literal["sandbox", "production"]
    account_reference: AccountID


class Binding(Closed):
    setup_id: ID
    expected_version: Positive = Field(le=100)
    revision_id: ID
    review_sha256: Digest


class AccountProposal(Closed):
    setup_id: ID
    expected_version: Counter = Field(le=100)
    idempotency_key: Key
    installation_id: ID
    installation_sha256: Digest
    label: Label
    permissions: Permissions


class CustomerProposal(Closed):
    setup_id: ID
    expected_version: Counter = Field(le=100)
    idempotency_key: Key
    account: Binding
    patient_link_id: ID
    customer_id: CustomerID
    label: Label


class Bound(Binding):
    idempotency_key: Key


class Activation(Bound):
    reviewed_account: Confirmed
    reviewed_environment: Confirmed
    reviewed_patient_customer: Confirmed | None = None
    confirm_local_activation: Confirmed


class Disable(Bound):
    confirm_disable: Confirmed


class Revoke(Bound):
    confirm_revoke: Confirmed


class Resolve(Closed):
    command_kind: CommandKind
    idempotency_key: Key
    request_sha256: Digest


class Patient(Output):
    patient_link_id: ID
    label: Label


class AccountReview(Output):
    kind: Literal["account"]
    setup_id: ID
    revision_id: ID
    revision: Positive = Field(le=20)
    installed: InstalledAccount
    label: Label
    permissions: Permissions
    connection_version_id: ID


class CustomerReview(Output):
    kind: Literal["customer"]
    setup_id: ID
    revision_id: ID
    revision: Positive = Field(le=20)
    installed: InstalledAccount
    label: Label
    account: Binding
    account_label: Label
    connection_version_id: ID
    customer_version_id: ID
    patient: Patient
    customer_id: CustomerID


Review = Annotated[AccountReview | CustomerReview, Field(discriminator="kind")]


class Effect(Output):
    setup_id: ID
    kind: Kind
    version: Positive = Field(le=100)
    revision_id: ID
    review_sha256: Digest
    state: State


class Receipt(Output):
    contract_version: Literal[1]
    outcome: Literal["recorded"]
    scope: Scope
    command_kind: CommandKind
    idempotency_key: Key
    request_sha256: Digest
    receipt_id: ID
    recorded_at: Timestamp
    effect: Effect
    receipt_sha256: Digest


class NotFound(Output):
    contract_version: Literal[1]
    outcome: Literal["not_found"]
    scope: Scope
    command_kind: CommandKind
    idempotency_key: Key
    request_sha256: Digest


class AccountTarget(Output):
    kind: Literal["account"]
    installation_id: ID


class CustomerTarget(Output):
    kind: Literal["customer"]
    account_setup_id: ID
    patient_link_id: ID


Target = Annotated[AccountTarget | CustomerTarget, Field(discriminator="kind")]


class Summary(Effect):
    target: Target
    label: Label
    usable_locally: bool = Field(strict=True)
    availability: Literal[
        "available",
        "finance_setup_disabled",
        "finance_installation_changed",
        "finance_account_changed",
        "finance_patient_unavailable",
        "finance_binding_unavailable",
        "finance_setup_inactive",
        "finance_setup_limit",
    ]

    @model_validator(mode="after")
    def same_target_kind(self):
        if self.kind != self.target.kind:
            raise ValueError("Summary target kind mismatch")
        return self


class Detail(Output):
    contract_version: Literal[1]
    scope: Scope
    summary: Summary
    review: Review
    last_receipt: Receipt


class Catalog(Output):
    contract_version: Literal[1]
    scope: Scope
    enabled: bool = Field(strict=True)
    installed_accounts: list[InstalledAccount] = Field(max_length=50)
    patients: list[Patient] = Field(max_length=100)
    setups: list[Summary] = Field(max_length=50)


class History(Output):
    contract_version: Literal[1]
    scope: Scope
    setup_id: ID
    receipts: list[Receipt] = Field(max_length=100)


def request_digest(scope, kind, request):
    return public_digest(
        "cosmas-finance-setup-request.v1",
        {
            "scope": scope,
            "command_kind": kind,
            "request": request.public(),
        },
    )


COMMANDS = {
    "propose_account": AccountProposal,
    "propose_customer": CustomerProposal,
    "activate": Activation,
    "disable": Disable,
    "revoke": Revoke,
}
