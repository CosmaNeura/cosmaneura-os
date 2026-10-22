"""Research bot proposals and one reviewed public read, bound to existing F-8.

Models can draft public queries, never attest human review. No bearer files,
model-supplied account identities, source saves, approvals or external sends.
"""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, select

from cosmas_os.adapters.public_research import PublicResearch
from cosmas_os.api.research_schemas import Search
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import research
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import CaptureBudget
from cosmas_os.config import settings as runtime_settings
from cosmas_os.models import (
    ActionRevision,
    AuditEvent,
    Decision,
    ExternalIdentity,
    ModelWorkAdmission,
    Operation,
    Ticket,
)
from cosmas_os.ports.agent_connectors import (
    CONNECTOR_REQUEST_ADAPTER as REQUEST_ADAPTER,
)
from cosmas_os.ports.agent_connectors import (
    CONNECTOR_TOOL_NAMES as TOOL_NAMES,
)
from cosmas_os.ports.agent_connectors import (
    ExecuteReviewedResearch,
    ProposeResearchQuery,
    ReadResearchResult,
    ResearchHandle,
    tool_definitions,
)
from cosmas_os.ports.research import research_digest
from cosmas_os.research_models import ResearchRun

__all__ = ["REQUEST_ADAPTER", "TOOL_NAMES", "ProposeResearchQuery", "ExecuteReviewedResearch",
    "ReadResearchResult", "ResearchHandle", "tool_definitions", "AgentConnectorToolExecutor",
    "list_research_queries", "review_research_query", "prepare_connector_intents"]

LANE = "encounter_agent_research"
ACTION = "research_public_lookup_v1"
CONTRACT = "cosmas-agent-research-intent.v1"
MAX_RESPONSE_BYTES = 48_000

def evidence_digest(context):
    """Only admitted evidence: a later question is not a new source consent."""
    return research_digest([{"entry_id": p.entry_id, "revision": p.revision,
        "label": p.label, "kind": p.kind, "sha256": work.digest(p.content)}
        for p in context.sources])


def result_projection(result):
    """Bound delivery explicitly; full verified records stay in their immutable run."""
    records = []
    for record in result["results"][:12]:
        fields = record["fields"][:3]
        projected = {**{key: record[key] for key in ("source", "id", "title", "url",
            "source_updated_at", "version", "retrieved_at", "truncated", "raw_response_sha256",
            "query_sha256", "result_scope", "attribution", "sha256")},
            "excerpt": record["excerpt"][:500],
            "fields": [{"label": field["label"], "text": field["text"][:150]} for field in fields],
            "delivery_omissions": {"excerpt_characters": max(0, len(record["excerpt"]) - 500),
                "fields": max(0, len(record["fields"]) - 3),
                "field_text_characters": sum(max(0, len(field["text"]) - 150) for field in fields)},
            "record_sha256_covers": "original retained SourceRecord, not this compact delivery"}
        if len(json.dumps([*records, projected], ensure_ascii=False, separators=(",", ":")).encode()) > 40_000:
            break
        records.append(projected)
    return {"contract": "agent-research.result.v1", "workspace_id": result["workspace_id"],
        "run_id": result["run_id"], "request_sha256": result["request_sha256"],
        "retained_lookup_sha256": research_digest(result), "state": result["state"],
        "query": result["query"], "topic": result["topic"], "sources": result["sources"],
        "results": records, "errors": result["errors"],
        "delivery_omissions": {"records": len(result["results"]) - len(records)},
        "source_save_required": True, "clinical_eligibility_established": False}


def _require(condition, code="agent_connector_unavailable", status=409):
    if not condition:
        raise ws.WorkspaceError(code, status)


def _now(session, clock=None):
    value = work.now(session, clock)
    _require(isinstance(value, datetime) and value.tzinfo is not None, status=503)
    return value.astimezone(UTC)


def _identity(session, box, owner, identity_id):
    _require(identity_id is not None, "agent_connector_identity_required", 403)
    identity = session.scalar(select(ExternalIdentity).where(
        ExternalIdentity.id == identity_id, ExternalIdentity.box_id == box,
        ExternalIdentity.principal_id == owner, ExternalIdentity.provider == "clerk",
        ExternalIdentity.active.is_(True),
    ).execution_options(populate_existing=True))
    _require(identity is not None, "agent_connector_identity_required", 403)
    assert identity is not None  # Narrow only after the runtime authorization check.
    return identity


