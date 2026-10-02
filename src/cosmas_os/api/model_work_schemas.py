"""Closed, bounded private model observations; never provider response bodies."""

from __future__ import annotations

import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from cosmas_os.api.session_prep_analysis_schemas import ConversationAnalysisFields
from cosmas_os.api.team_schemas import BotAddress, ConversationRequest, HandoffRetry
from cosmas_os.api.workspace_schemas import IdempotencyKey
from cosmas_os.application.workspace import WorkspaceError

MODEL_REQUEST_BYTES = 65_536
RETRY_REQUEST_BYTES = 2_048
MODEL_RESPONSE_BYTES = 16_384
ENTRY_MODEL_BYTES = 2_048
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Positive = Annotated[int, Field(strict=True, ge=1, le=9_007_199_254_740_991)]
Tokens = Annotated[int, Field(strict=True, ge=0, lt=1_000_000)]
State = Literal["reserved", "running", "completed", "failed", "unknown", "abandoned"]
Reason = Literal[
    "model_unavailable",
    "authority_changed",
    "source_changed",
    "dispatch_interrupted",
    "reservation_expired",
    "team_work_limit",
]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def literal_numbers_are_numbers(cls, value):
        if isinstance(value, dict):
            for key in ("contract_version", "unit", "attempt_number"):
                if key in value and type(value[key]) is not int:
                    raise ValueError("invalid numeric contract")
        return value


class AdmissionObservation(Closed):
    id: UUID
    state: State
    unit: Literal[1]
    admitted_at: AwareDatetime
    dispatch: Literal["not_started", "started", "unconfirmed"]
    usage: Literal["unknown", "verified"]
    input_tokens: Tokens | None
    output_tokens: Tokens | None

    @model_validator(mode="after")
    def consistent(self):
        if (self.usage == "verified") != (
            self.input_tokens is not None and self.output_tokens is not None
        ):
            raise ValueError("invalid usage observation")
        if self.usage == "unknown" and (
            self.input_tokens is not None or self.output_tokens is not None
        ):
            raise ValueError("invalid usage observation")
        if self.state in {"reserved", "abandoned"} and self.dispatch != "not_started":
            raise ValueError("invalid dispatch observation")
        if self.state in {"running", "completed"} and self.dispatch != "started":
            raise ValueError("invalid dispatch observation")
        if self.state == "unknown" and self.dispatch != "unconfirmed":
            raise ValueError("invalid dispatch observation")
        return self


class EntryAnchor(Closed):
    id: UUID
    revision: Positive


class ModelRequestObservation(Closed):
    contract_version: Literal[1]
    workspace_id: UUID
    idempotency_key: IdempotencyKey
    request_sha256: Hash
    outcome: Literal["saved", "reserved", "running", "unknown", "failed", "abandoned", "not_found"]
    admission: AdmissionObservation | None
    saved_entry: EntryAnchor | None
    reason: Reason | None

    @model_validator(mode="after")
    def consistent(self):
        if (self.outcome == "saved") != (self.saved_entry is not None):
            raise ValueError("invalid saved anchor")
        if self.outcome == "not_found":
            if self.admission is not None or self.reason is not None:
                raise ValueError("invalid absent observation")
        elif self.outcome != "saved":
            if self.admission is None or self.admission.state != self.outcome:
                raise ValueError("invalid admission outcome")
        elif self.admission is not None and self.admission.state not in {"completed", "failed"}:
            raise ValueError("invalid saved admission")
        return self


class RecordedRetry(Closed):
    attempt_id: UUID
    attempt_number: Literal[2, 3]
    recorded_at: AwareDatetime
    workspace_revision: Positive
    status: Literal["queued", "running", "completed", "failed", "interrupted"]
    result_entry: EntryAnchor | None
    admission: AdmissionObservation | None
    coverage: Literal["durable_admission", "retained_legacy"]
    reason: Reason | Literal["legacy_queued_unadmitted", "legacy_running_unconfirmed"] | None

    @model_validator(mode="after")
    def consistent(self):
        if (self.coverage == "durable_admission") != (self.admission is not None):
            raise ValueError("invalid retry coverage")
        if (self.status == "completed") != (self.result_entry is not None):
            raise ValueError("invalid retry result")
        if self.admission is not None:
            mapped = {
                "reserved": "queued",
                "running": "running",
                "completed": "completed",
                "failed": "failed",
                "unknown": "interrupted",
                "abandoned": "interrupted",
            }
            if self.status != mapped[self.admission.state]:
                raise ValueError("invalid retry lifecycle")
        return self


