"""Closed private portal work commands; no endpoint or credential input."""

from typing import Literal

from pydantic import model_validator

from cosmas_os.api.vendor_work_schemas import (
    ID,
    Closed,
    Confirmed,
    Day,
    Digest,
    Document,
    Evidence,
    Goal,
    Key,
    Message,
    ObservationHead,
    Output,
    Positive,
    ReviewedSource,
    Timestamp,
    public_digest,
)


class SetupBinding(Closed):
    connection_id: ID
    revision_id: ID
    version: Positive
    review_sha256: Digest


class Proposal(Closed):
    expected_workspace_revision: Positive
    proposed_operation_id: ID
    idempotency_key: Key
    action: Literal["document.upload", "referral.submit"]
    setup: SetupBinding
    source: ReviewedSource
    document: Document
    due_date: Day
    expected_outcome: Goal
    summary: Message | None = None
    uploaded_operation_id: ID | None = None

    @model_validator(mode="after")
    def exact_stage(self):
        if self.action == "document.upload" and (
            self.summary is not None or self.uploaded_operation_id is not None
        ):
            raise ValueError("Document upload is a separate action")
        if self.action == "referral.submit" and (
            self.summary is None or self.uploaded_operation_id is None
        ):
            raise ValueError("Referral requires a reviewed summary and accepted upload")
        return self


class Bound(Closed):
    expected_version: Positive
    revision_id: ID
    operation_id: ID
    payload_hash: Digest
    idempotency_key: Key


class Decision(Bound):
    review_sha256: Digest
    choice: Literal["approve", "reject"]
    reviewed_document: Confirmed
    reviewed_mapping: Confirmed
    reviewed_action: Confirmed


class Result(Bound):
    observation_head: ObservationHead
    evidence_sha256: Digest
    disposition: Literal["verified_in_portal", "reported_exception", "unable_to_establish"]
    evidence: Evidence


class CurrentResult(Output):
    receipt_id: ID
    receipt_sha256: Digest
    request_sha256: Digest
    recorded_at: Timestamp
    request: Result


class Verify(Bound):
    observation_head: ObservationHead
    evidence_sha256: Digest
    result_receipt_id: ID
    result_receipt_sha256: Digest
    reviewed_result: Confirmed
    reviewed_observations: Confirmed
    outcome_confirmed: Confirmed


Kind = Literal["propose", "decide", "withdraw", "submit", "status", "result", "verify"]


class Resolve(Closed):
    command_kind: Kind
    idempotency_key: Key
    request_sha256: Digest


COMMANDS = {
    "decide": Decision,
    "withdraw": Bound,
    "submit": Bound,
    "status": Bound,
    "result": Result,
    "verify": Verify,
}


def request_digest(wid, kind, request):
    return public_digest(
        "cosmas-portal-work-request.v1",
        {
            "scope": {"kind": "workspace", "id": wid},
            "command_kind": kind,
            "request": request.public(),
        },
    )