def _bound(session, box, owner, wid, handle):
    workspace = ws._workspace(session, box, owner, wid)
    ticket = session.scalar(select(Ticket).where(Ticket.id == handle.ticket_id,
        Ticket.box_id == box, Ticket.created_by_principal_id == owner,
        Ticket.lane == LANE, Ticket.appointment_id == workspace.appointment_id,
        Ticket.patient_link_id == workspace.patient_link_id).execution_options(populate_existing=True))
    revision = session.get(ActionRevision, handle.revision_id, populate_existing=True)
    _require(ticket is not None and revision is not None
        and ticket.current_revision_id == revision.id and revision.ticket_id == ticket.id
        and revision.box_id == box and not revision.invalidated
        and revision.action_type == ACTION and revision.payload_hash == handle.payload_hash
        and revision.payload_hash == research_digest(revision.payload), "agent_connector_intent_changed")
    assert ticket is not None and revision is not None
    payload = revision.payload
    _require(type(payload) is dict and set(payload) == {"contract", "workspace_id", "owner_id",
        "external_identity_id", "agent_id", "bot", "team_revision", "origin_admission_id",
        "origin_source_sha256", "evidence_sha256", "query", "topic", "sources", "expires_at"}
        and payload["contract"] == CONTRACT and payload["workspace_id"] == wid
        and payload["owner_id"] == owner, "agent_connector_intent_changed")
    _search(payload, key="agent-research:" + revision.id, expected=workspace.revision)
    _identity(session, box, owner, payload["external_identity_id"])
    return workspace, ticket, revision


def _search(payload, *, key, expected):
    return Search.model_validate_json(json.dumps({"contract_version": 1,
        "idempotency_key": key, "expected_revision": expected,
        "team_revision": payload["team_revision"], "bot": payload["bot"],
        "topic": payload["topic"], "sources": payload["sources"], "query": payload["query"],
        "public_query_confirmed": True}))


def _approved(session, ticket, revision):
    decision = session.scalar(select(Decision).where(Decision.ticket_id == ticket.id,
        Decision.action_revision_id == revision.id, Decision.box_id == ticket.box_id,
        Decision.actor_principal_id == revision.payload["owner_id"], Decision.kind == "approve"))
    audit = session.scalar(select(AuditEvent).where(AuditEvent.event_type == "agent_research.reviewed",
        AuditEvent.box_id == ticket.box_id, AuditEvent.action_revision_id == revision.id,
        AuditEvent.actor_principal_id == revision.payload["owner_id"],
        AuditEvent.approved_by_principal_id == revision.payload["owner_id"],
        AuditEvent.payload_hash == revision.payload_hash))
    _require(ticket.state == "approved" and decision is not None and audit is not None,
        "agent_connector_human_review_required", 403)


def _current_evidence(session, workspace, revision):
    payload = revision.payload
    version, bot, preferences = team.active_bot(session, workspace.box_id, workspace.owner_id,
        payload["bot"], payload["team_revision"])
    _require(preferences["role"] == "research" and bot.agent_id == payload["agent_id"],
        "agent_connector_role_denied", 403)
    origin = session.get(ModelWorkAdmission, payload["origin_admission_id"], populate_existing=True)
    _require(origin is not None and origin.workspace_id == workspace.id
        and origin.box_id == workspace.box_id and origin.owner_id == workspace.owner_id
        and origin.agent_id == bot.agent_id and origin.team_revision_id == version.id
        and origin.external_identity_id == payload["external_identity_id"]
        and origin.source_sha256 == payload["origin_source_sha256"]
        and work.digest(origin.prepared_envelope) == origin.envelope_sha256,
        "agent_connector_intent_changed")
    assert origin is not None
    context = work._context_for(session, workspace, version, preferences, bot, origin.request_body,
        draft_only=origin.kind == "private_handoff",
        prepared_contract=origin.envelope_contract)
    _require(evidence_digest(context) == payload["evidence_sha256"], "source_changed")


