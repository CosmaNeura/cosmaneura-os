"""Real signed review routes and F8 custody; no external lookup or paid model."""

from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration.test_workspace_capture import capture_case  # noqa: F401

from cosmas_os.api import app as api
from cosmas_os.application import agent_tools
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.models import Decision, Operation
from cosmas_os.ports.bot_capabilities import ModelCallFailure


@pytest.fixture
def research_review(capture_case, monkeypatch):  # noqa: F811
    f = capture_case
    configuration = f.configuration
    configuration.workspace_agent_tools_enabled = True
    configuration.workspace_llm_backend = "azure_gpt41"
    configuration.workspace_llm_api_key = SecretStr("invented-never-dispatched")
    monkeypatch.setattr(team, "runtime_settings", configuration)
    monkeypatch.setattr(api, "SessionLocal", lambda: Session(f.engine))
    bots = team.default_configuration()
    bot = str(uuid4())
    bots["bots"].append({"role": "research", "instance_id": bot, "name": "Research",
        "enabled": True, "include_notebook": True, "include_evidence": True})
    version = team.save(f.session, f.box, f.actor, expected=0, key="invented-review-team", configuration=bots)
    aid, _ = work.reserve_conversation(f.session, f.box, f.actor, f.workspace["id"],
        expected=1, team_revision=version["revision"], key="invented-public-query",
        role=bot, content="Propose a general public query for review.", external_identity_id=f.binding.id)
    claimed = work.claim(f.session, f.box, f.actor, aid)
    assert claimed and claimed.envelope["contract"] == "cosmas-gpt41-prepared.v7"
    value = agent_tools.AgentToolExecutor(f.session, claimed).execute({"tool": "propose_research_query",
        "topic": "literature", "sources": ["pubmed"], "query": "acute ankle injury evidence"})
    f.proposal = value["data"]
    work.settle(f.session, claimed, ModelCallFailure(dispatch="not_dispatched"))
    f.path = f"/workspaces/{f.workspace['id']}/agent-research"
    f.headers = {"Authorization": "Bearer " + f.token(), "X-Cosmas-Research-Contract": "1"}
    f.review = {key: f.proposal[key] for key in ("revision_id", "payload_hash")}
    f.review["public_query_confirmed"] = True
    yield f


def test_signed_desktop_and_mobile_review_the_same_proposal_exactly_once(research_review):
    f = research_review
    listed = f.client.get(f.path, headers=f.headers)
    assert listed.status_code == 200 and listed.json()["proposals"] == [f.proposal]
    path = f.path + f"/{f.proposal['ticket_id']}/review"
    approved = f.client.post(path, headers=f.headers, json=f.review)
    assert approved.status_code == 200 and approved.json()["state"] == "approved"
    mobile = {**f.headers, "Authorization": "Bearer " + f.token(sid="invented-phone-session")}
    replay = f.client.post(path, headers=mobile, json=f.review)
    assert replay.status_code == 200 and replay.json() == approved.json()
    assert replay.headers["cache-control"] == "no-store"
    with Session(f.engine) as session:
        assert session.scalar(select(func.count()).select_from(Decision).where(
            Decision.action_revision_id == f.proposal["revision_id"])) == 1
        op = session.scalar(select(Operation).where(Operation.action_revision_id == f.proposal["revision_id"]))
        assert op and op.status == "pending" and op.attempt_count == 0


@pytest.mark.parametrize("mutation", ["unsigned", "foreign", "hash", "bool", "extra", "identity_header", "query"])
def test_invalid_review_never_creates_a_decision_or_operation(research_review, mutation):
    f = research_review
    headers, body = dict(f.headers), dict(f.review)
    path = f.path + f"/{f.proposal['ticket_id']}/review"
    if mutation == "unsigned":
        headers.pop("Authorization")
    elif mutation == "foreign":
        headers["Authorization"] = "Bearer " + f.token(sub="unbound-reviewer")
    elif mutation == "hash":
        body["payload_hash"] = "0" * 64
    elif mutation == "bool":
        body["public_query_confirmed"] = 1
    elif mutation == "extra":
        body["actor_agent_id"] = str(uuid4())
    elif mutation == "identity_header":
        headers["X-Actor-Principal-Id"] = f.actor
    else:
        path += "?approve=true"
    response = f.client.post(path, headers=headers, json=body)
    assert response.status_code >= 400 and response.headers["cache-control"] == "no-store"
    with Session(f.engine) as session:
        assert session.scalar(select(func.count()).select_from(Decision).where(
            Decision.action_revision_id == f.proposal["revision_id"])) == 0
        assert session.scalar(select(func.count()).select_from(Operation).where(
            Operation.action_revision_id == f.proposal["revision_id"])) == 0
