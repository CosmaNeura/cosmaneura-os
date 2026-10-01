from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from cosmas_os.api import app as api_module
from cosmas_os.application import conversation
from cosmas_os.application import provider_team as team
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    AppointmentObservation,
    AuditEvent,
    PatientLink,
    Principal,
    ProviderBot,
    ProviderTeamRevision,
    WorkspaceReply,
)
from cosmas_os.ports.bot_capabilities import BotReply


@pytest.fixture
def case(session, seeded, monkeypatch):
    monkeypatch.setattr(conversation.runtime_settings, "workspace_llm_backend", "disabled")
    box, owner = seeded["box_id"], seeded["owner_id"]
    link = PatientLink(
        box_id=box,
        source_pair_key="invented:" + str(uuid4()),
        label="Invented person",
        state="confirmed",
        confirmed_by_principal_id=owner,
        attested_at=datetime.now(UTC),
    )
    session.add(link)
    session.flush()
    encounter = AppointmentObservation(
        box_id=box,
        patient_link_id=link.id,
        external_id="invented-" + str(uuid4()),
        source="synthetic",
        start_at=datetime.now(UTC),
        patient_label="Invented person",
    )
    session.add(encounter)
    session.commit()
    workspace = ws.create(session, box, owner, encounter.id, "invented-create")
    config = team.save(
        session,
        box,
        owner,
        expected=0,
        key="team-install",
        configuration=team.default_configuration(),
    )
    return box, owner, workspace, config


def ask(s, case, **values):
    box, owner, w, config = case
    result = conversation.ask(
        s,
        box,
        owner,
        w["id"],
        **{
            "model_contract": True,
            "expected": 1,
            "team_revision": config["revision"],
            "role": "visit_prep",
            "content": "Review my preparation",
            **values,
            "key": str(values.get("key", "invented-question")).ljust(8, "_"),
        },
    )

    assert result["outcome"] == "saved", result
    entry = result["saved_entry"]
    return {"entry_id": entry["id"], "entry_revision": entry["revision"],
            "workspace": ws.read(s,box,owner,w["id"],at_revision=entry["revision"])}


def test_private_team_install_replay_and_config_revisions(session, case):
    box, owner, _, config = case
    agents = [m["agent_id"] for m in config["members"]]
    assert len(set(agents)) == 4
    assert all(session.get(Principal, aid).principal_type == "agent" for aid in agents)
    assert (
        team.save(
            session,
            box,
            owner,
            expected=0,
            key="team-install",
            configuration=team.default_configuration(),
        )["revision"]
        == 1
    )
    changed = deepcopy(config["configuration"])
    changed["bots"][1]["name"] = "Prep partner"
    result = team.save(session, box, owner, expected=1, key="team-change", configuration=changed)
    assert [m["agent_id"] for m in result["members"]] == agents
    assert result["configuration"]["bots"][1]["name"] == "Prep partner"
    assert all(session.get(Principal, aid).display_name != "Prep partner" for aid in agents)
    assert (
        team.save(
            session,
            box,
            owner,
            expected=0,
            key="team-install",
            configuration=team.default_configuration(),
        )["revision"]
        == 1
    )
    with pytest.raises(ws.WorkspaceError, match="team_revision_conflict"):
        team.save(session, box, owner, expected=1, key="stale-team", configuration=changed)
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        team.save(session, box, owner, expected=0, key="team-install", configuration=changed)


def test_unsaved_starter_read_has_stable_research_and_no_writes(session, seeded):
    box, owner = seeded["box_id"], seeded["owner_id"]
    other = Principal(box_id=box, principal_type="human", display_name="Other invented owner",
                      state="active", is_owner=True)
    session.add(other)
    session.flush()
    models = (Principal, ProviderBot, ProviderTeamRevision, AuditEvent)
    before = [session.scalar(select(func.count()).select_from(model)) for model in models]
    statements = []

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", observe)
    try:
        first = team.read(session, box, owner)
        again = team.read(session, box, owner)
        other_team = team.read(session, box, other.id)
    finally:
        event.remove(connection, "before_cursor_execute", observe)
    assert first == again
    assert first["revision"] == 0 and len(first["members"]) == 5
    assert all(member["agent_id"] is None for member in first["members"])
    assert first["configuration"] == team.starter_configuration(box, owner)
    assert first["members"][-1]["instance_id"] != other_team["members"][-1]["instance_id"]
    assert statements and all(statement.lstrip().upper().startswith("SELECT ") for statement in statements)
    assert not session.new and not session.dirty and not session.deleted
    assert before == [session.scalar(select(func.count()).select_from(model)) for model in models]
    with pytest.raises(ws.WorkspaceError, match="team_revision_conflict"):
        team.active_bot(session, box, owner, first["members"][-1]["instance_id"], 0)


