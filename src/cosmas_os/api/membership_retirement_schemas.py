"""Exact negative admission for a conclusively rejected private local command."""

from typing import Literal

from pydantic import model_validator

from cosmas_os.api import membership_work_schemas as work
from cosmas_os.api.vendor_work_schemas import (
    ID,
    Closed,
    ContractVersion,
    Digest,
    Key,
    Output,
    Timestamp,
)

Reason = Literal[
    "membership_source_changed",
    "membership_revision_changed",
    "membership_result_changed",
    "membership_exception_unresolved",
    "membership_evidence_changed",
    "membership_history_limit",
]


class MembershipRetire(Closed):
    command_kind: work.Kind
    request: work.Proposal | work.Decision | work.Result | work.Verify | work.Withdraw
    request_sha256: Digest

    @model_validator(mode="after")
    def matching_command(self):
        if type(self.request) is not work.COMMANDS[self.command_kind]:
            raise ValueError("Exact command kind required")
        return self


class MembershipRetirementRecord(Closed):
    receipt_id: ID
    reason: Reason
    retired_at: Timestamp


class MembershipRetirementResponse(Output):
    contract_version: ContractVersion
    scope: work.Scope
    command_kind: work.Kind
    idempotency_key: Key
    request_sha256: Digest
    outcome: Literal["retired"]
    effect: None
    retirement: MembershipRetirementRecord
    receipt_sha256: Digest
