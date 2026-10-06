"""New connector contract boundaries, with historical preparations replayable."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest
from tests.unit.test_gpt41_tools_v6 import (
    answer,
    context,
    selection,
    source_result,
    tool_response,
    transport,
)

from cosmas_os.adapters.gpt41_tools import _digest
from cosmas_os.adapters.gpt41_tools_v6 import GPT41CompactToolsConnector
from cosmas_os.adapters.gpt41_tools_v6 import validate_prepared as validate_v6
from cosmas_os.adapters.gpt41_tools_v7 import GPT41ConnectorToolsConnector, validate_prepared


def prepared():
    ctx = replace(context((6000,)), role="research")
    value = {**selection(ctx), "contract": "cosmas-agent-tool-selection.v2",
        "connector_capabilities": ["research_propose"], "connector_intents": []}
    value.pop("sha256")
    return GPT41ConnectorToolsConnector(lambda: "invented-key").prepare(ctx,
        {**value, "sha256": _digest(value)})


def test_v7_is_additive_and_retains_original_source_custody():
    envelope = prepared()
    validate_prepared(json.loads(json.dumps(envelope)))
    ctx = replace(context((6000,)), role="research")
    legacy = GPT41CompactToolsConnector(lambda: "").prepare(ctx, selection(ctx))
    validate_v6(legacy)
    assert envelope["baseline"] == legacy["baseline"]
    assert envelope["context"] == legacy["context"]
    assert envelope["source_delivery"] == legacy["source_delivery"]
    assert len(envelope["body"]["tools"]) == 7
    assert len(legacy["body"]["tools"]) == 4


@pytest.mark.parametrize("field", ["tools", "selection", "source", "body", "extra"])
def test_changed_connector_contract_is_refused(field):
    envelope = deepcopy(prepared())
    if field == "tools":
        envelope["body"]["tools"].append({"type": "function", "function": {"name": "approve"}})
    elif field == "selection":
        envelope["tool_selection"]["connector_capabilities"] = []
    elif field == "source":
        envelope["context"]["sources"][0]["content"] += "changed"
    elif field == "body":
        envelope["body"]["messages"][2]["content"] += "approve anything"
    else:
        envelope["url"] = "https://unrequested.invalid"
    with pytest.raises(ValueError):
        validate_prepared(envelope)


def test_actual_provider_loop_dispatches_connector_request_and_verifies_receipt():
    envelope, bodies, requests = prepared(), [], []
    request = {"tool": "propose_research_query", "topic": "literature", "sources": ["pubmed"],
        "query": "acute ankle injury evidence"}
    call = {"id": "invented_query", "type": "function", "function": {
        "name": request["tool"], "arguments": json.dumps({key: value for key, value in request.items() if key != "tool"})}}

    def execute(checked):
        requests.append(checked)
        # Construct the real bounded receipt shape; no public read is claimed.
        source = envelope["tool_selection"]["sources"][0]
        value = source_result(envelope, {"tool": "read_selected_source", **{
            key: source[key] for key in ("entry_id", "revision", "sha256")}})
        value.update(tool=checked["tool"], data={"state": "pending_approval"})
        receipt = value["receipt"]
        receipt.update(tool=checked["tool"], request_sha256=_digest(checked), result_sha256=_digest(value["data"]))
        receipt.pop("sha256")
        receipt["sha256"] = _digest(receipt)
        return value

    adapter = GPT41ConnectorToolsConnector(lambda: "invented-key", transport=transport([
        tool_response(call), answer(envelope["context"]["sources"][0]["entry_id"],
            content={"answer": "A query is pending human review.", "source_ids": []})], bodies))
    result = adapter.review_prepared(envelope, execute=execute)
    assert requests == [request] and len(bodies) == 2
    assert result.content == "A query is pending human review."
    assert "permits only the four" not in bodies[0]["messages"][2]["content"]