def _view(session, workspace, ticket, revision, *, clock=None):
    operation = session.scalar(select(Operation).where(Operation.action_revision_id == revision.id))
    run = session.scalar(select(ResearchRun).where(ResearchRun.workspace_id == workspace.id,
        ResearchRun.box_id == workspace.box_id, ResearchRun.owner_id == workspace.owner_id,
        ResearchRun.idempotency_key == "agent-research:" + revision.id))
    state = ticket.state
    try:
        _current_evidence(session, workspace, revision)
    except ws.WorkspaceError as error:
        if error.code == "source_changed":
            state = "source_changed"
        elif error.code in {"team_revision_conflict", "bot_paused", "agent_connector_role_denied"}:
            state = "team_changed"
        else:
            raise
    if state in {"source_changed", "team_changed"}:
        pass
    elif operation and operation.attempt_count:
        state = "result_ready" if run and run.state != "running" else "outcome_unconfirmed"
    elif _now(session, clock) >= datetime.fromisoformat(revision.payload["expires_at"]):
        state = "expired"
    return {"contract": "agent-research.review.v1", "workspace_id": workspace.id,
        "ticket_id": ticket.id, "revision_id": revision.id, "payload_hash": revision.payload_hash,
        "state": state, "query": revision.payload["query"], "topic": revision.payload["topic"],
        "sources": revision.payload["sources"], "expires_at": revision.payload["expires_at"],
        "bot": revision.payload["bot"], "team_revision": revision.payload["team_revision"],
        "run_id": run.id if run else None,
        "next_step": "review_query" if state == "pending_approval" else
            "ask_research_to_execute" if state == "approved" else
            "start_new_query" if state in {"expired", "source_changed", "team_changed"} else
            "wait_for_result" if state == "outcome_unconfirmed" else "read_saved_result"}


def list_research_queries(session, box, owner, wid, *, external_identity_id, clock=None):
    _identity(session, box, owner, external_identity_id)
    workspace = ws._workspace(session, box, owner, wid)
    rows = session.execute(select(Ticket, ActionRevision).join(ActionRevision,
        ActionRevision.id == Ticket.current_revision_id).where(Ticket.box_id == box,
        Ticket.created_by_principal_id == owner, Ticket.lane == LANE,
        Ticket.appointment_id == workspace.appointment_id,
        Ticket.patient_link_id == workspace.patient_link_id,
        ActionRevision.payload["workspace_id"].astext == wid,
    ).order_by(ActionRevision.created_at.desc(), ActionRevision.id.desc()).limit(10)).all()
    values = []
    for ticket, revision in rows:
        handle = ResearchHandle(ticket_id=ticket.id, revision_id=revision.id, payload_hash=revision.payload_hash)
        _bound(session, box, owner, wid, handle)
        values.append(_view(session, workspace, ticket, revision, clock=clock))
    return {"contract": "agent-research.history.v1", "workspace_id": wid, "proposals": values}


def prepare_connector_intents(session, *, box, owner, workspace_id, agent_id,
        team_revision_id, context, settings, external_identity_id=None, clock=None):
    """Freeze only this Research agent's exact reviewed intents before dispatch."""
    if settings.get("role") != "research" or external_identity_id is None:
        return {"connector_capabilities": [], "connector_intents": []}
    _identity(session, box, owner, external_identity_id)
    workspace = ws._workspace(session, box, owner, workspace_id)
    current_version = team.current(session, box, owner)
    _require(current_version is not None, "agent_connector_role_denied", 403)
    assert current_version is not None
    version, bot, preferences = team.active_bot(session, box, owner,
        team.bot_address(settings), current_version.revision)
    _require(version.id == team_revision_id and bot.agent_id == agent_id
        and preferences["role"] == "research", "agent_connector_role_denied", 403)
    rows = session.execute(select(Ticket, ActionRevision).join(ActionRevision,
        ActionRevision.id == Ticket.current_revision_id).where(Ticket.box_id == box,
        Ticket.created_by_principal_id == owner, Ticket.lane == LANE, Ticket.state == "approved",
        Ticket.appointment_id == workspace.appointment_id,
        Ticket.patient_link_id == workspace.patient_link_id,
        ActionRevision.payload["workspace_id"].astext == workspace_id,
        ActionRevision.payload["agent_id"].astext == agent_id,
    ).order_by(ActionRevision.created_at.desc(), ActionRevision.id.desc()).limit(11)).all()
    handles = []
    for ticket, revision in rows:
        handle = ResearchHandle(ticket_id=ticket.id, revision_id=revision.id,
            payload_hash=revision.payload_hash)
        _bound(session, box, owner, workspace_id, handle)
        _approved(session, ticket, revision)
        if (revision.payload["external_identity_id"] != external_identity_id
                or revision.payload["team_revision"] != version.revision):
            continue
        if evidence_digest(context) != revision.payload["evidence_sha256"]:
            continue
        _current_evidence(session, workspace, revision)
        operation = session.scalar(select(Operation).where(Operation.action_revision_id == revision.id))
        if (_now(session, clock) >= datetime.fromisoformat(revision.payload["expires_at"])
                and (operation is None or not operation.attempt_count)):
            continue
        handles.append({"kind": "research", **handle.model_dump()})
    _require(len(handles) <= 10, "agent_connector_selection_too_large", 422)
    return {"connector_capabilities": ["research_propose"], "connector_intents": handles}


