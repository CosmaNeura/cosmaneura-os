"""Closed owner delivery settings. No credentials, URLs or provider operations."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from cosmas_os.api.vendor_work_schemas import (
    ID,
    Action,
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

Vendor = Literal["spruce", "srfax", "documo", "efax"]
Kind = Literal["account", "recipient"]
CommandKind = Literal["propose_account", "propose_recipient", "activate", "disable", "revoke"]
State = Literal["pending_review", "active", "disabled", "revoked"]
AccountReference = Annotated[
    str, Field(strict=True, min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$")
]
ContactID = Annotated[
    str, Field(strict=True, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
]
ACTIONS = {
    "spruce": {"spruce_secure_message", "spruce_fax", "spruce_media_upload"},
    "srfax": {"srfax_fax"},
    "documo": {"documo_fax"},
    "efax": {"efax_fax"},
}


class Scope(Output):
    box_id: ID
    owner_id: ID


class Permissions(Closed):
    read_status: bool = Field(strict=True)
    prepare_and_submit: bool = Field(strict=True)
    actions: list[Action] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def explicit_permissions(self):
        if (
            not self.read_status
            and not self.prepare_and_submit
            or len(set(self.actions)) != len(self.actions)
        ):
            raise ValueError("Distinct capabilities and an explicit local permission required")
        if "spruce_fax" in self.actions and "spruce_media_upload" not in self.actions:
            raise ValueError("Spruce fax requires its reviewed media upload capability")
        return self


class InstalledAccount(Output):
    installation_id: ID
    installation_sha256: Digest
    label: Label
    vendor: Vendor
    environment: Literal["sandbox", "production"]
    account_reference: AccountReference
    sender_label: Label
    capabilities: list[Action] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def exact_vendor(self):
        if (
            len(set(self.capabilities)) != len(self.capabilities)
            or set(self.capabilities) - ACTIONS[self.vendor]
            or self.vendor != "documo"
            and self.environment != "production"
        ):
            raise ValueError("Unsupported delivery capabilities")
        return self


class SecureRecipient(Closed):
    channel: Literal["secure"]
    contact_id: ContactID


class FaxRecipient(Closed):
    channel: Literal["fax"]
    number: Annotated[str, Field(strict=True, pattern=r"^\+1[2-9][0-9]{9}$")]


Destination = Annotated[SecureRecipient | FaxRecipient, Field(discriminator="channel")]


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


class RecipientProposal(Closed):
    setup_id: ID
    expected_version: Counter = Field(le=100)
    idempotency_key: Key
    account: Binding
    patient_link_id: ID
    destination: Destination
    label: Label
    permission_reference: Label
    expires_at: Timestamp


class Bound(Binding):
    idempotency_key: Key


class Activation(Bound):
    reviewed_account: Confirmed
    reviewed_environment: Confirmed
    reviewed_sender: Confirmed
    reviewed_capabilities: Confirmed
    reviewed_patient: Confirmed | None = None
    reviewed_recipient: Confirmed | None = None
    reviewed_permission: Confirmed | None = None
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


class RecipientReview(Output):
    kind: Literal["recipient"]
    setup_id: ID
    revision_id: ID
    revision: Positive = Field(le=20)
    installed: InstalledAccount
    label: Label
    account: Binding
    account_label: Label
    connection_version_id: ID
    correspondence_version_id: ID
    patient: Patient
    destination: Destination
    permission_reference: Label
    expires_at: Timestamp


Review = Annotated[AccountReview | RecipientReview, Field(discriminator="kind")]


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


class RecipientTarget(Output):
    kind: Literal["recipient"]
    account_setup_id: ID
    patient_link_id: ID


Target = Annotated[AccountTarget | RecipientTarget, Field(discriminator="kind")]


class Summary(Effect):
    target: Target
    label: Label
    usable_locally: bool = Field(strict=True)
    availability: Literal[
        "available",
        "vendor_setup_disabled",
        "vendor_installation_changed",
        "vendor_account_changed",
        "vendor_patient_unavailable",
        "vendor_binding_unavailable",
        "vendor_permission_expired",
        "vendor_setup_inactive",
        "vendor_setup_revision_required",
        "vendor_setup_limit",
    ]

    @model_validator(mode="after")
    def target_kind(self):
        if self.target.kind != self.kind:
            raise ValueError("Target kind mismatch")
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


COMMANDS = {
    "propose_account": AccountProposal,
    "propose_recipient": RecipientProposal,
    "activate": Activation,
    "disable": Disable,
    "revoke": Revoke,
}


class HistoryItem(Output):
    request: AccountProposal | RecipientProposal | Activation | Disable | Revoke
    receipt: Receipt

    @model_validator(mode="after")
    def exact_command(self):
        if type(self.request) is not COMMANDS[self.receipt.command_kind]:
            raise ValueError("Request kind mismatch")
        return self


class History(Output):
    contract_version: Literal[1]
    scope: Scope
    setup_id: ID
    items: list[HistoryItem] = Field(max_length=100)
    reviews: list[Review] = Field(max_length=20)


def request_digest(scope, kind, request):
    return public_digest(
        "cosmas-vendor-setup-request.v1",
        {"scope": scope, "command_kind": kind, "request": request.public()},
    )