def test_explicit_starter_save_activates_five_agents_and_recovers_without_reinstall(session, seeded, monkeypatch):
    box, owner = seeded["box_id"], seeded["owner_id"]
    # The first-party team works without provider connectors or the extended
    # account/resource setup workflow. Public I/O remains separately gated.
    for flag in ("workspace_team_setup_enabled", "workspace_google_connection_enabled",
                 "workspace_microsoft_connection_enabled", "workspace_core_connection_enabled",
                 "workspace_scheduling_enabled", "workspace_research_io_enabled"):
        monkeypatch.setattr(team.runtime_settings, flag, False)
    offered = team.read(session, box, owner)
    saved = team.save(session, box, owner, expected=0, key="starter-install",
                      configuration=offered["configuration"])
    agents = {team.bot_address(member): member["agent_id"] for member in saved["members"]}
    assert saved["revision"] == 1 and len(set(agents.values())) == 5
    assert saved["configuration"] == offered["configuration"]
    research = next(member for member in saved["members"] if member["role"] == "research")
    assert next(capability for capability in research["capabilities"]
                if capability["key"] == "research.public.read")["state"] == "awaiting_connection"
    for address, agent_id in agents.items():
        version, bot, settings = team.active_bot(session, box, owner, address, 1)
        assert version.revision == 1 and bot.agent_id == agent_id and settings["enabled"]
        assert session.get(Principal, agent_id).state == "active"
    assert team.save(session, box, owner, expected=0, key="starter-install",
                     configuration=offered["configuration"]) == saved
    assert session.scalar(select(func.count()).select_from(ProviderBot).where(
        ProviderBot.box_id == box, ProviderBot.owner_id == owner)) == 5
    assert session.scalar(select(func.count()).select_from(ProviderTeamRevision).where(
        ProviderTeamRevision.box_id == box, ProviderTeamRevision.owner_id == owner)) == 1
    assert team.read(session, box, owner) == saved


def test_saved_four_member_team_keeps_its_settings_without_adding_research(session, case):
    box, owner, _, original = case
    changed = deepcopy(original["configuration"])
    changed["bots"][0].update(enabled=False, include_evidence=False)
    saved = team.save(session, box, owner, expected=1, key="keep-personal-settings", configuration=changed)
    observed = team.read(session, box, owner)
    assert observed == saved
    assert observed["configuration"] == changed
    assert [member["agent_id"] for member in observed["members"]] == [member["agent_id"] for member in original["members"]]
    assert len(observed["members"]) == 4 and all(member["role"] != "research" for member in observed["members"])


def test_second_owner_has_separate_bots_and_cannot_read_private_reply(session, case):
    box, owner, w, config = case
    first = ask(session, case)
    other = Principal(
        box_id=box,
        principal_type="human",
        display_name="Other synthetic owner",
        state="active",
        is_owner=True,
    )
    session.add(other)
    session.commit()
    assert team.read(session, box, other.id)["revision"] == 0
    other_team = team.save(
        session,
        box,
        other.id,
        expected=0,
        key="team-install",
        configuration=team.default_configuration(),
    )
    assert set(m["agent_id"] for m in config["members"]).isdisjoint(
        m["agent_id"] for m in other_team["members"]
    )
    with pytest.raises(ws.WorkspaceError):
        conversation.ask(
            session,
            box,
            other.id,
            w["id"],
            expected=2,
            team_revision=1,
            key="foreign-question",
            role="visit_prep",
            content="Read private context",
        )
    reply = session.get(WorkspaceReply, first["entry_id"])
    new_entry = ws.append(
        session,
        box,
        owner,
        w["id"],
        expected=2,
        key="unanswered-turn",
        kind="conversation",
        content="Invented standalone question",
    )
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(
            text(
                "INSERT INTO workspace_replies SELECT :new_entry, workspace_id, box_id, owner_id, :foreign_agent, team_revision_id, agent_name, role, backend, context_revision, content, citations, created_at FROM workspace_replies WHERE entry_id=:entry"
            ),
            {
                "foreign_agent": other_team["members"][0]["agent_id"],
                "entry": reply.entry_id,
                "new_entry": new_entry["entry_id"],
            },
        )


