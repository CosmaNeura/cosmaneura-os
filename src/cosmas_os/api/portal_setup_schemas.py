"""Closed owner-only local portal administration; no endpoint or credential input."""

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
    Positive,
)

Capability = Literal["document.upload", "referral.submit", "referral.read"]
Reference = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{1,120}$")]
Kind = Literal["propose", "activate", "disable", "revoke"]


class Mappings(Closed):
    patient_link_id: ID
    practice_reference: Reference
    patient_reference: Reference
    recipient_reference: Reference
    practice_label: Label
    recipient_label: Label


class Proposal(Closed):
    connection_id: ID
    expected_version: Counter = Field(le=1000)
    idempotency_key: Key
    installation_id: ID
    profile_sha256: Digest
    configuration_sha256: Digest
    capabilities: list[Capability] = Field(min_length=1, max_length=3)
    mappings: Mappings

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("Distinct supported capabilities required")
        return self


class Bound(Closed):
    connection_id: ID
    expected_version: Positive = Field(le=1000)
    idempotency_key: Key
    revision_id: ID
    review_sha256: Digest


class Activation(Bound):
    reviewed_profile: Confirmed
    reviewed_practice: Confirmed
    reviewed_patient: Confirmed
    reviewed_recipient: Confirmed
    confirm_local_activation: Confirmed


class Disable(Bound):
    confirm_disable: Confirmed


class Revoke(Bound):
    confirm_revoke: Confirmed


class Resolve(Closed):
    command_kind: Kind
    idempotency_key: Key
    request_sha256: Digest


COMMANDS = {"propose": Proposal, "activate": Activation, "disable": Disable, "revoke": Revoke}