def review_research_query(session, box, owner, wid, ticket_id, revision_id, payload_hash, *,
        external_identity_id, public_query_confirmed, clock=None):
    """Called only by a signed human route; never exported as a model tool."""
    _require(public_query_confirmed is True, "agent_connector_human_review_required", 422)
    session.rollback()
    work.lock_owner(session, box, owner)
    _identity(session, box, owner, external_identity_id)
    handle = ResearchHandle(ticket_id=ticket_id, revision_id=revision_id, payload_hash=payload_hash)
    workspace, ticket, revision = _bound(session, box, owner, wid, handle)
    _require(revision.payload["external_identity_id"] == external_identity_id,
        "agent_connector_identity_required", 403)
    _current_evidence(session, workspace, revision)
    _require(_now(session, clock) < datetime.fromisoformat(revision.payload["expires_at"]),
        "agent_connector_intent_expired")
    if ticket.state == "approved":
        _approved(session, ticket, revision)
    else:
        _require(ticket.state == "pending_approval", "agent_connector_intent_changed")
        ticket.state, ticket.version = "approved", ticket.version + 1
        session.add(Decision(box_id=box, ticket_id=ticket.id, action_revision_id=revision.id,
            actor_principal_id=owner, kind="approve"))
        session.add(Operation(box_id=box, ticket_id=ticket.id, action_revision_id=revision.id,
            idempotency_key="agent-research:" + revision.id, adapter=ACTION,
            status="pending", attempt_count=0))
        session.add(AuditEvent(box_id=box, aggregate_type="ticket", aggregate_id=ticket.id,
            event_type="agent_research.reviewed", actor_principal_id=owner,
            initiated_by_principal_id=owner, approved_by_principal_id=owner,
            action_revision_id=revision.id, payload_hash=revision.payload_hash,
            outcome="approved"))
    session.flush()
    result = _view(session, workspace, ticket, revision, clock=clock)
    session.commit()
    return result


