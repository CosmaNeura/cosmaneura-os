"""Closed connector tool arguments and additive prepared-tool selection v2."""

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

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

UUIDText = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")]


class ProposeResearchQuery(ToolContract):
    tool: Literal["propose_research_query"]
    topic: str
    sources: list[str] = Field(min_length=1, max_length=3)
    query: str = Field(min_length=1, max_length=500)


class ResearchHandle(ToolContract):
    ticket_id: UUIDText
    revision_id: UUIDText
    payload_hash: Digest


class ExecuteReviewedResearch(ResearchHandle):
    tool: Literal["execute_reviewed_research"]


class ReadResearchResult(ResearchHandle):
    tool: Literal["read_research_result"]


CONNECTOR_REQUEST_ADAPTER = TypeAdapter(Annotated[
    ProposeResearchQuery | ExecuteReviewedResearch | ReadResearchResult,
    Field(discriminator="tool"),
])
CONNECTOR_TOOL_NAMES = ("propose_research_query", "execute_reviewed_research", "read_research_result")


def tool_definitions():
    descriptions = (
        "Draft an exact public query for human review. This performs no publisher read.",
        "Execute one exact human-reviewed Research intent. Uncertain reads are never retried.",
        "Read the retained result of one exact reviewed Research intent without publisher I/O.",
    )
    output = []
    for name, description, model in zip(CONNECTOR_TOOL_NAMES, descriptions,
            (ProposeResearchQuery, ExecuteReviewedResearch, ReadResearchResult), strict=True):
        schema = model.model_json_schema()
        schema["properties"].pop("tool")
        schema["required"].remove("tool")
        output.append({"name": name, "description": description, "parameters": schema})
    return output



class ResearchIntent(ResearchHandle):
    kind: Literal["research"]


class ToolSelectionV2(ToolContract):
    contract: Literal["cosmas-agent-tool-selection.v2"]
    sources: list[SourceHandle] = Field(max_length=12)
    teammate_drafts: list[DraftHandle] = Field(max_length=12)
    operations: list[OperationHandle] = Field(max_length=12)
    connector_capabilities: list[Literal["research_propose"]] = Field(max_length=1)
    connector_intents: list[ResearchIntent] = Field(max_length=10)
    sha256: Digest

    @model_validator(mode="after")
    def distinct_intents(self):
        identities = {(value.ticket_id, value.revision_id, value.payload_hash)
            for value in self.connector_intents}
        if len(identities) != len(self.connector_intents):
            raise ValueError("distinct reviewed connector intents required")
        return self


AgentConnectorToolRequest = Annotated[
    ListSelectedSources | ReadSelectedSource | ReadSavedTeammateDraft | ReadCurrentOperationStatus
    | ProposeResearchQuery | ExecuteReviewedResearch | ReadResearchResult,
    Field(discriminator="tool"),
]
REQUEST_ADAPTER = TypeAdapter(AgentConnectorToolRequest)
TOOL_NAMES = (
    "list_selected_sources", "read_selected_source", "read_saved_teammate_draft",
    "read_current_operation_status", *CONNECTOR_TOOL_NAMES,
)