def test_conversation_is_atomic_attributed_scoped_and_idempotent(session, case):
    box, owner, w, _ = case
    first = ask(session, case)
    entry = first["workspace"]["entries"][-1]
    assert entry["origin"] == "authenticated_human"
    assert entry["reply"]["role"] == "visit_prep"
    assert entry["reply"]["backend"] == "local_source_review_v1"
    assert entry["reply"]["citations"][0]["entry_id"] == w["entries"][0]["id"]
    assert ask(session, case)["entry_id"] == first["entry_id"]
    ws.append(
        session,
        box,
        owner,
        w["id"],
        expected=2,
        key="later-note",
        kind="scratchpad",
        content="New context",
    )
    assert ask(session, case)["workspace"]["revision"] == 2
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        ask(session, case, content="different payload")
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceReply)
            .where(WorkspaceReply.workspace_id == w["id"])
        )
        == 1
    )


def test_disabled_bot_and_stale_configuration_block_new_turn(session, case):
    box, owner, w, config = case
    changed = deepcopy(config["configuration"])
    changed["bots"][1]["enabled"] = False
    team.save(session, box, owner, expected=1, key="pause-bot", configuration=changed)
    with pytest.raises(ws.WorkspaceError, match="team_revision_conflict"):
        ask(session, case)
    with pytest.raises(ws.WorkspaceError, match="bot_paused"):
        ask(session, case, team_revision=2)
    assert ws.read(session, box, owner, w["id"])["revision"] == 1


def test_source_preferences_remove_content_and_old_answers_from_model_context(
    session, case, monkeypatch
):
    box, owner, w, config = case
    ws.append(
        session,
        box,
        owner,
        w["id"],
        expected=1,
        key="private-note",
        kind="scratchpad",
        content="Private notebook marker",
    )
    ask(session, case, expected=2)
    changed = deepcopy(config["configuration"])
    changed["bots"][1]["include_notebook"] = False
    changed["bots"][1]["include_evidence"] = False
    team.save(session, box, owner, expected=1, key="restrict-sources", configuration=changed)
    captured = []

    def review(self, context):
        captured.append(context)
        return BotReply("No source context provided.", ())

    monkeypatch.setattr(conversation.WorkspaceReviewConnector, "review", review)
    ask(session, case, expected=3, team_revision=2, key="restricted-question")
    assert captured[0].sources == () and captured[0].history == ()


def test_team_binding_revision_and_reply_are_immutable(session, case):
    box, owner, w, _ = case
    result = ask(session, case)
    for table, predicate, params in [
        ("workspace_replies", "entry_id=:id", {"id": result["entry_id"]}),
        ("provider_team_revisions", "owner_id=:id", {"id": owner}),
        ("provider_bots", "owner_id=:id", {"id": owner}),
    ]:
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(text(f"DELETE FROM {table} WHERE {predicate}"), params)
    events = session.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == w["id"]))
    assert all("content" not in e.detail and "question" not in e.detail for e in events)


def test_changed_preferences_drop_uncited_prior_model_text(session, case, monkeypatch):
    box, owner, _, config = case
    contexts = []

    def review(self, context):
        contexts.append(context)
        return BotReply("Uncited source-derived text", ())

    monkeypatch.setattr(conversation.WorkspaceReviewConnector, "review", review)
    ask(session, case)
    changed = deepcopy(config["configuration"])
    changed["bots"][1]["include_evidence"] = False
    team.save(session, box, owner, expected=1, key="remove-evidence", configuration=changed)
    ask(session, case, expected=2, team_revision=2, key="new-context")
    assert contexts[-1].history == () and contexts[-1].sources == ()


def test_revoked_owner_and_patient_cannot_access_team_or_chat(session, case):
    box, owner, w, _ = case
    session.get(Principal, owner).state = "disabled"
    session.commit()
    with pytest.raises(ws.WorkspaceError):
        team.read(session, box, owner)
    with pytest.raises(ws.WorkspaceError):
        ask(session, case)


