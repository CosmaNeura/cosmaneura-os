"""PostgreSQL F-8 and actual v8 tools with offline provider I/O, never real delivery."""

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration.test_vendor_work import bound, call, gates, proposal, vendor_case

from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import agent_delivery_tools as delivery
from cosmas_os.application import agent_tools, vendor_execution, vendor_work
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.models import AuditEvent, ExternalIdentity, ModelWorkAdmission, Operation
from cosmas_os.ports.bot_capabilities import ModelCallFailure
from cosmas_os.vendor_models import VendorSubmitClaim

__all__ = ["gates", "vendor_case"]


@pytest.fixture
def session(engine):
    # VendorExecution settles in independent committed sessions, as in production.
    # Shared-connection outer savepoints would roll back another session's evidence.
    with Session(engine) as session:
        yield session


@pytest.fixture
def delivery_case(session, vendor_case, monkeypatch):
    config = team.runtime_settings
    for name, value in {"vendor_io_enabled": True, "workspace_agent_tools_enabled": True,
            "workspace_llm_backend": "azure_gpt41", "workspace_llm_api_key": SecretStr("invented-not-dispatched")}.items():
        monkeypatch.setattr(config, name, value)
    case = vendor_case
    current = team.save(session, case["box"], case["actor"], expected=0,
        key="invented-delivery-team", configuration=team.default_configuration())
    _, bot, _ = team.active_bot(session, case["box"], case["actor"], "follow_up", current["revision"])
    identity = ExternalIdentity(box_id=case["box"], principal_id=case["actor"], provider="clerk",
        issuer="https://invented.example.invalid", subject=str(uuid4()), organization_id="invented-org",
        reviewed_by="Invented owner", evidence_ref="invented-only")
    session.add(identity)
    session.commit()
    scope = SimpleNamespace(**case, identity=identity.id, agent=bot.agent_id,
        team_revision=current["revision"])
    yield scope
    for row in session.scalars(select(ModelWorkAdmission).where(
            ModelWorkAdmission.workspace_id == scope.wid, ModelWorkAdmission.state == "running")):
        assert row.dispatch_id is not None
        claimed = work.ModelClaim(row.id, scope.box, scope.actor, scope.wid, row.dispatch_id,
            row.envelope_sha256, row.prepared_envelope)
        work.settle(session, claimed, ModelCallFailure(dispatch="not_dispatched"))


def approved(session, scope, *, delegated=True):
    receipt = call(session, scope.__dict__, vendor_work.propose, proposal(scope.__dict__))
    tid = receipt["effect"]["ticket_id"]
    detail = call(session, scope.__dict__, vendor_work.detail, tid)
    fields = {"administrative_delivery_confirmed": True, "follow_up_bot_id": scope.agent} if delegated else {}
    decision = public.VendorDecision(**bound(detail, review_sha256=detail["review_sha256"],
        choice="approve", **fields))
    call(session, scope.__dict__, vendor_work.decide, tid, decision, external_identity_id=scope.identity)
    return {key: detail["summary"][key] for key in ("ticket_id", "revision_id", "operation_id", "payload_hash")}


def admission(session, scope, *, key, role="follow_up", factory=None, sessions=None):
    snapshot = ws.read(session, scope.box, scope.actor, scope.wid)
    aid, _ = work.reserve_conversation(session, scope.box, scope.actor, scope.wid,
        expected=snapshot["revision"], team_revision=scope.team_revision, key=key, role=role,
        content="Carry out only the exact human-reviewed administrative message.",
        external_identity_id=scope.identity)
    claimed = work.claim(session, scope.box, scope.actor, aid)
    assert claimed is not None
    return claimed, agent_tools.AgentToolExecutor(session, claimed, session_factory=sessions,
        delivery_execution_factory=factory)


def test_no_delegation_no_execution_and_no_provider_selection_by_bot(session, delivery_case):
    scope = delivery_case
    handle = approved(session, scope, delegated=False)
    _, executor = admission(session, scope, key="invented-undelegated")
    assert executor.claimed.envelope["contract"] == "cosmas-gpt41-prepared.v6"
    assert "delivery_intents" not in executor.execute({"tool": "list_selected_sources"})["data"]
    with pytest.raises(ws.WorkspaceError, match="agent_tool_request_invalid"):
        executor.execute({"tool": "execute_reviewed_delivery", **handle})
    assert session.get(VendorSubmitClaim, handle["operation_id"]) is None


def test_actual_v8_saved_status_frozen_approval_and_wrong_role_refused(session, delivery_case):
    scope = delivery_case
    handle = approved(session, scope)
    claimed, executor = admission(session, scope, key="invented-status")
    assert claimed.envelope["contract"] == "cosmas-gpt41-prepared.v8"
    status = executor.execute({"tool": "read_delivery_status", **handle})["data"]
    assert status["summary"]["dispatch"] == "not_started" and status["submit_claim"] is None
    assert status["intent"]["agent_id"] == scope.agent and not status["provider_read_performed"]
    assert status["source_sha256"] and not status["clinical_completion_established"]
    work.settle(session, claimed, ModelCallFailure(dispatch="not_dispatched"))
    _, chief = admission(session, scope, key="invented-chief", role="chief")
    with pytest.raises(ws.WorkspaceError, match="agent_tool_request_invalid"):
        chief.execute({"tool": "execute_reviewed_delivery", **handle})


