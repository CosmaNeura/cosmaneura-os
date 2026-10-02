"""Synthetic fake HTTP qualification of compact delivery and full-source custody."""

import json
from copy import deepcopy
from dataclasses import asdict, replace
from typing import Any

import httpx
import pytest

from cosmas_os.adapters import gpt41
from cosmas_os.adapters.gpt41_tools import GPT41ToolsConnector, _digest
from cosmas_os.adapters.gpt41_tools import validate_prepared as validate_v5
from cosmas_os.adapters.gpt41_tools_v6 import GPT41CompactToolsConnector, validate_prepared
from cosmas_os.application import agent_tools
from cosmas_os.ports.bot_capabilities import BotContext, ModelCallFailure, SourcePassage


def invented_text(length: int, number: int) -> str:
    prefix = f"Invented source {number}: planned follow-up remains unconfirmed. "
    tail = f" INVENTED-TAIL-{number}"
    return prefix + "x" * (length - len(prefix) - len(tail)) + tail


def context(lengths: tuple[int, ...], *, scribe: bool = False) -> BotContext:
    sources = tuple(SourcePassage(f"invented-source-{i}", i + 1, f"Invented café source {i}",
        "evidence", invented_text(length, i)) for i, length in enumerate(lengths))
    return BotContext("invented-workspace", len(sources), "scribe" if scribe else "visit_prep",
        "Prepare an invented draft for human review.", "brief", sources, (), draft_only=scribe)


def selection(ctx: BotContext) -> dict[str, Any]:
    return agent_tools._selection([{"entry_id": source.entry_id, "revision": source.revision,
        "sha256": agent_tools._content_hash(source.content), "label": source.label,
        "kind": source.kind} for source in ctx.sources], [], [])


def prepared(lengths: tuple[int, ...] = (350,), *, scribe: bool = False) -> dict[str, Any]:
    ctx = context(lengths, scribe=scribe)
    return GPT41CompactToolsConnector(lambda: "invented-key").prepare(ctx, selection(ctx))


def answer(source_id: str, *, content: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"model": "gpt-4.1", "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant",
            "content": json.dumps(content if content is not None else {
                "answer": "Invented draft ready for human review.", "source_ids": [source_id]})}}]}


def read_call(envelope: dict[str, Any], index: int = 0) -> dict[str, Any]:
    source = envelope["tool_selection"]["sources"][index]
    return {"id": f"invented_read_{index}", "type": "function", "function": {
        "name": "read_selected_source", "arguments": json.dumps({
            key: source[key] for key in ("entry_id", "revision", "sha256")})}}


def tool_response(*calls: dict[str, Any]) -> dict[str, Any]:
    return {"model": "gpt-4.1", "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        "choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None, "tool_calls": list(calls)}}]}


def source_result(envelope: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    source = next(item for item in envelope["context"]["sources"]
        if item["entry_id"] == request["entry_id"])
    data = {key: source[key] for key in ("entry_id", "revision", "label", "kind", "content")}
    data["sha256"] = agent_tools._content_hash(source["content"])
    receipt = {"contract": "cosmas-agent-tool-receipt.v1", "tool": request["tool"],
        "admission_id": "invented-admission", "dispatch_id": "invented-dispatch",
        "actor_agent_id": "invented-agent", "initiated_by_human_id": "invented-human",
        "workspace_id": envelope["context"]["workspace_id"], "envelope_sha256": _digest(envelope),
        "selection_sha256": envelope["tool_selection"]["sha256"],
        "request_sha256": _digest(request), "result_sha256": _digest(data)}
    receipt["sha256"] = _digest(receipt)
    return {"contract": "cosmas-agent-tool-result.v1", "tool": request["tool"],
        "data": data, "receipt": receipt}


def transport(responses: list[dict[str, Any]], bodies: list[dict[str, Any]]) -> httpx.MockTransport:
    values = iter(responses)
    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == gpt41.ENDPOINT
        assert request.headers["Authorization"] == "Bearer invented-key"
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=next(values))
    return httpx.MockTransport(handle)