def test_gpt_error_is_retained_once_and_exact_retry_does_not_call_again(session, case, monkeypatch):
    from pydantic import SecretStr

    from cosmas_os.application import model_work
    from cosmas_os.ports.bot_capabilities import ModelCallFailure
    monkeypatch.setattr(conversation.runtime_settings, "workspace_enabled", True)
    monkeypatch.setattr(conversation.runtime_settings, "workspace_llm_backend", "azure_gpt41")
    monkeypatch.setattr(conversation.runtime_settings, "workspace_llm_api_key", SecretStr("invented-test-only"))
    calls = []
    def unavailable(claim):
        calls.append(claim.envelope_sha256)
        raise ModelCallFailure(dispatch="started_unconfirmed")
    monkeypatch.setattr(model_work, "dispatch_claim", unavailable)
    box, owner, workspace, _ = case
    command=dict(expected=1,team_revision=1,key="invented-error",role="visit_prep",content="Invented question",model_contract=True)
    first=conversation.ask(session,box,owner,workspace["id"],**command)
    assert first["outcome"]=="unknown" and first["saved_entry"] is None
    current=ws.read(session,box,owner,workspace["id"])
    assert current["entries"][-1]["reply"] is None and current["revision"]==2
    assert conversation.ask(session,box,owner,workspace["id"],**command)==first and len(calls)==1
    assert "provider detail" not in str(first)


def test_api_feature_gate_and_validation_do_not_echo_content(session, case, monkeypatch):
    box, owner, w, _ = case
    api_module.app.dependency_overrides[api_module.get_session] = lambda: session
    try:
        headers = {"X-Box-Id": box, "X-Actor-Principal-Id": owner}
        with TestClient(api_module.app) as client:
            monkeypatch.setattr(api_module.settings, "workspace_enabled", False)
            assert client.get("/provider-team", headers=headers).status_code == 404
            monkeypatch.setattr(api_module.settings, "workspace_enabled", True)
            response = client.post(
                f"/workspaces/{w['id']}/conversation",
                headers=headers,
                json={"content": "PRIVATE VALIDATION MARKER"},
            )
            assert response.status_code == 422 and "PRIVATE" not in response.text
            response = client.get("/provider-team", headers=headers)
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"

            def broken_read(*args, **kwargs):
                raise SQLAlchemyError("PRIVATE DATABASE PARAMETER")

            monkeypatch.setattr(api_module.ws, "read", broken_read)
            response = client.get(f"/workspaces/{w['id']}", headers=headers)
            assert response.status_code == 503 and "PRIVATE" not in response.text
    finally:
        api_module.app.dependency_overrides.clear()


@pytest.mark.parametrize("starter", [False, True], ids=["legacy", "starter"])
def test_concurrent_team_install_has_one_set_of_agents_and_reopens(engine, starter):
    with Session(engine) as s:
        seed = svc.provision_box(svc.Container(s), "Invented team concurrency")
    barrier = Barrier(2)
    configuration = (team.starter_configuration(seed["box_id"], seed["owner_id"])
                     if starter else team.default_configuration())

    def install(_):
        with Session(engine) as s:
            barrier.wait(timeout=10)
            return team.save(
                s,
                seed["box_id"],
                seed["owner_id"],
                expected=0,
                key="same-install",
                configuration=configuration,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(install, range(2)))
    assert results[0] == results[1]
    with Session(engine) as s:
        assert team.read(s, seed["box_id"], seed["owner_id"])["revision"] == 1
        assert (
            s.scalar(
                select(func.count())
                .select_from(ProviderBot)
                .where(ProviderBot.owner_id == seed["owner_id"])
            )
            == (5 if starter else 4)
        )


def add_scribe(s, case):
    box, owner, _, initial = case
    config = deepcopy(initial["configuration"])
    address = str(uuid4())
    config["bots"].append({**config["bots"][0], "instance_id": address, "name": "Private visit partner",
                          "job_focus": "Visit documentation", "working_preferences": "Keep sources separate"})
    return address, team.save(s, box, owner, expected=1, key="add-scribe", configuration=config)


