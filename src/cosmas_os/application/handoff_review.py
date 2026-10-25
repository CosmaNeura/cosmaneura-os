"""Human review of private teammate results; never model dispatch or external approval."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from sqlalchemy import select

from cosmas_os.adapters.gpt41 import _context
from cosmas_os.application import clinical_note_share, handoff_briefs, handoffs, model_work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import (
    ModelWorkAdmission,
    ProviderTeamRevision,
    WorkspaceEntry,
    WorkspaceHandoff,
    WorkspaceHandoffAttempt,
    WorkspaceHandoffReview,
    WorkspaceHandoffRevision,
    WorkspaceReply,
)


@dataclass(frozen=True)
class ReviewReadSnapshot:
    """Complete page-scoped immutable review inputs; never a command authority.

    Missing referenced records fail the normal validity checks. No preloaded
    path falls back to SQL or grants access to selected connector sources.
    """

    team: team.TeamReadSnapshot
    workspace_ids: frozenset[str]
    clinical: clinical_note_share.ClinicalSourceSnapshot
    replies: dict[str, WorkspaceReply]
    handoffs: dict[str, WorkspaceHandoff]
    attempts: tuple[WorkspaceHandoffAttempt, ...]
    reviews: tuple[WorkspaceHandoffReview, ...]
    revisions: tuple[WorkspaceHandoffRevision, ...]
    admissions: dict[str, ModelWorkAdmission]

    def __post_init__(self):
        owned = (*self.clinical.notes.values(), *self.replies.values(), *self.handoffs.values(),
            *self.attempts, *self.reviews, *self.revisions, *self.admissions.values())
        if (any(row.workspace_id not in self.workspace_ids or (row.box_id, row.owner_id) != (self.team.box, self.team.owner) for row in owned)
                or any(row.workspace_id not in self.workspace_ids or (row.box_id, row.actor_id) != (self.team.box, self.team.owner) for row in self.clinical.entries.values())
                or any(key != row.id for key, row in self.clinical.entries.items())
                or any(key != row.id for key, row in self.clinical.notes.items())
                or any(key != row.entry_id for key, row in self.replies.items())
                or any(key != row.id for key, row in self.handoffs.items())
                or any(key != row.handoff_attempt_id for key, row in self.admissions.items())):
            raise ws.WorkspaceError('handoff_snapshot_unavailable', 503)

    def require_scope(self, w):
        self.team.require_scope(w.box_id, w.owner_id)
        if w.id not in self.workspace_ids or any(entry.workspace_id == w.id and entry.kind in
                {'google_message', 'google_calendar', 'efax_inbound_source', 'fax_inbound_source', 'ehr_read_source', 'calendar_import_source'}
                for entry in self.clinical.entries.values()):
            raise ws.WorkspaceError('handoff_snapshot_unavailable', 503)

    def latest_attempt(self, handoff_id):
        return max((attempt for attempt in self.attempts if attempt.handoff_id == handoff_id),
            key=lambda attempt: attempt.number, default=None)

    def review_record(self, w, handoff):
        return max((review for review in self.reviews if review.handoff_id == handoff.id
            and (review.workspace_id, review.box_id, review.owner_id) == (w.id, w.box_id, w.owner_id)
            and review.workspace_revision <= w.revision), key=lambda review: review.workspace_revision, default=None)

    def revision_link(self, w, *, handoff_id=None, review_id=None):
        return next((link for link in self.revisions if (link.workspace_id, link.box_id, link.owner_id) == (w.id, w.box_id, w.owner_id)
            and (link.revision_handoff_id == handoff_id if handoff_id is not None else link.review_id == review_id)), None)


def _hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _selected_versions(s, w, settings, *, snapshot: ReviewReadSnapshot | None = None):
    from cosmas_os.ports.bot_capabilities import supports_skill

    if not supports_skill(settings, "saved_context"):
        return []
    entries = sorted((entry for entry in snapshot.clinical.entries.values()
        if (entry.workspace_id, entry.box_id, entry.actor_id) == (w.id, w.box_id, w.owner_id)
        and entry.revision <= w.revision and entry.kind in {"scratchpad", "evidence", "synthetic_source"}),
        key=lambda entry: entry.revision) if snapshot is not None else list(
        s.scalars(
            select(WorkspaceEntry)
            .where(
                WorkspaceEntry.workspace_id == w.id,
                WorkspaceEntry.box_id == w.box_id,
                WorkspaceEntry.actor_id == w.owner_id,
                WorkspaceEntry.revision <= w.revision,
                WorkspaceEntry.kind.in_(("scratchpad", "evidence", "synthetic_source")),
            )
            .order_by(WorkspaceEntry.revision)
        )
    )
    selected = (
        [e for e in entries if e.kind == "scratchpad"][-1:] if settings["include_notebook"] else []
    )
    if settings["include_evidence"]:
        selected += [e for e in entries if e.kind in {"evidence", "synthetic_source"}]
    versions = [
        {
            "entry_id": e.id,
            "revision": e.revision,
            "label": e.source_label or "Your jotted notes",
            "kind": e.kind,
            "sha256": _hash(e.content),
        }
        for e in selected
    ]
    from cosmas_os.application import selected_connector_sources
    from cosmas_os.application.model_work import _selected_connector_passages

    additional = (clinical_note_share.selected(s, w, settings, snapshot=snapshot.clinical) if w.appointment_id is not None else ()) if snapshot is not None else _selected_connector_passages(s, w, settings)
    for source in additional:
        entry = snapshot.clinical.entries.get(source.entry_id) if snapshot is not None else s.get(WorkspaceEntry, source.entry_id)
        if clinical_note_share.is_shared_snapshot(entry):
            clinical_note_share.validate_current_source(s, w, source.entry_id, snapshot=snapshot.clinical if snapshot is not None else None)
        else:
            selected_connector_sources.validate_selected_source(s, w, source.entry_id)
        versions.append({"entry_id": source.entry_id, "revision": source.revision,
                         "label": source.label, "kind": "evidence", "sha256": _hash(source.content)})
    if additional:
        versions = [v for v in versions if v["kind"] == "scratchpad"] + sorted(
            [v for v in versions if v["kind"] != "scratchpad"], key=lambda v: v["revision"])
    return versions


def _current_settings(s, w, handoff, *, snapshot: ReviewReadSnapshot | None = None):
    """Current human/team authority; reading a receipt does not consume history capacity."""
    version = snapshot.team.versions.get(handoff.team_revision_id) if snapshot is not None else s.get(ProviderTeamRevision, handoff.team_revision_id)
    if version is None:
        raise ws.WorkspaceError("handoff_context_changed")
    team_snapshot = snapshot.team if snapshot is not None else None
    _, chief, chief_settings = team.active_bot(s, w.box_id, w.owner_id, "chief", version.revision, snapshot=team_snapshot)
    address = team.address_for_agent(s, w.box_id, w.owner_id, handoff.recipient_agent_id, snapshot=team_snapshot)
    _, bot, settings = team.active_bot(s, w.box_id, w.owner_id, address, version.revision, snapshot=team_snapshot)
    if any(
        team.blocked(config, key)
        for config in (chief_settings, settings)
        for key in ("private_draft_handoff", "model_answer")
    ):
        raise ws.WorkspaceError("bot_capability_restricted")
    if (
        chief.agent_id != handoff.issuer_agent_id
        or bot.agent_id != handoff.recipient_agent_id
        or settings["role"] != handoff.recipient_role
        or address not in handoffs.available_roles(s, w.box_id, w.owner_id, version, chief_settings, snapshot=team_snapshot)
    ):
        raise ws.WorkspaceError("handoff_context_changed")
    return version, settings


def _binding(s, w, handoff, attempt, *, current=True, snapshot: ReviewReadSnapshot | None = None):
    """Verify saved intent/output and the current versions of every admitted source."""
    if (handoff.workspace_id, handoff.box_id, handoff.owner_id) != (w.id, w.box_id, w.owner_id):
        raise ws.WorkspaceError("handoff_unavailable", 404)
    from cosmas_os.application.handoff_revision import revision_depth

    if snapshot is not None:
        snapshot.require_scope(w)
    revision_depth(s, w, handoff.id, snapshot=snapshot)
    version = snapshot.team.versions.get(handoff.team_revision_id) if snapshot is not None else s.get(ProviderTeamRevision, handoff.team_revision_id)
    settings = None
    if current:
        version, settings = _current_settings(s, w, handoff, snapshot=snapshot)
    latest = snapshot.latest_attempt(handoff.id) if snapshot is not None else s.scalar(
        select(WorkspaceHandoffAttempt)
        .where(
            WorkspaceHandoffAttempt.handoff_id == handoff.id,
        )
        .order_by(WorkspaceHandoffAttempt.number.desc())
        .limit(1)
    )
    if (
        latest is None
        or latest.id != attempt.id
        or attempt.handoff_id != handoff.id
        or attempt.status != "completed"
        or attempt.result_entry_id is None
    ):
        raise ws.WorkspaceError("handoff_result_unavailable")
    row = snapshot.admissions.get(attempt.id) if snapshot is not None else s.scalar(
        select(ModelWorkAdmission).where(
            ModelWorkAdmission.handoff_attempt_id == attempt.id,
            ModelWorkAdmission.workspace_id == w.id,
            ModelWorkAdmission.box_id == w.box_id,
            ModelWorkAdmission.owner_id == w.owner_id,
        )
    )
    reply = snapshot.replies.get(attempt.result_entry_id) if snapshot is not None else s.get(WorkspaceReply, attempt.result_entry_id)
    entry = snapshot.clinical.entries.get(attempt.result_entry_id) if snapshot is not None else s.get(WorkspaceEntry, attempt.result_entry_id)
    try:
        if (
            row is None
            or row.kind != "private_handoff"
            or row.state != "completed"
            or row.result_entry_id != attempt.result_entry_id
            or row.request_entry_id != attempt.result_entry_id
            or row.agent_id != handoff.recipient_agent_id
            or row.team_revision_id != handoff.team_revision_id
            or row.envelope_contract != row.prepared_envelope.get("contract")
            or row.envelope_sha256 != model_work.digest(row.prepared_envelope)
            or reply is None
            or entry is None
            or version is None
            or (
                reply.workspace_id,
                reply.box_id,
                reply.owner_id,
                reply.agent_id,
                reply.team_revision_id,
                reply.role,
            )
            != (
                w.id,
                w.box_id,
                w.owner_id,
                handoff.recipient_agent_id,
                handoff.team_revision_id,
                handoff.recipient_role,
            )
            or (entry.workspace_id, entry.box_id, entry.actor_id, entry.kind)
            != (w.id, w.box_id, w.owner_id, "handoff_result")
        ):
            raise ValueError("result binding")
        context = _context(row.prepared_envelope["context"])
        task = row.request_body["task_brief"]
        handoff_briefs.validate(
            task, context, goal=handoff.brief, origin_id=handoff.origin_entry_id,
            prepared_contract=row.envelope_contract,
        )
        origin = snapshot.clinical.entries.get(handoff.origin_entry_id) if snapshot is not None else s.get(WorkspaceEntry, handoff.origin_entry_id)
        expected_question = handoff_briefs.question(task)
        if "revision_request" in row.request_body:
            from cosmas_os.application.handoff_revision import revision_question

            expected_question += revision_question(
                s, w, row.request_body["revision_request"], current=current, snapshot=snapshot
            )
        if (
            origin is None
            or task["depends_on"] != {"entry_id": origin.id, "revision": origin.revision}
            or context.workspace_id != w.id
            or context.role != handoff.recipient_role
            or context.question != expected_question
            or len(expected_question) > 12000
            or context.context_revision != reply.context_revision
            or row.source_sha256 != model_work.source_digest(context)
        ):
            raise ValueError("source intent")
        historical_settings = next(
            bot
            for bot in version.configuration["bots"]
            if team.bot_address(bot) == row.request_body["role"]
        )
        if historical_settings["role"] != handoff.recipient_role:
            raise ValueError("recipient address")
        versions = task["source_versions"]
        # Stored receipts still bind exact immutable passages, while a later selected
        # source is allowed to make that receipt historical rather than unreadable.
        for source in versions:
            source_entry = snapshot.clinical.entries.get(source["entry_id"]) if snapshot is not None else s.get(WorkspaceEntry, source["entry_id"])
            source_kind = source_entry.kind if source_entry is not None else None
            from cosmas_os.application import clinical_note_share, selected_connector_sources

            if clinical_note_share.is_shared_snapshot(source_entry):
                try:
                    source_entry = clinical_note_share.historical_source(s, w, source["entry_id"], snapshot=snapshot.clinical if snapshot is not None else None)
                except ws.WorkspaceError:
                    raise ValueError("saved clinical source binding") from None
                if current:
                    try:
                        clinical_note_share.validate_current_source(s, w, source["entry_id"], snapshot=snapshot.clinical if snapshot is not None else None)
                    except ws.WorkspaceError:
                        raise ws.WorkspaceError("handoff_sources_changed") from None
                source_kind = "evidence"
            elif selected_connector_sources.is_selected_connector(source_entry):

                source_entry = selected_connector_sources.historical_source(s, w, source["entry_id"])
                if current:
                    selected_connector_sources.validate_selected_source(s, w, source["entry_id"])
                source_kind = "evidence"
            if source_entry is None or (
                source_entry.workspace_id,
                source_entry.box_id,
                source_entry.actor_id,
                source_entry.revision,
                source_kind,
                source_entry.source_label or "Your jotted notes",
                _hash(source_entry.content),
            ) != (
                w.id,
                w.box_id,
                w.owner_id,
                source["revision"],
                source["kind"],
                source["label"],
                source["sha256"],
            ):
                raise ValueError("saved source binding")
        if current and versions != _selected_versions(s, w, settings, snapshot=snapshot):
            raise ws.WorkspaceError("handoff_sources_changed")
        by_id = {source["entry_id"]: source for source in versions}
        if any(
            cited["entry_id"] not in by_id
            or any(
                cited[field] != by_id[cited["entry_id"]][field]
                for field in ("revision", "label", "kind")
            )
            for cited in reply.citations
        ):
            raise ValueError("result citations")
        return row, reply, versions
    except (ValueError, TypeError, KeyError, StopIteration, AttributeError):
        raise ws.WorkspaceError("handoff_result_unverifiable") from None


def _record(s, w, handoff, *, snapshot: ReviewReadSnapshot | None = None):
    return snapshot.review_record(w, handoff) if snapshot is not None else s.scalar(
        select(WorkspaceHandoffReview)
        .where(
            WorkspaceHandoffReview.handoff_id == handoff.id,
            WorkspaceHandoffReview.workspace_id == w.id,
            WorkspaceHandoffReview.box_id == w.box_id,
            WorkspaceHandoffReview.owner_id == w.owner_id,
            WorkspaceHandoffReview.workspace_revision <= w.revision,
        )
        .order_by(WorkspaceHandoffReview.workspace_revision.desc())
        .limit(1)
    )


def _review_for(s, w, handoff, attempt, *, current, snapshot: ReviewReadSnapshot | None = None):
    """Verify provenance separately from whether this decision authorizes current work."""
    review = _record(s, w, handoff, snapshot=snapshot)
    if review is None or review.attempt_id != attempt.id:
        return None
    try:
        row, reply, versions = _binding(s, w, handoff, attempt, current=current, snapshot=snapshot)
        if (
            review.result_entry_id != attempt.result_entry_id
            or review.agent_id != reply.agent_id
            or review.result_sha256 != _hash(reply.content)
            or review.source_sha256 != row.source_sha256
            or review.source_versions != versions
        ):
            return None
    except ws.WorkspaceError:
        return None
    from cosmas_os.application.handoff_revision import revision_handoff_for_review

    return {
        "id": review.id,
        "attempt_id": review.attempt_id,
        "result_entry_id": review.result_entry_id,
        "result_sha256": review.result_sha256,
        "decision": review.decision,
        "feedback": review.feedback,
        "created_at": review.created_at.isoformat(),
        **revision_handoff_for_review(s, w, review.id, snapshot=snapshot),
    }


def result_recovery_digest(s, w, handoff, attempt):
    """Identify an exact historical result without granting current source access."""
    try:
        _, reply, _ = _binding(s, w, handoff, attempt, current=False)
    except ws.WorkspaceError:
        return None
    return _hash(reply.content)


def stored_review_for(s, w, handoff, attempt, *, snapshot: ReviewReadSnapshot | None = None):
    """Exact immutable command receipt for recovery; never current-work authorization."""
    return _review_for(s, w, handoff, attempt, current=False, snapshot=snapshot)


def review_for(s, w, handoff, attempt, *, snapshot: ReviewReadSnapshot | None = None):
    """Return a decision only while reviewed source and team authority remain current."""
    return _review_for(s, w, handoff, attempt, current=True, snapshot=snapshot)


def review_status_for(s, w, handoff, attempt):
    current = review_for(s, w, handoff, attempt)
    return "current" if current else "stale" if _record(s, w, handoff) else "not_reviewed"


def _command_receipt(s, w, review):
    """A public command commitment confirms history even when output is withheld."""
    workspace = ws.read(s, w.box_id, w.owner_id, w.id)
    entry = next(e for e in workspace["entries"] if e["id"] == review.result_entry_id)
    from cosmas_os.application.selected_connector_sources import projection_unavailable

    return {
        "entry_revision": review.workspace_revision,
        "workspace": workspace,
        "request_sha256": payload_hash({
            "workspace_id": w.id, "handoff_id": review.handoff_id,
            "expected_revision": review.expected_revision,
            "idempotency_key": review.idempotency_key, "attempt_id": review.attempt_id,
            "result_entry_id": review.result_entry_id, "result_sha256": review.result_sha256,
            "decision": review.decision, "feedback": review.feedback,
        }),
        "feedback_withheld": projection_unavailable(entry),
    }


def review(
    s,
    box,
    actor,
    wid,
    hid,
    *,
    expected,
    key,
    attempt_id,
    result_entry_id,
    result_sha256,
    decision,
    feedback="",
    external_identity_id=None,
    reauthenticate=None,
):
    s.rollback()
    model_work.lock_owner(s, box, actor)
    if reauthenticate:
        reauthenticate()
    model_work._identity(s, box, actor, external_identity_id)
    w = ws._workspace(s, box, actor, wid, writing=True)
    if (
        type(expected) is not int
        or expected < 1
        or not isinstance(key, str)
        or re.fullmatch(r"[A-Za-z0-9:_-]{8,100}", key) is None
        or decision not in {"accepted", "changes_requested"}
        or not isinstance(feedback, str)
        or len(feedback) > 2000
        or "\0" in feedback
        or decision == "changes_requested"
        and not feedback.strip()
        or not isinstance(result_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", result_sha256) is None
    ):
        raise ws.WorkspaceError("invalid_handoff_review", 422)
    request_hash = payload_hash(
        {
            "handoff_id": hid,
            "expected_revision": expected,
            "attempt_id": attempt_id,
            "result_entry_id": result_entry_id,
            "result_sha256": result_sha256,
            "decision": decision,
            "feedback": feedback,
        }
    )
    replay = s.scalar(
        select(WorkspaceHandoffReview).where(
            WorkspaceHandoffReview.workspace_id == wid,
            WorkspaceHandoffReview.idempotency_key == key,
        )
    )
    if replay and replay.request_hash != request_hash:
        raise ws.WorkspaceError("idempotency_conflict")
    handoff = s.scalar(
        select(WorkspaceHandoff).where(
            WorkspaceHandoff.id == hid,
            WorkspaceHandoff.workspace_id == wid,
            WorkspaceHandoff.box_id == box,
            WorkspaceHandoff.owner_id == actor,
        )
    )
    attempt = s.scalar(
        select(WorkspaceHandoffAttempt).where(
            WorkspaceHandoffAttempt.id == attempt_id,
            WorkspaceHandoffAttempt.handoff_id == hid,
            WorkspaceHandoffAttempt.workspace_id == wid,
            WorkspaceHandoffAttempt.box_id == box,
            WorkspaceHandoffAttempt.owner_id == actor,
        )
    )
    if handoff is None or attempt is None:
        raise ws.WorkspaceError("handoff_unavailable", 404)
    if replay:
        if stored_review_for(s, w, handoff, attempt) is None:
            raise ws.WorkspaceError("handoff_review_unverifiable")
        if reauthenticate:
            reauthenticate()
        model_work._identity(s, box, actor, external_identity_id)
        return _command_receipt(s, w, replay)
    row, reply, versions = _binding(s, w, handoff, attempt)
    if attempt.result_entry_id != result_entry_id or _hash(reply.content) != result_sha256:
        raise ws.WorkspaceError("handoff_result_changed")
    if s.scalar(
        select(WorkspaceHandoffReview.id).where(WorkspaceHandoffReview.attempt_id == attempt_id)
    ):
        raise ws.WorkspaceError("handoff_result_already_reviewed")
    if w.revision != expected:
        raise ws.WorkspaceError("workspace_revision_conflict")
    if w.revision >= 500:
        raise ws.WorkspaceError("workspace_history_limit")
    w.revision += 1
    saved = WorkspaceHandoffReview(
        workspace_id=wid,
        box_id=box,
        owner_id=actor,
        handoff_id=hid,
        attempt_id=attempt_id,
        result_entry_id=result_entry_id,
        agent_id=reply.agent_id,
        result_sha256=result_sha256,
        source_sha256=row.source_sha256,
        source_versions=versions,
        expected_revision=expected,
        workspace_revision=w.revision,
        decision=decision,
        feedback=feedback,
        idempotency_key=key,
        request_hash=request_hash,
    )
    s.add(saved)
    ws._audit(s, w, "handoff_result_reviewed")
    try:
        s.flush()
        if reauthenticate:
            reauthenticate()
        model_work._identity(s, box, actor, external_identity_id)
        ws._workspace(s, box, actor, wid, writing=True)
        s.commit()
    except Exception:
        s.rollback()
        raise
    return _command_receipt(s, w, saved)