def delivered(body: dict[str, Any]) -> dict[str, Any]:
    return json.loads(body["messages"][1]["content"])


@pytest.mark.parametrize("lengths", [(6000,), (20000,), (5000,) * 7])
def test_full_original_custody_and_independent_delivery_decoder_windows_survive_json_rehydrate(lengths):
    ctx = context(lengths)
    envelope = prepared(lengths)
    original_hash = _digest(envelope)
    saved = json.loads(json.dumps(envelope, ensure_ascii=False))
    validate_prepared(saved)
    assert _digest(saved) == original_hash
    assert gpt41._context(saved["context"]) == ctx
    assert envelope["context"] == asdict(ctx)
    assert envelope["baseline"] == gpt41.GPT41Connector(lambda: "").prepare(ctx)
    prompt = delivered(saved["body"])
    assert sum(len(item["text"]) for item in prompt["sources"]) <= 6000
    assert all(len(item["text"]) <= 1000 for item in prompt["sources"])
    assert sum(item["prefix_chars"] for item in prompt["decoder_source_windows"]) <= 30000
    assert all(item["prefix_chars"] <= 5000 for item in prompt["decoder_source_windows"])
    by_id = {item["source_id"]: item for item in prompt["sources"]}
    assert prompt["decoder_source_windows"] == [{"entry_id": item["source_id"],
        "revision": item["revision"], "prefix_chars": len(item["text"]),
        "sha256": agent_tools._content_hash(item["text"])} for item in prompt["sources"]]
    for source, record, handle in zip(ctx.sources, saved["source_delivery"], saved["tool_selection"]["sources"], strict=True):
        text = by_id.get(source.entry_id, {}).get("text", "")
        assert record["sha256"] == handle["sha256"] == agent_tools._content_hash(source.content)
        assert record["excerpt_sha256"] == agent_tools._content_hash(text)
        assert record["excerpt_chars"] == len(text)
        assert record["delivery"] == ("excerpt" if text else "omitted")
    if len(lengths) == 7:
        assert saved["source_delivery"][0]["delivery"] == "omitted"
        assert len(saved["tool_selection"]["sources"]) == 7
        assert len(saved["baseline"]["sources"]) == 6
    else:
        assert saved["tool_selection"]["sources"][0]["sha256"] != agent_tools._content_hash(
            saved["baseline"]["sources"][0]["text"])


def test_complete_delivered_source_finishes_directly_without_executor_or_added_provider_round():
    envelope, bodies = prepared(), []
    original = deepcopy(envelope)
    supplied = delivered(envelope["body"])
    assert envelope["source_delivery"][0]["delivery"] == "complete"
    assert supplied["sources"][0]["text"] == envelope["context"]["sources"][0]["content"]
    assert supplied["sources"][0]["truncated"] is False
    assert "source_delivery" not in supplied and "decoder_source_windows" not in supplied
    def forbidden(_: dict[str, Any]) -> dict[str, Any]:
        pytest.fail("complete supplied source must not require a read")
    result = GPT41CompactToolsConnector(lambda: "invented-key", transport=transport([
        answer("invented-source-0")], bodies)).review_prepared(envelope, execute=forbidden)
    assert len(bodies) == 1 and result.citations[0].entry_id == "invented-source-0"
    assert result.input_tokens == 100 and envelope == original


def test_complete_small_source_request_has_no_more_than_160_bytes_over_unchanged_v5():
    ctx = context((350, 350, 350))
    selected = selection(ctx)
    v5 = GPT41ToolsConnector(lambda: "invented-key").prepare(ctx, selected)
    v6 = GPT41CompactToolsConnector(lambda: "invented-key").prepare(ctx, selected)
    def encode(body):
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(encode(v6["body"])) <= len(encode(v5["body"])) + 160


