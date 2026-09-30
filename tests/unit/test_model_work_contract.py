"""Reject ambiguous receipts and transport before touching a model or ledger."""

import json
from copy import deepcopy

import pytest
from starlette.requests import Request
from tests.helpers.task_brief import REQUIREMENTS

from cosmas_os.api.model_work_schemas import (
    AdmissionObservation,
    HandoffRetryObservation,
    ModelRequestObservation,
    checked_response,
    contract_header,
    read_model_request,
)
from cosmas_os.api.team_schemas import ConversationRequest, HandoffRetry, TeamConfiguration
from cosmas_os.application import provider_team, team_resources, team_setup
from cosmas_os.application.workspace import WorkspaceError

ID = "10000000-0000-4000-8000-000000000001"
OTHER = "10000000-0000-4000-8000-000000000002"


def observation():
    return {
        "contract_version": 1,
        "workspace_id": ID,
        "idempotency_key": "invented-ask",
        "request_sha256": "a" * 64,
        "outcome": "running",
        "saved_entry": None,
        "reason": None,
        "admission": {
            "id": OTHER,
            "state": "running",
            "unit": 1,
            "admitted_at": "2026-09-21T22:00:00Z",
            "dispatch": "started",
            "usage": "unknown",
            "input_tokens": None,
            "output_tokens": None,
        },
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.update(contract_version=True),
        lambda v: v.update(provider_output="private answer"),
        lambda v: v.update(outcome="not_found"),
        lambda v: v.update(outcome="saved"),
        lambda v: v.update(saved_entry={"id": ID, "revision": 2}),
        lambda v: v["admission"].update(unit=True),
        lambda v: v["admission"].update(state="abandoned"),
        lambda v: v["admission"].update(dispatch="not_started"),
        lambda v: v["admission"].update(usage="verified", input_tokens=20),
        lambda v: v["admission"].update(input_tokens=0),
        lambda v: v["admission"].update(admitted_at="2026-09-21T22:00:00"),
    ],
)
def test_ambiguous_or_private_receipt_rejected(mutate):
    value = observation()
    mutate(value)
    with pytest.raises(WorkspaceError) as error:
        checked_response(value, ModelRequestObservation)
    assert error.value.code == "model_observation_unavailable"


def test_historical_saved_anchor_and_absent_observation_are_distinct():
    value = observation()
    value.update(outcome="saved", admission=None, saved_entry={"id": OTHER, "revision": 2})
    assert checked_response(value, ModelRequestObservation)["saved_entry"]["revision"] == 2
    value.update(outcome="not_found", saved_entry=None)
    assert checked_response(value, ModelRequestObservation)["admission"] is None
    with pytest.raises(WorkspaceError):
        checked_response(value, ModelRequestObservation, maximum=100)


def test_retry_receipt_binds_new_attempt_and_durable_queue_without_result():
    value = {
        "contract_version": 1,
        "workspace_id": ID,
        "handoff_id": ID,
        "previous_attempt_id": ID,
        "idempotency_key": "invented-retry",
        "request_sha256": "b" * 64,
        "outcome": "recorded",
        "recorded": {
            "attempt_id": OTHER,
            "attempt_number": 2,
            "recorded_at": "2026-09-21T22:00:00Z",
            "workspace_revision": 3,
            "status": "queued",
            "result_entry": None,
            "coverage": "durable_admission",
            "reason": None,
            "admission": {
                **observation()["admission"],
                "state": "reserved",
                "dispatch": "not_started",
            },
        },
    }
    assert checked_response(value, HandoffRetryObservation)["recorded"]["status"] == "queued"
    for changed in (
        {"attempt_id": ID},
        {"coverage": "retained_legacy"},
        {"status": "completed"},
        {"attempt_number": True},
    ):
        invalid = deepcopy(value)
        invalid["recorded"].update(changed)
        with pytest.raises(WorkspaceError):
            checked_response(invalid, HandoffRetryObservation)


@pytest.mark.parametrize(
    "state,dispatch",
    [
        ("reserved", "not_started"),
        ("abandoned", "not_started"),
        ("unknown", "unconfirmed"),
        ("completed", "started"),
        ("failed", "not_started"),
        ("failed", "started"),
    ],
)
def test_truthful_dispatch_observations(state, dispatch):
    value = {**observation()["admission"], "state": state, "dispatch": dispatch}
    assert AdmissionObservation.model_validate(value).state == state