def test_additional_bot_exact_retry_pause_and_old_client_preservation(session, case):
    box, owner, _, original = case
    address, installed = add_scribe(session, case)
    extra = installed["members"][-1]
    assert extra["instance_id"] == address and extra["role"] == "scribe"
    assert extra["agent_id"] not in {m["agent_id"] for m in original["members"]}
    assert session.get(Principal, extra["agent_id"]).display_name == "Scribe"
    assert team.save(session, box, owner, expected=1, key="add-scribe", configuration=installed["configuration"]) == installed
    assert team.read(session, box, owner) == installed
    assert {template["role"] for template in installed["templates"]} == {
        "scribe", "visit_prep", "follow_up", "research",
    }
    with pytest.raises(ws.WorkspaceError, match="team_member_missing"):
        team.save(session, box, owner, expected=2, key="old-client", configuration=original["configuration"])
    rebound = deepcopy(installed["configuration"])
    rebound["bots"][-1]["role"] = "follow_up"
    with pytest.raises(ws.WorkspaceError, match="team_template_immutable"):
        team.save(session, box, owner, expected=2, key="rebind", configuration=rebound)
    reply = ask(session, case, team_revision=2, role=address)
    assert reply["workspace"]["entries"][-1]["reply"]["agent_id"] == extra["agent_id"]
    paused = deepcopy(installed["configuration"])
    paused["bots"][-1]["enabled"] = False
    team.save(session, box, owner, expected=2, key="pause-extra", configuration=paused)
    with pytest.raises(ws.WorkspaceError, match="bot_paused"):
        ask(session, case, expected=2, team_revision=3, role=address, key="paused")
    assert ask(session, case, team_revision=2, role=address)["entry_id"] == reply["entry_id"]
    assert session.get(Principal, extra["agent_id"]).state == "disabled"


def test_same_template_bots_have_separate_memory_and_private_addresses(session, case, monkeypatch):
    box, owner, _, _ = case
    address, installed = add_scribe(session, case)
    calls = []
    def reply(context):
        calls.append(context)
        return BotReply("Invented private result", (), "local_source_review_v1")
    monkeypatch.setattr(conversation, "generate_reply", reply)
    ask(session, case, team_revision=2, role="scribe", content="Baseline private question")
    ask(session, case, team_revision=2, role=address, expected=2, key="extra-turn", content="Extra private question")
    assert calls[-1].history == () and calls[-1].role == "scribe"
    assert calls[-1].job_focus == "Visit documentation"
    assert calls[-1].working_preferences == "Keep sources separate"
    ask(session, case, team_revision=2, role="scribe", expected=3, key="baseline-again")
    assert ("user", "Baseline private question") in calls[-1].history
    assert all("Extra private question" not in value for _, value in calls[-1].history)
    other = Principal(box_id=box, principal_type="human", display_name="Invented other owner", state="active", is_owner=True)
    session.add(other)
    session.commit()
    team.save(session, box, other.id, expected=0, key="other-team", configuration=team.default_configuration())
    with pytest.raises(ws.WorkspaceError, match="bot_paused"):
        team.active_bot(session, box, other.id, address, 1)
    with pytest.raises(ws.WorkspaceError, match="team_member_unavailable"):
        team.address_for_agent(session, box, other.id, installed["members"][-1]["agent_id"])


def test_concurrent_additional_install_creates_one_extra_principal(engine):
    with Session(engine) as s:
        seed = svc.provision_box(svc.Container(s), "Invented additional bot concurrency")
        team.save(s, seed["box_id"], seed["owner_id"], expected=0, key="install", configuration=team.default_configuration())
    config = team.default_configuration()
    config["bots"].append({**config["bots"][0], "instance_id": str(uuid4()), "name": "Extra Scribe"})
    barrier = Barrier(2)
    def install(_):
        with Session(engine) as s:
            barrier.wait(timeout=10)
            return team.save(s, seed["box_id"], seed["owner_id"], expected=1, key="same-extra", configuration=config)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(install, range(2)))
    assert results[0] == results[1]
    with Session(engine) as s:
        assert team.read(s, seed["box_id"], seed["owner_id"]) == results[0]
        assert s.scalar(select(func.count()).select_from(ProviderBot).where(ProviderBot.owner_id == seed["owner_id"])) == 5


