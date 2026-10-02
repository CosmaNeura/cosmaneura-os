"""Private text-draft delivery. No external tool, approval or shared work queue."""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from cosmas_os.application import handoff_briefs
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings as runtime_settings
from cosmas_os.models import (
    AuditEvent,
    ModelWorkAdmission,
    ProviderTeamRevision,
    WorkspaceEntry,
    WorkspaceHandoff,
    WorkspaceHandoffAttempt,
)
from cosmas_os.ports.bot_capabilities import supports_skill


def available_roles(s, box, owner, version, chief_settings):
    if any(team.blocked(chief_settings, key) for key in ("private_draft_handoff", "model_answer")):
        return ()
    roles = []
    for candidate in version.configuration["bots"]:
        role = team.bot_address(candidate)
        if candidate["role"] == "chief" or not candidate["enabled"]:
            continue
        if any(team.blocked(candidate, key) for key in ("private_draft_handoff", "model_answer")):
            continue
        # Chief sees work status and may incorporate it even without citations.
        if not supports_skill(candidate, "work_status") or (
            (chief_settings["include_notebook"] or chief_settings["include_evidence"])
            and not supports_skill(candidate, "saved_context")
        ):
            continue
        # A generated brief can contain facts from Chief's input, not only cited facts.
        # Do not route it to a bot whose settings exclude any of that source class.
        if any(
            chief_settings[key] and not candidate[key]
            for key in ("include_notebook", "include_evidence")
        ):
            continue
        try:
            team.active_bot(s, box, owner, role, version.revision)
        except ws.WorkspaceError:
            continue
        roles.append(role)
    return tuple(roles)


def model_usage_count(s, wid):
    from cosmas_os.application.model_work import workspace_units

    return workspace_units(s, wid)


def _audit(s, attempt, outcome):
    s.add(
        AuditEvent(
            box_id=attempt.box_id,
            aggregate_type="workspace_handoff",
            aggregate_id=attempt.handoff_id,
            event_type="workspace.handoff_" + outcome,
            initiated_by_principal_id=attempt.owner_id,
            outcome=outcome,
            detail={"attempt_id": attempt.id, "attempt": attempt.number},
        )
    )


def read(s, w, revision):
    handoffs = s.scalars(
        select(WorkspaceHandoff)
        .join(WorkspaceEntry, WorkspaceEntry.id == WorkspaceHandoff.origin_entry_id)
        .where(
            WorkspaceHandoff.workspace_id == w.id,
            WorkspaceHandoff.box_id == w.box_id,
            WorkspaceHandoff.owner_id == w.owner_id,
            WorkspaceEntry.revision <= revision,
        )
        .order_by(
            WorkspaceEntry.revision,
            WorkspaceHandoff.recipient_role,
            WorkspaceHandoff.recipient_agent_id,
        )
    )
    output = []
    from cosmas_os.application import handoff_review, handoff_revision, model_work

    as_of = model_work.now(s)
    for handoff in handoffs:
        attempts = list(
            s.scalars(
                select(WorkspaceHandoffAttempt)
                .where(WorkspaceHandoffAttempt.handoff_id == handoff.id)
                .order_by(WorkspaceHandoffAttempt.number)
            )
        )
        latest = attempts[-1]
        states = {a.id: model_work.attempt_state(s, a, as_of) for a in attempts}
        evidence = handoff_briefs.projection(s, handoff, states[latest.id][2])
        reviewed = handoff_review.stored_review_for(s, w, handoff, latest)
        brief = handoff.brief
        related_admissions = [state[2] for state in states.values() if state[2] is not None]
        origin_admission = s.scalar(select(ModelWorkAdmission).where(
            ModelWorkAdmission.request_entry_id == handoff.origin_entry_id,
            ModelWorkAdmission.workspace_id == w.id,
            ModelWorkAdmission.box_id == w.box_id,
            ModelWorkAdmission.owner_id == w.owner_id,
        ))
        if origin_admission is not None:
            related_admissions.append(origin_admission)
        source_unavailable = False
        for admission in related_admissions:
            from cosmas_os.adapters.gpt41 import _context
            from cosmas_os.application import google_message

            for passage in _context(admission.prepared_envelope["context"]).sources:
                original = s.get(WorkspaceEntry, passage.entry_id)
                if original is not None and original.kind == "google_message":
                    try:
                        google_message.validate_selected_source(s, w, original.id)
                    except ws.WorkspaceError:
                        brief = "The selected email is unavailable. Check its account access before using this draft."
                        evidence.pop("task_brief", None)
                        evidence.pop("completion_evidence", None)
                        evidence["task_brief_unavailable"] = True
                        source_unavailable = True
                        break
        revision_metadata = handoff_revision.revision_for(s, w, handoff)
        if source_unavailable:
            if reviewed:
                reviewed = {**reviewed, "feedback": "Email access must be checked before viewing this feedback."}
            if "revision_request" in revision_metadata:
                revision_metadata["revision_request"] = {**revision_metadata["revision_request"],
                    "feedback": "Email access must be checked before viewing this feedback."}
        output.append(
            {
                "id": handoff.id,
                "origin_entry_id": handoff.origin_entry_id,
                "recipient_role": handoff.recipient_role,
                "recipient_agent_id": handoff.recipient_agent_id,
                "recipient_key": team.address_for_agent(
                    s, w.box_id, w.owner_id, handoff.recipient_agent_id
                ),
                "recipient_name": handoff.recipient_name,
                "brief": brief,
                "context_revision": handoff.context_revision,
                "status": states[latest.id][0],
                "attempt_id": latest.id,
                "attempt_count": latest.number,
                "result_entry_id": latest.result_entry_id,
                "error_code": states[latest.id][1],
                **evidence,
                "result_sha256": evidence.get("completion_evidence", {}).get("sha256"),
                "review": reviewed,
                "review_status": handoff_review.review_status_for(s, w, handoff, latest),
                **revision_metadata,
                "attempts": [
                    {
                        "id": a.id,
                        "number": a.number,
                        "status": states[a.id][0],
                        "error_code": states[a.id][1],
                        "created_at": a.created_at.isoformat(),
                        "started_at": a.started_at.isoformat() if a.started_at else None,
                        "completed_at": a.completed_at.isoformat() if a.completed_at else None,
                    }
                    for a in attempts
                ],
            }
        )
    return output


