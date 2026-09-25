"""Permanent no-admission proof for an exact owner decision, send or verification."""

from typing import Literal

from pydantic import model_validator

from cosmas_os.api.vendor_work_schemas import (
    ID,
    BoundCommand,
    Closed,
    ContractVersion,
    Digest,
    Key,
    Output,
    Timestamp,
    VendorArtifactContent,
    VendorArtifactIntent,
    VendorDecision,
    VendorProposal,
    VendorVerify,
)


class VendorRetire(Closed):
    command_kind: Literal["decide", "submit", "verify"]
    request: VendorVerify | VendorDecision | BoundCommand
    request_sha256: Digest

    @model_validator(mode="after")
    def exact_kind(self):
        expected = {"decide": VendorDecision, "submit": BoundCommand, "verify": VendorVerify}
        if type(self.request) is not expected[self.command_kind]:
            raise ValueError("retirement command and request disagree")
        return self


class RetirementScope(Closed):
    kind: Literal["workspace"]
    id: ID


class RetirementRecord(Closed):
    receipt_id: ID
    ticket_id: ID
    revision_id: ID
    operation_id: ID
    payload_hash: Digest
    retired_at: Timestamp
    receipt_sha256: Digest


class RetirementResponse(Output):
    contract_version: ContractVersion
    scope: RetirementScope
    command_kind: Literal["decide", "submit", "verify"]
    idempotency_key: Key
    request_sha256: Digest
    outcome: Literal["retired"]
    effect: None
    summary: None
    retirement: RetirementRecord
    observed_at: Timestamp


class VendorPreparationRetire(Closed):
    command_kind: Literal["propose", "artifact_intent", "artifact_content"]
    request: VendorProposal | VendorArtifactIntent | VendorArtifactContent
    request_sha256: Digest

    @model_validator(mode="after")
    def exact_kind(self):
        expected = {"propose": VendorProposal, "artifact_intent": VendorArtifactIntent,
                    "artifact_content": VendorArtifactContent}
        if type(self.request) is not expected[self.command_kind]:
            raise ValueError("retirement command and request disagree")
        return self


class PreparationRetirementRecord(Closed):
    receipt_id: ID
    retired_at: Timestamp
    receipt_sha256: Digest


class PreparationCommandRetirementResponse(Output):
    contract_version: ContractVersion
    scope: RetirementScope
    command_kind: Literal["propose"]
    idempotency_key: Key
    request_sha256: Digest
    outcome: Literal["retired"]
    effect: None
    summary: None
    retirement: PreparationRetirementRecord
    observed_at: Timestamp


class PreparationArtifactRetirementResponse(Output):
    contract_version: ContractVersion
    scope: RetirementScope
    command_kind: Literal["artifact_intent", "artifact_content"]
    idempotency_key: Key
    request_sha256: Digest
    outcome: Literal["retired"]
    effect: None
    artifact: None
    retirement: PreparationRetirementRecord
    observed_at: Timestamp