@pytest.mark.parametrize("lengths", [(6000,), (20000,), (5000,) * 7])
def test_outbound_v6_excerpt_diagnostics_never_expose_a_competing_tool_handle_hash(lengths):
    envelope, bodies = prepared(lengths), []
    original = deepcopy(envelope)
    stored_hash = _digest(envelope)
    GPT41CompactToolsConnector(lambda: "invented-key", transport=transport([
        answer("invented-source-1" if len(lengths) == 7 else "invented-source-0")], bodies)).review_prepared(
            envelope, execute=lambda _: pytest.fail("direct reply does not request a tool"))
    prompt = delivered(bodies[0])
    assert "decoder_source_windows" not in prompt
    assert prompt["displayed_excerpt_windows"] == [{
        "entry_id": item["source_id"], "revision": item["revision"],
        "prefix_chars": len(item["text"])} for item in prompt["sources"]]
    assert all(set(record) == {"entry_id", "revision", "excerpt_chars", "delivery"}
        for record in prompt["source_delivery"])
    visible_selection = json.loads(bodies[0]["messages"][3]["content"])["tool_selection"]
    assert visible_selection == envelope["tool_selection"]
    wire = json.dumps(bodies[0], ensure_ascii=False)
    for record in envelope["source_delivery"]:
        assert record["excerpt_sha256"] not in wire
    assert "ONLY from tool_selection.sources" in bodies[0]["messages"][2]["content"]
    assert envelope == original and _digest(envelope) == stored_hash
    validate_prepared(envelope)


def test_historical_v6_envelope_hash_stays_fixed_while_outbound_projection_is_unambiguous():
    envelope = prepared((6000,))
    # Computed from the previously reviewed25a361a preparation. This pins the
    # persisted body/manifest/decoder without pinning the new model-only view.
    assert _digest(envelope) == "db0f2c5e14242d475c7f85e8cc5f9a74113888bdb784a27ebc566c076022046c"
    saved = json.loads(json.dumps(envelope, sort_keys=True, ensure_ascii=False))
    validate_prepared(saved)
    adapter = GPT41CompactToolsConnector(lambda: "invented-key")
    assert adapter._request_body(saved) == adapter._request_body(envelope)
    assert _digest(saved) == _digest(envelope)
    assert adapter._request_body(saved) != saved["body"]


def test_model_following_the_only_visible_source_handle_reads_full_text_and_can_quote_its_tail():
    envelope, bodies, reads = prepared((12000,), scribe=True), [], []
    original = deepcopy(envelope)
    def provider(request):
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) == 1:
            prompt = delivered(body)
            assert "sha256" not in json.dumps(prompt)
            handle = json.loads(body["messages"][3]["content"])["tool_selection"]["sources"][0]
            call = {"id": "copy_full_handle", "type": "function", "function": {
                "name": "read_selected_source", "arguments": json.dumps({
                    key: handle[key] for key in ("entry_id", "revision", "sha256")})}}
            return httpx.Response(200, json=tool_response(call))
        return httpx.Response(200, json=answer("invented-source-0", content={
            "excerpts": [{"source_id": "invented-source-0", "quote": "INVENTED-TAIL-0"}],
            "needs_from_clinician": []}))
    def execute(request):
        reads.append(request)
        return source_result(envelope, request)
    result = GPT41CompactToolsConnector(lambda: "invented-key", transport=httpx.MockTransport(provider)).review_prepared(
        envelope, execute=execute)
    assert reads == [{"tool": "read_selected_source", **{key: envelope["tool_selection"]["sources"][0][key]
        for key in ("entry_id", "revision", "sha256")}}]
    returned = json.loads(bodies[1]["messages"][-1]["content"])
    assert len(returned["data"]["content"]) == 12000
    assert returned["receipt"]["envelope_sha256"] == _digest(original)
    assert "INVENTED-TAIL-0" in result.content and len(bodies) == 2
    assert envelope == original


