"""Read-only product tools bound to a running admission and exact saved evidence."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmas_os.adapters.gpt41 import _context
from cosmas_os.application import model_work as work
from cosmas_os.application import operations_status as operations
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    ModelWorkAdmission,
    WorkspaceEntry,
    WorkspaceHandoff,
    WorkspaceHandoffAttempt,
    WorkspaceReply,
)
from cosmas_os.ports.agent_tools import (
    REQUEST_ADAPTER,
    AgentToolRequest,
    DraftHandle,
    ListSelectedSources,
    ReadCurrentOperationStatus,
    ReadSavedTeammateDraft,
    ReadSelectedSource,
    SourceHandle,
    ToolSelection,
)
from cosmas_os.ports.bot_capabilities import BotContext, supports_skill

MAX_REQUEST_BYTES = 2048
MAX_RESPONSE_BYTES = 48_000
MAX_CONTENT_CHARS = 20_000


def _content_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _selection(sources, drafts, statuses):
    value = {
        "contract": "cosmas-agent-tool-selection.v1",
        "sources": sources,
        "teammate_drafts": drafts,
        "operations": statuses,
    }
    return ToolSelection.model_validate({**value, "sha256": work.digest(value)}).model_dump()


def _draft_rows(s, *, box, owner, workspace_id, agent_id, team_revision_id, context_revision, source_handles):
    """Chief can inspect its own completed assignments; a recipient gets its
    Chief's saved origin only. Siblings cannot scan each other's private work."""
    assignments = list(s.scalars(select(WorkspaceHandoff).where(
        WorkspaceHandoff.box_id == box,
        WorkspaceHandoff.owner_id == owner,
        WorkspaceHandoff.workspace_id == workspace_id,
        WorkspaceHandoff.team_revision_id == team_revision_id,
        WorkspaceHandoff.context_revision <= context_revision,
        (WorkspaceHandoff.issuer_agent_id == agent_id) | (WorkspaceHandoff.recipient_agent_id == agent_id),
    ).order_by(WorkspaceHandoff.created_at.desc(), WorkspaceHandoff.id).limit(13)))
    if len(assignments) > 12:
        raise ws.WorkspaceError("agent_tool_selection_too_large", 422)
    rows = {}
    for assignment in assignments:
        if assignment.recipient_agent_id == agent_id:
            ids = [assignment.origin_entry_id]
        else:
            ids = list(s.scalars(select(WorkspaceHandoffAttempt.result_entry_id).where(
                WorkspaceHandoffAttempt.handoff_id == assignment.id,
                WorkspaceHandoffAttempt.status == "completed",
            ).order_by(WorkspaceHandoffAttempt.number.desc()).limit(1)))
        for entry_id in ids:
            entry = s.get(WorkspaceEntry, entry_id, populate_existing=True)
            reply = s.get(WorkspaceReply, entry_id, populate_existing=True)
            expected_agent = assignment.issuer_agent_id if assignment.recipient_agent_id == agent_id else assignment.recipient_agent_id
            if not entry or not reply or (
                entry.workspace_id != workspace_id or entry.box_id != box
                or entry.revision > context_revision or reply.workspace_id != workspace_id
                or reply.box_id != box or reply.owner_id != owner or reply.agent_id != expected_agent
                or reply.agent_id == agent_id or reply.team_revision_id != team_revision_id
            ):
                continue
            admission = s.scalar(select(ModelWorkAdmission).where(
                ModelWorkAdmission.workspace_id == workspace_id,
                ModelWorkAdmission.box_id == box,
                ModelWorkAdmission.owner_id == owner,
                ModelWorkAdmission.agent_id == expected_agent,
                ModelWorkAdmission.request_entry_id == entry.id,
                ModelWorkAdmission.result_entry_id == entry.id,
                ModelWorkAdmission.state == "completed",
            ).execution_options(populate_existing=True))
            if not admission or admission.team_revision_id != team_revision_id or (
                work.digest(admission.prepared_envelope) != admission.envelope_sha256
                or admission.prepared_envelope.get("contract") != admission.envelope_contract
            ):
                continue
            try:
                prior = _context(admission.prepared_envelope["context"])
                selected = {(p["entry_id"], p["revision"], p["sha256"]) for p in source_handles}
                prior_sources = {(p.entry_id, p.revision, _content_hash(p.content)) for p in prior.sources}
                if not prior_sources <= selected or work.source_digest(prior) != admission.source_sha256:
                    continue
            except (ValueError, TypeError, KeyError):
                continue
            if len(reply.content) > MAX_CONTENT_CHARS:
                raise ws.WorkspaceError("agent_tool_selection_too_large", 422)
            rows[entry.id] = (entry, reply)
    return list(rows.values())


def prepare_tool_selection(
    s: Session, *, box: str, owner: str, workspace_id: str, agent_id: str,
    team_revision_id: str, context_revision: int, settings: dict, context: BotContext,
):
    """Freeze metadata before model dispatch; source contents stay in the saved
    context. No new work, connector consent or role capability is created."""
    if context.workspace_id != workspace_id or context.context_revision != context_revision or agent_id == owner:
        raise ws.WorkspaceError("agent_tool_scope_invalid", 422)
    source_rows = [SourceHandle(entry_id=p.entry_id, revision=p.revision,
        sha256=_content_hash(p.content), label=p.label, kind=p.kind).model_dump() for p in context.sources]
    if len(source_rows) > 12 or any(len(p.content) > MAX_CONTENT_CHARS for p in context.sources):
        raise ws.WorkspaceError("agent_tool_selection_too_large", 422)
    draft_rows = []
    for entry, reply in _draft_rows(s, box=box, owner=owner, workspace_id=workspace_id,
        agent_id=agent_id, team_revision_id=team_revision_id, context_revision=context_revision,
        source_handles=source_rows):
        draft_rows.append(DraftHandle(entry_id=entry.id, revision=entry.revision,
            sha256=_content_hash(reply.content), agent_id=reply.agent_id, role=reply.role,
            label=reply.agent_name).model_dump())
    status_rows = []
    if settings.get("role") == "chief" and supports_skill(settings, "work_status"):
        snapshot = work.project_workspace(s, ws.read(s, box, owner, workspace_id))
        for row in operations.linked(s, box, owner, workspace_id, snapshot, settings):
            if row["kind"] in operations.KINDS and row["record_id"] and row["evidence"]["commitment"]:
                status_rows.append({"kind": row["kind"], "record_id": row["record_id"],
                    "commitment": row["evidence"]["commitment"]})
    return _selection(source_rows, draft_rows, status_rows)


class AgentToolExecutor:
    """One scoped server-side reader. No model-supplied identity or HTTP client."""

    def __init__(self, session: Session, claimed: work.ModelClaim, *,
        reauthenticate: Callable[[], None] | None = None,
        clock: Callable[[], datetime] | None = None):
        self.session, self.claimed = session, claimed
        self.reauthenticate, self.clock = reauthenticate, clock

    def _guard(self):
        s, claimed = self.session, self.claimed
        if not work.team.runtime_settings.workspace_agent_tools_enabled:
            raise ws.WorkspaceError("agent_tools_paused", 503)
        if not isinstance(claimed, work.ModelClaim) or work.digest(claimed.envelope) != claimed.envelope_sha256:
            raise ws.WorkspaceError("agent_tool_admission_invalid", 403)
        if self.reauthenticate:
            self.reauthenticate()
        row = s.scalar(select(ModelWorkAdmission).where(
            ModelWorkAdmission.id == claimed.admission_id,
            ModelWorkAdmission.box_id == claimed.box,
            ModelWorkAdmission.owner_id == claimed.owner,
            ModelWorkAdmission.workspace_id == claimed.workspace_id,
        ).execution_options(populate_existing=True))
        if not row or row.state != "running" or row.dispatch_id != claimed.dispatch_id or (
            row.envelope_sha256 != claimed.envelope_sha256
            or work.digest(row.prepared_envelope) != claimed.envelope_sha256
            or row.prepared_envelope != claimed.envelope
            or work.effective_state(row, work.now(s, self.clock)) != "running"
            or row.agent_id == row.owner_id
            or row.envelope_contract != "cosmas-gpt41-prepared.v5"
            or row.prepared_envelope.get("contract") != "cosmas-gpt41-prepared.v5"
        ):
            raise ws.WorkspaceError("agent_tool_admission_invalid", 403)
        work.read_workspace(s, claimed.box, claimed.owner, claimed.workspace_id, row.external_identity_id)
        _, version, bot, settings = work._current_input(s, row)
        if bot.agent_id != row.agent_id or version.id != row.team_revision_id:
            raise ws.WorkspaceError("agent_tool_authority_changed", 403)
        try:
            context = _context(row.prepared_envelope["context"])
            selection = ToolSelection.model_validate(row.prepared_envelope["tool_selection"])
            value = selection.model_dump()
            commitment = value.pop("sha256")
            if commitment != work.digest(value) or context.workspace_id != claimed.workspace_id or (
                work.source_digest(context) != row.source_sha256
                or [p.model_dump() for p in selection.sources] != [
                    SourceHandle(entry_id=p.entry_id, revision=p.revision, sha256=_content_hash(p.content),
                        label=p.label, kind=p.kind).model_dump() for p in context.sources
                ]
            ):
                raise ValueError("invalid selection")
        except (ValueError, TypeError, KeyError):
            raise ws.WorkspaceError("agent_tool_selection_invalid", 403) from None
        return row, context, selection, settings

    def execute(self, request: AgentToolRequest | dict):
        try:
            value = request.model_dump() if isinstance(request, BaseModel) else request
            if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > MAX_REQUEST_BYTES:
                raise ValueError("oversized request")
            checked = REQUEST_ADAPTER.validate_python(value)
        except (ValidationError, ValueError, TypeError, RecursionError):
            raise ws.WorkspaceError("agent_tool_request_invalid", 422) from None
        row, context, selection, settings = self._guard()
        if isinstance(checked, ListSelectedSources):
            data = selection.model_dump(exclude={"contract", "sha256"})
        elif isinstance(checked, ReadSelectedSource):
            source = next((p for p in context.sources if p.entry_id == checked.entry_id
                and p.revision == checked.revision and _content_hash(p.content) == checked.sha256), None)
            if not source:
                raise ws.WorkspaceError("agent_tool_source_unavailable", 404)
            data = {**next(p.model_dump() for p in selection.sources if p.entry_id == source.entry_id),
                "content": source.content}
        elif isinstance(checked, ReadSavedTeammateDraft):
            handle = next((p for p in selection.teammate_drafts if p.entry_id == checked.entry_id
                and p.revision == checked.revision and p.sha256 == checked.sha256), None)
            if not handle:
                raise ws.WorkspaceError("agent_tool_draft_unavailable", 404)
            candidates = _draft_rows(self.session, box=row.box_id, owner=row.owner_id,
                workspace_id=row.workspace_id, agent_id=row.agent_id, team_revision_id=row.team_revision_id,
                context_revision=row.context_revision, source_handles=[p.model_dump() for p in selection.sources])
            selected = next(((entry, reply) for entry, reply in candidates if entry.id == handle.entry_id
                and entry.revision == handle.revision and reply.agent_id == handle.agent_id
                and reply.role == handle.role and _content_hash(reply.content) == handle.sha256), None)
            if not selected:
                raise ws.WorkspaceError("agent_tool_source_changed", 409)
            data = {**handle.model_dump(), "content": selected[1].content,
                "completion_kind": "saved_private_draft", "external_work_established": False}
        else:
            assert isinstance(checked, ReadCurrentOperationStatus)
            if not any(p.kind == checked.kind and p.record_id == checked.record_id
                and p.commitment == checked.commitment for p in selection.operations):
                raise ws.WorkspaceError("agent_tool_operation_unavailable", 404)
            if settings.get("role") != "chief" or not supports_skill(settings, "work_status"):
                raise ws.WorkspaceError("agent_tool_authority_changed", 403)
            data = operations.read(self.session, row.box_id, row.owner_id, row.workspace_id,
                kind=checked.kind, record_id=checked.record_id, now=work.now(self.session, self.clock))
            if data["evidence"]["commitment"] != checked.commitment:
                raise ws.WorkspaceError("agent_tool_source_changed", 409)
        self._guard()  # Revoked identity, changed source or expired lease withholds the result.
        receipt = {"contract": "cosmas-agent-tool-receipt.v1", "tool": checked.tool,
            "admission_id": row.id, "dispatch_id": row.dispatch_id, "workspace_id": row.workspace_id,
            "actor_agent_id": row.agent_id, "initiated_by_human_id": row.owner_id,
            "envelope_sha256": row.envelope_sha256, "selection_sha256": selection.sha256,
            "request_sha256": work.digest(checked.model_dump()), "result_sha256": work.digest(data)}
        receipt["sha256"] = work.digest(receipt)
        result = {"contract": "cosmas-agent-tool-result.v1", "tool": checked.tool, "data": data, "receipt": receipt}
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > MAX_RESPONSE_BYTES:
            raise ws.WorkspaceError("agent_tool_response_too_large", 422)
        return result
