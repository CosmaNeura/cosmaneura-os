"""Closed, read-only tools for one saved model admission.

Tool requests carry exact evidence handles, never identities, URLs or action grants.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9._:/-]+$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Revision = Annotated[int, Field(strict=True, ge=1)]
Label = Annotated[str, StringConstraints(min_length=1, max_length=160)]
Kind = Annotated[str, StringConstraints(min_length=1, max_length=64)]
OperationKind = Literal["inbox", "follow_up", "scheduling", "membership", "payment"]


class ToolContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class SourceHandle(ToolContract):
    entry_id: Identifier
    revision: Revision
    sha256: Digest
    label: Label
    kind: Kind


class DraftHandle(ToolContract):
    entry_id: Identifier
    revision: Revision
    sha256: Digest
    agent_id: Identifier
    role: Kind
    label: Label


class OperationHandle(ToolContract):
    kind: OperationKind
    record_id: Identifier
    commitment: Digest


class ToolSelection(ToolContract):
    contract: Literal["cosmas-agent-tool-selection.v1"]
    sources: list[SourceHandle] = Field(max_length=12)
    teammate_drafts: list[DraftHandle] = Field(max_length=12)
    operations: list[OperationHandle] = Field(max_length=12)
    sha256: Digest


class ListSelectedSources(ToolContract):
    tool: Literal["list_selected_sources"]


class ReadSelectedSource(ToolContract):
    tool: Literal["read_selected_source"]
    entry_id: Identifier
    revision: Revision
    sha256: Digest


class ReadSavedTeammateDraft(ToolContract):
    tool: Literal["read_saved_teammate_draft"]
    entry_id: Identifier
    revision: Revision
    sha256: Digest


class ReadCurrentOperationStatus(ToolContract):
    tool: Literal["read_current_operation_status"]
    kind: OperationKind
    record_id: Identifier
    commitment: Digest


AgentToolRequest = Annotated[
    ListSelectedSources | ReadSelectedSource | ReadSavedTeammateDraft | ReadCurrentOperationStatus,
    Field(discriminator="tool"),
]
REQUEST_ADAPTER = TypeAdapter(AgentToolRequest)
TOOL_NAMES = (
    "list_selected_sources",
    "read_selected_source",
    "read_saved_teammate_draft",
    "read_current_operation_status",
)


def tool_definitions():
    """JSON schemas contain only the argument fields accepted by execute()."""
    descriptions = (
        "List exact admitted evidence handles without reading their contents.",
        "Read one selected source using its exact revision and content hash.",
        "Read one selected saved teammate draft; completion is draft preparation only.",
        "Read one selected operation's current saved receipt status; this grants no action.",
    )
    models = (ListSelectedSources, ReadSelectedSource, ReadSavedTeammateDraft, ReadCurrentOperationStatus)
    result = []
    for name, description, model in zip(TOOL_NAMES, descriptions, models, strict=True):
        schema = model.model_json_schema()
        schema["properties"].pop("tool")
        schema["required"].remove("tool")
        result.append({"name": name, "description": description, "parameters": schema})
    return result