class HandoffRetryObservation(Closed):
    contract_version: Literal[1]
    workspace_id: UUID
    handoff_id: UUID
    previous_attempt_id: UUID
    idempotency_key: IdempotencyKey
    request_sha256: Hash
    outcome: Literal["recorded", "not_found"]
    recorded: RecordedRetry | None

    @model_validator(mode="after")
    def consistent(self):
        if (self.outcome == "recorded") != (self.recorded is not None):
            raise ValueError("invalid retry observation")
        if self.recorded and self.recorded.attempt_id == self.previous_attempt_id:
            raise ValueError("invalid retry attempt binding")
        return self


class ConversationBinding(Closed, ConversationAnalysisFields):
    kind: Literal["conversation"]
    expected_revision: Positive
    team_revision: Positive
    idempotency_key: IdempotencyKey
    role: BotAddress


class HandoffBinding(Closed):
    kind: Literal["private_handoff"]
    handoff_id: UUID
    attempt_id: UUID


class AdmittedBot(Closed):
    address: BotAddress
    agent_id: UUID
    role: Literal["scribe", "visit_prep", "follow_up", "chief", "custom", "research"]
    name: str = Field(min_length=1, max_length=40)
    team_revision: Positive


class EntryModelRequest(Closed):
    contract_version: Literal[1]
    request_sha256: Hash
    request: Annotated[ConversationBinding | HandoffBinding, Field(discriminator="kind")]
    bot: AdmittedBot
    admission: AdmissionObservation
    reason: Reason | None

    @model_validator(mode="after")
    def consistent(self):
        if isinstance(self.request, ConversationBinding) and (
            self.request.role != self.bot.address
            or self.request.team_revision != self.bot.team_revision
        ):
            raise ValueError("invalid request bot binding")
        return self


def contract_header(request, *, required=False):
    values = request.headers.getlist("x-cosmas-model-contract")
    if values and values != ["1"]:
        raise WorkspaceError("model_contract_unsupported", 426)
    if required and not values:
        raise WorkspaceError("model_contract_required", 426)
    return bool(values)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


async def read_model_request[RequestModel: BaseModel](
    request, schema: type[RequestModel]
) -> RequestModel:
    from cosmas_os.api.handoff_review_schemas import HandoffReview, HandoffRevision

    maximum = 12_288 if schema is HandoffReview else RETRY_REQUEST_BYTES if schema in {HandoffRetry, HandoffRevision} else MODEL_REQUEST_BYTES
    if schema not in {ConversationRequest, HandoffRetry, HandoffReview, HandoffRevision}:
        raise ValueError("unsupported private model request")
    try:
        if (
            request.query_params
            or len(request.headers.getlist("content-type")) != 1
            or request.headers["content-type"].split(";", 1)[0].strip().lower()
            != "application/json"
            or len(request.headers.getlist("authorization")) > 1
            or request.headers.getlist("content-encoding")
        ):
            raise ValueError()
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > maximum:
                raise ValueError()
            body.extend(chunk)
        value = json.loads(body, object_pairs_hook=_unique)
        # Reject unpaired surrogates before storage/hashing, including JSON escapes.
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return schema.model_validate(value)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise WorkspaceError("invalid_model_request", 422) from None


def checked_response(value, schema, *, maximum=MODEL_RESPONSE_BYTES):
    try:
        checked = schema.model_validate(value).model_dump(mode="json")
        if (
            len(
                json.dumps(
                    checked, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode()
            )
            > maximum
        ):
            raise ValueError()
        return checked
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise WorkspaceError("model_observation_unavailable", 503) from None
