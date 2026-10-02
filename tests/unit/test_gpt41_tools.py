"""Actual fake HTTP rounds through the pinned product tool adapter."""

import json
from copy import deepcopy

import httpx
import pytest

from cosmas_os.adapters import gpt41
from cosmas_os.adapters.gpt41_tools import GPT41ToolsConnector, _digest, validate_prepared
from cosmas_os.application import agent_tools
from cosmas_os.ports.bot_capabilities import BotContext, ModelCallFailure, SourcePassage


def prepared():
    source = SourcePassage("invented-source", 1, "Invented source", "evidence", "Invented provider plan.")
    ctx = BotContext("invented-workspace", 1, "visit_prep", "Prepare the agenda", "brief", (source,), ())
    selection = agent_tools._selection([{"entry_id": source.entry_id, "revision": source.revision,
        "sha256": agent_tools._content_hash(source.content), "label": source.label, "kind": source.kind}], [], [])
    return GPT41ToolsConnector(lambda: "invented-key").prepare(ctx, selection)


def answer(*, model="gpt-4.1", content=None, finish="stop", usage=None):
    return {"model": model, "usage": usage or {"prompt_tokens": 100, "completion_tokens": 20},
        "choices": [{"finish_reason": finish, "message": {"role": "assistant",
            "content": json.dumps(content or {"answer": "Invented agenda ready for review.", "source_ids": ["invented-source"]})}}]}


def tool(name="list_selected_sources", arguments=None, call_id="call_1"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments or {})}}


def request_tools(*calls):
    value = answer()
    value["choices"][0] = {"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": list(calls)}}
    return value


def executor(envelope, calls):
    def execute(request):
        calls.append(request)
        data = envelope["tool_selection"] if request["tool"] == "list_selected_sources" else {"content": "Invented provider plan."}
        receipt = {"contract": "cosmas-agent-tool-receipt.v1", "tool": request["tool"],
            "admission_id": "invented-admission", "dispatch_id": "invented-dispatch",
            "actor_agent_id": "invented-agent", "initiated_by_human_id": "invented-human",
            "workspace_id": envelope["context"]["workspace_id"], "envelope_sha256": _digest(envelope),
            "selection_sha256": envelope["tool_selection"]["sha256"],
            "request_sha256": _digest(request), "result_sha256": _digest(data)}
        receipt["sha256"] = _digest(receipt)
        return {"contract": "cosmas-agent-tool-result.v1", "tool": request["tool"], "data": data, "receipt": receipt}
    return execute


def connector(responses, requests, *, monotonic=None):
    values = iter(responses)
    def handle(request):
        assert str(request.url) == gpt41.ENDPOINT
        assert request.headers["Authorization"] == "Bearer invented-key"
        body = json.loads(request.content)
        assert body["model"] == "gpt-4.1" and body["store"] is False
        requests.append(body)
        value = next(values)
        if isinstance(value, Exception):
            raise value
        return httpx.Response(200, json=value)
    return GPT41ToolsConnector(lambda: "invented-key", transport=httpx.MockTransport(handle),
        **({"monotonic": monotonic} if monotonic else {}))


def test_actual_two_http_rounds_execute_selected_tool_and_aggregate_usage():
    envelope, requests, calls = prepared(), [], []
    result = connector([request_tools(tool()), answer()], requests).review_prepared(envelope, execute=executor(envelope, calls))
    assert calls == [{"tool": "list_selected_sources"}]
    assert len(requests) == 2 and requests[1]["messages"][-1]["role"] == "tool"
    returned = json.loads(requests[1]["messages"][-1]["content"])
    assert returned["receipt"]["actor_agent_id"] != returned["receipt"]["initiated_by_human_id"]
    assert result.input_tokens == 200 and result.output_tokens == 40
    assert result.citations[0].entry_id == "invented-source"
    assert result.response_sha256 is not None and len(result.response_sha256) == 64


def test_three_rounds_list_then_exact_source_read_and_final_answer():
    envelope, requests, calls = prepared(), [], []
    source = envelope["tool_selection"]["sources"][0]
    read = tool("read_selected_source", {key: source[key] for key in ("entry_id", "revision", "sha256")}, "call_2")
    result = connector([request_tools(tool()), request_tools(read), answer()], requests).review_prepared(envelope, execute=executor(envelope, calls))
    assert len(requests) == 3 and [r["tool"] for r in calls] == ["list_selected_sources", "read_selected_source"]
    assert result.input_tokens == 300 and result.output_tokens == 60