class AgentConnectorToolExecutor:
    def __init__(self, session, claimed, *, guard, configuration=None,
            port_factory=None, clock=None):
        self.session, self.claimed, self.guard = session, claimed, guard
        self.configuration = configuration or (lambda: runtime_settings)
        self.port_factory, self.clock = port_factory or PublicResearch, clock

    def _guard(self):
        row, context, selection, preferences = self.guard()
        _require(isinstance(self.claimed, work.ModelClaim) and row.id == self.claimed.admission_id
            and row.agent_id != row.owner_id and preferences["role"] == "research",
            "agent_connector_role_denied", 403)
        _identity(self.session, row.box_id, row.owner_id, row.external_identity_id)
        return row, context, selection

    def execute(self, request):
        try:
            _require(len(json.dumps(request, ensure_ascii=False).encode()) <= 2048,
                "agent_tool_request_invalid", 422)
            checked = REQUEST_ADAPTER.validate_python(request)
        except (ValueError, TypeError, ValidationError):
            raise ws.WorkspaceError("agent_tool_request_invalid", 422) from None
        row, context, selection = self._guard()
        if isinstance(checked, ProposeResearchQuery):
            values = selection.model_dump() if hasattr(selection, "model_dump") else selection
            _require("research_propose" in values.get("connector_capabilities", []),
                "agent_connector_role_denied", 403)
            result = self._propose(row, context, checked)
        else:
            values = selection.model_dump() if hasattr(selection, "model_dump") else selection
            handle = checked.model_dump(exclude={"tool"})
            _require(any({key: item.get(key) for key in handle} == handle
                for item in values.get("connector_intents", []) if item.get("kind") == "research"),
                "agent_connector_intent_unavailable", 403)
            result = self._read_or_execute(row, context, checked)
        self._guard()
        _require(len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode())
            <= MAX_RESPONSE_BYTES, "agent_connector_result_too_large", 503)
        return result

    def _propose(self, row, context, request):
        session = self.session
        proposal = request.model_dump(exclude={"tool"})
        _search({**proposal, "bot": row.request_body["role"],
            "team_revision": row.request_body["team_revision"]}, key="validate-public-query",
            expected=context.context_revision)
        key = work.digest({"admission_id": row.id, **proposal})
        session.rollback()
        work.lock_owner(session, row.box_id, row.owner_id)
        self._guard()
        workspace = ws._workspace(session, row.box_id, row.owner_id, row.workspace_id, writing=True)
        prior = session.scalar(select(ActionRevision).where(ActionRevision.action_type == ACTION,
            ActionRevision.target_ref == key, ActionRevision.box_id == row.box_id))
        if prior:
            ticket = session.get(Ticket, prior.ticket_id)
            _require(ticket is not None, "agent_connector_intent_changed")
            assert ticket is not None
            return _view(session, workspace, ticket, prior, clock=self.clock)
        count = session.scalar(select(func.count()).select_from(Ticket).where(Ticket.box_id == row.box_id,
            Ticket.created_by_principal_id == row.owner_id, Ticket.lane == LANE,
            Ticket.appointment_id == workspace.appointment_id))
        _require(count < 100, "agent_connector_history_limit")
        payload = {"contract": CONTRACT, "workspace_id": row.workspace_id, "owner_id": row.owner_id,
            "external_identity_id": row.external_identity_id, "agent_id": row.agent_id,
            "bot": row.request_body["role"], "team_revision": row.request_body["team_revision"],
            "origin_admission_id": row.id, "origin_source_sha256": row.source_sha256,
            "evidence_sha256": evidence_digest(context), **proposal,
            "expires_at": (_now(session, self.clock) + timedelta(minutes=30)).isoformat()}
        ticket = Ticket(id=str(uuid4()), box_id=row.box_id, lane=LANE, state="pending_approval",
            created_by_principal_id=row.owner_id, appointment_id=workspace.appointment_id,
            patient_link_id=workspace.patient_link_id)
        revision = ActionRevision(id=str(uuid4()), ticket_id=ticket.id, box_id=row.box_id,
            revision_number=1, action_type=ACTION, target_ref=key, content=request.query,
            payload=payload, payload_hash=research_digest(payload), automation_class="hitl_required",
            policy_version=CONTRACT, charter_version="research-public-read-v1",
            config_version=str(row.team_revision_id), created_by_principal_id=row.agent_id)
        session.add(ticket)
        session.flush()
        session.add(revision)
        session.flush()
        ticket.current_revision_id = revision.id
        session.add(AuditEvent(box_id=row.box_id, aggregate_type="ticket", aggregate_id=ticket.id,
            event_type="agent_research.proposed", actor_principal_id=row.agent_id,
            initiated_by_principal_id=row.owner_id, action_revision_id=revision.id,
            payload_hash=revision.payload_hash, outcome="pending_approval"))
        session.commit()
        return _view(session, workspace, ticket, revision, clock=self.clock)

    def _read_or_execute(self, row, context, request):
        session = self.session
        session.rollback()
        work.lock_owner(session, row.box_id, row.owner_id)
        self._guard()
        workspace, ticket, revision = _bound(session, row.box_id, row.owner_id,
            row.workspace_id, request)
        payload = revision.payload
        _require(payload["agent_id"] == row.agent_id
            and payload["external_identity_id"] == row.external_identity_id
            and evidence_digest(context) == payload["evidence_sha256"], "source_changed")
        _approved(session, ticket, revision)
        key = "agent-research:" + revision.id
        prior = session.scalar(select(ResearchRun).where(ResearchRun.workspace_id == workspace.id,
            ResearchRun.box_id == row.box_id, ResearchRun.owner_id == row.owner_id,
            ResearchRun.idempotency_key == key))
        operation = session.scalar(select(Operation).where(Operation.action_revision_id == revision.id)
            .with_for_update().execution_options(populate_existing=True))
        _require(operation is not None and operation.ticket_id == ticket.id
            and operation.box_id == row.box_id and operation.adapter == ACTION
            and operation.idempotency_key == key, "agent_connector_intent_changed")
        assert operation is not None
        if prior:
            _require(operation.attempt_count == 1 and prior.agent_id == row.agent_id, "agent_connector_intent_changed")
            result = research.observation(prior)
            _require({k: result["request"][k] for k in ("bot", "team_revision", "topic", "sources", "query")}
                == {k: payload[k] for k in ("bot", "team_revision", "topic", "sources", "query")},
                "agent_connector_intent_changed")
            return result_projection(result)
        if isinstance(request, ReadResearchResult) or operation.attempt_count:
            return {"contract": "agent-research.result.v1", "ticket_id": ticket.id,
                "revision_id": revision.id, "payload_hash": revision.payload_hash,
                "state": "outcome_unconfirmed" if operation.attempt_count else "not_started",
                "results": [], "errors": []}
        _require(operation.status == "pending" and operation.attempt_count == 0,
            "agent_connector_intent_changed")
        _require(_now(session, self.clock) < datetime.fromisoformat(payload["expires_at"]),
            "agent_connector_intent_expired")
        _current_evidence(session, workspace, revision)
        config = self.configuration().model_copy(deep=True)
        _require(config.workspace_research_available and config.workspace_research_io_enabled,
            "agent_connector_disabled", 403)
        factory = self.port_factory
        configured, frozen = factory.configured(config), factory.selection(config)
        _require(set(payload["sources"]) <= configured, "research_source_not_configured")
        command = _search(payload, key=key, expected=workspace.revision)
        operation.status, operation.attempt_count = "running", 1
        operation.started_at = _now(session, self.clock)
        session.commit()  # First and only invocation is durable before provider I/O.
        operation_id = operation.id
        budget = CaptureBudget(30)

        def current():
            budget.check()
            # The publisher application may have staged its immutable result.
            # Guard queries refresh their own authority rows; expiring all rows
            # here would discard that pending result before its final commit.
            self._guard()
            latest = self.configuration()
            _require(latest.workspace_research_available and latest.workspace_research_io_enabled
                and factory.selection(latest) == frozen, "agent_connector_disabled", 403)
            w, t, r = _bound(session, row.box_id, row.owner_id, row.workspace_id, request)
            _approved(session, t, r)
            _require(_now(session, self.clock) < datetime.fromisoformat(r.payload["expires_at"]),
                "agent_connector_intent_expired")
            _require(evidence_digest(context) == r.payload["evidence_sha256"], "source_changed")
            return budget.check()

        try:
            with factory(config) as port:
                result = research.search(session, row.box_id, row.owner_id, row.workspace_id,
                    request=command, configured=configured, port=port,
                    check=budget.check, reauthenticate=current)
            current()
            work.lock_owner(session, row.box_id, row.owner_id)
            self._guard()
            operation = session.get(Operation, operation_id, populate_existing=True)
            _require(operation is not None, "agent_connector_intent_changed")
            assert operation is not None
            operation.status, operation.completed_at = "succeeded", _now(session, self.clock)
            operation.result_receipt_hash = research_digest(result)
            session.commit()
            return result_projection(result)
        except Exception:
            session.rollback()
            operation = session.get(Operation, operation_id, populate_existing=True)
            if operation and operation.status == "running":
                operation.status, operation.error_message = "unknown", "research_outcome_unconfirmed"
                session.commit()
            raise