def request(body=b"{}", headers=None, query=b""):
    parts = iter([(body[:17], True), (body[17:], False)])

    async def receive():
        chunk, more = next(parts)
        return {"type": "http.request", "body": chunk, "more_body": more}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/workspaces/test/conversation",
            "headers": headers or [(b"content-type", b"application/json")],
            "query_string": query,
        },
        receive,
    )


@pytest.mark.asyncio
async def test_request_bounds_duplicates_surrogates_and_original_normalization():
    body = {
        "expected_revision": 1,
        "team_revision": 1,
        "idempotency_key": "invented-ask",
        "role": "scribe",
        "content": "\u0085Invented\U0001f600\u001c",
    }
    parsed = await read_model_request(request(json.dumps(body).encode()), ConversationRequest)
    # The retained Pydantic wire normalization differs from Python str.strip:
    # U+001C is retained and remains part of the legacy request digest.
    assert parsed.content == "Invented\U0001f600\u001c"
    for raw in (
        json.dumps({**body, "content": "\ud800"}).encode(),
        json.dumps(body).encode()[:-1] + b',"role":"chief"}',
        b" " * 65_537,
        json.dumps({**body, "unexpected": True}).encode(),
    ):
        with pytest.raises(WorkspaceError) as error:
            await read_model_request(request(raw), ConversationRequest)
        assert error.value.code == "invalid_model_request"
    with pytest.raises(WorkspaceError):
        await read_model_request(request(b" " * 2_049), HandoffRetry)


def test_contract_negotiation_rejects_duplicate_or_unknown_headers():
    for values in ([b"1", b"1"], [b"2"], [b""], [b"01"]):
        with pytest.raises(WorkspaceError):
            contract_header(request(headers=[(b"x-cosmas-model-contract", v) for v in values]))
    assert contract_header(request(headers=[(b"x-cosmas-model-contract", b"1")]))
    with pytest.raises(WorkspaceError) as error:
        contract_header(request(), required=True)
    assert error.value.status == 426


def test_owner_pause_and_explicit_empty_sources_survive_roundtrip_without_defaults():
    original = provider_team.default_configuration()
    assert "model_work" not in TeamConfiguration.model_validate(original).model_dump(mode="json")
    changed = deepcopy(original)
    changed["model_work"] = {"version": 1, "max_attempts_per_24h": 0}
    changed["bots"][0]["resources"] = {"version": 1, "allowed": []}
    normalized = provider_team.configuration_value(changed)
    assert normalized["model_work"]["max_attempts_per_24h"] == 0
    assert normalized["bots"][0]["resources"]["allowed"] == []
    assert team_setup.review_required(original, normalized)
    assert team_setup.review_required(normalized, original)
    with pytest.raises(WorkspaceError):
        team_setup.require_compatible(1, normalized)
    team_setup.require_compatible(2, normalized)
    with pytest.raises(ValueError):
        TeamConfiguration.model_validate({**original, "model_work": None})
    invalid = deepcopy(original)
    invalid["bots"][0]["resources"] = None
    with pytest.raises(ValueError):
        TeamConfiguration.model_validate(invalid)


def test_stale_binding_can_be_retained_but_not_copied_or_changed():
    original = provider_team.default_configuration()
    binding = {"purpose": "core_preparation", "resource_ref": "a" * 64}
    original["bots"][0]["resources"] = {"version": 1, "allowed": [binding]}
    inventory = {"contract_version": 1, "resources": [], "inventory_sha256": "b" * 64}
    changed = deepcopy(original)
    changed["bots"][0]["name"] = "New private name"
    team_resources.validate_transition(original, changed, inventory)
    assert (
        team_resources.source(changed["bots"][0], "core_preparation", inventory)["selection"]
        == "unavailable"
    )
    assert (
        team_resources.source(changed["bots"][0], "scheduling_context", inventory)["selection"]
        == "denied"
    )
    changed["bots"][1]["resources"] = {"version": 1, "allowed": [binding]}
    with pytest.raises(WorkspaceError) as error:
        team_resources.validate_transition(original, changed, inventory)
    assert error.value.code == "team_resource_changed"
    with pytest.raises(WorkspaceError):
        team_resources.require(original["bots"][0], "core_preparation", "c" * 64)
    team_resources.require({}, "core_preparation", "c" * 64)


