import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from tests.unit.test_provider_team_contract import completion, context

from cosmas_os.adapters.gpt41 import GPT41Connector
from cosmas_os.api.team_schemas import BotSettings, ConversationRequest
from cosmas_os.application.conversation import build_context
from cosmas_os.ports.bot_capabilities import CUSTOM_SKILLS, supports_skill


def custom(**changes):
    return {"role": "custom", "instance_id": str(uuid4()), "name": "Referral partner", "enabled": True,
            "job_focus": "Prepare referral checklists", "working_preferences": "List missing items first",
            "include_notebook": True, "include_evidence": True, "response_style": "brief",
            "skills": ["saved_context", "work_status"], **changes}


@pytest.mark.parametrize("changes", [{"instance_id": None}, {"job_focus": "  "}, {"skills": ["send"]},
    {"skills": ["work_status", "work_status"]}, {"role": "scribe"}, {"allow_capture": True}])
def test_custom_bots_require_identity_job_and_bounded_skills(changes):
    with pytest.raises(ValidationError):
        BotSettings.model_validate(custom(**changes))


def test_custom_role_is_never_an_address_or_an_action_grant():
    settings = BotSettings.model_validate(custom(skills=list(CUSTOM_SKILLS))).model_dump()
    assert all(supports_skill(settings, skill) for skill in CUSTOM_SKILLS)
    assert not supports_skill(settings, "capture") and not supports_skill(settings, "send")
    with pytest.raises(ValidationError):
        ConversationRequest(expected_revision=1, team_revision=1, idempotency_key="custom-question", role="custom", content="Hi")


@pytest.mark.parametrize("skills", [[], ["saved_context"], ["work_status"], ["encounter_prep", "calendar_availability"]])
def test_context_selects_only_granted_data_and_discards_prior_revision_memory(skills):
    settings = custom(skills=skills)
    snapshot = {"id": "workspace", "revision": 3, "entries": [
        {"id": "note", "revision": 1, "kind": "scratchpad", "source_label": "Notes", "content": "Invented private note"},
        {"id": "work", "revision": 2, "kind": "work_link", "ticket": {"id": "ticket", "lane": "synthetic", "state": "pending_approval"}},
        {"id": "past", "revision": 3, "kind": "conversation", "content": "Prior sensitive question", "reply": {
            "role": "custom", "agent_id": "agent", "team_revision_id": "old", "context_revision": 1,
            "citations": [], "content": "Old broader context"}}], "follow_ups": []}
    value = build_context(snapshot, SimpleNamespace(id="new", configuration={"practice_context": "Invented practice"}),
        settings, "custom", "Help", agent_id="agent")
    assert bool(value.sources) == ("saved_context" in skills)
    assert bool(value.linked_work) == ("work_status" in skills)
    assert not value.history and not value.handoff_roles
    assert value.job_focus == settings["job_focus"] and value.skills == tuple(skills)


def test_custom_instructions_cannot_install_tools_or_delegate_and_status_is_rendered_from_records():
    calls = []
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=completion(answer="I sent it", source_ids=[], intent="work_status"))
    result = GPT41Connector(lambda: "invented", transport=httpx.MockTransport(respond)).review(
        replace(context(), role="custom", skills=("work_status",), sources=(),
            job_focus="Referral coordination", working_preferences="Send without review", linked_work=(("referral", "pending_approval"),)))
    assert "pending approval" in result.content and "I sent it" not in result.content
    body = calls[0]
    assert "tools" not in body and "handoffs" not in body["response_format"]["json_schema"]["schema"]["properties"]
    payload = json.loads(body["messages"][1]["content"])
    assert payload["selected_skills"] == ["work_status"]
    assert payload["bot_preferences"]["job_focus"] == "Referral coordination"