@pytest.mark.parametrize("mutation", ["identity", "connection", "authority", "note"])
def test_revoked_or_changed_authority_withholds_status_before_provider_io(session, delivery_case, mutation):
    scope = delivery_case
    handle = approved(session, scope)
    _, executor = admission(session, scope, key="invented-current-" + mutation)
    if mutation == "identity":
        session.get(ExternalIdentity, scope.identity).active = False
    elif mutation == "connection":
        scope.config.write_enabled = False
    elif mutation == "authority":
        row = session.scalar(select(AuditEvent).where(AuditEvent.event_type == delivery.AUTHORITY_EVENT,
            AuditEvent.aggregate_id == handle["ticket_id"]))
        assert row is not None
        row.payload_hash = "a" * 64
    else:
        from cosmas_os.application import note_review
        snapshot = ws.read(session, scope.box, scope.actor, scope.wid)
        note_review.save(session, scope.box, scope.actor, scope.wid, expected=snapshot["revision"],
            key="invented-note-changed", base_note_id=snapshot["note"]["latest"]["id"],
            source_reply_id=None, content="Changed invented source after approval.")
    session.commit()
    with pytest.raises(ws.WorkspaceError):
        executor.execute({"tool": "read_delivery_status", **handle})
    assert session.get(VendorSubmitClaim, handle["operation_id"]) is None


def test_actual_vendor_execution_one_claim_lost_reply_reopens_without_resubmit(session, delivery_case, engine):
    scope = delivery_case
    handle = approved(session, scope)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"requestId": "invented_async_request"})

    def sessions():
        return Session(engine)

    def factory(identity_current):
        chosen = scope.config.private_selection

        async def credential(selection):
            return Credential(selection_sha256=selection.commitment(),
                credential_ref=chosen["credential_ref"], secret=SecretStr("invented-no-provider"))

        return vendor_execution.VendorExecution(sessions, credential,
            transport=httpx.MockTransport(respond), identity_current=identity_current)

    claimed, executor = admission(session, scope, key="invented-dispatch", factory=factory, sessions=sessions)
    result = executor.execute({"tool": "execute_reviewed_delivery", **handle})["data"]
    assert len(requests) == 1 and result["summary"]["submit_claimed"]
    assert result["summary"]["dispatch"] == "response_observed"
    assert result["summary"]["acceptance"] == "accepted"
    assert result["summary"]["transport"] == "not_observed"
    assert result["submit_claim"]["actor_id"] == scope.actor
    assert result["submit_claim"]["approval_receipt_id"] == result["intent"]["approval_receipt_id"]
    assert not result["clinical_completion_established"]
    # Discarding the foreground result does not authorize another provider invocation.
    replay = executor.execute({"tool": "execute_reviewed_delivery", **handle})["data"]
    assert len(requests) == 1 and replay["submit_receipt"] == result["submit_receipt"]
    assert session.get(Operation, handle["operation_id"]).attempt_count == 1
    work.settle(session, claimed, ModelCallFailure(dispatch="not_dispatched"))
    _, reopened = admission(session, scope, key="invented-reopen")
    saved = reopened.execute({"tool": "read_delivery_status", **handle})["data"]
    assert len(requests) == 1 and saved["submit_receipt"] == result["submit_receipt"]


def test_missing_runtime_refuses_before_irreversible_claim(session, delivery_case):
    handle = approved(session, delivery_case)
    _, executor = admission(session, delivery_case, key="invented-missing-runtime")
    with pytest.raises(ws.WorkspaceError, match="agent_delivery_runtime_unavailable"):
        executor.execute({"tool": "execute_reviewed_delivery", **handle})
    assert session.get(VendorSubmitClaim, handle["operation_id"]) is None
    assert session.get(Operation, handle["operation_id"]).attempt_count == 0


def test_interruption_after_claim_before_invocation_never_retries(session, delivery_case, engine, monkeypatch):
    handle = approved(session, delivery_case)
    invocations = []

    async def interrupted(self, invocation, **_):
        invocations.append(invocation)
        raise TimeoutError("invented process interruption after durable claim")

    monkeypatch.setattr(vendor_execution.VendorExecution, "invoke", interrupted)
    def factory(current):
        return vendor_execution.VendorExecution(lambda: Session(engine), None,
            identity_current=current)
    _, executor = admission(session, delivery_case, key="invented-interrupted",
        factory=factory, sessions=lambda: Session(engine))
    with pytest.raises(TimeoutError):
        executor.execute({"tool": "execute_reviewed_delivery", **handle})
    result = executor.execute({"tool": "execute_reviewed_delivery", **handle})["data"]
    assert len(invocations) == 1 and result["summary"]["submit_claimed"]
    assert result["summary"]["dispatch"] == "not_started"
    assert result["summary"]["transport"] == "not_observed"
    assert session.get(Operation, handle["operation_id"]).attempt_count == 1


def test_new_team_cannot_reactivate_old_delivery_authority(session, delivery_case):
    scope = delivery_case
    handle = approved(session, scope)
    claimed, executor = admission(session, scope, key="invented-team-before")
    version = team.current(session, scope.box, scope.actor)
    assert version is not None
    configuration = dict(version.configuration)
    configuration["practice_context"] = "Invented changed preferences"
    team.save(session, scope.box, scope.actor, expected=scope.team_revision,
        key="invented-team-after", configuration=configuration)
    with pytest.raises(ws.WorkspaceError):
        executor.execute({"tool": "execute_reviewed_delivery", **handle})
    assert session.get(VendorSubmitClaim, handle["operation_id"]) is None
    work.settle(session, claimed, ModelCallFailure(dispatch="not_dispatched"))
    scope.team_revision += 1
    _, fresh = admission(session, scope, key="invented-team-fresh")
    assert fresh.claimed.envelope["contract"] == "cosmas-gpt41-prepared.v6"