def test_removed_excerpt_hash_still_cannot_authorize_a_full_source_read():
    envelope, bodies, reads = prepared((12000,)), [], []
    excerpt_hash = envelope["source_delivery"][0]["excerpt_sha256"]
    original_hash = envelope["tool_selection"]["sources"][0]["sha256"]
    assert excerpt_hash != original_hash
    call = read_call(envelope)
    arguments = json.loads(call["function"]["arguments"])
    arguments["sha256"] = excerpt_hash
    call["function"]["arguments"] = json.dumps(arguments)
    def guarded_reader(request):
        reads.append(request)
        assert request["sha256"] == excerpt_hash
        raise agent_tools.ws.WorkspaceError("agent_tool_source_unavailable", 404)
    with pytest.raises(ModelCallFailure) as failure:
        GPT41CompactToolsConnector(lambda: "invented-key", transport=transport([
            tool_response(call)], bodies)).review_prepared(envelope, execute=guarded_reader)
    assert len(bodies) == len(reads) == 1
    assert failure.value.outcome == "invalid_output"
    assert excerpt_hash not in json.dumps(bodies[0])


def chief_envelope() -> dict[str, Any]:
    ctx = replace(context((6000,)), role="chief", handoff_roles=("scribe",), handoff_targets=(
        {"address": "scribe", "role": "scribe", "name": "Invented Scribe",
            "job_focus": "Prepare invented notes for review."},))
    return GPT41CompactToolsConnector(lambda: "invented-key").prepare(ctx, selection(ctx))


def test_sorted_jsonb_rehydrate_preserves_exact_chief_target_provider_string_and_direct_reply():
    envelope, bodies = chief_envelope(), []
    saved = json.loads(json.dumps(envelope, sort_keys=True, ensure_ascii=False))
    assert list(saved["context"]["handoff_targets"][0]) != list(envelope["context"]["handoff_targets"][0])
    validate_prepared(saved)
    assert _digest(saved) == _digest(envelope)
    assert saved["body"] == envelope["body"]
    result = GPT41CompactToolsConnector(lambda: "invented-key", transport=transport([
        answer("invented-source-0", content={"answer": "Invented Chief draft.",
            "source_ids": ["invented-source-0"], "handoffs": []})], bodies)).review_prepared(
                saved, execute=lambda _: pytest.fail("direct reply needs no tool"))
    assert result.content == "Invented Chief draft."
    assert bodies == [GPT41CompactToolsConnector(lambda: "")._request_body(envelope)]
    assert saved["body"] == envelope["body"] and _digest(saved) == _digest(envelope)


def packet_context(count: int = 6, length: int = 4500) -> BotContext:
    digest = "a" * 64
    return replace(context((length,) * count), role="scribe", draft_only=True,
        sources=tuple(replace(source, label=f"Reviewed Scribe snapshot · {digest} · {index + 1}/{count}")
            for index, source in enumerate(context((length,) * count).sources)))


def test_indivisible_reviewed_scribe_packet_is_complete_in_initial_delivery_even_above_compact_budget():
    ctx, bodies = packet_context(), []
    envelope = GPT41CompactToolsConnector(lambda: "invented-key").prepare(ctx, selection(ctx))
    prompt = delivered(envelope["body"])
    assert sum(len(source["text"]) for source in prompt["sources"]) == 27000
    assert all(record["delivery"] == "complete" for record in envelope["source_delivery"])
    assert all(not source["truncated"] for source in prompt["sources"])
    assert {source["source_id"]: source["text"] for source in prompt["sources"]} == {
        source.entry_id: source.content for source in ctx.sources}
    # A packet-tail quote is actually supplied, so no lazy read is required.
    tail = "INVENTED-TAIL-0"
    result = GPT41CompactToolsConnector(lambda: "invented-key", transport=transport([
        answer(ctx.sources[0].entry_id, content={"excerpts": [{"source_id": ctx.sources[0].entry_id,
            "quote": tail}], "needs_from_clinician": []})], bodies)).review_prepared(
                envelope, execute=lambda _: pytest.fail("complete packet must not need partial lazy reads"))
    assert len(bodies) == 1 and tail in result.content