@pytest.mark.parametrize("mutate", [
    lambda e: e["body"].update(model="unapproved-model"),
    lambda e: e["body"]["tools"][0]["function"]["parameters"].update(additionalProperties=True),
    lambda e: e["tool_selection"]["sources"][0].update(revision=2),
    lambda e: e["context"].update(question="different question"),
    lambda e: e.update(contract="cosmas-gpt41-prepared.v4"),
])
def test_changed_preparation_fails_before_http(mutate):
    envelope = prepared()
    mutate(envelope)
    requests = []
    with pytest.raises(ModelCallFailure) as error:
        connector([], requests).review_prepared(envelope, execute=lambda r: pytest.fail("unexpected tool"))
    assert error.value.dispatch == "not_dispatched" and requests == []


@pytest.mark.parametrize("call", [
    tool("send_email"), tool("read_selected_source", {"url": "https://invented.invalid"}),
    tool("list_selected_sources", {"owner_id": "invented-human"}),
    {"id": "invented-call", "type": "function", "function": {"name": "list_selected_sources", "arguments": "{}", "extra": "forbidden"}},
    tool("list_selected_sources", {"tool": "list_selected_sources"}),
])
def test_unknown_tools_or_extra_arguments_are_not_executed(call):
    envelope, requests, calls = prepared(), [], []
    with pytest.raises(ModelCallFailure) as error:
        connector([request_tools(call)], requests).review_prepared(envelope, execute=executor(envelope, calls))
    assert len(requests) == 1 and calls == [] and error.value.input_tokens == 100


def test_duplicate_tool_ids_and_repeated_reads_stop_without_another_http_round():
    envelope, requests, calls = prepared(), [], []
    with pytest.raises(ModelCallFailure):
        connector([request_tools(tool(), tool(call_id="call_1"))], requests).review_prepared(envelope, execute=executor(envelope, calls))
    assert len(requests) == 1 and calls == []
    requests, calls = [], []
    with pytest.raises(ModelCallFailure):
        connector([request_tools(tool()), request_tools(tool(call_id="call_2"))], requests).review_prepared(envelope, execute=executor(envelope, calls))
    assert len(requests) == 2 and len(calls) == 1


def test_round_and_tool_budget_are_enforced_before_execution():
    envelope, requests, calls = prepared(), [], []
    with pytest.raises(ModelCallFailure):
        connector([request_tools(*(tool(call_id="call_" + str(i)) for i in range(5)))], requests).review_prepared(envelope, execute=executor(envelope, calls))
    assert len(requests) == 1 and calls == []


def test_four_distinct_tools_use_two_http_rounds_then_force_final_answer():
    envelope, requests, calls = prepared(), [], []
    source = envelope["tool_selection"]["sources"][0]
    handles = {key: source[key] for key in ("entry_id", "revision", "sha256")}
    requested = request_tools(tool(), tool("read_selected_source", handles, "call_2"),
        tool("read_saved_teammate_draft", {**handles, "entry_id": "invented-draft"}, "call_3"),
        tool("read_current_operation_status", {"kind": "follow_up", "record_id": "invented-work", "commitment": "a" * 64}, "call_4"))
    connector([requested, answer()], requests).review_prepared(envelope, execute=executor(envelope, calls))
    assert len(requests) == 2 and len(calls) == 4 and requests[1]["tool_choice"] == "none"


def test_third_provider_round_cannot_start_another_tool_round():
    envelope, requests, calls = prepared(), [], []
    source = envelope["tool_selection"]["sources"][0]
    read = tool("read_selected_source", {key: source[key] for key in ("entry_id", "revision", "sha256")}, "call_2")
    more = tool("read_saved_teammate_draft", {"entry_id": "invented-draft", "revision": 1, "sha256": "a" * 64}, "call_3")
    with pytest.raises(ModelCallFailure) as error:
        connector([request_tools(tool()), request_tools(read), request_tools(more)], requests).review_prepared(envelope, execute=executor(envelope, calls))
    assert len(requests) == 3 and len(calls) == 2 and error.value.input_tokens == 300


def test_stale_executor_withholds_draft_and_does_not_repeat_model_dispatch():
    envelope, requests = prepared(), []
    def stale(_):
        raise agent_tools.ws.WorkspaceError("source_changed")
    with pytest.raises(ModelCallFailure) as error:
        connector([request_tools(tool())], requests).review_prepared(envelope, execute=stale)
    assert len(requests) == 1 and error.value.input_tokens == 100 and error.value.dispatch == "response_received"


