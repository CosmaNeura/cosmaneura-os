"""Actual PostgreSQL F-8 review/claim/recovery; injected offline reader, no acceptance claim."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration.test_model_work_admission import case

from cosmas_os.application import agent_connector_tools as tools
from cosmas_os.application import agent_tools
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    Decision,
    ExternalIdentity,
    ModelWorkAdmission,
    Operation,
)
from cosmas_os.ports.bot_capabilities import ModelCallFailure
from cosmas_os.research_models import ResearchRun


@pytest.fixture
def connected_case(engine, monkeypatch):
    monkeypatch.setattr(team.runtime_settings, "workspace_agent_tools_enabled", True)
    monkeypatch.setattr(team.runtime_settings, "workspace_llm_backend", "azure_gpt41")
    monkeypatch.setattr(team.runtime_settings, "workspace_llm_api_key", SecretStr("invented-never-dispatched"))
    monkeypatch.setattr(team.runtime_settings, "workspace_research_enabled", True)
    monkeypatch.setattr(team.runtime_settings, "workspace_research_io_enabled", True)
    monkeypatch.setattr(tools, "PublicResearch", EmptyPublicReader)
    box, owner, wid, revision = case(engine)
    with Session(engine) as session:
        version = team.current(session, box, owner)
        assert version is not None
        configuration = dict(version.configuration)
        configuration["bots"] = list(configuration["bots"]) + [{"role": "research",
            "instance_id": str(uuid4()), "name": "Invented Research", "enabled": True,
            "include_notebook": True, "include_evidence": True}]
        current = team.save(session, box, owner, expected=revision,
            key="invented-connector-team", configuration=configuration)
        identity = ExternalIdentity(box_id=box, principal_id=owner, provider="clerk",
            issuer="https://invented.example.invalid", subject=str(uuid4()),
            organization_id="invented-org", reviewed_by="Invented owner", evidence_ref="invented-only")
        session.add(identity)
        session.commit()
        source = ws.append(session, box, owner, wid, expected=1, key="invented-connector-source",
            kind="scratchpad", content="Invented ankle question. Allergy not yet confirmed.")
        scope = SimpleNamespace(box=box, owner=owner, wid=wid, team_revision=current["revision"],
            bot=configuration["bots"][-1]["instance_id"], identity=identity.id,
            source_entry=source["entry_id"])
    monkeypatch.setattr(team.runtime_settings, "auth_mode", "clerk_jwt")
    monkeypatch.setattr(team.runtime_settings, "workspace_authenticated_enabled", True)
    monkeypatch.setattr(team.runtime_settings, "synth_seed", False)
    monkeypatch.setattr(team.runtime_settings, "beta_box_id", box)
    monkeypatch.setattr(team.runtime_settings, "clerk_issuer", "https://invented.example.invalid")
    monkeypatch.setattr(team.runtime_settings, "clerk_jwks_url", "https://invented.example.invalid/.well-known/jwks.json")
    monkeypatch.setattr(team.runtime_settings, "clerk_audience", "invented-local")
    monkeypatch.setattr(team.runtime_settings, "clerk_organization_id", "invented-org")
    monkeypatch.setattr(team.runtime_settings, "clerk_authorized_parties", "http://localhost:5173")
    monkeypatch.setattr(team.runtime_settings, "cors_allowed_origins", "http://localhost:5173")
    yield scope
    with Session(engine) as session:
        for row in session.scalars(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == wid,
                ModelWorkAdmission.state.in_(("reserved", "running")))):
            if row.state == "reserved":
                claimed = work.claim(session, box, owner, row.id)
            else:
                assert row.dispatch_id is not None
                claimed = work.ModelClaim(row.id, box, owner, wid, row.dispatch_id,
                    row.envelope_sha256, row.prepared_envelope)
            if claimed:
                work.settle(session, claimed, ModelCallFailure(dispatch="not_dispatched"))


class EmptyPublicReader:
    """Offline application test port, not a real connector acceptance substitute."""
    calls = []

    @classmethod
    def configured(cls, _):
        return frozenset({"pubmed"})

    @staticmethod
    def selection(_):
        return "invented-fixed-selection"

    def __init__(self, _):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def lookup(self, source, query, *, check):
        check()
        self.calls.append((source, query))
        return []


def admission(session, scope, *, key, handles=(), role=None, identity=True):
    snapshot = ws.read(session, scope.box, scope.owner, scope.wid)
    aid, _ = work.reserve_conversation(session, scope.box, scope.owner, scope.wid,
        expected=snapshot["revision"], team_revision=scope.team_revision, key=key,
        role=role or scope.bot, content="Review the current invented evidence and connector intent.",
        external_identity_id=scope.identity if identity else None)
    claimed = work.claim(session, scope.box, scope.owner, aid)
    assert claimed is not None
    # Exercise the real parent v7 envelope and unified AgentToolExecutor.
    assert claimed.envelope["contract"] == "cosmas-gpt41-prepared.v7" if identity and not role else True
    reader = agent_tools.AgentToolExecutor(session, claimed)
    return claimed, reader


def propose(session, scope):
    claimed, executor = admission(session, scope, key="invented-propose")
    request = {"tool": "propose_research_query", "topic": "literature", "sources": ["pubmed"],
        "query": "acute ankle injury evidence"}
    proposal = executor.execute(request)["data"]
    replay = executor.execute(request)["data"]
    assert replay["ticket_id"] == proposal["ticket_id"]
    work.settle(session, claimed, ModelCallFailure(dispatch="not_dispatched"))
    return proposal


def approve(session, scope, proposal):
    return tools.review_research_query(session, scope.box, scope.owner, scope.wid,
        proposal["ticket_id"], proposal["revision_id"], proposal["payload_hash"],
        external_identity_id=scope.identity, public_query_confirmed=True)


def handle(proposal):
    return {"kind": "research", **{key: proposal[key] for key in ("ticket_id", "revision_id", "payload_hash")}}


def execute_request(proposal, tool="execute_reviewed_research"):
    return {"tool": tool, **{key: proposal[key] for key in ("ticket_id", "revision_id", "payload_hash")}}


def test_real_f8_proposal_human_review_claim_and_recovery_do_not_duplicate_io(engine, connected_case):
    scope = connected_case
    EmptyPublicReader.calls = []
    with Session(engine) as session:
        proposal = propose(session, scope)
        assert proposal["state"] == "pending_approval" and not EmptyPublicReader.calls
        assert session.scalar(select(Decision).where(Decision.ticket_id == proposal["ticket_id"])) is None
        assert session.scalar(select(Operation).where(Operation.ticket_id == proposal["ticket_id"])) is None
        approved = approve(session, scope, proposal)
        assert approved["state"] == "approved" and not EmptyPublicReader.calls
        assert approve(session, scope, proposal) == approved
        claimed, executor = admission(session, scope, key="invented-execute", handles=[handle(proposal)])
        result = executor.execute(execute_request(proposal))["data"]
        assert result["state"] == "completed" and EmptyPublicReader.calls == [("pubmed", proposal["query"])]
        assert executor.execute(execute_request(proposal))["data"] == result
        assert executor.execute(execute_request(proposal, "read_research_result"))["data"] == result
        operation = session.scalar(select(Operation).where(Operation.ticket_id == proposal["ticket_id"]))
        assert operation is not None
        assert operation.attempt_count == 1 and operation.status == "succeeded"
        assert len(EmptyPublicReader.calls) == 1
        work.settle(session, claimed, ModelCallFailure(dispatch="not_dispatched"))


@pytest.mark.parametrize("failure", ["unreviewed", "wrong_hash", "unselected", "revoked_identity"])
def test_model_cannot_execute_without_exact_human_review_and_current_scope(engine, connected_case, failure):
    scope = connected_case
    EmptyPublicReader.calls = []
    with Session(engine) as session:
        proposal = propose(session, scope)
        if failure != "unreviewed":
            approve(session, scope, proposal)
        claimed, executor = admission(session, scope, key="invented-denied-" + failure,
            handles=[] if failure == "unselected" else [handle(proposal)])
        request = execute_request(proposal)
        if failure == "unselected":
            request["ticket_id"] = str(uuid4())
        if failure == "wrong_hash":
            request["payload_hash"] = "0" * 64
        if failure == "revoked_identity":
            identity = session.get(ExternalIdentity, scope.identity)
            assert identity is not None
            identity.active = False
            session.commit()
        with pytest.raises(ws.WorkspaceError):
            executor.execute(request)
        assert not EmptyPublicReader.calls
        work.settle(session, claimed, ModelCallFailure(dispatch="not_dispatched"))


def test_changed_evidence_refuses_human_review_and_retainable_metadata(engine, connected_case):
    scope = connected_case
    with Session(engine) as session:
        proposal = propose(session, scope)
        snapshot = ws.read(session, scope.box, scope.owner, scope.wid)
        ws.append(session, scope.box, scope.owner, scope.wid, expected=snapshot["revision"],
            key="invented-changed-source", kind="scratchpad", content="Changed invented source tail.")
        with pytest.raises(ws.WorkspaceError, match="source_changed"):
            approve(session, scope, proposal)
        session.rollback()
        rows = tools.list_research_queries(session, scope.box, scope.owner, scope.wid,
            external_identity_id=scope.identity)
        assert rows["proposals"][0]["state"] == "source_changed"
        assert rows["proposals"][0]["next_step"] == "start_new_query"


def test_expired_intent_refuses_new_dispatch_before_provider_io(engine, connected_case):
    scope = connected_case
    EmptyPublicReader.calls = []
    with Session(engine) as session:
        proposal = propose(session, scope)
        with pytest.raises(ws.WorkspaceError, match="intent_expired"):
            tools.review_research_query(session, scope.box, scope.owner, scope.wid,
                proposal["ticket_id"], proposal["revision_id"], proposal["payload_hash"],
                external_identity_id=scope.identity, public_query_confirmed=True,
                clock=lambda: datetime.now(UTC) + timedelta(hours=1))
        assert not EmptyPublicReader.calls


def test_lost_response_after_claim_never_retries_missing_or_running_lookup(engine, connected_case, monkeypatch):
    scope = connected_case
    EmptyPublicReader.calls = []
    with Session(engine) as session:
        proposal = propose(session, scope)
        approve(session, scope, proposal)
        claimed, executor = admission(session, scope, key="invented-lost-response", handles=[handle(proposal)])

        def lost(*args, **kwargs):
            raise TimeoutError("invented interruption after durable operation claim")

        monkeypatch.setattr(tools.research, "search", lost)
        with pytest.raises(TimeoutError):
            executor.execute(execute_request(proposal))
        observation = executor.execute(execute_request(proposal))["data"]
        assert observation["state"] == "outcome_unconfirmed" and not EmptyPublicReader.calls
        operation = session.scalar(select(Operation).where(Operation.ticket_id == proposal["ticket_id"]))
        assert operation is not None
        assert operation.status == "unknown" and operation.attempt_count == 1
        assert session.scalar(select(ResearchRun).where(ResearchRun.workspace_id == scope.wid)) is None
        work.settle(session, claimed, ModelCallFailure(dispatch="not_dispatched"))


def test_nonresearch_role_and_missing_external_identity_cannot_propose(engine, connected_case):
    scope = connected_case
    with Session(engine) as session:
        claimed, executor = admission(session, scope, key="invented-wrong-role", role="visit_prep")
        with pytest.raises(ws.WorkspaceError):
            executor.execute({"tool": "propose_research_query", "topic": "literature",
                "sources": ["pubmed"], "query": "invented evidence"})
        work.settle(session, claimed, ModelCallFailure(dispatch="not_dispatched"))
        claimed, executor = admission(session, scope, key="invented-no-identity", identity=False)
        with pytest.raises(ws.WorkspaceError):
            executor.execute({"tool": "propose_research_query", "topic": "literature",
                "sources": ["pubmed"], "query": "invented evidence"})
        work.settle(session, claimed, ModelCallFailure(dispatch="not_dispatched"))


def test_prior_team_approved_intent_is_skipped_in_new_team_admission(engine, connected_case):
    scope = connected_case
    with Session(engine) as session:
        proposal = propose(session, scope)
        approve(session, scope, proposal)
        current = team.current(session, scope.box, scope.owner)
        assert current is not None
        configuration = dict(current.configuration)
        configuration["practice_context"] = "Invented changed team context"
        version = team.save(session, scope.box, scope.owner, expected=current.revision,
            key="invented-new-team", configuration=configuration)
        scope.team_revision = version["revision"]
        claimed, executor = admission(session, scope, key="invented-after-team-change")
        assert claimed.envelope["tool_selection"]["connector_intents"] == []
        assert claimed.envelope["tool_selection"]["connector_capabilities"] == ["research_propose"]
        with pytest.raises(ws.WorkspaceError, match="intent_unavailable"):
            executor.execute(execute_request(proposal))
        work.settle(session, claimed, ModelCallFailure(dispatch="not_dispatched"))
