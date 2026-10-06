"""Exact delivery envelopes and real adapter loops with synthetic HTTP replies."""
import json
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from tests.unit.test_gpt41_tools_v6 import (
    answer,
    context,
    selection,
    source_result,
    tool_response,
    transport,
)
from tests.unit.test_gpt41_tools_v7 import prepared as prepared_v7

from cosmas_os.adapters.gpt41_tools import _digest
from cosmas_os.adapters.gpt41_tools_v7 import validate_prepared as validate_v7
from cosmas_os.adapters.gpt41_tools_v8 import GPT41DeliveryToolsConnector, validate_prepared
from cosmas_os.ports.agent_delivery_tools import TOOL_NAMES
from cosmas_os.ports.bot_capabilities import ModelCallFailure


def prepared():
    ctx = replace(context((6000,)), role="follow_up")
    intent = {"kind": "vendor_delivery", **{key: str(uuid4()) for key in (
        "ticket_id", "revision_id", "operation_id", "approval_receipt_id", "agent_id",
        "team_revision_id", "external_identity_id")}, **{key: "a" * 64 for key in (
        "payload_hash", "approval_receipt_sha256", "authority_sha256", "evidence_sha256")}}
    selected = {**selection(ctx), "contract": "cosmas-agent-tool-selection.v3",
        "connector_capabilities": [], "connector_intents": [], "delivery_intents": [intent]}
    selected.pop("sha256")
    return GPT41DeliveryToolsConnector(lambda: "invented-key").prepare(ctx, {**selected, "sha256": _digest(selected)})


def test_nine_exact_tools_source_custody_and_v7_replay_unchanged():
    legacy = prepared_v7()
    legacy_hash = _digest(legacy)
    current = prepared()
    validate_prepared(json.loads(json.dumps(current)))
    validate_v7(legacy)
    assert _digest(legacy) == legacy_hash
    assert len(legacy["body"]["tools"]) == 7
    assert tuple(tool["function"]["name"] for tool in current["body"]["tools"]) == TOOL_NAMES
    assert len(TOOL_NAMES) == 9
    for tool in current["body"]["tools"][-2:]:
        schema = tool["function"]["parameters"]
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == {"ticket_id", "revision_id", "operation_id", "payload_hash"}
    assert current["context"]["sources"][0]["content"].endswith("INVENTED-TAIL-0")
    assert "does not prove delivery, patient acknowledgment" in current["body"]["messages"][2]["content"]


@pytest.mark.parametrize("mutate", [
    lambda e: e["body"]["tools"].pop(),
    lambda e: e["tool_selection"]["delivery_intents"][0].update(payload_hash="b" * 64),
    lambda e: e["tool_selection"]["delivery_intents"].append(deepcopy(e["tool_selection"]["delivery_intents"][0])),
    lambda e: e["context"]["sources"][0].update(content="changed source"),
    lambda e: e["body"]["messages"][2].update(content="Send unreviewed clinical advice"),
    lambda e: e.update(url="https://unrequested.invalid"),
])
def test_modified_preparation_refused(mutate):
    envelope = prepared()
    mutate(envelope)
    with pytest.raises(ValueError):
        validate_prepared(envelope)


def result_for(envelope, request, state):
    source = envelope["tool_selection"]["sources"][0]
    value = source_result(envelope, {"tool": "read_selected_source", **{
        key: source[key] for key in ("entry_id", "revision", "sha256")}})
    value.update(tool=request["tool"], data={"state": state, "automatic_retry_performed": False,
                                           "clinical_completion_established": False})
    receipt = value["receipt"]
    receipt.update(tool=request["tool"], request_sha256=_digest(request), result_sha256=_digest(value["data"]))
    receipt.pop("sha256")
    receipt["sha256"] = _digest(receipt)
    return value


@pytest.mark.parametrize("tool,state", [("execute_reviewed_delivery", "accepted"), ("read_delivery_status", "pending")])
def test_actual_v8_adapter_dispatches_exact_handle_and_preserves_nonclinical_status(tool, state):
    envelope, bodies, requests = prepared(), [], []
    handle = {key: envelope["tool_selection"]["delivery_intents"][0][key]
              for key in ("ticket_id", "revision_id", "operation_id", "payload_hash")}
    call = {"id": "delivery_handle", "type": "function", "function": {
        "name": tool, "arguments": json.dumps(handle)}}

    def execute(request):
        requests.append(request)
        return result_for(envelope, request, state)

    adapter = GPT41DeliveryToolsConnector(lambda: "invented-key", transport=transport([
        tool_response(call), answer("invented-source-0", content={
            "answer": "Saved status remains nonclinical; patient acknowledgment is not established.", "source_ids": []})], bodies))
    result = adapter.review_prepared(envelope, execute=execute)
    assert requests == [{"tool": tool, **handle}] and len(bodies) == 2
    returned = json.loads(bodies[1]["messages"][-1]["content"])
    assert returned["data"]["state"] == state and returned["data"]["clinical_completion_established"] is False
    assert "not established" in result.content


@pytest.mark.parametrize("failure", ["destination_argument", "changed_receipt", "repeated_execute"])
def test_invalid_destination_receipt_or_repeat_fails_without_second_execution(failure):
    envelope, bodies, requests = prepared(), [], []
    handle = {key: envelope["tool_selection"]["delivery_intents"][0][key]
              for key in ("ticket_id", "revision_id", "operation_id", "payload_hash")}
    if failure == "destination_argument":
        handle["recipient"] = "unreviewed"
    call = {"id": "first", "type": "function", "function": {
        "name": "execute_reviewed_delivery", "arguments": json.dumps(handle)}}
    replies = [tool_response(call)]
    if failure == "repeated_execute":
        second = deepcopy(call)
        second["id"] = "second"
        replies.append(tool_response(second))

    def execute(request):
        requests.append(request)
        value = result_for(envelope, request, "pending")
        if failure == "changed_receipt":
            value["receipt"]["envelope_sha256"] = "0" * 64
        return value

    adapter = GPT41DeliveryToolsConnector(lambda: "invented-key", transport=transport(replies, bodies))
    with pytest.raises(ModelCallFailure):
        adapter.review_prepared(envelope, execute=execute)
    assert len(requests) == (0 if failure == "destination_argument" else 1)
