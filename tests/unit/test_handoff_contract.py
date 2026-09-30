import json

import httpx
import pytest
from pydantic import ValidationError

from cosmas_os.adapters.gpt41 import GPT41Connector
from cosmas_os.api.team_schemas import HandoffRetry
from cosmas_os.ports.bot_capabilities import BotContext, ConnectorUnavailable, SourcePassage


def test_chief_receives_a_closed_draft_handoff_contract():
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer": "Queuing a draft for Scribe.",
                                    "source_ids": [],
                                    "handoffs": [
                                        {
                                            "role": "scribe",
                                            "intended_role": "scribe",
                                            "brief": "Organize the saved notes; flag missing information.",
                                        }
                                    ],
                                }
                            )
                        },
                    }
                ],
            },
        )

    context = BotContext(
        "invented", 1, "chief", "Ask Scribe for a draft", "brief", (), (), handoff_roles=("scribe",)
    )
    reply = GPT41Connector(lambda: "invented", transport=httpx.MockTransport(respond)).review(
        context
    )
    assert reply.handoffs[0].role == "scribe"
    schema = calls[0]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["handoffs"]["items"]["properties"]["role"]["enum"] == ["scribe"]
    assert "tools" not in calls[0]
    assert json.loads(calls[0]["messages"][1]["content"])["allowed_handoff_roles"] == ["scribe"]


@pytest.mark.parametrize(
    "role,briefs",
    [
        ("chief", [{"role": "chief", "brief": "Repeat this"}]),
        ("chief", [{"role": "follow_up", "brief": "Not permitted by context"}]),
        ("chief", [{"role": "scribe", "brief": "A"}, {"role": "scribe", "brief": "B"}]),
        ("chief", [{"role": "scribe", "brief": " "}]),
        ("chief", [{"role": "scribe", "brief": "x" * 4001}]),
        ("chief", [{"role": "scribe", "brief": "A", "approve": True}]),
        ("scribe", [{"role": "scribe", "brief": "Delegate recursively"}]),
    ],
)
def test_invalid_or_recursive_handoffs_are_rejected_without_retry(role, briefs):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer": "Draft",
                                    "source_ids": [],
                                    "handoffs": [{**brief, "intended_role": "scribe"} for brief in briefs],
                                }
                            )
                        },
                    }
                ],
            },
        )

    context = BotContext("invented", 1, role, "Draft", "brief", (), (), handoff_roles=("scribe",))
    with pytest.raises(ConnectorUnavailable):
        GPT41Connector(lambda: "invented", transport=httpx.MockTransport(respond)).review(context)
    assert len(calls) == 1


def test_retry_cannot_change_brief_recipient_or_grant_authority():
    with pytest.raises(ValidationError):
        HandoffRetry.model_validate(
            {
                "expected_revision": 2,
                "previous_attempt_id": "00000000-0000-0000-0000-000000000001",
                "idempotency_key": "invented",
                "brief": "Change the original",
                "approve": True,
            }
        )


@pytest.mark.parametrize(
    "quote,source_id,accepted",
    [
        ("Discuss access and confirm the next appointment.", "note", True),
        ("Discussed access and confirmed the next appointment.", "note", False),
        ("Discuss access and confirm the next appointment.", "foreign-note", False),
        ("Appointment confirmed.", "note", False),
        (" ", "note", False),
    ],
)
def test_scribe_draft_preserves_source_words_and_rejects_invented_completion(
    quote, source_id, accepted
):
    source_text = "Discuss access and confirm the next appointment."
    context = BotContext(
        "invented",
        1,
        "scribe",
        "Make a draft",
        "brief",
        (SourcePassage("note", 1, "Saved note", "scratchpad", source_text),),
        (),
        draft_only=True,
    )

    def respond(request):
        body = json.loads(request.content)
        assert set(body["response_format"]["json_schema"]["schema"]["properties"]) == {
            "excerpts",
            "needs_from_clinician",
        }
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "excerpts": [{"source_id": source_id, "quote": quote}],
                                    "needs_from_clinician": [
                                        "Did the planned discussion take place?"
                                    ],
                                }
                            )
                        },
                    }
                ],
            },
        )

    connector = GPT41Connector(lambda: "invented", transport=httpx.MockTransport(respond))
    if accepted:
        result = connector.review(context)
        assert f"“{source_text}”" in result.content
        assert result.backend == "azure_gpt41_source_draft_v1"
        assert result.citations == context.sources
        assert "Needs from clinician:" in result.content and "confirmed" not in result.content
    else:
        with pytest.raises(ConnectorUnavailable):
            connector.review(context)