@pytest.mark.parametrize("mutation", ["missing-part", "duplicate-part", "inconsistent-count", "oversized", "crowded-out"])
def test_incomplete_or_overflowed_reviewed_packet_fails_before_provider_dispatch(mutation):
    ctx = packet_context()
    if mutation == "missing-part":
        ctx = replace(ctx, sources=ctx.sources[:-1])
    elif mutation == "duplicate-part":
        ctx = replace(ctx, sources=(replace(ctx.sources[0], label=ctx.sources[1].label), *ctx.sources[1:]))
    elif mutation == "inconsistent-count":
        ctx = replace(ctx, sources=(replace(ctx.sources[0], label=f"Reviewed Scribe snapshot · {'a' * 64} · 1/7"), *ctx.sources[1:]))
    elif mutation == "oversized":
        ctx = packet_context(7, 4500)
    else:
        extra = SourcePassage("invented-new-reference", 7, "Invented later reference", "evidence", invented_text(5000, 7))
        ctx = replace(ctx, sources=(*ctx.sources, extra))
    bodies = []
    with pytest.raises(agent_tools.ws.WorkspaceError, match="scribe_source_context_too_large"):
        GPT41CompactToolsConnector(lambda: "invented-key", transport=transport([], bodies)).prepare(ctx, selection(ctx))
    assert bodies == []


@pytest.mark.parametrize("mutation", ["original-target", "baseline-target", "delivery-target", "baseline-schema"])
def test_sorted_rehydration_does_not_authorize_changed_chief_targets_or_schema(mutation):
    saved, bodies = json.loads(json.dumps(chief_envelope(), sort_keys=True)), []
    if mutation == "original-target":
        saved["context"]["handoff_targets"][0]["name"] = "Invented changed recipient"
    elif mutation in {"baseline-target", "delivery-target"}:
        body = saved["baseline"]["body"] if mutation == "baseline-target" else saved["body"]
        content = json.loads(body["messages"][1]["content"])
        content["handoff_targets"][0]["role"] = "research"
        body["messages"][1]["content"] = json.dumps(content)
    else:
        saved["baseline"]["body"]["response_format"]["json_schema"]["schema"]["additionalProperties"] = True
    with pytest.raises(ModelCallFailure) as failure:
        GPT41CompactToolsConnector(lambda: "invented-key", transport=transport([], bodies)).review_prepared(
            saved, execute=lambda _: pytest.fail("altered request must not execute"))
    assert failure.value.dispatch == "not_dispatched" and bodies == []


@pytest.mark.parametrize("lengths", [(6000, 350), (20000, 350), (5000,) * 7])
def test_verified_full_read_replaces_only_its_excerpt_and_keeps_exact_original_envelope(lengths):
    envelope, bodies, reads = prepared(lengths), [], []
    original = deepcopy(envelope)
    def execute(request: dict[str, Any]) -> dict[str, Any]:
        reads.append(request)
        return source_result(envelope, request)
    citation = envelope["baseline"]["sources"][0]["source_id"]
    result = GPT41CompactToolsConnector(lambda: "invented-key", transport=transport([
        tool_response(read_call(envelope)), answer(citation)], bodies)).review_prepared(envelope, execute=execute)
    assert len(bodies) == 2 and len(reads) == 1
    first, second = delivered(bodies[0]), delivered(bodies[1])
    assert second["sources"] == [item for item in first["sources"] if item["source_id"] != "invented-source-0"]
    assert second["source_delivery"] == first["source_delivery"]
    assert second["displayed_excerpt_windows"] == first["displayed_excerpt_windows"]
    result_data = json.loads(bodies[1]["messages"][-1]["content"])
    assert result_data["data"]["content"] == envelope["context"]["sources"][0]["content"]
    assert result_data["receipt"]["envelope_sha256"] == _digest(original)
    assert result.input_tokens == 200 and envelope == original


@pytest.mark.parametrize("field", ["content", "entry_id", "revision", "sha256", "label", "kind", "extra", "missing"])
def test_semantically_wrong_full_read_is_rejected_even_with_rehashed_result_receipt(field):
    envelope, bodies = prepared((6000,)), []
    def execute(request: dict[str, Any]) -> dict[str, Any]:
        result = source_result(envelope, request)
        if field == "extra":
            result["data"]["external_work_established"] = True
        elif field == "missing":
            del result["data"]["label"]
        else:
            result["data"][field] = 2 if field == "revision" else "invented changed value"
        result["receipt"]["result_sha256"] = _digest(result["data"])
        result["receipt"]["sha256"] = _digest({key: value for key, value in result["receipt"].items() if key != "sha256"})
        return result
    with pytest.raises(ModelCallFailure) as failure:
        GPT41CompactToolsConnector(lambda: "invented-key", transport=transport([
            tool_response(read_call(envelope))], bodies)).review_prepared(envelope, execute=execute)
    assert len(bodies) == 1 and failure.value.dispatch == "response_received"