def test_retirement_preserves_private_history_exact_retries_and_fences_new_work(session, case):
    box, owner, w, _ = case
    address, installed = add_scribe(session, case)
    principal_id = installed["members"][-1]["agent_id"]
    reply = ask(session, case, team_revision=2, role=address)
    retired_config = deepcopy(installed["configuration"])
    retired_config["bots"][-1].update(enabled=False, retired=True)
    saved = team.save(session, box, owner, expected=2, key="retire-extra", configuration=retired_config)
    principal = session.get(Principal, principal_id)
    retired_at = principal.tombstoned_at
    assert retired_at is not None and principal.state == "disabled"
    assert team.save(session, box, owner, expected=2, key="retire-extra", configuration=retired_config) == saved
    assert team.save(session, box, owner, expected=1, key="add-scribe", configuration=installed["configuration"]) == installed
    assert principal.tombstoned_at == retired_at and principal.state == "disabled"
    assert team.read(session, box, owner) == saved
    assert team.address_for_agent(session, box, owner, principal_id) == address
    assert ask(session, case, team_revision=2, role=address)["entry_id"] == reply["entry_id"]
    assert ws.read(session, box, owner, w["id"])["entries"][-1]["reply"]["agent_id"] == principal_id
    with pytest.raises(ws.WorkspaceError, match="bot_paused"):
        ask(session, case, expected=2, team_revision=3, role=address, key="retired-new-turn")
    for change in ({"retired": False}, {"name": "Rewrite retired history"}):
        invalid = deepcopy(retired_config)
        invalid["bots"][-1].update(change)
        with pytest.raises(ws.WorkspaceError, match="team_member_retired"):
            team.save(session, box, owner, expected=3, key="invalid-retired-edit", configuration=invalid)
    # Omission is not deletion: old clients must retain every saved bot address.
    with pytest.raises(ws.WorkspaceError, match="team_member_missing"):
        team.save(session, box, owner, expected=3, key="omit-retired", configuration=team.default_configuration())
    assert session.scalar(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.aggregate_id == principal_id, AuditEvent.event_type == "provider_team.bot_retired")) == 1
    assert team.current(session, box, owner).revision == 3


def test_retirement_requires_an_owned_installation_and_replacement_has_new_memory(session, case, monkeypatch):
    box, owner, _, _ = case
    address, installed = add_scribe(session, case)
    ask(session, case, team_revision=2, role=address, content="Original private conversation")
    other = Principal(box_id=box, principal_type="human", display_name="Invented other owner", state="active", is_owner=True)
    session.add(other)
    session.commit()
    forged = deepcopy(installed["configuration"])
    forged["bots"][-1].update(enabled=False, retired=True)
    with pytest.raises(ws.WorkspaceError, match="team_member_unavailable"):
        team.save(session, box, other.id, expected=0, key="foreign-retirement", configuration=forged)
    assert team.current(session, box, other.id) is None
    team.save(session, box, owner, expected=2, key="retire-owned", configuration=forged)
    replacement = str(uuid4())
    forged["bots"].append({**installed["configuration"]["bots"][-1], "instance_id": replacement})
    replaced = team.save(session, box, owner, expected=3, key="replace-retired", configuration=forged)
    assert replaced["members"][-1]["agent_id"] != installed["members"][-1]["agent_id"]
    contexts = []
    def answer(context):
        contexts.append(context)
        return BotReply("Invented replacement result", (), "local_source_review_v1")
    monkeypatch.setattr(conversation, "generate_reply", answer)
    ask(session, case, expected=2, team_revision=4, role=replacement, key="replacement-turn")
    assert contexts[0].history == ()
    assert team.read(session, box, owner)["configuration"]["bots"][-2]["retired"]


def test_concurrent_retirement_commits_one_tombstone_and_receipt(engine):
    with Session(engine) as s:
        seed = svc.provision_box(svc.Container(s), "Invented retirement concurrency")
        config = team.default_configuration()
        config["bots"].append({**config["bots"][0], "instance_id": str(uuid4()), "name": "Retiring Scribe"})
        installed = team.save(s, seed["box_id"], seed["owner_id"], expected=0, key="install", configuration=config)
    config["bots"][-1].update(enabled=False, retired=True)
    barrier = Barrier(2)
    def retire(_):
        with Session(engine) as s:
            barrier.wait(timeout=10)
            return team.save(s, seed["box_id"], seed["owner_id"], expected=1, key="same-retirement", configuration=config)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(retire, range(2)))
    assert results[0] == results[1]
    with Session(engine) as s:
        principal = s.get(Principal, installed["members"][-1]["agent_id"])
        assert principal.tombstoned_at is not None and principal.state == "disabled"
        assert s.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.aggregate_id == principal.id, AuditEvent.event_type == "provider_team.bot_retired")) == 1
        assert team.read(s, seed["box_id"], seed["owner_id"]) == results[0]