@pytest.mark.parametrize("field", ["body", "context", "sources", "flags", "decoder"])
def test_corrupted_prepared_envelope_cannot_reach_credentials(field):
    from tests.unit.test_provider_team_contract import context

    from cosmas_os.adapters.gpt41 import GPT41Connector
    from cosmas_os.ports.bot_capabilities import ModelCallFailure

    calls = []
    port = GPT41Connector(lambda: calls.append("credential") or "not-used")
    envelope = port.prepare(context())
    if field == "body":
        envelope["body"]["messages"][0]["content"] = "Changed instructions"
    elif field == "context":
        envelope["context"]["sources"][0]["kind"] = "private_token"
    elif field == "sources":
        envelope["sources"][0]["text"] = "Changed private source"
    elif field == "flags":
        envelope["flags"]["can_handoff"] = True
    else:
        envelope["decoder"] = "unknown.v2"
    with pytest.raises(ModelCallFailure) as failure:
        port.review_prepared(envelope)
    assert failure.value.dispatch == "not_dispatched" and calls == []


def test_maximum_valid_model_source_envelope_fits_finite_bound():
    from dataclasses import replace

    from tests.unit.test_provider_team_contract import context

    from cosmas_os.adapters.gpt41 import GPT41Connector
    from cosmas_os.ports.bot_capabilities import FollowUpStatus, SourcePassage

    # Maximum retained selected text and supplementary-plane UTF-8; provider
    # excerpts use escaped JSON, so this checks both forms in the same envelope.
    # Twelve installed bots includes Chief: all eleven eligible recipients
    # must fit together with the largest legal saved input.
    recipients = tuple(f"10000000-0000-4000-8000-{n:012d}" for n in range(11))
    value = context(
        role="chief",
        context_revision=500,
        question="😀" * 4000,
        sources=tuple(
            SourcePassage(f"invented-{n}", n + 1, "😀" * 160, "evidence", "😀" * 20000)
            for n in range(12)
        ),
        history=tuple(("assistant" if n % 2 else "user", "😀" * 3000) for n in range(8)),
        practice_context="😀" * 1000,
        job_focus="😀" * 500,
        working_preferences="😀" * 2000,
        follow_ups=tuple(
            FollowUpStatus(str(n), "approved", "2026-09-21", False, False, False)
            for n in range(500)
        ),
        linked_work=tuple(("artifact_chase", "needs_review") for n in range(500)),
        handoff_roles=recipients,
        handoff_targets=tuple(
            {"address": address, "role": "custom", "name": "😀" * 40, "job_focus": "😀" * 500}
            for address in recipients
        ),
    )
    for character in ("😀", "\x01"):
        changed = replace(
            value,
            sources=tuple(replace(source, content=character * 20000) for source in value.sources),
        )
        envelope = GPT41Connector(lambda: "").prepare(changed)
        assert (
            len(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode())
            <= 2 * 1048576
        )
        assert (
            len(envelope["sources"]) <= 12
            and sum(len(source["text"]) for source in envelope["sources"]) <= 30000
        )


def test_chief_recipient_inventory_and_output_limit_are_independent():
    import httpx
    from tests.unit.test_provider_team_contract import completion, context

    from cosmas_os.adapters.gpt41 import GPT41Connector
    from cosmas_os.ports.bot_capabilities import ModelCallFailure

    recipients = tuple(f"10000000-0000-4000-8000-{n:012d}" for n in range(11))
    value = context(role="chief", handoff_roles=recipients, handoff_limit=1,
        handoff_targets=tuple({"address": address, "role": "custom", "name": "Draft partner", "job_focus": "Prepare drafts"}
                              for address in recipients))
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(
            200,
            json=completion(
                source_ids=[],
                handoffs=[{"role": recipients[-1], "intended_role": "custom", "requirements": REQUIREMENTS, "brief": "Review the saved preparation."}],
            ),
        )

    port = GPT41Connector(lambda: "invented", transport=httpx.MockTransport(respond))
    result = port.review(value)
    assert result.handoffs[0].role == recipients[-1]
    schema = calls[0]["response_format"]["json_schema"]["schema"]["properties"]["handoffs"]
    assert schema["maxItems"] == 1
    assert schema["items"]["properties"]["role"]["enum"] == list(recipients)

    def over_limit(request):
        return httpx.Response(
            200,
            json=completion(
                source_ids=[],
                handoffs=[
                    {"role": address, "intended_role": "custom", "requirements": REQUIREMENTS, "brief": "Review the saved preparation."}
                    for address in recipients[:2]
                ],
            ),
        )

    with pytest.raises(ModelCallFailure) as failure:
        GPT41Connector(lambda: "invented", transport=httpx.MockTransport(over_limit)).review(value)
    assert failure.value.dispatch == "response_received"
    assert failure.value.outcome == "invalid_output"
    assert (failure.value.input_tokens, failure.value.output_tokens) == (25, 10)
