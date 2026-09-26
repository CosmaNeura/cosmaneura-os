from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tests.integration.test_provider_team import ask, case
from tests.integration.test_workspace_capture import admit, capture_case
from tests.integration.test_workspace_handoffs import model, worker
from tests.integration.test_workspace_prep import read as prep_read
from tests.integration.test_workspace_prep import setup as prep_setup
from tests.integration.test_workspace_scheduling import read as scheduling_read
from tests.integration.test_workspace_scheduling import scheduling_case
from tests.unit.test_custom_bot_contract import custom

from cosmas_os.adapters.gpt41 import _context
from cosmas_os.application import conversation, handoffs, model_work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.models import Principal, WorkspaceReply
from cosmas_os.ports.bot_capabilities import BotReply, DraftBrief

# Pytest discovers these imported fixtures in this module.
__all__ = ["case", "capture_case", "model", "scheduling_case"]


def add(s, box, owner, config, *bots):
    value = deepcopy(config["configuration"])
    value["bots"].extend(bots)
    return team.save(s, box, owner, expected=config["revision"], key=str(uuid4()), configuration=value)


def test_two_custom_bots_have_persistent_private_identity_history_and_retirement(session, case, monkeypatch):
    box, owner, w, config = case
    a, b = custom(), custom(name="Checklist partner")
    saved = add(session, box, owner, config, a, b)
    ids = [m["agent_id"] for m in saved["members"][-2:]]
    assert len(set(ids)) == 2
    assert {template["role"] for template in saved["templates"]} == {
        "scribe", "visit_prep", "follow_up", "research",
    }
    assert all(session.get(Principal, aid).display_name == "Custom bot" for aid in ids)
    seen = []
    def reply(ctx):
        seen.append(ctx)
        return BotReply("Private custom response", ())
    monkeypatch.setattr(conversation, "generate_reply", reply)
    for i, bot in enumerate((a, b, a), 1):
        result = ask(session, (box, owner, w, saved), expected=i, key=f"custom-{i}", role=bot["instance_id"], content=f"Question {i}")
        assert session.get(WorkspaceReply, result["entry_id"]).agent_id == ids[0 if bot is a else 1]
    assert not seen[0].history and not seen[1].history
    assert seen[2].history == (("user", "Question 1"), ("assistant", "Private custom response"))
    assert seen[2].job_focus == a["job_focus"] and seen[2].working_preferences == a["working_preferences"]
    before = team.read(session, box, owner)
    value = deepcopy(before["configuration"])
    value["bots"][-2].update(enabled=False, retired=True)
    retired = team.save(session, box, owner, expected=2, key="retire-custom", configuration=value)
    assert team.save(session, box, owner, expected=2, key="retire-custom", configuration=value)["revision"] == 3
    assert session.get(Principal, ids[0]).tombstoned_at
    with pytest.raises(ws.WorkspaceError, match="bot_paused"):
        ask(session, (box, owner, w, retired), expected=4, role=a["instance_id"])
    assert len(ws.read(session, box, owner, w["id"])["entries"]) == 4
    value["bots"][-2].update(enabled=True, retired=False)
    with pytest.raises(ws.WorkspaceError, match="team_member_retired"):
        team.save(session, box, owner, expected=3, key="revive-custom", configuration=value)


def test_database_rejects_bare_custom_identity(session, case):
    box, owner, _, config = case
    principal = Principal(box_id=box, principal_type="agent", display_name="Custom bot", agent_key="provider_custom", is_owner=False)
    session.add(principal)
    session.flush()
    with pytest.raises(IntegrityError, match="ck_provider_bot_custom_identity"), session.begin_nested():
        session.execute(text("INSERT INTO provider_bots (agent_id, box_id, owner_id, role) VALUES (:agent,:box,:owner,'custom')"),
            {"agent": principal.id, "box": box, "owner": owner})


@pytest.mark.parametrize("change", [None, "saved_context", "work_status", "include_notebook"])
def test_chief_assignments_to_custom_bot_obey_scope_and_revalidate_before_execution(session, case, model, monkeypatch, change):
    box, owner, w, config = case
    bot = custom()
    saved = add(session, box, owner, config, bot)
    contexts = []
    def reply(ctx):
        contexts.append(ctx)
        return BotReply("Private draft", ctx.sources, "azure_gpt41", handoffs=(
            (DraftBrief(bot["instance_id"], "Prepare a referral checklist"),) if ctx.role == "chief" else ()))
    monkeypatch.setattr(model_work, "dispatch_claim", lambda claim: reply(_context(claim.envelope["context"])))
    result = ask(session, (box, owner, w, saved), role="chief")
    assert bot["instance_id"] in contexts[0].handoff_roles
    assert result["workspace"]["handoffs"][0]["recipient_role"] == "custom"
    if change:
        value = deepcopy(saved["configuration"])
        if change == "include_notebook":
            value["bots"][-1][change] = False
        else:
            value["bots"][-1]["skills"].remove(change)
        saved = team.save(session, box, owner, expected=2, key="restrict-custom", configuration=value)
        version = team.current(session, box, owner)
        assert bot["instance_id"] not in handoffs.available_roles(session, box, owner, version, value["bots"][3])
    assert worker(session)
    h = ws.read(session, box, owner, w["id"])["handoffs"][0]
    if change:
        assert h["status"] != "completed" and len(contexts) == 1
    else:
        assert h["status"] == "completed" and contexts[1].role == "custom" and not contexts[1].handoff_roles
        assert contexts[1].job_focus == bot["job_focus"]
        assert not worker(session)


@pytest.mark.parametrize("revoke", [False, True])
def test_custom_calendar_skill_and_revocation_during_io(scheduling_case, revoke):
    f = scheduling_case
    saved = add(f.session, f.box, f.actor, team.read(f.session, f.box, f.actor), custom(skills=["calendar_availability"]))
    bot = saved["configuration"]["bots"][-1]
    f.bot = {"address": bot["instance_id"], "team_revision": saved["revision"]}
    # Release setup read locks before the callback writes through another session.
    f.session.commit()
    if revoke:
        def after():
            with Session(f.engine) as s:
                value = deepcopy(saved["configuration"])
                value["bots"][-1]["skills"] = []
                team.save(s, f.box, f.actor, expected=saved["revision"], key="revoke-skill", configuration=value)
        f.scheduling.after = after
    response = scheduling_read(f)
    assert response.status_code == (409 if revoke else 200), response.text
    if revoke:
        assert "slots" not in response.json()
        f.bot["team_revision"] += 1
        f.scheduling.calls.clear()
        assert scheduling_read(f).status_code == 409 and not f.scheduling.calls


@pytest.mark.parametrize("revoke", [False, True])
def test_custom_prep_skill_is_read_only_and_rechecked(capture_case, revoke):
    f = capture_case
    _, config = prep_setup(f)
    saved = add(f.session, f.box, f.actor, config, custom(skills=["encounter_prep"]))
    bot = {"address": saved["configuration"]["bots"][-1]["instance_id"], "team_revision": saved["revision"]}
    assert admit(f, bot=bot).status_code == 409 and not f.port.calls
    # Release setup read locks before the callback writes through another session.
    f.session.commit()
    if revoke:
        def after(phase):
            if phase == "prep":
                with Session(f.engine) as s:
                    value = deepcopy(saved["configuration"])
                    value["bots"][-1]["skills"] = []
                    team.save(s, f.box, f.actor, expected=saved["revision"], key="revoke-prep", configuration=value)
        f.port.after = after
    response = prep_read(f, bot)
    assert response.status_code == (409 if revoke else 200), response.text
    if revoke:
        assert "Invented intake" not in response.text
