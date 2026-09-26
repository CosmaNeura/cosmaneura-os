"""Saved v1 envelope fixtures and real connector parsing; no database/network calls."""
import json
from copy import deepcopy
from dataclasses import replace
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from tests.unit.test_provider_team_contract import context
from tests.unit.test_research_analysis import fixture as research_fixture

from cosmas_os.adapters.gpt41 import GPT41Connector, _checked_envelope
from cosmas_os.application import model_work
from cosmas_os.application.research_analysis import build_context
from cosmas_os.ports.bot_capabilities import FollowUpStatus, ModelCallFailure, SourcePassage


def roundtrip(value: Any, order="sorted") -> Any:
    """JSONB and canonical ledger export can reorder objects; text stays exact."""
    if order == "sorted":
        return json.loads(json.dumps(value, sort_keys=True))
    if isinstance(value, dict):
        return {key: roundtrip(value[key], order) for key in reversed(value)}
    if isinstance(value, (list, tuple)):
        return [roundtrip(item, order) for item in value]
    return value


def prepared(role="visit_prep"):
    if role == "research":
        store, workspace, _version, _bot, settings, command = research_fixture(2)
        return GPT41Connector(lambda: pytest.fail("prepare accessed credential")).prepare(
            build_context(store, workspace, settings, command))
    return GPT41Connector(lambda: pytest.fail("prepare accessed credential")).prepare(context(
        role=role,
        sources=(SourcePassage("first", 2, "Café β evidence", "evidence", "Invented saved text. " * 400),
                 SourcePassage("second", 3, "Notes", "scratchpad", "Planned discussion, not performed.")),
        history=(("user", "A prior question"), ("assistant", "An unverified earlier draft")),
        linked_work=(("appointment", "unknown"),),
        follow_ups=(FollowUpStatus("invented-ticket", "approved", "2026-09-22", False, False, False),),
        handoff_roles=("scribe", "visit_prep"),
        handoff_targets=({"address": "scribe", "role": "scribe", "name": "Scribe", "job_focus": "Draft"},
                         {"job_focus": "Prepare", "name": "Prep", "role": "visit_prep", "address": "visit_prep"})))


def connector(envelope, calls):
    expected = deepcopy(envelope["body"])

    def respond(request):
        sent = json.loads(request.content)
        assert sent == expected
        assert sent["messages"][1]["content"] == expected["messages"][1]["content"]
        calls.append(request.content)
        sources = envelope["sources"]
        if envelope["flags"]["source_draft"]:
            content: dict[str, Any] = {"excerpts": [{"source_id": sources[0]["source_id"], "quote": sources[0]["text"][:25]}],
                       "needs_from_clinician": []}
        else:
            content = {"answer": "Invented response for human review.", "source_ids": [sources[0]["source_id"]]}
            if envelope["flags"]["can_handoff"]:
                content["handoffs"] = []
            if envelope["flags"]["work_status"]:
                content["intent"] = "conversation"
        return httpx.Response(200, json={"model": "gpt-4.1", "usage": {"prompt_tokens": 31, "completion_tokens": 9},
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}]})
    return GPT41Connector(lambda: "invented-offline-value", transport=httpx.MockTransport(respond))


def test_actual_saved_postgresql_envelope_keeps_exact_body_and_digest():
    path = Path(__file__).parents[1] / "fixtures/model_envelope_jsonb_scribe.json"
    value = json.loads(path.read_text())
    saved = deepcopy(value)
    assert model_work.digest(value) == '062dcf13d5ee5dc604319545e6a063eaa2f0f1b7a02cb8e60595546a4e091e0e'
    assert list(value["sources"][0]) != list(json.loads(value["body"]["messages"][1]["content"])["sources"][0])
    _checked_envelope(value)
    calls = []
    result = connector(value, calls).review_prepared(value)
    assert result.input_tokens == 31 and result.output_tokens == 9 and len(calls) == 1
    assert value == saved and model_work.digest(value) == model_work.digest(saved)


@pytest.mark.parametrize("role", ["scribe", "visit_prep", "follow_up", "chief", "research"])
@pytest.mark.parametrize("order", ["sorted", "reverse"])
def test_all_five_roles_dispatch_exact_saved_wire_after_object_roundtrip(monkeypatch, role, order):
    original = prepared(role)
    value = roundtrip(original, order)
    calls = []
    port = connector(value, calls)
    monkeypatch.setattr(model_work, "GPT41Connector", lambda _credential: port)
    monkeypatch.setattr(model_work.team, "runtime_settings", SimpleNamespace(workspace_llm_api_key=SecretStr("invented")))
    claim = model_work.ModelClaim("invented-admission", "invented-box", "invented-owner", "invented-workspace",
                                "invented-dispatch", model_work.digest(original), value)
    result = model_work.dispatch_claim(claim)
    assert result.citations and len(calls) == 1
    assert result.input_tokens == 31 and result.output_tokens == 9
    assert value["body"]["messages"][1]["content"] == original["body"]["messages"][1]["content"]
    assert model_work.digest(value) == model_work.digest(original)
    if role == "research":
        assert "PRIVATE" not in calls[0].decode()