def test_wrong_receipt_hash_is_rejected_before_a_second_http_request():
    envelope, bodies = prepared((6000,)), []
    def execute(request: dict[str, Any]) -> dict[str, Any]:
        result = source_result(envelope, request)
        result["receipt"]["request_sha256"] = "a" * 64
        result["receipt"]["sha256"] = _digest({key: value for key, value in result["receipt"].items() if key != "sha256"})
        return result
    with pytest.raises(ModelCallFailure):
        GPT41CompactToolsConnector(lambda: "invented-key", transport=transport([
            tool_response(read_call(envelope))], bodies)).review_prepared(envelope, execute=execute)
    assert len(bodies) == 1


@pytest.mark.parametrize("tool_name", ["list_selected_sources", "read_saved_teammate_draft", "read_current_operation_status"])
def test_metadata_teammate_and_status_reads_do_not_make_an_omitted_clinical_source_citable(tool_name):
    envelope, bodies = prepared((5000,) * 7), []
    handle = envelope["tool_selection"]["sources"][0]
    arguments = ({key: handle[key] for key in ("entry_id", "revision", "sha256")}
        if tool_name == "read_saved_teammate_draft" else {"kind": "follow_up",
            "record_id": "invented-operation", "commitment": "a" * 64}
        if tool_name == "read_current_operation_status" else {})
    call = {"id": "invented_nonclinical_read", "type": "function", "function": {
        "name": tool_name, "arguments": json.dumps(arguments)}}
    def execute(request: dict[str, Any]) -> dict[str, Any]:
        # Receipt is valid transport evidence, but this tool is not a source read.
        result = source_result(envelope, {"tool": tool_name, "entry_id": handle["entry_id"]})
        result["receipt"]["request_sha256"] = _digest(request)
        result["receipt"]["sha256"] = _digest({key: value for key, value in result["receipt"].items() if key != "sha256"})
        return result
    with pytest.raises(ModelCallFailure) as failure:
        GPT41CompactToolsConnector(lambda: "invented-key", transport=transport([
            tool_response(call), answer(handle["entry_id"])], bodies)).review_prepared(envelope, execute=execute)
    assert len(bodies) == 2 and failure.value.outcome == "invalid_output"


@pytest.mark.parametrize("mutation", ["excerpt", "manifest", "decoder-window", "full-tail", "full-handle", "schema"])
def test_changed_delivery_or_original_is_rejected_before_http(mutation):
    envelope, bodies = prepared((6000,)), []
    if mutation in {"excerpt", "decoder-window"}:
        prompt = delivered(envelope["body"])
        if mutation == "excerpt":
            prompt["sources"][0]["text"] = "Invented replacement excerpt"
        else:
            prompt["decoder_source_windows"][0]["prefix_chars"] = 6000
        envelope["body"]["messages"][1]["content"] = json.dumps(prompt)
    elif mutation == "manifest":
        envelope["source_delivery"][0]["delivery"] = "complete"
    elif mutation == "full-tail":
        envelope["context"]["sources"][0]["content"] = envelope["context"]["sources"][0]["content"][:-1] + "z"
    elif mutation == "full-handle":
        envelope["tool_selection"]["sources"][0]["sha256"] = "a" * 64
    else:
        envelope["body"]["tools"][0]["function"]["parameters"]["additionalProperties"] = True
    with pytest.raises(ModelCallFailure) as failure:
        GPT41CompactToolsConnector(lambda: "invented-key", transport=transport([], bodies)).review_prepared(
            envelope, execute=lambda _: pytest.fail("invalid preparation must not execute"))
    assert failure.value.dispatch == "not_dispatched" and bodies == []


