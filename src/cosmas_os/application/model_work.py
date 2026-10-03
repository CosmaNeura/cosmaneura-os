"""Owner-scoped admission, single dispatch and truthful model-work observations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, exists, func, or_, select

from cosmas_os.adapters.gpt41 import SUPPORTED_PREPARED_CONTRACTS as TEXT_PREPARED_CONTRACTS
from cosmas_os.adapters.gpt41 import GPT41Connector, _context
from cosmas_os.adapters.gpt41_tools import CURRENT_PREPARED_CONTRACT as TOOL_PREPARED_CONTRACT
from cosmas_os.adapters.gpt41_tools import GPT41ToolsConnector
from cosmas_os.adapters.gpt41_tools import validate_prepared as validate_tools
from cosmas_os.adapters.gpt41_tools_v6 import (
    CURRENT_PREPARED_CONTRACT as COMPACT_TOOL_PREPARED_CONTRACT,
)
from cosmas_os.adapters.gpt41_tools_v6 import GPT41CompactToolsConnector
from cosmas_os.adapters.gpt41_tools_v6 import validate_prepared as validate_compact_tools
from cosmas_os.api.model_work_schemas import (
    ENTRY_MODEL_BYTES,
    EntryModelRequest,
    HandoffRetryObservation,
    ModelRequestObservation,
    checked_response,
)
from cosmas_os.application import handoff_briefs
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.application.encounter_access import patient_visible
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import (
    AppointmentObservation,
    EncounterWorkspace,
    ExternalIdentity,
    ModelUsageObservation,
    ModelWorkAdmission,
    PatientLink,
    Principal,
    ProviderTeamRevision,
    WorkspaceEntry,
    WorkspaceHandoff,
    WorkspaceHandoffAttempt,
    WorkspaceReply,
)
from cosmas_os.ports.bot_capabilities import BotReply, ModelCallFailure
from cosmas_os.ports.task_brief import TaskRequirements

ACTIVE = {"reserved", "running"}
TERMINAL = {"completed", "failed", "unknown", "abandoned"}
TOOL_PREPARED_CONTRACTS = {TOOL_PREPARED_CONTRACT, COMPACT_TOOL_PREPARED_CONTRACT}
SUPPORTED_PREPARED_CONTRACTS = TEXT_PREPARED_CONTRACTS | TOOL_PREPARED_CONTRACTS


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def now(s, clock=None):
    value = clock() if clock else s.scalar(select(func.clock_timestamp()))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ws.WorkspaceError("model_clock_unavailable", 503)
    return value.astimezone(UTC)


def effective_state(row, as_of):
    if row.state == "reserved" and as_of >= row.reservation_expires_at:
        return "abandoned"
    if row.state == "running" and as_of >= row.lease_ends_at:
        return "unknown"
    return row.state


def lock_owner(s, box, owner, *, active=True):
    person = s.scalar(
        select(Principal)
        .where(Principal.id == owner, Principal.box_id == box, Principal.principal_type == "human")
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if person is None or active and (person.state != "active" or person.tombstoned_at is not None):
        raise ws.WorkspaceError("workspace_access_denied", 403)
    return person


def _identity(s, box, owner, external_identity_id):
    if (
        external_identity_id is not None
        and s.scalar(
            select(ExternalIdentity.id).where(
                ExternalIdentity.id == external_identity_id,
                ExternalIdentity.box_id == box,
                ExternalIdentity.principal_id == owner,
                ExternalIdentity.active.is_(True),
            )
        )
        is None
    ):
        raise ws.WorkspaceError("workspace_access_denied", 403)


def read_workspace(s, box, owner, wid, external_identity_id=None):
    """Authorization without SELECT FOR UPDATE, suitable for a read-only resolver."""
    person = s.scalar(
        select(Principal.id).where(
            Principal.id == owner,
            Principal.box_id == box,
            Principal.principal_type == "human",
            Principal.state == "active",
            Principal.tombstoned_at.is_(None),
        )
    )
    if person is None:
        raise ws.WorkspaceError("workspace_access_denied", 403)
    _identity(s, box, owner, external_identity_id)
    workspace = s.scalar(
        select(EncounterWorkspace)
        .where(
            EncounterWorkspace.id == wid,
            EncounterWorkspace.box_id == box,
            EncounterWorkspace.owner_id == owner,
        )
        .execution_options(populate_existing=True)
    )
    if workspace is None:
        raise ws.WorkspaceError("workspace_unavailable", 404)
    encounter = s.scalar(
        select(AppointmentObservation.id)
        .join(PatientLink, PatientLink.id == AppointmentObservation.patient_link_id)
        .where(
            AppointmentObservation.id == workspace.appointment_id,
            AppointmentObservation.box_id == box,
            AppointmentObservation.patient_link_id == workspace.patient_link_id,
            PatientLink.box_id == box,
            PatientLink.state == "confirmed",
            PatientLink.revoked_at.is_(None),
            patient_visible(owner),
        )
    )
    if encounter is None:
        raise ws.WorkspaceError("encounter_unavailable", 404)
    return workspace


def usage(s, box, owner, *, as_of=None, configuration=None):
    as_of = as_of or now(s)
    cutoff = as_of - timedelta(hours=24)
    recent = and_(ModelWorkAdmission.admitted_at > cutoff, ModelWorkAdmission.admitted_at <= as_of)
    active = or_(
        and_(
            ModelWorkAdmission.state == "reserved",
            ModelWorkAdmission.reservation_expires_at > as_of,
        ),
        and_(ModelWorkAdmission.state == "running", ModelWorkAdmission.lease_ends_at > as_of),
    )
    admissions = list(
        s.scalars(
            select(ModelWorkAdmission).where(
                ModelWorkAdmission.box_id == box,
                ModelWorkAdmission.owner_id == owner,
                or_(recent, active),
            )
        )
    )
    legacy_replies = s.scalar(
        select(func.count())
        .select_from(WorkspaceReply)
        .where(
            WorkspaceReply.box_id == box,
            WorkspaceReply.owner_id == owner,
            WorkspaceReply.created_at > cutoff,
            WorkspaceReply.created_at <= as_of,
            WorkspaceReply.backend.like("azure_gpt41%"),
            ~exists().where(ModelWorkAdmission.request_entry_id == WorkspaceReply.entry_id),
            ~exists().where(WorkspaceHandoffAttempt.result_entry_id == WorkspaceReply.entry_id),
        )
    )
    stamp = func.coalesce(WorkspaceHandoffAttempt.started_at, WorkspaceHandoffAttempt.created_at)
    legacy_attempts = s.scalar(
        select(func.count())
        .select_from(WorkspaceHandoffAttempt)
        .where(
            WorkspaceHandoffAttempt.box_id == box,
            WorkspaceHandoffAttempt.owner_id == owner,
            stamp > cutoff,
            stamp <= as_of,
            or_(
                WorkspaceHandoffAttempt.started_at.is_not(None),
                WorkspaceHandoffAttempt.status == "queued",
                WorkspaceHandoffAttempt.error_code.is_(None),
                WorkspaceHandoffAttempt.error_code.not_in(
                    ["team_work_limit", "authority_changed", "legacy_queued_unadmitted"]
                ),
            ),
            ~exists().where(ModelWorkAdmission.handoff_attempt_id == WorkspaceHandoffAttempt.id),
        )
    )
    legacy = (legacy_replies or 0) + (legacy_attempts or 0)
    version = team.current(s, box, owner)
    configuration = (
        configuration if configuration is not None else version.configuration if version else {}
    )
    policy = configuration.get("model_work")
    occupied = len(admissions) + legacy
    observed = {}
    if admissions:
        for item in s.scalars(
            select(ModelUsageObservation)
            .where(ModelUsageObservation.admission_id.in_([row.id for row in admissions]))
            .order_by(ModelUsageObservation.observed_at, ModelUsageObservation.id)
        ):
            if item.admission_id not in observed or item.kind == "late_usage":
                observed[item.admission_id] = item
    complete = legacy == 0 and all(
        row.id in observed and observed[row.id].usage == "verified" for row in admissions
    )
    verified = [item for item in observed.values() if item.usage == "verified"]
    return {
        "contract_version": 1,
        "policy": policy,
        "team_revision": version.revision if version else 0,
        "as_of": as_of.isoformat(),
        "window_start": cutoff.isoformat(),
        "admitted_units": sum(cutoff < row.admitted_at <= as_of for row in admissions) + legacy,
        "occupied_units": occupied,
        "remaining_units": None
        if policy is None
        else max(0, policy["max_attempts_per_24h"] - occupied),
        "pending_units": sum(effective_state(row, as_of) in ACTIVE for row in admissions),
        "unknown_units": sum(effective_state(row, as_of) == "unknown" for row in admissions),
        "verified_input_tokens": sum(item.input_tokens for item in verified)
        if verified
        else (0 if complete else None),
        "verified_output_tokens": sum(item.output_tokens for item in verified)
        if verified
        else (0 if complete else None),
        "usage_complete": complete,
        "coverage": "new_admissions_and_retained_legacy_records",
    }


def workspace_units(s, wid):
    direct = (
        s.scalar(
            select(func.count())
            .select_from(ModelWorkAdmission)
            .where(
                ModelWorkAdmission.workspace_id == wid, ModelWorkAdmission.kind == "conversation"
            )
        )
        or 0
    )
    attempts = (
        s.scalar(
            select(func.count())
            .select_from(WorkspaceHandoffAttempt)
            .where(WorkspaceHandoffAttempt.workspace_id == wid)
        )
        or 0
    )
    legacy = (
        s.scalar(
            select(func.count())
            .select_from(WorkspaceReply)
            .where(
                WorkspaceReply.workspace_id == wid,
                WorkspaceReply.backend.like("azure_gpt41%"),
                ~exists().where(ModelWorkAdmission.request_entry_id == WorkspaceReply.entry_id),
                ~exists().where(WorkspaceHandoffAttempt.result_entry_id == WorkspaceReply.entry_id),
            )
        )
        or 0
    )
    return direct + attempts + legacy


def source_digest(context):
    value = asdict(context)
    for field in ("context_revision", "handoff_roles", "handoff_targets", "handoff_limit"):
        value.pop(field)
    return digest(value)


def admission_observation(s, row, as_of):
    state = effective_state(row, as_of)
    observations = list(
        s.scalars(
            select(ModelUsageObservation)
            .where(ModelUsageObservation.admission_id == row.id)
            .order_by(ModelUsageObservation.observed_at, ModelUsageObservation.id)
        )
    )
    best = next(
        (item for item in reversed(observations) if item.kind == "late_usage"),
        observations[-1] if observations else None,
    )
    dispatch = (
        "not_started"
        if row.dispatch_id is None
        else "unconfirmed"
        if state == "unknown"
        else "started"
    )
    if best and best.dispatch == "not_dispatched":
        dispatch = "not_started"
    return {
        "id": row.id,
        "state": state,
        "unit": 1,
        "admitted_at": row.admitted_at.isoformat(),
        "dispatch": dispatch,
        "usage": best.usage if best else "unknown",
        "input_tokens": best.input_tokens if best else None,
        "output_tokens": best.output_tokens if best else None,
    }


def _reason(row, as_of):
    effective = effective_state(row, as_of)
    if effective != row.state:
        return "reservation_expired" if effective == "abandoned" else "dispatch_interrupted"
    return row.reason


def conversation_observation(s, workspace, *, key, request_hash, as_of):
    row = s.scalar(
        select(ModelWorkAdmission).where(
            ModelWorkAdmission.workspace_id == workspace.id, ModelWorkAdmission.request_key == key
        )
    )
    entry = s.scalar(
        select(WorkspaceEntry).where(
            WorkspaceEntry.workspace_id == workspace.id, WorkspaceEntry.idempotency_key == key
        )
    )
    if (
        row
        and (row.kind != "conversation" or row.request_hash != request_hash)
        or entry
        and entry.request_hash != request_hash
    ):
        raise ws.WorkspaceError("idempotency_conflict")
    result = {
        "contract_version": 1,
        "workspace_id": workspace.id,
        "idempotency_key": key,
        "request_sha256": request_hash,
        "outcome": "not_found",
        "admission": None,
        "saved_entry": None,
        "reason": None,
    }
    reply = s.get(WorkspaceReply, entry.id) if entry else None
    if row:
        if not entry or row.request_entry_id != entry.id:
            raise ws.WorkspaceError("model_observation_unavailable", 503)
        result.update(
            admission=admission_observation(s, row, as_of),
            outcome=effective_state(row, as_of),
            reason=_reason(row, as_of),
        )
        if (row.result_entry_id is not None) != (reply is not None):
            raise ws.WorkspaceError("model_observation_unavailable", 503)
    elif entry and reply is None:
        raise ws.WorkspaceError("idempotency_conflict")
    if reply:
        result.update(outcome="saved", saved_entry={"id": entry.id, "revision": entry.revision})
    return checked_response(result, ModelRequestObservation)


def conversation_request_hash(*, expected, team_revision, role, content, research_analysis=None, inbox_analysis=None, membership_analysis=None, session_prep_analysis=None):
    value = {"expected": expected, "team_revision": team_revision, "role": role, "content": content}
    if research_analysis is not None:
        from cosmas_os.application.research_analysis import selection

        value["research_analysis"] = selection(research_analysis)
    if inbox_analysis is not None:
        from cosmas_os.application.inbox_analysis import selection

        if research_analysis is not None:
            raise ws.WorkspaceError("invalid_inbox_analysis", 422)
        value["inbox_analysis"] = selection(inbox_analysis)
    if membership_analysis is not None:
        from cosmas_os.application.membership_analysis import selection

        if research_analysis is not None or inbox_analysis is not None:
            raise ws.WorkspaceError("invalid_membership_analysis", 422)
        value["membership_analysis"] = selection(membership_analysis)
    if session_prep_analysis is not None:
        from cosmas_os.application.session_prep_analysis import selection

        if any(item is not None for item in (research_analysis, inbox_analysis, membership_analysis)):
            raise ws.WorkspaceError("invalid_session_prep_analysis", 422)
        value["session_prep_analysis"] = selection(session_prep_analysis)
    return payload_hash(value)


def resolve_conversation(
    s,
    box,
    owner,
    wid,
    *,
    expected,
    team_revision,
    key,
    role,
    content,
    research_analysis=None,
    inbox_analysis=None,
    membership_analysis=None,
    session_prep_analysis=None,
    external_identity_id=None,
    reauthenticate=None,
    clock=None,
):
    if reauthenticate:
        reauthenticate()
    workspace = read_workspace(s, box, owner, wid, external_identity_id)
    request_hash = conversation_request_hash(
        expected=expected, team_revision=team_revision, role=role, content=content,
        research_analysis=research_analysis, inbox_analysis=inbox_analysis, membership_analysis=membership_analysis,
        session_prep_analysis=session_prep_analysis,
    )
    return conversation_observation(
        s, workspace, key=key, request_hash=request_hash, as_of=now(s, clock)
    )


def _usage_record(
    s,
    row,
    *,
    at,
    dispatch,
    outcome,
    input_tokens=None,
    output_tokens=None,
    response_sha256=None,
    late=False,
):
    verified = (
        type(input_tokens) is int
        and type(output_tokens) is int
        and 0 <= input_tokens < 1_000_000
        and 0 <= output_tokens < 1_000_000
    )
    values = {
        "kind": "late_usage" if late else "terminal",
        "dispatch": dispatch,
        "outcome": outcome,
        "usage": "verified" if verified else "unknown",
        "input_tokens": input_tokens if verified else None,
        "output_tokens": output_tokens if verified else None,
        "model": "gpt-4.1",
        "envelope_sha256": row.envelope_sha256,
        "response_sha256": response_sha256,
    }
    receipt_hash = digest(values)
    existing = s.scalar(
        select(ModelUsageObservation).where(
            ModelUsageObservation.admission_id == row.id,
            ModelUsageObservation.kind == values["kind"],
        )
    )
    if existing:
        if existing.receipt_hash != receipt_hash:
            raise ws.WorkspaceError("model_observation_conflict")
        return
    s.add(
        ModelUsageObservation(
            admission_id=row.id,
            workspace_id=row.workspace_id,
            box_id=row.box_id,
            owner_id=row.owner_id,
            observed_at=at,
            receipt_hash=receipt_hash,
            **values,
        )
    )


def _finish(s, row, state, reason, at, *, dispatch=None, outcome=None, reply=None):
    row.state, row.reason, row.finalized_at = state, reason, at
    _usage_record(
        s,
        row,
        at=at,
        dispatch=dispatch
        or ("not_dispatched" if row.dispatch_id is None else "started_unconfirmed"),
        outcome=outcome or ("reservation_expired" if state == "abandoned" else "interrupted"),
        input_tokens=reply.input_tokens if reply else None,
        output_tokens=reply.output_tokens if reply else None,
        response_sha256=getattr(reply, "response_sha256", None),
    )
    if row.handoff_attempt_id is not None:
        from cosmas_os.application import handoffs

        attempt = s.get(WorkspaceHandoffAttempt, row.handoff_attempt_id)
        if attempt and attempt.status in {"queued", "running"}:
            status = {
                "completed": "completed",
                "failed": "failed",
                "unknown": "interrupted",
                "abandoned": "interrupted",
            }[state]
            handoffs._terminal(s, attempt, status, error=reason, result=row.result_entry_id)


def _context_for(
    s, workspace, version, settings, bot, command, *, handoff_roles=(), draft_only=False, session_prep_phase="before", prepared_contract=None
):
    from cosmas_os.application import conversation

    if "session_prep_analysis" in command:
        from cosmas_os.application import session_prep_analysis

        if draft_only or any(key in command for key in ("research_analysis", "inbox_analysis", "membership_analysis")):
            raise ws.WorkspaceError("invalid_session_prep_analysis", 422)
        if not team.runtime_settings.workspace_session_prep_available:
            raise ws.WorkspaceError("authority_changed")
        return session_prep_analysis.build_context(
            s, workspace, version, settings, bot, command, phase=session_prep_phase
        )
    if "membership_analysis" in command:
        from cosmas_os.application import membership_analysis

        if draft_only or "research_analysis" in command or "inbox_analysis" in command:
            raise ws.WorkspaceError("membership_bot_required")
        return membership_analysis.build_context(s, workspace, settings, command)
    if settings["role"] == "custom" and settings.get("skills") == ["membership_review"]:
        raise ws.WorkspaceError("membership_selection_required")

    if "inbox_analysis" in command:
        from cosmas_os.application import inbox_analysis

        if draft_only or "research_analysis" in command:
            raise ws.WorkspaceError("inbox_bot_required")
        return inbox_analysis.build_context(s, workspace, settings, command)
    if settings["role"] == "custom" and settings.get("skills") == ["inbox_review"]:
        raise ws.WorkspaceError("inbox_selection_required")
    if "research_analysis" in command:
        from cosmas_os.application import research_analysis

        if not team.runtime_settings.workspace_research_available:
            raise ws.WorkspaceError("authority_changed")
        if draft_only:
            raise ws.WorkspaceError("research_bot_required")
        return research_analysis.build_context(s, workspace, settings, command)
    targets = tuple(
        {
            "address": team.bot_address(candidate),
            "role": candidate["role"],
            "name": candidate["name"],
            "job_focus": candidate.get("job_focus", ""),
        }
        for candidate in version.configuration["bots"]
        if team.bot_address(candidate) in handoff_roles
    )
    context = conversation.build_context(
        project_workspace(s, ws.read(s, workspace.box_id, workspace.owner_id, workspace.id)),
        version,
        settings,
        settings["role"],
        command["content"],
        handoff_roles=handoff_roles,
        include_history=not draft_only,
        draft_only=draft_only,
        agent_id=bot.agent_id,
        handoff_targets=targets,
        additional_sources=_selected_connector_passages(s, workspace, settings),
    )
    selected_google_kinds = {"google_message", "google_calendar"}
    if any(s.get(WorkspaceEntry, source.entry_id).kind in selected_google_kinds
           for source in context.sources if s.get(WorkspaceEntry, source.entry_id) is not None) and (
            len(context.sources) > 12 or any(len(source.content) > 5000 and not (
                prepared_contract == handoff_briefs.FULL_SOURCE_CONTRACT
                and s.get(WorkspaceEntry, source.entry_id).kind == "efax_inbound_source"
            ) for source in context.sources)
            or sum(len(source.content) for source in context.sources) > 30000):
        has_calendar = any(s.get(WorkspaceEntry, source.entry_id).kind == "google_calendar"
            for source in context.sources if s.get(WorkspaceEntry, source.entry_id) is not None)
        raise ws.WorkspaceError("selected_google_context_too_large" if has_calendar else "google_message_context_too_large", 422)
    has_fax = any(s.get(WorkspaceEntry, source.entry_id).kind == "efax_inbound_source"
                  for source in context.sources if s.get(WorkspaceEntry, source.entry_id) is not None)
    if has_fax:
        try:
            handoff_briefs.validate_sources(context,
                version=2 if prepared_contract == handoff_briefs.FULL_SOURCE_CONTRACT else 1,
                prepared_contract=prepared_contract)
        except ValueError:
            raise ws.WorkspaceError("efax_inbound_source_context_too_large", 422) from None
    if "task_brief" in command:
        try:
            if not draft_only:
                raise ValueError("task brief requires private handoff")
            task = command["task_brief"]
            handoff_briefs.validate(task, context, goal=command["content"],
                origin_id=task["depends_on"]["entry_id"], prepared_contract=prepared_contract)
            context = replace(context, question=handoff_briefs.question(task))
        except (ValueError, TypeError, KeyError):
            raise ws.WorkspaceError("source_changed") from None
    if "revision_request" in command:
        from cosmas_os.application.handoff_revision import revision_question

        if not draft_only or "task_brief" not in command:
            raise ws.WorkspaceError("source_changed")
        question = context.question + revision_question(s, workspace, command["revision_request"])
        if len(question) > 12000:
            raise ws.WorkspaceError("handoff_revision_too_large", 422)
        context = replace(context, question=question)
    return context


def _google_message_passages(s, workspace, settings):
    """Only human-selected, current Google custody enters model evidence.

    The saved entry remains a separate source class so note review never changes.
    Its verified model passage uses the existing pinned evidence decoder shape.
    """
    if not team.runtime_settings.workspace_google_message_available:
        return ()
    from cosmas_os.application import google_message
    from cosmas_os.ports.bot_capabilities import SourcePassage

    return tuple(SourcePassage(row.id, row.revision, row.source_label, "evidence", row.content)
                 for row in google_message.selected_entries(s, workspace, settings, workspace.revision))


def _google_calendar_passages(s, workspace, settings):
    """Frozen human-reviewed summaries enter evidence only after current custody."""
    if not team.runtime_settings.workspace_google_calendar_available:
        return ()
    from cosmas_os.application import google_calendar
    from cosmas_os.ports.bot_capabilities import SourcePassage

    return tuple(SourcePassage(row.id, row.revision, row.source_label, "evidence", row.content)
                 for row in google_calendar.selected_entries(s, workspace, settings, workspace.revision))


def _selected_google_passages(s, workspace, settings):
    return tuple(sorted(
        (*_google_message_passages(s, workspace, settings), *_google_calendar_passages(s, workspace, settings)),
        key=lambda source: source.revision,
    ))


def _selected_connector_passages(s, workspace, settings):
    sources = _selected_google_passages(s, workspace, settings)
    if not team.runtime_settings.efax_inbound_source_available:
        return sources
    from cosmas_os.application import efax_inbound_source
    from cosmas_os.ports.bot_capabilities import SourcePassage

    reviewed = efax_inbound_source.selected_entries(s, workspace, settings, workspace.revision)
    return tuple(sorted((*sources, *(SourcePassage(row.id, row.revision, row.source_label,
                        "evidence", row.content) for row in reviewed)), key=lambda source: source.revision))


def _allowance(s, box, owner, as_of, configuration):
    meter = usage(s, box, owner, as_of=as_of, configuration=configuration)
    if meter["remaining_units"] is not None and meter["remaining_units"] < 1:
        raise ws.WorkspaceError("team_work_limit")
    return meter


def _new_admission(
    s,
    workspace,
    version,
    settings,
    bot,
    command,
    request_hash,
    context,
    as_of,
    external_identity_id,
    *,
    attempt=None,
):
    full_source_task = command.get("task_brief", {}).get("version") == 2
    tools_available = (team.runtime_settings.workspace_agent_tools_enabled
        and not any(key in command for key in (
            "research_analysis", "inbox_analysis", "membership_analysis", "session_prep_analysis")))
    if full_source_task and not tools_available:
        raise ws.WorkspaceError("handoff_source_contract_unavailable", 422)
    if context.role == "chief" and context.handoff_roles and context.handoff_limit:
        try:
            handoff_briefs.validate_sources(context, version=2 if tools_available else 1,
                prepared_contract=handoff_briefs.FULL_SOURCE_CONTRACT if tools_available else None)
        except (ValueError, TypeError, KeyError):
            raise ws.WorkspaceError("handoff_source_context_too_large", 422) from None
    try:
        if not any(
            key in command for key in ("research_analysis", "inbox_analysis", "membership_analysis", "session_prep_analysis")
        ) and team.runtime_settings.workspace_agent_tools_enabled:
            from cosmas_os.application.agent_tools import prepare_tool_selection

            selection = prepare_tool_selection(s, box=workspace.box_id, owner=workspace.owner_id,
                workspace_id=workspace.id, agent_id=bot.agent_id, team_revision_id=version.id,
                context_revision=context.context_revision, settings=settings, context=context)
            envelope = GPT41CompactToolsConnector(lambda: "").prepare(context, selection)
        else:
            envelope = GPT41Connector(lambda: "").prepare(context)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise ws.WorkspaceError("model_unavailable", 503) from None
    if full_source_task and envelope["contract"] != handoff_briefs.FULL_SOURCE_CONTRACT:
        raise ws.WorkspaceError("handoff_source_contract_unavailable", 422)
    # Application bounds use canonical bytes; the DB has a finite allowance for
    # PostgreSQL jsonb's inserted whitespace/escaping, not a larger model body.
    if len(canonical(command)) > 65_536:
        raise ws.WorkspaceError("model_request_too_large", 422)
    workspace.revision += 1
    entry = WorkspaceEntry(
        workspace_id=workspace.id,
        box_id=workspace.box_id,
        actor_id=workspace.owner_id,
        revision=workspace.revision,
        kind="handoff_result" if attempt else "conversation",
        content=command["content"],
        idempotency_key=command["idempotency_key"],
        request_hash=request_hash,
    )
    s.add(entry)
    s.flush()
    row = ModelWorkAdmission(
        box_id=workspace.box_id,
        owner_id=workspace.owner_id,
        workspace_id=workspace.id,
        agent_id=bot.agent_id,
        team_revision_id=version.id,
        external_identity_id=external_identity_id,
        kind="private_handoff" if attempt else "conversation",
        request_key=command["idempotency_key"],
        request_hash=request_hash,
        handoff_attempt_id=attempt.id if attempt else None,
        expected_revision=command["expected_revision"],
        context_revision=context.context_revision,
        request_body=command,
        prepared_envelope=envelope,
        envelope_contract=envelope["contract"],
        envelope_sha256=digest(envelope),
        source_sha256=source_digest(context),
        admitted_at=as_of,
        reservation_expires_at=as_of + (timedelta(hours=24) if attempt else timedelta(seconds=10)),
        state="reserved",
        request_entry_id=entry.id,
    )
    s.add(row)
    s.flush()
    return row


def reserve_conversation(
    s,
    box,
    owner,
    wid,
    *,
    expected,
    team_revision,
    key,
    role,
    content,
    research_analysis=None,
    inbox_analysis=None,
    membership_analysis=None,
    session_prep_analysis=None,
    external_identity_id=None,
    reauthenticate=None,
    clock=None,
):
    from cosmas_os.application import handoffs

    s.rollback()
    lock_owner(s, box, owner)
    if reauthenticate:
        reauthenticate()
    workspace = ws._workspace(s, box, owner, wid, writing=True)
    _identity(s, box, owner, external_identity_id)
    request_hash = conversation_request_hash(
        expected=expected, team_revision=team_revision, role=role, content=content,
        research_analysis=research_analysis, inbox_analysis=inbox_analysis, membership_analysis=membership_analysis,
        session_prep_analysis=session_prep_analysis,
    )
    at = now(s, clock)
    prior = conversation_observation(s, workspace, key=key, request_hash=request_hash, as_of=at)
    if prior["outcome"] != "not_found":
        s.commit()
        return None, prior
    # No current-model/policy gate precedes the exact historical lookup above.
    if workspace.revision != expected:
        raise ws.WorkspaceError("workspace_revision_conflict")
    if workspace.revision >= 500:
        raise ws.WorkspaceError("workspace_history_limit")
    if not isinstance(content, str) or not content or len(content) > 4000:
        raise ws.WorkspaceError("invalid_entry", 400)
    if not team.runtime_settings.workspace_llm_available:
        raise ws.WorkspaceError("model_unavailable")
    version, bot, settings = team.active_bot(s, box, owner, role, team_revision)
    if team.blocked(settings, "model_answer"):
        raise ws.WorkspaceError("bot_capability_restricted")
    rows = list(
        s.scalars(
            select(ModelWorkAdmission)
            .where(
                ModelWorkAdmission.workspace_id == wid,
                ModelWorkAdmission.kind == "conversation",
                ModelWorkAdmission.state.in_(ACTIVE),
            )
            .order_by(ModelWorkAdmission.id)
            .with_for_update()
        )
    )
    for row in rows:
        effective = effective_state(row, at)
        if effective in ACTIVE:
            raise ws.WorkspaceError("model_attempt_in_progress")
        _finish(
            s,
            row,
            effective,
            "reservation_expired" if effective == "abandoned" else "dispatch_interrupted",
            at,
        )
    s.flush()
    count = workspace_units(s, wid)
    if count >= 50:
        raise ws.WorkspaceError("workspace_model_turn_limit")
    meter = _allowance(s, box, owner, at, version.configuration)
    roles = (
        handoffs.available_roles(s, box, owner, version, settings)
        if settings["role"] == "chief"
        else ()
    )
    remaining = meter["remaining_units"]
    handoff_limit = min(
        3, max(0, 49 - count), max(0, remaining - 1) if remaining is not None else 3
    )
    roles = roles if handoff_limit else ()
    command = {
        "expected_revision": expected,
        "team_revision": team_revision,
        "idempotency_key": key,
        "role": role,
        "content": content,
    }
    if research_analysis is not None:
        from cosmas_os.application.research_analysis import selection

        command["research_analysis"] = selection(research_analysis)
    if inbox_analysis is not None:
        from cosmas_os.application.inbox_analysis import selection

        command["inbox_analysis"] = selection(inbox_analysis)
    if membership_analysis is not None:
        from cosmas_os.application.membership_analysis import selection

        command["membership_analysis"] = selection(membership_analysis)
    if session_prep_analysis is not None:
        from cosmas_os.application.session_prep_analysis import selection

        command["session_prep_analysis"] = selection(session_prep_analysis)
    tools_available = team.runtime_settings.workspace_agent_tools_enabled
    context = _context_for(s, workspace, version, settings, bot, command, handoff_roles=roles,
        prepared_contract=handoff_briefs.FULL_SOURCE_CONTRACT if tools_available else None)
    from dataclasses import replace

    context = replace(context, handoff_limit=0 if any(item is not None for item in (research_analysis, inbox_analysis, membership_analysis, session_prep_analysis)) else handoff_limit)
    if context.role == "chief" and context.handoff_roles and context.handoff_limit:
        # Each installed recipient may select a different notebook/evidence set.
        # Validate those possible full source sets before paying Chief, rather
        # than discovering a recipient-only overflow during child publication.
        tools_available = team.runtime_settings.workspace_agent_tools_enabled
        for address in context.handoff_roles:
            _, recipient, recipient_settings = team.active_bot(s, box, owner, address, version.revision)
            child = _context_for(s, workspace, version, recipient_settings, recipient,
                {"content": "Preflight private draft source bounds."}, draft_only=True,
                prepared_contract=handoff_briefs.FULL_SOURCE_CONTRACT if tools_available else None)
            try:
                handoff_briefs.validate_sources(child, version=2 if tools_available else 1,
                    prepared_contract=handoff_briefs.FULL_SOURCE_CONTRACT if tools_available else None)
            except (ValueError, TypeError, KeyError):
                raise ws.WorkspaceError("handoff_source_context_too_large", 422) from None
    row = _new_admission(
        s,
        workspace,
        version,
        settings,
        bot,
        command,
        request_hash,
        context,
        now(s, clock),
        external_identity_id,
    )
    admission_id = row.id
    s.commit()
    return admission_id, None


@dataclass(frozen=True)
class ModelClaim:
    admission_id: str
    box: str
    owner: str
    workspace_id: str
    dispatch_id: str
    envelope_sha256: str
    envelope: dict


def _current_input(s, row, *, reauthenticate=None, session_prep_phase="before"):
    if reauthenticate:
        reauthenticate()
    _identity(s, row.box_id, row.owner_id, row.external_identity_id)
    workspace = ws._workspace(s, row.box_id, row.owner_id, row.workspace_id, writing=True)
    command = row.request_body
    version, bot, settings = team.active_bot(
        s, row.box_id, row.owner_id, command["role"], command["team_revision"]
    )
    if any(key in command for key in ("research_analysis", "inbox_analysis", "membership_analysis", "session_prep_analysis")) and (
        row.kind != "conversation" or bot.agent_id != row.agent_id
        or version.id != row.team_revision_id
        or conversation_request_hash(
            expected=command["expected_revision"], team_revision=command["team_revision"],
            role=command["role"], content=command["content"],
            research_analysis=command.get("research_analysis"), inbox_analysis=command.get("inbox_analysis"), membership_analysis=command.get("membership_analysis"),
            session_prep_analysis=command.get("session_prep_analysis"),
        ) != row.request_hash
    ):
        raise ws.WorkspaceError("source_changed")
    if row.kind == "private_handoff":
        from cosmas_os.application import handoffs

        attempt = s.get(WorkspaceHandoffAttempt, row.handoff_attempt_id)
        assignment = s.get(WorkspaceHandoff, attempt.handoff_id) if attempt else None
        _, chief, chief_settings = team.active_bot(
            s, row.box_id, row.owner_id, "chief", command["team_revision"]
        )
        if (
            assignment is None
            or chief.agent_id != assignment.issuer_agent_id
            or assignment.recipient_agent_id != bot.agent_id
            or command["role"]
            not in handoffs.available_roles(s, row.box_id, row.owner_id, version, chief_settings)
        ):
            raise ws.WorkspaceError("authority_changed")
        if "task_brief" in command:
            origin = s.get(WorkspaceEntry, assignment.origin_entry_id)
            if (command["content"] != assignment.brief or origin is None
                or not isinstance(command["task_brief"], dict)
                or command["task_brief"].get("depends_on") != {"entry_id": origin.id, "revision": origin.revision}):
                raise ws.WorkspaceError("source_changed")
    if (
        not team.runtime_settings.workspace_llm_available
        or team.blocked(settings, "model_answer")
        or version.configuration.get("model_work", {}).get("max_attempts_per_24h") == 0
        or row.kind == "private_handoff"
        and team.blocked(settings, "private_draft_handoff")
    ):
        raise ws.WorkspaceError("authority_changed")
    if command.get("task_brief", {}).get("version") == 2 and (
        row.envelope_contract != handoff_briefs.FULL_SOURCE_CONTRACT
        or not team.runtime_settings.workspace_agent_tools_enabled
    ):
        raise ws.WorkspaceError("authority_changed")
    frozen = _context(row.prepared_envelope["context"])
    context = _context_for(
        s,
        workspace,
        version,
        settings,
        bot,
        command,
        handoff_roles=frozen.handoff_roles,
        draft_only=row.kind == "private_handoff",
        session_prep_phase=session_prep_phase,
        prepared_contract=row.envelope_contract,
    )
    if source_digest(context) != row.source_sha256:
        raise ws.WorkspaceError("source_changed")
    return workspace, version, bot, settings


def claim(s, box, owner, admission_id, *, reauthenticate=None, clock=None):
    s.rollback()
    workspace_id = s.scalar(
        select(ModelWorkAdmission.workspace_id).where(
            ModelWorkAdmission.id == admission_id,
            ModelWorkAdmission.box_id == box,
            ModelWorkAdmission.owner_id == owner,
        )
    )
    lock_owner(s, box, owner, active=False)
    if workspace_id is None:
        raise ws.WorkspaceError("model_observation_unavailable", 404)
    s.scalar(
        select(EncounterWorkspace)
        .where(
            EncounterWorkspace.id == workspace_id,
            EncounterWorkspace.box_id == box,
            EncounterWorkspace.owner_id == owner,
        )
        .with_for_update()
    )
    row = s.scalar(
        select(ModelWorkAdmission)
        .where(
            ModelWorkAdmission.id == admission_id,
            ModelWorkAdmission.box_id == box,
            ModelWorkAdmission.owner_id == owner,
        )
        .with_for_update()
    )
    if row is None:
        raise ws.WorkspaceError("model_observation_unavailable", 404)
    at = now(s, clock)
    if row.state != "reserved":
        s.commit()
        return None
    if effective_state(row, at) == "abandoned":
        _finish(s, row, "abandoned", "reservation_expired", at)
        s.commit()
        return None
    try:
        _current_input(s, row, reauthenticate=reauthenticate)
        if (
            row.envelope_contract not in SUPPORTED_PREPARED_CONTRACTS
            or row.envelope_contract != row.prepared_envelope.get("contract")
            or digest(row.prepared_envelope) != row.envelope_sha256
        ):
            raise ws.WorkspaceError("source_changed")
        if row.envelope_contract in TOOL_PREPARED_CONTRACTS:
            try:
                validator = validate_compact_tools if row.envelope_contract == COMPACT_TOOL_PREPARED_CONTRACT else validate_tools
                validator(row.prepared_envelope)
            except (ValueError, TypeError, KeyError):
                raise ws.WorkspaceError("source_changed") from None
    except ws.WorkspaceError as error:
        _finish(
            s,
            row,
            "failed",
            "source_changed" if error.code == "source_changed" else "authority_changed",
            at,
            outcome="source_withheld" if error.code == "source_changed" else "authority_withheld",
        )
        s.commit()
        return None
    # Refresh after locks/checks: an earlier transaction timestamp is not a lease.
    at = now(s, clock)
    if effective_state(row, at) == "abandoned":
        _finish(s, row, "abandoned", "reservation_expired", at)
        s.commit()
        return None
    row.state, row.dispatch_id = "running", str(uuid4())
    row.started_at, row.lease_ends_at = at, at + timedelta(seconds=90)
    if row.handoff_attempt_id:
        attempt = s.get(WorkspaceHandoffAttempt, row.handoff_attempt_id)
        if attempt.status != "queued":
            raise ws.WorkspaceError("handoff_attempt_conflict")
        attempt.status, attempt.started_at = "running", at
    result = ModelClaim(
        row.id,
        box,
        owner,
        row.workspace_id,
        row.dispatch_id,
        row.envelope_sha256,
        json.loads(canonical(row.prepared_envelope)),
    )
    s.commit()
    return result


def dispatch_claim(claimed, *, session_factory=None, transport=None):
    if digest(claimed.envelope) != claimed.envelope_sha256:
        raise ModelCallFailure()
    key = team.runtime_settings.workspace_llm_api_key
    if claimed.envelope.get("contract") in TOOL_PREPARED_CONTRACTS:
        from cosmas_os.application.agent_tools import AgentToolExecutor
        from cosmas_os.db import make_session_factory
        from cosmas_os.models import AuditEvent

        factory = session_factory or make_session_factory()
        def execute(request):
            with factory() as tool_session:
                value = AgentToolExecutor(tool_session, claimed).execute(request)
                receipt = value["receipt"]
                tool_session.add(AuditEvent(box_id=claimed.box, aggregate_type="model_admission",
                    aggregate_id=claimed.admission_id, event_type="workspace.agent_tool_read",
                    actor_principal_id=receipt["actor_agent_id"], initiated_by_principal_id=claimed.owner,
                    outcome="read", correlation_id=claimed.dispatch_id, payload_hash=receipt["sha256"],
                    detail=receipt))
                tool_session.commit()
                return value
        connector = (GPT41CompactToolsConnector if claimed.envelope["contract"] == COMPACT_TOOL_PREPARED_CONTRACT
            else GPT41ToolsConnector)
        return connector(lambda: key.get_secret_value() if key else "", transport=transport).review_prepared(
            claimed.envelope, execute=execute)
    return GPT41Connector(lambda: key.get_secret_value() if key else "").review_prepared(
        claimed.envelope
    )


def settle(s, claimed, result, *, reauthenticate=None, clock=None):
    from cosmas_os.application import conversation

    s.rollback()
    lock_owner(s, claimed.box, claimed.owner, active=False)
    # Owner lock is always first. Workspace precedes admission to match reserves.
    workspace = s.scalar(
        select(EncounterWorkspace)
        .where(
            EncounterWorkspace.id == claimed.workspace_id,
            EncounterWorkspace.box_id == claimed.box,
            EncounterWorkspace.owner_id == claimed.owner,
        )
        .with_for_update()
    )
    row = s.scalar(
        select(ModelWorkAdmission)
        .where(
            ModelWorkAdmission.id == claimed.admission_id,
            ModelWorkAdmission.workspace_id == claimed.workspace_id,
            ModelWorkAdmission.box_id == claimed.box,
            ModelWorkAdmission.owner_id == claimed.owner,
        )
        .with_for_update()
    )
    if (
        workspace is None
        or row is None
        or row.dispatch_id != claimed.dispatch_id
        or row.envelope_sha256 != claimed.envelope_sha256
    ):
        raise ws.WorkspaceError("model_observation_conflict")
    at = now(s, clock)
    failure = result if isinstance(result, ModelCallFailure) else None
    if not failure and not isinstance(result, BotReply):
        failure = ModelCallFailure(dispatch="response_received", outcome="invalid_output")
        result = failure
    if row.state in TERMINAL and row.state != "unknown":
        s.commit()
        return
    if effective_state(row, at) == "unknown":
        if row.state != "unknown":
            _finish(s, row, "unknown", "dispatch_interrupted", at)
        if type(result.input_tokens) is int and type(result.output_tokens) is int:
            _usage_record(
                s,
                row,
                at=at,
                dispatch="response_received",
                outcome="invalid_output" if failure else "valid_output",
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                response_sha256=getattr(result, "response_sha256", None),
                late=True,
            )
        s.commit()
        return
    if failure:
        state = "unknown" if failure.dispatch == "started_unconfirmed" else "failed"
        _finish(
            s,
            row,
            state,
            "dispatch_interrupted" if state == "unknown" else "model_unavailable",
            at,
            dispatch=failure.dispatch,
            outcome=failure.outcome,
            reply=failure,
        )
        s.commit()
        return
    assert isinstance(result, BotReply)
    try:
        workspace, version, bot, settings = _current_input(s, row, reauthenticate=reauthenticate, session_prep_phase="after")
        frozen = _context(row.prepared_envelope["context"])
        if row.envelope_contract in {"cosmas-gpt41-prepared.v4", *TOOL_PREPARED_CONTRACTS}:
            try:
                for brief in result.handoffs:
                    TaskRequirements.model_validate(brief.requirements)
            except (ValueError, TypeError):
                raise ws.WorkspaceError("invalid_model_output") from None
        if (
            not result.backend.startswith("azure_gpt41")
            or not result.content.strip()
            or len(result.content) > 20000
            or not {(item.entry_id, item.revision) for item in result.citations}
            <= {(item.entry_id, item.revision) for item in frozen.sources}
            or row.kind == "private_handoff"
            and (
                result.handoffs
                or result.backend
                != ("azure_gpt41_source_draft_v1" if frozen.role == "scribe" else "azure_gpt41")
            )
            or len(result.handoffs) > frozen.handoff_limit
            or not {brief.role for brief in result.handoffs} <= set(frozen.handoff_roles)
        ):
            raise ws.WorkspaceError("invalid_model_output")
    except ws.WorkspaceError as error:
        _finish(
            s,
            row,
            "failed",
            "source_changed"
            if error.code == "source_changed"
            else "model_unavailable"
            if error.code == "invalid_model_output"
            else "authority_changed",
            at,
            dispatch="response_received",
            outcome="source_withheld"
            if error.code == "source_changed"
            else "invalid_output"
            if error.code == "invalid_model_output"
            else "authority_withheld",
            reply=result,
        )
        s.commit()
        return
    at = now(s, clock)
    if effective_state(row, at) == "unknown":
        _finish(s, row, "unknown", "dispatch_interrupted", at)
        _usage_record(
            s,
            row,
            at=at,
            dispatch="response_received",
            outcome="valid_output",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            response_sha256=getattr(result, "response_sha256", None),
            late=True,
        )
        s.commit()
        return
    # Preparing children and flushing the publication can themselves take time.
    # Keep every staged child, entry, reply and audit behind a savepoint so a
    # closing lease or authority check leaves only the original paid admission.
    publication = s.begin_nested()
    try:
        entry = s.get(WorkspaceEntry, row.request_entry_id)
        published = result
        if result.handoffs:
            from dataclasses import replace

            queued, refused = reserve_children(
                s,
                workspace,
                entry,
                version,
                bot,
                frozen,
                result.handoffs,
                external_identity_id=row.external_identity_id,
                clock=clock,
                prepared_contract=row.envelope_contract,
            )
            published = replace(
                result,
                content=f"Private draft requests: {queued} queued; {refused} not started. Review each teammate’s recorded status below.",
            )
        # Pending child entries have no answer and do not alter selected inputs.
        _current_input(s, row, reauthenticate=reauthenticate, session_prep_phase="after")
        conversation.record_reply(s, workspace, entry, version, bot, settings, frozen, published)
        s.flush()
        if reauthenticate:
            reauthenticate()
        read_workspace(s, row.box_id, row.owner_id, row.workspace_id, row.external_identity_id)
    except ws.WorkspaceError as error:
        publication.rollback()
        at = now(s, clock)
        if effective_state(row, at) != "unknown":
            _finish(
                s,
                row,
                "failed",
                "source_changed" if error.code == "source_changed" else "model_unavailable" if error.code == "invalid_model_output" else "authority_changed",
                at,
                dispatch="response_received",
                outcome="source_withheld"
                if error.code == "source_changed"
                else "invalid_output" if error.code == "invalid_model_output" else "authority_withheld",
                reply=result,
            )
            s.commit()
            return
    at = now(s, clock)
    if effective_state(row, at) == "unknown":
        if publication.is_active:
            publication.rollback()
        _finish(s, row, "unknown", "dispatch_interrupted", at)
        _usage_record(
            s,
            row,
            at=at,
            dispatch="response_received",
            outcome="valid_output",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            response_sha256=getattr(result, "response_sha256", None),
            late=True,
        )
        s.commit()
        return
    publication.commit()
    row.result_entry_id = row.request_entry_id
    _finish(
        s,
        row,
        "completed",
        None,
        at,
        dispatch="response_received",
        outcome="valid_output",
        reply=result,
    )
    s.commit()


def run_conversation(
    s,
    box,
    owner,
    wid,
    *,
    external_identity_id=None,
    reauthenticate=None,
    clock=None,
    dispatch=None,
    **command,
):
    sources = None
    if command.get("session_prep_analysis") is not None:
        from cosmas_os.application.session_prep_analysis import Sources

        # Exact historical lookup precedes Core I/O, configuration and model gates.
        s.rollback()
        prior = resolve_conversation(
            s, box, owner, wid, external_identity_id=external_identity_id,
            reauthenticate=reauthenticate, clock=clock, **command,
        )
        s.rollback()
        if prior["outcome"] != "not_found":
            return prior
        sources = s.info.get("session_prep_analysis_sources")
        if not isinstance(sources, Sources):
            raise ws.WorkspaceError("session_prep_analysis_unavailable", 503)
        sources.refresh("before")
    admission_id, prior = reserve_conversation(
        s,
        box,
        owner,
        wid,
        external_identity_id=external_identity_id,
        reauthenticate=reauthenticate,
        clock=clock,
        **command,
    )
    if prior is not None:
        return prior
    claimed = claim(s, box, owner, admission_id, reauthenticate=reauthenticate, clock=clock)
    if claimed:
        try:
            result = (dispatch or dispatch_claim)(claimed)
        except ModelCallFailure as failure:
            result = failure
        if sources is not None and isinstance(result, BotReply):
            s.rollback()
            try:
                sources.refresh("after")
            except ws.WorkspaceError:
                # Cleared sources withhold output while retaining actual usage.
                # Cancellation keeps the existing unknown-outcome lease.
                pass
        settle(s, claimed, result, reauthenticate=reauthenticate, clock=clock)
    return resolve_conversation(
        s,
        box,
        owner,
        wid,
        external_identity_id=external_identity_id,
        reauthenticate=reauthenticate,
        clock=clock,
        **command,
    )


def project_workspace(s, value, *, as_of=None):
    as_of = as_of or now(s)
    entries = {entry["id"]: entry for entry in value["entries"]}
    rows = (
        list(
            s.scalars(
                select(ModelWorkAdmission).where(
                    ModelWorkAdmission.workspace_id == value["id"],
                    ModelWorkAdmission.request_entry_id.in_(entries),
                )
            )
        )
        if entries
        else []
    )
    if len(rows) > 50:
        raise ws.WorkspaceError("model_observation_unavailable", 503)
    for row in rows:
        from cosmas_os.application.selected_connector_sources import projection_unavailable

        if projection_unavailable(entries[row.request_entry_id]):
            continue  # Private quoted intent is withheld with its source-derived output.
        version = s.get(ProviderTeamRevision, row.team_revision_id)
        command = row.request_body
        config = next(
            (
                bot
                for bot in version.configuration["bots"]
                if team.bot_address(bot) == command["role"]
            ),
            None,
        )
        if config is None:
            raise ws.WorkspaceError("model_observation_unavailable", 503)
        if row.kind == "conversation":
            binding = {
                "kind": "conversation",
                **{
                    key: command[key]
                    for key in ("expected_revision", "team_revision", "idempotency_key", "role")
                },
            }
            if "research_analysis" in command:
                from cosmas_os.application.research_analysis import selection

                binding["research_analysis"] = selection(command["research_analysis"])
            if "inbox_analysis" in command:
                from cosmas_os.application.inbox_analysis import selection

                binding["inbox_analysis"] = selection(command["inbox_analysis"])
            if "membership_analysis" in command:
                from cosmas_os.application.membership_analysis import selection

                binding["membership_analysis"] = selection(command["membership_analysis"])
            if "session_prep_analysis" in command:
                from cosmas_os.application.session_prep_analysis import selection

                binding["session_prep_analysis"] = selection(command["session_prep_analysis"])
        else:
            attempt = s.get(WorkspaceHandoffAttempt, row.handoff_attempt_id)
            binding = {
                "kind": "private_handoff",
                "handoff_id": attempt.handoff_id,
                "attempt_id": attempt.id,
            }
        metadata = {
            "contract_version": 1,
            "request_sha256": row.request_hash,
            "request": binding,
            "bot": {
                "address": command["role"],
                "agent_id": row.agent_id,
                "role": config["role"],
                "name": config["name"],
                "team_revision": version.revision,
            },
            "admission": admission_observation(s, row, as_of),
            "reason": _reason(row, as_of),
        }
        entries[row.request_entry_id]["model_request"] = checked_response(
            metadata, EntryModelRequest, maximum=ENTRY_MODEL_BYTES
        )
    return {**value, "model_contract_version": 1, "model_observed_at": as_of.isoformat()}


def reserve_children(
    s, workspace, origin, version, chief, context, briefs, *, external_identity_id, clock=None, prepared_contract=None
):
    from dataclasses import replace

    from cosmas_os.application import handoffs

    if len(briefs) > 3 or len({brief.role for brief in briefs}) != len(briefs):
        raise ws.WorkspaceError("invalid_handoff", 400)
    queued = refused = 0
    for brief in briefs:
        if (
            brief.role not in context.handoff_roles
            or not brief.brief.strip()
            or len(brief.brief) > 4000
        ):
            raise ws.WorkspaceError("invalid_handoff", 400)
        # The prepared recipient has an immutable identity, even if it was
        # disabled while Chief was running; such a child is never dispatched.
        config = next(
            bot for bot in version.configuration["bots"] if team.bot_address(bot) == brief.role
        )
        from cosmas_os.models import ProviderBot

        recipient = s.scalar(
            select(ProviderBot).where(
                ProviderBot.box_id == workspace.box_id,
                ProviderBot.owner_id == workspace.owner_id,
                (ProviderBot.instance_id == brief.role)
                if config.get("instance_id")
                else and_(ProviderBot.instance_id.is_(None), ProviderBot.role == brief.role),
            )
        )
        assignment = WorkspaceHandoff(
            workspace_id=workspace.id,
            box_id=workspace.box_id,
            owner_id=workspace.owner_id,
            origin_entry_id=origin.id,
            issuer_agent_id=chief.agent_id,
            recipient_agent_id=recipient.agent_id,
            recipient_role=config["role"],
            recipient_name=config["name"],
            team_revision_id=version.id,
            context_revision=context.context_revision,
            brief=brief.brief,
        )
        s.add(assignment)
        s.flush()
        at = now(s, clock)
        reason = None
        try:
            team.active_bot(s, workspace.box_id, workspace.owner_id, brief.role, version.revision)
            if workspace.revision >= 500 or workspace_units(s, workspace.id) >= 50:
                raise ws.WorkspaceError("team_work_limit")
            _allowance(s, workspace.box_id, workspace.owner_id, at, version.configuration)
        except ws.WorkspaceError as error:
            reason = "team_work_limit" if error.code == "team_work_limit" else "authority_changed"
        attempt = WorkspaceHandoffAttempt(
            handoff_id=assignment.id,
            workspace_id=workspace.id,
            box_id=workspace.box_id,
            owner_id=workspace.owner_id,
            number=1,
            status="failed" if reason else "queued",
            idempotency_key="initial",
            request_hash=payload_hash({"origin": origin.id, "role": brief.role}),
            error_code=reason,
            completed_at=at if reason else None,
        )
        s.add(attempt)
        s.flush()
        if reason:
            refused += 1
            handoffs._audit(s, attempt, "not_admitted")
            continue
        command = {
            "expected_revision": workspace.revision,
            "team_revision": version.revision,
            "idempotency_key": "handoff:" + attempt.id,
            "role": brief.role,
            "content": brief.brief,
        }
        child_context = _context_for(
            s, workspace, version, config, recipient, command, draft_only=True,
            prepared_contract=prepared_contract
        )
        child_context = replace(child_context, context_revision=context.context_revision)
        if brief.requirements is not None:
            try:
                task = handoff_briefs.prepare(brief, child_context, origin,
                    version=2 if prepared_contract == handoff_briefs.FULL_SOURCE_CONTRACT else 1,
                    prepared_contract=prepared_contract)
            except (ValueError, TypeError, KeyError):
                raise ws.WorkspaceError("invalid_model_output") from None
            command["task_brief"] = task
            child_context = replace(child_context, question=handoff_briefs.question(task))
        request_hash = payload_hash({"handoff": assignment.id, "attempt": attempt.id})
        _new_admission(
            s,
            workspace,
            version,
            config,
            recipient,
            command,
            request_hash,
            child_context,
            at,
            external_identity_id,
            attempt=attempt,
        )
        handoffs._audit(s, attempt, "queued")
        queued += 1
    return queued, refused


def attempt_state(s, attempt, as_of):
    row = s.scalar(
        select(ModelWorkAdmission).where(ModelWorkAdmission.handoff_attempt_id == attempt.id)
    )
    if row:
        state = effective_state(row, as_of)
        return (
            {
                "reserved": "queued",
                "running": "running",
                "completed": "completed",
                "failed": "failed",
                "unknown": "interrupted",
                "abandoned": "interrupted",
            }[state],
            _reason(row, as_of),
            row,
        )
    if attempt.status in {"queued", "running"}:
        return (
            "interrupted",
            "legacy_queued_unadmitted"
            if attempt.status == "queued"
            else "legacy_running_unconfirmed",
            None,
        )
    return attempt.status, attempt.error_code, None


def retry_observation(s, workspace, hid, *, expected, previous_attempt, key, as_of):
    assignment = s.scalar(
        select(WorkspaceHandoff).where(
            WorkspaceHandoff.id == hid,
            WorkspaceHandoff.workspace_id == workspace.id,
            WorkspaceHandoff.box_id == workspace.box_id,
            WorkspaceHandoff.owner_id == workspace.owner_id,
        )
    )
    if assignment is None:
        raise ws.WorkspaceError("handoff_unavailable", 404)
    request_hash = payload_hash({"expected": expected, "previous_attempt": previous_attempt})
    result = {
        "contract_version": 1,
        "workspace_id": workspace.id,
        "handoff_id": hid,
        "previous_attempt_id": previous_attempt,
        "idempotency_key": key,
        "request_sha256": request_hash,
        "outcome": "not_found",
        "recorded": None,
    }
    attempt = s.scalar(
        select(WorkspaceHandoffAttempt).where(
            WorkspaceHandoffAttempt.handoff_id == hid,
            WorkspaceHandoffAttempt.idempotency_key == key,
        )
    )
    if attempt is None:
        return checked_response(result, HandoffRetryObservation)
    if attempt.request_hash != request_hash or attempt.number not in {2, 3}:
        raise ws.WorkspaceError("idempotency_conflict")
    previous = s.scalar(
        select(WorkspaceHandoffAttempt).where(
            WorkspaceHandoffAttempt.handoff_id == hid,
            WorkspaceHandoffAttempt.number == attempt.number - 1,
        )
    )
    if previous is None or previous.id != previous_attempt:
        raise ws.WorkspaceError("idempotency_conflict")
    status, reason, row = attempt_state(s, attempt, as_of)
    entry = s.get(WorkspaceEntry, row.request_entry_id) if row else None
    actual_result = (
        s.get(WorkspaceEntry, attempt.result_entry_id) if attempt.result_entry_id else None
    )
    if actual_result and s.get(WorkspaceReply, actual_result.id) is None:
        raise ws.WorkspaceError("model_observation_unavailable", 503)
    if row and (row.result_entry_id != attempt.result_entry_id or entry is None):
        raise ws.WorkspaceError("model_observation_unavailable", 503)
    safe_reason = (
        reason
        if reason
        in {
            "model_unavailable",
            "authority_changed",
            "source_changed",
            "dispatch_interrupted",
            "reservation_expired",
            "team_work_limit",
            "legacy_queued_unadmitted",
            "legacy_running_unconfirmed",
        }
        else (
            "authority_changed"
            if status == "failed"
            else "dispatch_interrupted"
            if status == "interrupted"
            else None
        )
    )
    result.update(
        outcome="recorded",
        recorded={
            "attempt_id": attempt.id,
            "attempt_number": attempt.number,
            "recorded_at": attempt.created_at.isoformat(),
            "workspace_revision": entry.revision
            if entry
            else max(expected, actual_result.revision if actual_result else expected),
            "status": status,
            "result_entry": {"id": actual_result.id, "revision": actual_result.revision}
            if actual_result
            else None,
            "admission": admission_observation(s, row, as_of) if row else None,
            "coverage": "durable_admission" if row else "retained_legacy",
            "reason": safe_reason,
        },
    )
    return checked_response(result, HandoffRetryObservation)


def resolve_retry(
    s,
    box,
    owner,
    wid,
    hid,
    *,
    expected,
    previous_attempt,
    key,
    external_identity_id=None,
    reauthenticate=None,
    clock=None,
):
    if reauthenticate:
        reauthenticate()
    workspace = read_workspace(s, box, owner, wid, external_identity_id)
    return retry_observation(
        s,
        workspace,
        hid,
        expected=expected,
        previous_attempt=previous_attempt,
        key=key,
        as_of=now(s, clock),
    )


def reserve_retry(
    s,
    box,
    owner,
    wid,
    hid,
    *,
    expected,
    previous_attempt,
    key,
    external_identity_id=None,
    reauthenticate=None,
    clock=None,
):
    from cosmas_os.application import handoffs

    s.rollback()
    lock_owner(s, box, owner)
    if reauthenticate:
        reauthenticate()
    _identity(s, box, owner, external_identity_id)
    workspace = ws._workspace(s, box, owner, wid, writing=True)
    at = now(s, clock)
    prior = retry_observation(
        s, workspace, hid, expected=expected, previous_attempt=previous_attempt, key=key, as_of=at
    )
    if prior["outcome"] == "recorded":
        s.commit()
        return prior
    if workspace.revision != expected:
        raise ws.WorkspaceError("workspace_revision_conflict")
    if not team.runtime_settings.workspace_llm_available:
        raise ws.WorkspaceError("model_unavailable")
    assignment = s.get(WorkspaceHandoff, hid)
    version, bot, settings = handoffs._check_context(s, workspace, assignment)
    latest = s.scalar(
        select(WorkspaceHandoffAttempt)
        .where(WorkspaceHandoffAttempt.handoff_id == hid)
        .order_by(WorkspaceHandoffAttempt.number.desc())
        .limit(1)
        .with_for_update()
    )
    status, reason, old = attempt_state(s, latest, at)
    if latest.id != previous_attempt or status not in {"failed", "interrupted"}:
        raise ws.WorkspaceError("handoff_attempt_conflict")
    if latest.number >= 3 or workspace_units(s, wid) >= 50:
        raise ws.WorkspaceError("handoff_limit")
    original = s.scalar(select(ModelWorkAdmission).join(
        WorkspaceHandoffAttempt, WorkspaceHandoffAttempt.id == ModelWorkAdmission.handoff_attempt_id
    ).where(WorkspaceHandoffAttempt.handoff_id == hid).order_by(WorkspaceHandoffAttempt.number).limit(1))
    parent = s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.request_entry_id == assignment.origin_entry_id))
    if parent and parent.envelope_contract in {"cosmas-gpt41-prepared.v4", *TOOL_PREPARED_CONTRACTS} and (original is None or "task_brief" not in original.request_body):
        raise ws.WorkspaceError("handoff_context_changed")
    _allowance(s, box, owner, now(s, clock), version.configuration)
    if old and old.state in ACTIVE:
        _finish(s, old, effective_state(old, at), reason, at)
    elif old is None and latest.status in {"queued", "running"}:
        handoffs._terminal(s, latest, "interrupted", error=reason)
    s.flush()
    attempt = WorkspaceHandoffAttempt(
        handoff_id=hid,
        workspace_id=wid,
        box_id=box,
        owner_id=owner,
        number=latest.number + 1,
        status="queued",
        idempotency_key=key,
        request_hash=payload_hash({"expected": expected, "previous_attempt": previous_attempt}),
    )
    s.add(attempt)
    s.flush()
    command = {
        "expected_revision": expected,
        "team_revision": version.revision,
        "idempotency_key": "handoff:" + attempt.id,
        "role": team.bot_address(settings),
        "content": assignment.brief,
    }
    if original and "task_brief" in original.request_body:
        command["task_brief"] = original.request_body["task_brief"]
        if "revision_request" in original.request_body:
            command["revision_request"] = original.request_body["revision_request"]
    context = _context_for(s, workspace, version, settings, bot, command, draft_only=True,
        prepared_contract=original.envelope_contract if original else None)
    _new_admission(
        s,
        workspace,
        version,
        settings,
        bot,
        command,
        payload_hash({"handoff": hid, "attempt": attempt.id}),
        context,
        now(s, clock),
        external_identity_id,
        attempt=attempt,
    )
    handoffs._audit(s, attempt, "queued")
    s.commit()
    return resolve_retry(
        s,
        box,
        owner,
        wid,
        hid,
        expected=expected,
        previous_attempt=previous_attempt,
        key=key,
        external_identity_id=external_identity_id,
        reauthenticate=reauthenticate,
        clock=clock,
    )


def recover_expired(s, *, clock=None, maximum=100):
    # Discovery takes no row lock. Each transition follows the same owner-first
    # order as reserve/claim/settle; no SKIP LOCKED inference assumptions remain.
    s.rollback()
    at = now(s, clock)
    ids = list(
        s.execute(
            select(
                ModelWorkAdmission.id,
                ModelWorkAdmission.box_id,
                ModelWorkAdmission.owner_id,
                ModelWorkAdmission.workspace_id,
            )
            .where(
                or_(
                    and_(
                        ModelWorkAdmission.state == "reserved",
                        ModelWorkAdmission.reservation_expires_at <= at,
                    ),
                    and_(
                        ModelWorkAdmission.state == "running",
                        ModelWorkAdmission.lease_ends_at <= at,
                    ),
                )
            )
            .order_by(ModelWorkAdmission.admitted_at)
            .limit(maximum)
        )
    )
    s.rollback()
    for aid, box, owner, wid in ids:
        lock_owner(s, box, owner, active=False)
        s.scalar(select(EncounterWorkspace).where(EncounterWorkspace.id == wid).with_for_update())
        row = s.scalar(
            select(ModelWorkAdmission).where(ModelWorkAdmission.id == aid).with_for_update()
        )
        at = now(s, clock)
        state = effective_state(row, at)
        if row.state in ACTIVE and state in TERMINAL:
            _finish(
                s,
                row,
                state,
                "reservation_expired" if state == "abandoned" else "dispatch_interrupted",
                at,
            )
        s.commit()
    return len(ids)


def process_next(factory, *, dispatch=None, clock=None):
    with factory() as s:
        recover_expired(s, clock=clock)
        candidates = s.execute(
            select(ModelWorkAdmission.id, ModelWorkAdmission.box_id, ModelWorkAdmission.owner_id)
            .where(
                ModelWorkAdmission.kind == "private_handoff", ModelWorkAdmission.state == "reserved"
            )
            .order_by(ModelWorkAdmission.admitted_at, ModelWorkAdmission.id)
            .limit(3)
        ).all()
        claimed = None
        for aid, box, owner in candidates:
            claimed = claim(s, box, owner, aid, clock=clock)
            if claimed is not None:
                break
            current = s.get(ModelWorkAdmission, aid)
            if current is not None and current.state in {"failed", "abandoned"}:
                return True
    if claimed is None:
        return False
    try:
        result = (dispatch or dispatch_claim)(claimed)
    except ModelCallFailure as failure:
        result = failure
    with factory() as s:
        settle(s, claimed, result, clock=clock)
    return True