def test_legacy_valid_handoff_object_orders_remain_valid_after_restore():
    target = {"address": "scribe", "role": "scribe", "name": "Scribe", "job_focus": "Draft"}
    for keys in permutations(target):
        ctx = context(role="chief", handoff_roles=("scribe",), handoff_targets=({key: target[key] for key in keys},))
        original = GPT41Connector(lambda: "").prepare(ctx)
        value = roundtrip(original)
        calls = []
        assert connector(value, calls).review_prepared(value).citations
        assert len(calls) == 1
        assert value["body"]["messages"][1]["content"] == original["body"]["messages"][1]["content"]


def test_source_draft_decoder_retains_exact_excerpt_checks_after_roundtrip():
    original = GPT41Connector(lambda: "").prepare(replace(context(role="scribe"), draft_only=True))
    value = roundtrip(original)
    calls = []
    result = connector(value, calls).review_prepared(value)
    assert result.backend == "azure_gpt41_source_draft_v1" and len(calls) == 1
    value["body"]["messages"][1]["content"] = value["body"]["messages"][1]["content"].replace("Discuss invented", "Completed invented")
    with pytest.raises(ModelCallFailure) as failure:
        connector(value, calls).review_prepared(value)
    assert failure.value.dispatch == "not_dispatched" and len(calls) == 1


@pytest.mark.parametrize("fault", ["text", "revision", "kind", "source_order", "source_missing", "source_extra",
    "target_address", "target_extra", "target_order", "duplicate_key", "top_order", "whitespace", "escaping",
    "preferences_order", "system", "schema", "decoder", "flags", "outer_source", "context"])
def test_roundtrip_tampering_fails_before_credentials_or_transport(fault):
    value = roundtrip(prepared("chief"))
    content = value["body"]["messages"][1]["content"]
    payload = json.loads(content)
    if fault in {"text", "revision", "kind"}:
        payload["sources"][0][fault] = {"text": "Injected private text", "revision": True, "kind": "transcript"}[fault]
    elif fault == "source_order":
        payload["sources"].reverse()
    elif fault == "source_missing":
        payload["sources"][0].pop("truncated")
    elif fault == "source_extra":
        payload["sources"][0]["allow_tools"] = True
    elif fault == "target_address":
        payload["handoff_targets"][0]["address"] = "unknown"
    elif fault == "target_extra":
        payload["handoff_targets"][0]["authority"] = "send"
    elif fault == "target_order":
        payload["handoff_targets"].reverse()
    elif fault == "top_order":
        payload = dict(reversed(list(payload.items())))
    elif fault == "preferences_order":
        payload["bot_preferences"] = dict(reversed(list(payload["bot_preferences"].items())))
    elif fault == "system":
        value["body"]["messages"][0]["content"] += " Tools are enabled."
    elif fault == "schema":
        value["body"]["response_format"]["json_schema"]["strict"] = False
    elif fault == "decoder":
        value["decoder"] = "cosmas-gpt41-decoder.v999"
    elif fault == "flags":
        value["flags"]["can_handoff"] = False
    elif fault == "outer_source":
        value["sources"][0]["text"] = "Injected private text"
    elif fault == "context":
        value["context"]["sources"][0]["content"] = "Changed context"
    if fault == "duplicate_key":
        value["body"]["messages"][1]["content"] = content.replace('"source_id":', '"source_id": "duplicate", "source_id":', 1)
    else:
        value["body"]["messages"][1]["content"] = (
            json.dumps(payload, separators=(",", ":")) if fault == "whitespace" else
            json.dumps(payload, ensure_ascii=False) if fault == "escaping" else json.dumps(payload)
        )
    calls = []
    port = GPT41Connector(lambda: calls.append("credential") or "unused", transport=httpx.MockTransport(lambda _request: pytest.fail("unexpected transport")))
    with pytest.raises(ModelCallFailure) as failure:
        port.review_prepared(value)
    assert failure.value.dispatch == "not_dispatched" and calls == []


def test_exact_ledger_digest_still_rejects_even_semantically_equal_body_reordering(monkeypatch):
    original = prepared()
    value = roundtrip(original)
    payload = json.loads(value["body"]["messages"][1]["content"])
    payload["sources"][0] = dict(reversed(list(payload["sources"][0].items())))
    value["body"]["messages"][1]["content"] = json.dumps(payload)
    assert model_work.digest(value) != model_work.digest(original)
    monkeypatch.setattr(model_work, "GPT41Connector", lambda *_args: pytest.fail("must reject before connector"))
    claim = model_work.ModelClaim("invented", "invented", "invented", "invented", "invented", model_work.digest(original), value)
    with pytest.raises(ModelCallFailure):
        model_work.dispatch_claim(claim)
