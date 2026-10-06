"""Follow-up execution of exact F-8 human-reviewed administrative messages.

The configured existing VendorExecution owns credentials, current installation,
one irreversible submit claim and provider settlement. No queue or retry is added.
"""

import asyncio
import json
import time

from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import vendor_execution as execution
from cosmas_os.application import vendor_settings_admission
from cosmas_os.application import vendor_work as vendor
from cosmas_os.application import workspace as ws
from cosmas_os.application.agent_connector_tools import _identity, _require, evidence_digest
from cosmas_os.models import AuditEvent, Operation
from cosmas_os.ports.agent_delivery_tools import (
    DELIVERY_REQUEST_ADAPTER,
    DeliveryHandle,
    DeliveryIntent,
    ExecuteReviewedDelivery,
)
from cosmas_os.ports.bot_capabilities import supports_skill
from cosmas_os.ports.vendor_connectors import SpruceMessageIntent
from cosmas_os.vendor_models import VendorCommandReceipt, VendorSubmitClaim, VendorWorkRevision

AUTHORITY_EVENT = "workspace.agent_delivery_authorized"
MAX_RESPONSE_BYTES = 48_000


def _binding(session, workspace, handle):
    _, ticket, revision, command = vendor._bound(session, workspace, handle.ticket_id,
        revision_id=handle.revision_id, writing=False)
    _require(ticket.current_revision_id == handle.revision_id
        and revision.intended_operation_id == handle.operation_id
        and revision.payload_hash == handle.payload_hash
        and revision.action == "spruce_secure_message"
        and isinstance(command.intent, SpruceMessageIntent)
        and command.intent.destination.channel == "secure"
        and command.intent.attachment is None, "agent_delivery_intent_changed")
    return ticket, revision


def _approval(session, workspace, revision, *, agent_id, team_revision_id, external_identity_id):
    receipt = session.scalar(select(VendorCommandReceipt).where(
        VendorCommandReceipt.action_revision_id == revision.action_revision_id,
        VendorCommandReceipt.workspace_id == workspace.id,
        VendorCommandReceipt.box_id == workspace.box_id,
        VendorCommandReceipt.owner_id == workspace.owner_id,
        VendorCommandReceipt.actor_id == workspace.owner_id,
        VendorCommandReceipt.command_kind == "decide",
        VendorCommandReceipt.public_request["choice"].as_string() == "approve",
    ).execution_options(populate_existing=True))
    _require(receipt is not None, "agent_delivery_human_review_required", 403)
    assert receipt is not None
    request = public.VendorDecision.model_validate(receipt.public_request)
    _require(request.administrative_delivery_confirmed is True
        and request.follow_up_bot_id == agent_id
        and request.revision_id == revision.action_revision_id
        and request.operation_id == revision.intended_operation_id
        and request.payload_hash == revision.payload_hash
        and request.review_sha256 == revision.review_sha256
        and public.request_digest("decide", vendor._scope(workspace), request)
            == receipt.request_sha256, "agent_delivery_human_review_required", 403)
    vendor.command_response(session, receipt)  # Validate the retained public receipt commitment.
    detail = {"approval_receipt_id": receipt.id, "approval_receipt_sha256": receipt.receipt_sha256,
        "revision_id": revision.action_revision_id, "payload_hash": revision.payload_hash,
        "operation_id": revision.intended_operation_id, "agent_id": agent_id,
        "team_revision_id": team_revision_id, "external_identity_id": external_identity_id}
    authority = session.scalar(select(AuditEvent).where(AuditEvent.box_id == workspace.box_id,
        AuditEvent.aggregate_type == "vendor_work", AuditEvent.aggregate_id == revision.ticket_id,
        AuditEvent.event_type == AUTHORITY_EVENT,
        AuditEvent.actor_principal_id == workspace.owner_id,
        AuditEvent.detail == detail, AuditEvent.payload_hash == work.digest(detail)))
    _require(authority is not None, "agent_delivery_human_review_required", 403)
    return receipt, work.digest(detail)