@pytest.mark.parametrize("quote_region", ["eligible-prefix", "full-read-tail"])
def test_scribe_exact_full_read_makes_received_tail_eligible_for_strict_verbatim_output(quote_region):
    envelope, bodies = prepared((6000,), scribe=True), []
    source = envelope["context"]["sources"][0]
    quote = source["content"][:70] if quote_region == "eligible-prefix" else "INVENTED-TAIL-0"
    responses = [tool_response(read_call(envelope)), answer(source["entry_id"], content={
        "excerpts": [{"source_id": source["entry_id"], "quote": quote}],
        "needs_from_clinician": ["Can you confirm the missing visit details?"]})]
    def run():
        return GPT41CompactToolsConnector(lambda: "invented-key",
            transport=transport(responses, bodies)).review_prepared(
            envelope, execute=lambda request: source_result(envelope, request))
    if quote_region == "full-read-tail":
        assert quote not in envelope["baseline"]["sources"][0]["text"]
    result = run()
    assert quote in result.content and result.backend == "azure_gpt41_source_draft_v1"
    assert len(bodies) == 2


@pytest.mark.parametrize("quote", ["INVENTED-TAIL-0", "x" * 1100])
def test_scribe_unread_tail_or_merely_stored_baseline_does_not_grant_quote_eligibility(quote):
    envelope, bodies = prepared((6000,), scribe=True), []
    source = envelope["context"]["sources"][0]
    assert quote in source["content"]
    assert quote not in delivered(envelope["body"])["sources"][0]["text"]
    with pytest.raises(ModelCallFailure) as failure:
        GPT41CompactToolsConnector(lambda: "invented-key", transport=transport([
            answer(source["entry_id"], content={"excerpts": [{"source_id": source["entry_id"], "quote": quote}],
                "needs_from_clinician": []})], bodies)).review_prepared(
                    envelope, execute=lambda _: pytest.fail("no read was requested"))
    assert len(bodies) == 1 and failure.value.outcome == "invalid_output"


@pytest.mark.parametrize("read", [False, True])
def test_initially_omitted_source_handle_cannot_be_cited_until_exact_full_read(read):
    envelope, bodies = prepared((5000,) * 7), []
    assert envelope["source_delivery"][0]["delivery"] == "omitted"
    responses = ([tool_response(read_call(envelope))] if read else []) + [answer("invented-source-0")]
    def run():
        return GPT41CompactToolsConnector(lambda: "invented-key", transport=transport(responses, bodies)).review_prepared(
            envelope, execute=lambda request: source_result(envelope, request))
    if read:
        assert run().citations[0].entry_id == "invented-source-0"
        assert len(bodies) == 2
    else:
        with pytest.raises(ModelCallFailure) as failure:
            run()
        assert len(bodies) == 1 and failure.value.outcome == "invalid_output"


def test_v5_json_replay_keeps_its_original_excerpt_after_a_read_and_rejects_v6_envelope():
    ctx, bodies = context((2000,)), []
    old = GPT41ToolsConnector(lambda: "invented-key").prepare(ctx, selection(ctx))
    saved = json.loads(json.dumps(old, ensure_ascii=False))
    validate_v5(saved)
    GPT41ToolsConnector(lambda: "invented-key", transport=transport([
        tool_response(read_call(saved)), answer("invented-source-0")], bodies)).review_prepared(
            saved, execute=lambda request: source_result(saved, request))
    assert len(bodies) == 2 and delivered(bodies[1])["sources"] == delivered(bodies[0])["sources"]
    assert bodies[0] == saved["body"]
    assert json.dumps(bodies[0], separators=(",", ":"), ensure_ascii=False).encode() == json.dumps(
        saved["body"], separators=(",", ":"), ensure_ascii=False).encode()
    assert _digest(saved["baseline"]) == _digest(gpt41.GPT41Connector(lambda: "").prepare(ctx))
    with pytest.raises(ModelCallFailure) as failure:
        GPT41ToolsConnector(lambda: "invented-key", transport=transport([], [])).review_prepared(
            prepared(), execute=lambda _: pytest.fail("wrong version must not dispatch"))
    assert failure.value.dispatch == "not_dispatched"
