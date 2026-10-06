"""Exact reviewed administrative delivery tools; historical envelopes stay unchanged."""

from copy import deepcopy

from cosmas_os.adapters.gpt41_tools import _canonical, _digest
from cosmas_os.adapters.gpt41_tools_v7 import (
    CONNECTOR_INSTRUCTIONS,
    GPT41ConnectorToolsConnector,
)
from cosmas_os.adapters.gpt41_tools_v7 import (
    validate_prepared as validate_v7,
)
from cosmas_os.ports.agent_delivery_tools import REQUEST_ADAPTER, TOOL_NAMES, ToolSelectionV3
from cosmas_os.ports.agent_delivery_tools import tool_definitions as delivery_definitions

CURRENT_PREPARED_CONTRACT = "cosmas-gpt41-prepared.v8"
DELIVERY_INSTRUCTIONS = CONNECTOR_INSTRUCTIONS.replace(
    "No tool sends messages, books appointments, prescribes, approves, signs, changes patient records or grants account access.",
    "Only execute_reviewed_delivery can submit an exact, separately human-approved administrative "
    "secure message selected in delivery_intents. Its approval names this Follow up bot and binds "
    "the reviewed recipient, unchanged message and source revision. You cannot grant that approval, "
    "change the message or destination, attach a document, send clinical advice or execute any other action. "
    "read_delivery_status reads retained receipts without provider I/O. Submission accepted means "
    "the provider accepted this action; it does not prove delivery, patient acknowledgment or clinical "
    "completion. Preserve unknown outcomes and never resend after an uncertain response. "
    "No function books appointments, prescribes, signs or grants account access.",
)


def _legacy_selection(selection):
    value = {key: value for key, value in selection.items() if key not in {"sha256", "delivery_intents"}}
    value["contract"] = "cosmas-agent-tool-selection.v2"
    return {**value, "sha256": _digest(value)}


def _project(legacy, selection):
    value = deepcopy(legacy)
    value.update(contract=CURRENT_PREPARED_CONTRACT, decoder="cosmas-gpt41-decoder.v8",
        tool_selection=selection)
    value["body"]["messages"][2]["content"] = legacy["body"]["messages"][2]["content"].replace(
        CONNECTOR_INSTRUCTIONS, DELIVERY_INSTRUCTIONS, 1)
    value["body"]["messages"][3]["content"] = _canonical({"tool_selection": selection})
    value["body"]["tools"].extend({"type": "function", "function": definition}
        for definition in delivery_definitions())
    return value


def validate_prepared(envelope):
    if (not isinstance(envelope, dict) or envelope.get("contract") != CURRENT_PREPARED_CONTRACT
        or envelope.get("decoder") != "cosmas-gpt41-decoder.v8"):
        raise ValueError("invalid delivery envelope")
    selection = ToolSelectionV3.model_validate(envelope["tool_selection"]).model_dump()
    if selection["sha256"] != _digest({key: value for key, value in selection.items() if key != "sha256"}):
        raise ValueError("delivery selection changed")
    legacy = deepcopy(envelope)
    legacy.update(contract="cosmas-gpt41-prepared.v7", decoder="cosmas-gpt41-decoder.v7",
        tool_selection=_legacy_selection(selection))
    legacy["body"]["messages"][2]["content"] = legacy["body"]["messages"][2]["content"].replace(
        DELIVERY_INSTRUCTIONS, CONNECTOR_INSTRUCTIONS, 1)
    legacy["body"]["messages"][3]["content"] = _canonical({"tool_selection": legacy["tool_selection"]})
    legacy["body"]["tools"] = legacy["body"]["tools"][:7]
    validate_v7(legacy)
    if envelope != _project(legacy, selection) or len(_canonical(envelope).encode()) > 2 * 1_048_576:
        raise ValueError("delivery request differs from exact preparation")
    return envelope


class GPT41DeliveryToolsConnector(GPT41ConnectorToolsConnector):
    request_adapter = REQUEST_ADAPTER
    tool_names = TOOL_NAMES

    def _validate(self, envelope):
        return validate_prepared(envelope)

    def prepare(self, context, tool_selection):
        selection = ToolSelectionV3.model_validate(tool_selection).model_dump()
        value = _project(super().prepare(context, _legacy_selection(selection)), selection)
        validate_prepared(value)
        return value