def prepare_delivery_intents(session, *, box, owner, workspace_id, agent_id,
        team_revision_id, context, settings, external_identity_id=None, clock=None):
    """Metadata only. Private handoffs and draft contexts never gain delivery authority."""
    if (settings.get("role") != "follow_up" or not supports_skill(settings, "work_status")
            or external_identity_id is None or context.draft_only
            or not team.runtime_settings.vendor_work_enabled
            or not team.runtime_settings.vendor_io_enabled):
        return {"delivery_intents": []}
    _identity(session, box, owner, external_identity_id)
    workspace = ws._workspace(session, box, owner, workspace_id)
    current = team.current(session, box, owner)
    _require(current is not None, "agent_delivery_role_denied", 403)
    assert current is not None
    version, bot, preferences = team.active_bot(session, box, owner,
        team.bot_address(settings), current.revision)
    _require(version.id == team_revision_id and bot.agent_id == agent_id
        and preferences["role"] == "follow_up", "agent_delivery_role_denied", 403)
    rows = session.scalars(select(VendorWorkRevision).where(
        VendorWorkRevision.box_id == box, VendorWorkRevision.owner_id == owner,
        VendorWorkRevision.workspace_id == workspace_id,
        VendorWorkRevision.action == "spruce_secure_message",
    ).order_by(VendorWorkRevision.created_at.desc(), VendorWorkRevision.action_revision_id.desc()).limit(100))
    handles = []
    for revision in rows:
        handle = DeliveryHandle(ticket_id=revision.ticket_id, revision_id=revision.action_revision_id,
            operation_id=revision.intended_operation_id, payload_hash=revision.payload_hash)
        try:
            ticket, revision = _binding(session, workspace, handle)
            _require(ticket.state in {"approved", "closed"}, "agent_delivery_intent_changed")
            vendor._new_current(session, workspace, revision, None)
            receipt, authority = _approval(session, workspace, revision, agent_id=agent_id,
                team_revision_id=team_revision_id, external_identity_id=external_identity_id)
        except ws.WorkspaceError:
            continue  # Unreviewed, stale or revoked deliveries confer no handle.
        handles.append(DeliveryIntent(kind="vendor_delivery", **handle.model_dump(),
            approval_receipt_id=receipt.id, approval_receipt_sha256=receipt.receipt_sha256,
            authority_sha256=authority, agent_id=agent_id, team_revision_id=team_revision_id,
            external_identity_id=external_identity_id, evidence_sha256=evidence_digest(context)).model_dump())
    _require(len(handles) <= 10, "agent_delivery_selection_too_large", 422)
    return {"delivery_intents": handles}


