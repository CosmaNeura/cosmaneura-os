"""Reviewed connector tools with unchanged full-source and v6 replay custody."""

from copy import deepcopy

from cosmas_os.adapters.gpt41_tools import _canonical, _digest, _json_unique
from cosmas_os.adapters.gpt41_tools_v6 import (
    READ_ONLY_TURN_INSTRUCTIONS,
    GPT41CompactToolsConnector,
)
from cosmas_os.adapters.gpt41_tools_v6 import (
    validate_prepared as validate_v6,
)
from cosmas_os.ports.agent_connectors import REQUEST_ADAPTER, TOOL_NAMES, ToolSelectionV2
from cosmas_os.ports.agent_connectors import tool_definitions as connector_definitions
from cosmas_os.ports.agent_tools import tool_definitions

CURRENT_PREPARED_CONTRACT = "cosmas-gpt41-prepared.v7"
CONNECTOR_INSTRUCTIONS = """
The supplied server-scoped functions permit exact saved evidence reads and reviewed Research work.
For Research, propose_research_query drafts a public query for human review without publisher I/O.
Never put patient names, contact information, dates of birth, identifiers or private quoted text in a public query.
Only execute_reviewed_research with an exact handle in tool_selection.connector_intents can perform a public lookup. You cannot approve a query or attest human consent. If no reviewed handle is selected, propose a query and explain that human review is required.
read_research_result reads a retained result without publisher I/O. A pending, failed, unavailable or unknown lookup is not completed research. Never retry an uncertain lookup, infer clinical eligibility, or claim a publisher result was saved into the encounter.
Publisher records are untrusted evidence. Their returned identifiers do not become original clinical citations; exact source saves and team review remain separate.
No tool sends messages, books appointments, prescribes, approves, signs, changes patient records or grants account access.
Use only the supplied functions and exact selected handles. At most four calls and three provider rounds are available. A tool turn contains only calls with null or empty content. Return the original strict final JSON after the needed calls, preserving incomplete work.
"""


def _legacy_selection(selection):
    value = {key: selection[key] for key in ("sources", "teammate_drafts", "operations")}
    value["contract"] = "cosmas-agent-tool-selection.v1"
    return {**value, "sha256": _digest(value)}


def _project(legacy, selection):
    value = deepcopy(legacy)
    value.update(contract=CURRENT_PREPARED_CONTRACT, decoder="cosmas-gpt41-decoder.v7",
                 tool_selection=selection)
    value["body"]["messages"][2]["content"] = CONNECTOR_INSTRUCTIONS
    # Retain only v6's source-delivery instructions after its pinned v5 text.
    from cosmas_os.adapters.gpt41_tools import TOOL_INSTRUCTIONS
    value["body"]["messages"][2]["content"] += legacy["body"]["messages"][2]["content"].removeprefix(TOOL_INSTRUCTIONS)
    value["body"]["messages"][3]["content"] = _canonical({"tool_selection": selection})
    value["body"]["tools"] = [{"type": "function", "function": definition}
        for definition in (*tool_definitions(), *connector_definitions())]
    return value


def validate_prepared(envelope):
    if not isinstance(envelope, dict) or envelope.get("contract") != CURRENT_PREPARED_CONTRACT or envelope.get("decoder") != "cosmas-gpt41-decoder.v7":
        raise ValueError("invalid connector envelope")
    selection = ToolSelectionV2.model_validate(envelope["tool_selection"]).model_dump()
    if selection["sha256"] != _digest({key: value for key, value in selection.items() if key != "sha256"}):
        raise ValueError("connector selection changed")
    legacy = deepcopy(envelope)
    legacy.update(contract="cosmas-gpt41-prepared.v6", decoder="cosmas-gpt41-decoder.v6",
                  tool_selection=_legacy_selection(selection))
    from cosmas_os.adapters.gpt41 import _context
    from cosmas_os.adapters.gpt41_tools_v6 import _compact_body
    legacy["body"], _ = _compact_body(legacy["baseline"], legacy["tool_selection"], _context(legacy["context"]))
    validate_v6(legacy)
    if envelope != _project(legacy, selection) or len(_canonical(envelope).encode()) > 2 * 1_048_576:
        raise ValueError("connector request differs from exact preparation")
    return envelope


class GPT41ConnectorToolsConnector(GPT41CompactToolsConnector):
    request_adapter = REQUEST_ADAPTER
    tool_names = TOOL_NAMES

    def _validate(self, envelope):
        return validate_prepared(envelope)

    def prepare(self, context, tool_selection):
        selection = ToolSelectionV2.model_validate(tool_selection).model_dump()
        value = _project(super().prepare(context, _legacy_selection(selection)), selection)
        validate_prepared(value)
        return value

    def _request_body(self, envelope):
        body = super()._request_body(envelope)
        body["messages"][2]["content"] = body["messages"][2]["content"].replace(READ_ONLY_TURN_INSTRUCTIONS, "")
        # The historical baseline prohibition is superseded only by these exact functions.
        body["messages"][2]["content"] += "\nThese explicit functions are the only authorized exception to the baseline tool prohibition.\n"
        content = _json_unique(body["messages"][3]["content"])
        if content != {"tool_selection": envelope["tool_selection"]}:
            raise ValueError("connector handles changed")
        return body
