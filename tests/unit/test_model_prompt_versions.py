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


def test_pre_change_fixture_bytes_are_unchanged():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == (
        "cbe3c0304ad8b675a3090e35aab4ab8e30d433df3b11dd03aa7ae5fab640670b"
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
    assert new["contract"] == "cosmas-gpt41-prepared.v2"
    assert new["decoder"] == "cosmas-gpt41-decoder.v2"
    # The legacy fixture includes truncated excerpts; preserve its truncation
    # marker when comparing exactly the same bounded source selection.
    equivalent = port._prepare_value(_context(old["context"]), source_records=old["sources"])
    for key in ("context", "sources", "flags"):
        assert json.loads(json.dumps(equivalent[key])) == old[key]
    assert equivalent["body"]["messages"][1] == old["body"]["messages"][1]
    assert equivalent["body"]["response_format"] == old["body"]["response_format"]
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


@pytest.mark.parametrize("version", ["v1", "v2"])
@pytest.mark.parametrize("fault", ["relabel", "mixed_decoder", "unknown", "instructions", "tools", "invented_capability"])
def test_version_or_authority_tampering_is_rejected_before_credentials(version, fault):
    value = deepcopy(LEGACY["chief"])
    if version == "v2":
        value = GPT41Connector(lambda: "").prepare(_context(value["context"]))
    if fault == "relabel":
        other = "v2" if version == "v1" else "v1"
        value["contract"], value["decoder"] = f"cosmas-gpt41-prepared.{other}", f"cosmas-gpt41-decoder.{other}"
    elif fault == "mixed_decoder":
        value["decoder"] = "cosmas-gpt41-decoder.v2" if version == "v1" else "cosmas-gpt41-decoder.v1"
    elif fault == "unknown":
        value["contract"], value["decoder"] = "cosmas-gpt41-prepared.v3", "cosmas-gpt41-decoder.v3"
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
