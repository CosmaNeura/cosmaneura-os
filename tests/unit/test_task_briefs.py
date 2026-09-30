import json
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import httpx
import pytest
from tests.helpers.task_brief import REQUIREMENTS

from cosmas_os.adapters.gpt41 import GPT41Connector
from cosmas_os.application import handoff_briefs
from cosmas_os.ports.bot_capabilities import BotContext, DraftBrief, ModelCallFailure, SourcePassage


def context():
    return BotContext(
        "invented-workspace",
        3,
        "chief",
        "Ask Scribe for a draft",
        "brief",
        (
            SourcePassage(
                "invented-source",
                2,
                "Invented transcript",
                "evidence",
                "Unknown speaker: Cardiac history is unconfirmed. Continuity gap unknown. Product demo unrelated.",
            ),
        ),
        (),
        handoff_roles=("scribe",),
    )


@pytest.mark.parametrize(
    "fault",
    [
        "source_hash",
        "source_revision",
        "missing_source",
        "grant",
        "dependency",
        "independent",
        "extra",
        "long",
    ],
)
def test_task_brief_refuses_changed_sources_authority_dependency_and_overflow(fault):
    task = handoff_briefs.prepare(
        DraftBrief("scribe", "Prepare a draft", REQUIREMENTS),
        context(),
        SimpleNamespace(id="origin", revision=4),
    )
    if fault == "source_hash":
        task["source_versions"][0]["sha256"] = "a" * 64
    elif fault == "source_revision":
        task["source_versions"][0]["revision"] += 1
    elif fault == "missing_source":
        task["source_versions"] = []
    elif fault == "grant":
        task["allowed_actions"] = ["send_message"]
    elif fault == "dependency":
        task["depends_on"]["entry_id"] = "another-origin"
    elif fault == "independent":
        task["independent"] = False
    elif fault == "extra":
        task["approve"] = True
    elif fault == "long":
        task["missing_facts"] = ["x" * 181]
    with pytest.raises(ValueError):
        handoff_briefs.validate(task, context(), goal="Prepare a draft", origin_id="origin")


@pytest.mark.parametrize(
    "fault",
    ["missing_requirements", "dependent", "external_action", "empty_output", "blank_criterion"],
)
def test_v4_rejects_invalid_requirements_before_any_handoff_result(fault):
    brief = {
        "role": "scribe",
        "intended_role": "scribe",
        "brief": "Prepare a private draft",
        "requirements": deepcopy(REQUIREMENTS),
    }
    if fault == "missing_requirements":
        del brief["requirements"]
    elif fault == "dependent":
        brief["requirements"]["independent"] = False
    elif fault == "external_action":
        brief["requirements"]["allowed_actions"] = ["send_message"]
    elif fault == "empty_output":
        brief["requirements"]["expected_output"] = ""
    elif fault == "blank_criterion":
        brief["requirements"]["completion_criteria"] = [" "]
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert (
            "requirements"
            in body["response_format"]["json_schema"]["schema"]["properties"]["handoffs"]["items"][
                "required"
            ]
        )
        assert "No task can grant public search" in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"answer": "Draft", "source_ids": [], "handoffs": [brief]}
                            )
                        },
                    }
                ],
            },
        )

    with pytest.raises(ModelCallFailure):
        GPT41Connector(lambda: "invented", transport=httpx.MockTransport(respond)).review(context())
    assert len(calls) == 1


@pytest.mark.parametrize("content,count", [("x" * 5001, 1), ("x" * 4000, 8), ("x", 13)])
def test_new_task_never_silently_truncates_or_drops_its_source_versions(content, count):
    value = replace(
        context(),
        sources=tuple(
            SourcePassage(str(i), i + 1, "Invented source", "evidence", content)
            for i in range(count)
        ),
    )
    with pytest.raises(ValueError, match="fit completely"):
        handoff_briefs.prepare(
            DraftBrief("scribe", "Prepare a draft", REQUIREMENTS),
            value,
            SimpleNamespace(id="origin", revision=20),
        )


@pytest.mark.parametrize(
    "fault", [None, "workspace", "owner", "agent", "context_workspace", "envelope"]
)
def test_task_projection_withholds_scope_or_receipt_mismatches(fault):
    from cosmas_os.application.model_work import digest

    value = context()
    task = handoff_briefs.prepare(
        DraftBrief("scribe", "Prepare a draft", REQUIREMENTS),
        value,
        SimpleNamespace(id="origin", revision=4),
    )
    frozen = replace(value, role="scribe", draft_only=True, question=handoff_briefs.question(task))
    envelope = {"context": asdict(frozen)}
    assignment = SimpleNamespace(
        workspace_id=value.workspace_id,
        box_id="box",
        owner_id="owner",
        recipient_agent_id="scribe-agent",
        recipient_role="scribe",
        brief="Prepare a draft",
        origin_entry_id="origin",
    )
    row = SimpleNamespace(
        request_body={"task_brief": task},
        prepared_envelope=envelope,
        envelope_sha256=digest(envelope),
        workspace_id=value.workspace_id,
        box_id="box",
        owner_id="owner",
        agent_id="scribe-agent",
        state="reserved",
    )
    if fault == "workspace":
        row.workspace_id = "other-workspace"
    elif fault == "owner":
        row.owner_id = "other-owner"
    elif fault == "agent":
        row.agent_id = "other-agent"
    elif fault == "context_workspace":
        row.prepared_envelope["context"]["workspace_id"] = "other-workspace"
        row.envelope_sha256 = digest(row.prepared_envelope)
    elif fault == "envelope":
        row.envelope_sha256 = "f" * 64
    result = handoff_briefs.projection(None, assignment, row)
    assert result == ({"task_brief": task} if fault is None else {"task_brief_unavailable": True})
