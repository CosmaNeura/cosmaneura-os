"""Exact reviewed administrative delivery handles; no model consent or destination."""

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from cosmas_os.ports.agent_connectors import (
    ExecuteReviewedResearch,
    ProposeResearchQuery,
    ReadResearchResult,
    ResearchIntent,
    UUIDText,
)
from cosmas_os.ports.agent_tools import (
    Digest,
    DraftHandle,
    ListSelectedSources,
    OperationHandle,
    ReadCurrentOperationStatus,
    ReadSavedTeammateDraft,
    ReadSelectedSource,
    SourceHandle,
    ToolContract,
)


class DeliveryHandle(ToolContract):
    ticket_id: UUIDText
    revision_id: UUIDText
    operation_id: UUIDText
    payload_hash: Digest


class ExecuteReviewedDelivery(DeliveryHandle):
    tool: Literal["execute_reviewed_delivery"]


class ReadDeliveryStatus(DeliveryHandle):
    tool: Literal["read_delivery_status"]


class DeliveryIntent(DeliveryHandle):
    kind: Literal["vendor_delivery"]
    approval_receipt_id: UUIDText
    approval_receipt_sha256: Digest
    authority_sha256: Digest
    agent_id: UUIDText
    team_revision_id: UUIDText
    external_identity_id: UUIDText
    evidence_sha256: Digest


class ToolSelectionV3(ToolContract):
    contract: Literal["cosmas-agent-tool-selection.v3"]
    sources: list[SourceHandle] = Field(max_length=12)
    teammate_drafts: list[DraftHandle] = Field(max_length=12)
    operations: list[OperationHandle] = Field(max_length=12)
    connector_capabilities: list[Literal["research_propose"]] = Field(max_length=1)
    connector_intents: list[ResearchIntent] = Field(max_length=10)
    delivery_intents: list[DeliveryIntent] = Field(max_length=10)
    sha256: Digest

    @model_validator(mode="after")
    def distinct_intents(self):
        for values in (self.connector_intents, self.delivery_intents):
            if len({value.revision_id for value in values}) != len(values):
                raise ValueError("distinct reviewed intents required")
        return self


DELIVERY_TOOL_NAMES = ("execute_reviewed_delivery", "read_delivery_status")
DELIVERY_REQUEST_ADAPTER = TypeAdapter(Annotated[
    ExecuteReviewedDelivery | ReadDeliveryStatus, Field(discriminator="tool")])
REQUEST_ADAPTER = TypeAdapter(Annotated[
    ListSelectedSources | ReadSelectedSource | ReadSavedTeammateDraft | ReadCurrentOperationStatus
    | ProposeResearchQuery | ExecuteReviewedResearch | ReadResearchResult
    | ExecuteReviewedDelivery | ReadDeliveryStatus, Field(discriminator="tool")])
TOOL_NAMES = ("list_selected_sources", "read_selected_source", "read_saved_teammate_draft",
    "read_current_operation_status", "propose_research_query", "execute_reviewed_research",
    "read_research_result", *DELIVERY_TOOL_NAMES)


def tool_definitions():
    output = []
    for model, description in ((ExecuteReviewedDelivery,
            "Execute one exact human-approved administrative Spruce message. Never retry an uncertain dispatch."),
            (ReadDeliveryStatus, "Read retained delivery evidence only; no provider read or clinical completion assertion.")):
        schema = model.model_json_schema()
        name = schema["properties"].pop("tool")["const"]
        schema["required"].remove("tool")
        output.append({"name": name, "description": description, "parameters": schema})
    return output
