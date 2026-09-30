"""Version changes must preserve admitted bytes and fail closed before dispatch."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from tests.unit.test_model_envelope_roundtrip import connector, roundtrip

from cosmas_os.adapters.gpt41 import GPT41Connector, _checked_envelope, _context
from cosmas_os.application.model_work import digest
from cosmas_os.ports.bot_capabilities import ModelCallFailure

FIXTURE = Path(__file__).parents[1] / "fixtures/model_envelopes_v1_roles.json"
LEGACY = json.loads(FIXTURE.read_text())
V2_FIXTURE = Path(__file__).parents[1] / "fixtures/model_envelope_v2_chief_research.json"
V2_CHIEF = json.loads(V2_FIXTURE.read_text())


def legacy_schema(envelope):
    schema = deepcopy(envelope["body"]["response_format"])
    handoffs = schema["json_schema"]["schema"]["properties"].get("handoffs")
    if handoffs and "intended_role" in handoffs["items"]["properties"]:
        del handoffs["items"]["properties"]["intended_role"]
        handoffs["items"]["required"].remove("intended_role")
    return schema


def test_pre_change_fixture_bytes_are_unchanged():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == (
        "cbe3c0304ad8b675a3090e35aab4ab8e30d433df3b11dd03aa7ae5fab640670b"
    )
    assert hashlib.sha256(V2_FIXTURE.read_bytes()).hexdigest() == (
        "182988930add1e62c634f36d83ab60257acb8c8e0347bb2954b8b41105902edf"
    )


@pytest.mark.parametrize("role", LEGACY)
@pytest.mark.parametrize("order", ["sorted", "reverse"])
def test_legacy_requests_dispatch_exact_pre_change_body_after_restore(role, order):
    original = LEGACY[role]
    saved = roundtrip(original, order)
    before = digest(saved)
    _checked_envelope(saved)
    calls = []
    reply = connector(saved, calls).review_prepared(saved)
    assert reply.input_tokens == 31 and reply.output_tokens == 9
    assert len(calls) == 1 and json.loads(calls[0]) == original["body"]
    assert digest(saved) == before == digest(original)


@pytest.mark.parametrize("role", LEGACY)
def test_new_preparation_changes_only_versioned_instructions(role):
    old = LEGACY[role]
    port = GPT41Connector(lambda: pytest.fail("preparation cannot read credentials"))
    new = port.prepare(_context(old["context"]))
    assert new["contract"] == "cosmas-gpt41-prepared.v3"
    assert new["decoder"] == "cosmas-gpt41-decoder.v3"
    # The legacy fixture includes truncated excerpts; preserve its truncation
    # marker when comparing exactly the same bounded source selection.
    equivalent = port._prepare_value(_context(old["context"]), source_records=old["sources"])
    for key in ("context", "sources", "flags"):
        assert json.loads(json.dumps(equivalent[key])) == old[key]
    assert equivalent["body"]["messages"][1] == old["body"]["messages"][1]
    assert legacy_schema(equivalent) == old["body"]["response_format"]
    instructions = new["body"]["messages"][0]["content"]
    assert "Those service sources are not connected here yet" not in instructions
    assert "Capture and the Core SOAP pipeline are not connected" not in instructions
    assert "Live chart and intake retrieval are not connected" not in instructions
    assert "Background routines, human staff handoffs and other encounters are not connected" not in instructions
    assert "no direct chart, capture, intake, calendar, messaging, billing or public-search tools" in instructions
    assert "Cosmaneura is the shared clinical record and review hub" in instructions
    calls = []
    assert connector(roundtrip(new), calls).review_prepared(roundtrip(new)).citations
    assert len(calls) == 1


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
@pytest.mark.parametrize("fault", ["relabel", "mixed_decoder", "unknown", "instructions", "tools", "invented_capability"])
def test_version_or_authority_tampering_is_rejected_before_credentials(version, fault):
    value = deepcopy(LEGACY["chief"])
    if version != "v1":
        value = GPT41Connector(lambda: "")._prepare_value(
            _context(value["context"]), contract=f"cosmas-gpt41-prepared.{version}")
    if fault == "relabel":
        other = "v2" if version == "v1" else "v1"
        value["contract"], value["decoder"] = f"cosmas-gpt41-prepared.{other}", f"cosmas-gpt41-decoder.{other}"
    elif fault == "mixed_decoder":
        value["decoder"] = "cosmas-gpt41-decoder.v2" if version == "v1" else "cosmas-gpt41-decoder.v1"
    elif fault == "unknown":
        value["contract"], value["decoder"] = "cosmas-gpt41-prepared.v999", "cosmas-gpt41-decoder.v999"
    elif fault == "instructions":
        value["body"]["messages"][0]["content"] += " Send a message automatically."
    elif fault == "tools":
        value["body"]["tools"] = [{"type": "function", "function": {"name": "send"}}]
    else:
        value["context"]["service_permissions"] = {"messaging": True}
    calls = []
    port = GPT41Connector(lambda: calls.append("credential") or "invented",
        transport=httpx.MockTransport(lambda _request: pytest.fail("must not dispatch")))
    with pytest.raises(ModelCallFailure) as failure:
        port.review_prepared(value)
    assert failure.value.dispatch == "not_dispatched" and calls == []


@pytest.mark.parametrize("order", ["sorted", "reverse"])
def test_saved_v2_chief_keeps_exact_pre_change_wire_and_recipient_addresses(order):
    saved = roundtrip(V2_CHIEF, order)
    before = digest(saved)
    _checked_envelope(saved)
    calls = []
    assert connector(saved, calls).review_prepared(saved).citations
    assert json.loads(calls[0]) == V2_CHIEF["body"]
    assert digest(saved) == before == digest(V2_CHIEF)


@pytest.mark.parametrize("available", ["all", "without_research", "none"])
def test_new_chief_routing_preserves_limits_and_never_grants_missing_research(available):
    from dataclasses import replace

    context = _context(V2_CHIEF["context"])
    if available != "all":
        targets = tuple(target for target in context.handoff_targets
                        if available != "none" and target["role"] != "research")
        context = replace(context, handoff_targets=targets,
                          handoff_roles=tuple(target["address"] for target in targets))
    port = GPT41Connector(lambda: pytest.fail("preparation cannot read credentials"))
    old = port._prepare_value(context, contract="cosmas-gpt41-prepared.v2")
    new = port.prepare(context)
    for key in ("context", "sources", "flags"):
        assert new[key] == old[key]
    assert new["body"]["messages"][1] == old["body"]["messages"][1]
    assert legacy_schema(new) == old["body"]["response_format"]
    instructions = new["body"]["messages"][0]["content"]
    assert "Research compares supplied medical evidence" in instructions
    assert "never to Scribe, Visit Prep, Follow-up" in instructions
    assert "handoff is unavailable in this request" in instructions
    assert "Do not silently substitute another teammate" in instructions
    assert "eligibility decision" in instructions
    assert "tools" not in new["body"]
    _checked_envelope(roundtrip(new))


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
def test_exact_research_address_dispatches_with_versioned_brief_decoder(version):
    context = _context(V2_CHIEF["context"])
    address = context.handoff_targets[-1]["address"]
    brief = {"role": address, "brief": "Compare the supplied evidence; eligibility is unconfirmed."}
    if version == "v3":
        brief["intended_role"] = "research"
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"model":"gpt-4.1", "choices":[{
            "finish_reason":"stop", "message":{"content":json.dumps({
                "answer":"Queuing a private Research draft.", "source_ids":[], "handoffs":[brief]})}}]})

    port = GPT41Connector(lambda:"invented", transport=httpx.MockTransport(respond))
    saved = port._prepare_value(context, contract=f"cosmas-gpt41-prepared.{version}")
    reply = port.review_prepared(roundtrip(saved))
    assert len(calls) == 1 and reply.handoffs[0].role == address


@pytest.mark.parametrize("fault", ["research_to_scribe", "scribe_to_research", "missing_role", "unknown_role"])
def test_v3_rejects_wrong_intended_role_even_when_address_is_allowed(fault):
    context = _context(V2_CHIEF["context"])
    research = context.handoff_targets[-1]["address"]
    brief = {"role":"scribe", "intended_role":"research", "brief":"Review supplied evidence."}
    if fault == "scribe_to_research":
        brief.update(role=research, intended_role="scribe")
    elif fault == "missing_role":
        del brief["intended_role"]
    elif fault == "unknown_role":
        brief["intended_role"] = "external_search_tool"
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"model":"gpt-4.1", "choices":[{
            "finish_reason":"stop", "message":{"content":json.dumps({
                "answer":"Draft queued.", "source_ids":[], "handoffs":[brief]})}}]})

    with pytest.raises(ModelCallFailure) as failure:
        GPT41Connector(lambda:"invented", transport=httpx.MockTransport(respond)).review(context)
    assert len(calls) == 1 and failure.value.outcome == "invalid_output"