def _check_context(s, w, handoff):
    version = s.get(ProviderTeamRevision, handoff.team_revision_id)
    _, chief, chief_settings = team.active_bot(s, w.box_id, w.owner_id, "chief", version.revision)
    address = team.address_for_agent(s, w.box_id, w.owner_id, handoff.recipient_agent_id)
    _, bot, settings = team.active_bot(s, w.box_id, w.owner_id, address, version.revision)
    if any(
        team.blocked(config, key)
        for config in (chief_settings, settings)
        for key in ("private_draft_handoff", "model_answer")
    ):
        raise ws.WorkspaceError("bot_capability_restricted")
    if chief.agent_id != handoff.issuer_agent_id or bot.agent_id != handoff.recipient_agent_id:
        raise ws.WorkspaceError("handoff_context_changed")
    if settings["role"] != handoff.recipient_role or address not in available_roles(
        s, w.box_id, w.owner_id, version, chief_settings
    ):
        raise ws.WorkspaceError("handoff_context_changed")
    if w.revision >= 500:
        raise ws.WorkspaceError("workspace_history_limit")
    return version, bot, settings


def retry(s, box, owner, wid, hid, *, expected, previous_attempt, key, **options):
    from cosmas_os.application.model_work import reserve_retry

    return reserve_retry(
        s,
        box,
        owner,
        wid,
        hid,
        expected=expected,
        previous_attempt=previous_attempt,
        key=key,
        **options,
    )


def _terminal(s, attempt, status, *, error=None, result=None):
    attempt.status, attempt.error_code, attempt.result_entry_id = status, error, result
    attempt.completed_at = datetime.now(UTC)
    _audit(s, attempt, status)


def recover_interrupted(s, *, now=None):
    from cosmas_os.application.model_work import recover_expired

    return recover_expired(s, clock=(lambda: now) if now is not None else None)


def process_next(factory):
    if not runtime_settings.workspace_llm_available:
        return False
    from cosmas_os.application.model_work import process_next as admitted_next

    return admitted_next(factory)


async def run_worker(factory, stop, *, progress=None):
    async def lane():
        while not stop.is_set():
            worked = False
            try:
                worked = await asyncio.to_thread(process_next, factory)
            except Exception:
                # Private failure details stay out of worker health.
                if progress is not None:
                    progress.failed()
            else:
                if progress is not None:
                    progress.succeeded()
            if worked:
                continue  # No artificial dwell between already-admitted jobs.
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except TimeoutError:
                pass

    try:
        # Claims commit before model I/O. Existing owner locks, leases, source
        # checks and single-dispatch records fence all three independent lanes.
        await asyncio.gather(*(lane() for _ in range(3)))
    finally:
        if progress is not None:
            progress.stopped()