class AgentDeliveryToolExecutor:
    def __init__(self, session, claimed, *, guard, session_factory=None,
            execution_factory=None, clock=None):
        self.session, self.claimed, self.guard = session, claimed, guard
        self.sessions, self.execution_factory, self.clock = session_factory, execution_factory, clock

    def _guard(self):
        row, context, selection, preferences = self.guard()
        _require(isinstance(self.claimed, work.ModelClaim) and row.id == self.claimed.admission_id
            and row.agent_id != row.owner_id and row.kind == "conversation"
            and not context.draft_only and preferences["role"] == "follow_up"
            and supports_skill(preferences, "work_status"), "agent_delivery_role_denied", 403)
        _identity(self.session, row.box_id, row.owner_id, row.external_identity_id)
        _require(team.runtime_settings.vendor_work_enabled and team.runtime_settings.vendor_io_enabled,
            "agent_delivery_disabled", 403)
        return row, context, selection

    def _current(self, session, row, context, intent):
        _identity(session, row.box_id, row.owner_id, row.external_identity_id)
        _require(intent.agent_id == row.agent_id and intent.team_revision_id == row.team_revision_id
            and intent.external_identity_id == row.external_identity_id
            and intent.evidence_sha256 == evidence_digest(context), "agent_delivery_authority_changed", 403)
        workspace = vendor._owner(session, row.box_id, row.owner_id, row.workspace_id)
        ticket, revision = _binding(session, workspace, intent)
        _require(ticket.state in {"approved", "closed"}, "agent_delivery_intent_changed")
        vendor._new_current(session, workspace, revision, None)
        receipt, authority = _approval(session, workspace, revision, agent_id=row.agent_id,
            team_revision_id=row.team_revision_id, external_identity_id=row.external_identity_id)
        _require((receipt.id, receipt.receipt_sha256, authority) ==
            (intent.approval_receipt_id, intent.approval_receipt_sha256, intent.authority_sha256),
            "agent_delivery_authority_changed", 403)
        return workspace, ticket, revision

    def _fresh_authority(self, intent):
        """The async runtime callback never shares the foreground SQLAlchemy session."""
        from cosmas_os.application.agent_tools import AgentToolExecutor
        _require(self.sessions is not None, "agent_delivery_runtime_unavailable", 503)
        assert self.sessions is not None  # Narrow only after the runtime guard.
        with self.sessions() as session:
            checker = AgentToolExecutor(session, self.claimed, clock=self.clock)
            row, context, _, preferences = checker._guard()
            _require(row.kind == "conversation" and not context.draft_only
                and preferences["role"] == "follow_up"
                and supports_skill(preferences, "work_status")
                and team.runtime_settings.vendor_work_enabled
                and team.runtime_settings.vendor_io_enabled, "agent_delivery_role_denied", 403)
            self._current(session, row, context, intent)
        return True

    def execute(self, request):
        try:
            request = request.model_dump() if isinstance(request, BaseModel) else request
            _require(len(json.dumps(request, ensure_ascii=False, allow_nan=False).encode()) <= 2048,
                "agent_tool_request_invalid", 422)
            checked = DELIVERY_REQUEST_ADAPTER.validate_python(request)
        except (ValueError, TypeError, ValidationError, RecursionError):
            raise ws.WorkspaceError("agent_tool_request_invalid", 422) from None
        row, context, selection = self._guard()
        values = selection.model_dump() if hasattr(selection, "model_dump") else selection
        handle = checked.model_dump(exclude={"tool"})
        candidate = next((item for item in values.get("delivery_intents", [])
            if {key: item.get(key) for key in handle} == handle), None)
        _require(candidate is not None, "agent_delivery_intent_unavailable", 403)
        intent = DeliveryIntent.model_validate(candidate)
        workspace, ticket, revision = self._current(self.session, row, context, intent)
        if isinstance(checked, ExecuteReviewedDelivery):
            operation = self.session.get(Operation, intent.operation_id, populate_existing=True)
            _require(operation is not None, "agent_delivery_intent_changed")
            assert operation is not None
            claim = self.session.get(VendorSubmitClaim, operation.id, populate_existing=True)
            if claim is None:
                _require(ticket.state == "approved" and operation.attempt_count == 0,
                    "agent_delivery_intent_changed")
                _require(self.sessions is not None and self.execution_factory is not None,
                    "agent_delivery_runtime_unavailable", 503)
                assert self.execution_factory is not None
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    pass
                else:
                    raise ws.WorkspaceError("agent_delivery_async_context_unavailable", 503)

                async def identity_current():
                    try:
                        return await asyncio.to_thread(self._fresh_authority, intent)
                    except ws.WorkspaceError:
                        return False

                runtime = self.execution_factory(identity_current)
                _require(vendor_settings_admission.runtime_matches(self.session,
                    revision.connection_version_id, runtime), "agent_delivery_runtime_unavailable", 503)
                command = public.BoundCommand(expected_version=ticket.version,
                    **{key: value for key, value in handle.items() if key != "ticket_id"},
                    idempotency_key="agent-delivery:" + intent.operation_id)
                _, invocation = execution.claim_submit(self.session, row.box_id, row.owner_id,
                    workspace.id, ticket.id, command)
                if invocation is not None:
                    # VendorExecution owns its 45-second transport deadline and late settlement.
                    asyncio.run(runtime.invoke(invocation, deadline=time.monotonic() + 45))
        self.session.rollback()
        row, context, _ = self._guard()
        workspace, ticket, revision = self._current(self.session, row, context, intent)
        result = self._status(row, ticket, revision, intent)
        _require(len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode())
            <= MAX_RESPONSE_BYTES, "agent_delivery_result_too_large", 503)
        return result

    def _status(self, row, ticket, revision, intent):
        claim = self.session.get(VendorSubmitClaim, intent.operation_id, populate_existing=True)
        receipt = self.session.get(VendorCommandReceipt, claim.command_receipt_id) if claim else None
        if claim:
            _require((claim.box_id, claim.owner_id, claim.workspace_id, claim.ticket_id,
                claim.action_revision_id, claim.actor_id, claim.approval_receipt_id,
                claim.command_sha256, claim.source_sha256) == (row.box_id, row.owner_id,
                row.workspace_id, intent.ticket_id, intent.revision_id, row.owner_id,
                intent.approval_receipt_id, revision.private_command_sha256, revision.source_proof_sha256)
                and receipt is not None, "agent_delivery_intent_changed")
        if receipt:
            _require(receipt.command_kind == "submit" and receipt.operation_id == intent.operation_id
                and receipt.action_revision_id == intent.revision_id
                and receipt.ticket_id == intent.ticket_id and receipt.box_id == row.box_id
                and receipt.owner_id == row.owner_id and receipt.workspace_id == row.workspace_id,
                "agent_delivery_intent_changed")
            vendor.command_response(self.session, receipt)
        return {"contract": "agent-delivery.status.v1", "workspace_id": row.workspace_id,
            "agent_id": row.agent_id, "team_revision_id": row.team_revision_id,
            "external_identity_id": row.external_identity_id, "source_sha256": row.source_sha256,
            "intent": intent.model_dump(), "summary": vendor._summary(self.session, ticket, revision),
            "submit_receipt": {"id": receipt.id, "sha256": receipt.receipt_sha256} if receipt else None,
            "submit_claim": {"operation_id": claim.operation_id, "actor_id": claim.actor_id,
                "approval_receipt_id": claim.approval_receipt_id,
                "command_sha256": claim.command_sha256, "source_sha256": claim.source_sha256,
                "claimed_at": public.timestamp(claim.claimed_at),
                "completed_at": public.timestamp(claim.completed_at) if claim.completed_at else None,
                "dispatch": claim.dispatch} if claim else None,
            "provider_read_performed": False, "automatic_retry_performed": False,
            "clinical_completion_established": False}