def test_timeout_after_one_tool_round_is_uncertain_without_retry_or_fabricated_usage():
    envelope, requests, calls = prepared(), [], []
    with pytest.raises(ModelCallFailure) as error:
        connector([request_tools(tool()), httpx.ReadTimeout("invented transport failure")], requests).review_prepared(envelope, execute=executor(envelope, calls))
    assert len(requests) == 2 and len(calls) == 1
    assert error.value.dispatch == "started_unconfirmed" and error.value.input_tokens is None
    assert error.value.response_sha256 is not None


@pytest.mark.parametrize("value", [
    answer(model="different-model"), answer(finish="length"),
    answer(content={"answer": "Invented answer", "source_ids": ["unselected-teammate-draft"]}),
])
def test_model_mismatch_incomplete_answer_or_new_citation_is_rejected(value):
    envelope, requests = prepared(), []
    with pytest.raises(ModelCallFailure):
        connector([value], requests).review_prepared(envelope, execute=lambda r: pytest.fail("unexpected tool"))
    assert len(requests) == 1


def test_late_response_hits_total_deadline_without_retry():
    envelope, requests = prepared(), []
    ticks = iter([0, 0, 0, 61])
    with pytest.raises(ModelCallFailure):
        connector([answer()], requests, monotonic=lambda: next(ticks)).review_prepared(envelope, execute=lambda r: pytest.fail("unexpected tool"))
    assert len(requests) == 1


def test_tool_result_receipt_tampering_is_not_passed_to_model():
    envelope, requests, calls = prepared(), [], []
    good = executor(envelope, calls)
    def altered(request):
        result = good(request)
        result["receipt"]["result_sha256"] = "a" * 64
        return result
    with pytest.raises(ModelCallFailure):
        connector([request_tools(tool())], requests).review_prepared(envelope, execute=altered)
    assert len(requests) == 1


def test_tool_receipts_cannot_change_admission_or_principals_between_reads():
    envelope, requests, calls = prepared(), [], []
    source = envelope["tool_selection"]["sources"][0]
    read = tool("read_selected_source", {key: source[key] for key in ("entry_id", "revision", "sha256")}, "call_2")
    good = executor(envelope, calls)
    def altered(request):
        result = good(request)
        if len(calls) == 2:
            result["receipt"]["dispatch_id"] = "invented-different-dispatch"
            result["receipt"].pop("sha256")
            result["receipt"]["sha256"] = _digest(result["receipt"])
        return result
    with pytest.raises(ModelCallFailure):
        connector([request_tools(tool(), read)], requests).review_prepared(envelope, execute=altered)
    assert len(requests) == 1 and len(calls) == 2


@pytest.mark.parametrize("usage", [
    {"prompt_tokens": True, "completion_tokens": 20},
    {"prompt_tokens": 100, "completion_tokens": -1},
    {"prompt_tokens": 100},
])
def test_missing_or_untrusted_usage_is_not_fabricated(usage):
    envelope, requests, calls = prepared(), [], []
    result = connector([request_tools(tool()), answer(usage=usage)], requests).review_prepared(envelope, execute=executor(envelope, calls))
    assert result.input_tokens is None and result.output_tokens is None and len(requests) == 2


def test_refusal_with_selected_tool_is_never_executed():
    envelope, requests, calls = prepared(), [], []
    value = request_tools(tool())
    value["choices"][0]["message"]["refusal"] = "Invented refusal"
    with pytest.raises(ModelCallFailure):
        connector([value], requests).review_prepared(envelope, execute=executor(envelope, calls))
    assert len(requests) == 1 and calls == []


def test_v5_baseline_remains_exact_original_v4_and_does_not_change_old_supported_union():
    envelope = prepared()
    validate_prepared(envelope)
    ctx = gpt41._context(envelope["context"])
    assert envelope["baseline"] == gpt41.GPT41Connector(lambda: "").prepare(ctx)
    assert "cosmas-gpt41-prepared.v5" not in gpt41.SUPPORTED_PREPARED_CONTRACTS
    old = deepcopy(envelope["baseline"])
    with pytest.raises(ModelCallFailure) as error:
        GPT41ToolsConnector(lambda: "invented-key").review_prepared(old, execute=lambda _: pytest.fail("unexpected tool"))
    assert error.value.dispatch == "not_dispatched"
