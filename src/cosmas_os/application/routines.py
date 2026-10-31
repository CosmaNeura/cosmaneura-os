"""Owner-scheduled, private reports over existing F-8 shared work.

All source reads and the immutable output commit in one local transaction.
There is no pending-action queue, model call, notification or external port.
"""

import asyncio
from datetime import timedelta
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from cosmas_os.api.routine_brief_schemas import IncomingSection
from cosmas_os.api.vendor_work_schemas import bounded
from cosmas_os.application import follow_up, provider_team, routine_inbox, shared_work
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import AuditEvent, ProviderBot, RoutineRevision, RoutineRun
from cosmas_os.ports.bot_capabilities import supports_skill
from cosmas_os.ports.routines import BriefSchedule


def _local(s):
    if settings.workspace_hosted_enabled:
        # Private routine records may use the configured synthetic staging DB.
        # Only routine source reads opt in; delivery keeps its separate gate.
        if (not settings.workspace_available or settings.data_mode != "synthetic"
                or s.get_bind().engine.url != make_url(settings.database_url)):
            raise ws.WorkspaceError("routines_connection_required", 403)
    else:
        follow_up._local(s)
    if not settings.workspace_routines_enabled:
        raise ws.WorkspaceError("routines_unavailable", 404)


def _now(s):
    return s.scalar(select(func.clock_timestamp()))


def _bot(s, box, owner, address, *, writing=False):
    _local(s)
    ws._human(s, box, owner, creating=writing)
    bot = s.scalar(select(ProviderBot).where(ProviderBot.box_id == box,
        ProviderBot.owner_id == owner,
        ProviderBot.role == address if address in {"chief", "scribe", "visit_prep", "follow_up"}
        else ProviderBot.instance_id == address,
        ProviderBot.instance_id.is_(None) if address in {"chief", "scribe", "visit_prep", "follow_up"}
        else ProviderBot.instance_id.is_not(None)))
    if bot is None:
        raise ws.WorkspaceError("routine_unavailable", 404)
    return bot


def _latest(s, bot):
    return s.scalar(select(RoutineRevision).where(RoutineRevision.agent_id == bot.agent_id,
        RoutineRevision.box_id == bot.box_id, RoutineRevision.owner_id == bot.owner_id)
        .order_by(RoutineRevision.revision.desc()).limit(1))


def _recent(s, bot, limit=20):
    return list(s.scalars(select(RoutineRun).where(RoutineRun.agent_id == bot.agent_id,
        RoutineRun.box_id == bot.box_id, RoutineRun.owner_id == bot.owner_id)
        .order_by(RoutineRun.completed_at.desc(), RoutineRun.id).limit(limit)))


def _eligibility(s, bot, revision, now):
    config = BriefSchedule.model_validate(revision.configuration)
    if not config.enabled:
        return "paused", None
    current = provider_team.current(s, bot.box_id, bot.owner_id)
    if current is None or current.id != revision.team_revision_id:
        return "team_changed", None
    try:
        _, _, bot_config = provider_team.active_bot(s, bot.box_id, bot.owner_id,
            bot.instance_id or bot.role, current.revision)
    except ws.WorkspaceError:
        return "bot_unavailable", None
    if not supports_skill(bot_config, "work_status"):
        return "skill_unavailable", None
    if provider_team.blocked(bot_config, "practice_work_brief"):
        return "restricted", None
    state, scheduled = config.due(now, revision.created_at)
    if state != "due":
        return state, scheduled
    day = now.astimezone(ZoneInfo(config.timezone)).date()
    if s.scalar(select(RoutineRun.id).where(RoutineRun.agent_id == bot.agent_id,
                                          RoutineRun.local_date == day)):
        return "already_run", scheduled
    runs = list(s.scalars(select(RoutineRun.completed_at).where(
        RoutineRun.agent_id == bot.agent_id, RoutineRun.completed_at > now - timedelta(days=7))))
    # Changing the schedule or time zone never resets its rolling limit. The
    # minimum spacing also prevents a date-line/time-zone edit causing a burst.
    if len(runs) >= config.max_runs_per_seven_days or any(t > now - timedelta(hours=20) for t in runs):
        return "run_limit", scheduled
    return "due", scheduled


def _metadata(run):
    return {"id": run.id, "scheduled_at": run.scheduled_at.isoformat(),
            "completed_at": run.completed_at.isoformat(), "local_date": run.local_date.isoformat()}


def _view(s, bot, revision):
    now = _now(s)
    team = provider_team.current(s, bot.box_id, bot.owner_id)
    config = BriefSchedule.model_validate(revision.configuration) if revision else None
    status = _eligibility(s, bot, revision, now)[0] if revision else "not_configured"
    upcoming = config.next_occurrence(now) if config and config.enabled else None
    return {"bot": bot.instance_id or bot.role, "agent_id": bot.agent_id,
        "revision": revision.revision if revision else 0, "team_revision": team.revision if team else 0,
        "configuration": config.model_dump(mode="json") if config else None, "status": status,
        "next_scheduled_at": upcoming.isoformat() if upcoming else None,
        "runs": [_metadata(run) for run in _recent(s, bot)]}


def read(s, box, owner, address):
    bot = _bot(s, box, owner, address)
    return _view(s, bot, _latest(s, bot))


def save(s, box, owner, address, *, expected, team_revision, key, configuration):
    bot = _bot(s, box, owner, address, writing=True)
    try:
        config = BriefSchedule.model_validate(configuration)
    except ValidationError:
        raise ws.WorkspaceError("invalid_routine", 422) from None
    if not isinstance(key, str) or not 1 <= len(key) <= 100:
        raise ws.WorkspaceError("invalid_routine", 422)
    value = config.model_dump(mode="json")
    digest = payload_hash({"expected": expected, "team_revision": team_revision, "configuration": value})
    prior = s.scalar(select(RoutineRevision).where(RoutineRevision.agent_id == bot.agent_id,
                                                  RoutineRevision.idempotency_key == key))
    if prior:
        if prior.request_hash != digest:
            raise ws.WorkspaceError("idempotency_conflict")
        return _view(s, bot, prior)
    latest = _latest(s, bot)
    revision = latest.revision if latest else 0
    if revision != expected:
        raise ws.WorkspaceError("routine_revision_conflict")
    if revision >= 100:
        raise ws.WorkspaceError("routine_history_limit")
    current = provider_team.current(s, box, owner)
    if current is None or current.revision != team_revision:
        raise ws.WorkspaceError("team_revision_conflict")
    if config.enabled:
        _, _, bot_config = provider_team.active_bot(s, box, owner, address, team_revision)
        if not supports_skill(bot_config, "work_status"):
            raise ws.WorkspaceError("routine_skill_required")
    row = RoutineRevision(box_id=box, owner_id=owner, agent_id=bot.agent_id,
        revision=revision + 1, team_revision_id=current.id, configuration=value,
        idempotency_key=key, request_hash=digest)
    s.add(row)
    s.flush()
    s.add(AuditEvent(box_id=box, aggregate_type="private_routine", aggregate_id=row.id,
        actor_principal_id=owner, event_type="routine.configured",
        outcome="enabled" if config.enabled else "paused",
        detail={"revision": row.revision}))
    s.commit()
    return _view(s, bot, row)


def _counts(items, day):
    # A dated publication can remain readable after withdrawal or replacement.
    # Neither state represents active work or a verified outcome.
    opened = [item for item in items if item["state"] in {"sent", "approved"}]
    return {"open": len(opened),
        "overdue": sum(item["due_date"] < day for item in opened),
        "awaiting_acceptance": sum(item["pending_offer"] for item in opened),
        "responsible_unavailable": sum(not item["responsible"]["available"] for item in opened),
        "verified_complete": sum(item["state"] == "closed" and item["human_completion"] for item in items)}


def _snapshot(s, box, owner, day):
    items, cursor = [], None
    # Bound every run; a partial result is explicitly identified.
    for _ in range(4):
        page = shared_work.catalog(s, box, owner, after=cursor, vendor=True, _routine_read=True)
        for item in page["items"]:
            kind, state = item.get("work_kind"), item["state"]
            supported = {"follow_up": {"sent", "closed"},
                "visit_preparation": {"approved", "closed"},
                "vendor_delivery": {"approved", "closed", "withdrawn", "superseded"}}
            if kind not in supported or state not in supported[kind]:
                raise ws.WorkspaceError("routine_result_unavailable")
            items.append({"ticket_id": item["ticket_id"], "revision_id": item["revision_id"],
                "payload_hash": item["payload_hash"], "version": item["version"],
                "work_kind": kind, "state": state,
                "ready_for_review": state == "approved" and item["ready_for_review"],
                "body": item["body"][:180],
                "due_date": item["due_date"], "responsible": {
                    **item["responsible"], "name": item["responsible"]["name"][:80]},
                "pending_offer": item["pending_offer"] is not None,
                "human_completion": state == "closed" and (
                    item["vendor_work"]["verification"] == "verified"
                    if kind == "vendor_delivery" else any(r["kind"] in {"human_completion", "provider_verification"}
                    for r in item["receipts"]))})
        cursor = page["next_cursor"]
        if cursor is None:
            break
    return {"kind": "practice_work_brief", "local_date": day, "items": items,
            "counts": _counts(items, day), "truncated": cursor is not None,
            "source": "F-8 shared follow-ups", "model_used": False}


def run_once(s, box, owner, address, *, incoming_sources=None):
    """A tick is safe to retry after a lost reply, concurrent tick or restart."""
    bot = _bot(s, box, owner, address, writing=True)
    revision = _latest(s, bot)
    if revision is None:
        return {"status": "not_configured"}
    now = _now(s)
    state, scheduled = _eligibility(s, bot, revision, now)
    if state != "due":
        return {"status": state}
    if settings.workspace_enrollment_managed:
        from cosmas_os.application.enrollment_access import require_worker_admission
        require_worker_admission(s, settings, box=box, owner=owner, operation_id=revision.id,
                                 approval_sha256=revision.request_hash)
    config = BriefSchedule.model_validate(revision.configuration)
    day = now.astimezone(ZoneInfo(config.timezone)).date()
    snapshot = _snapshot(s, box, owner, day.isoformat())
    if incoming_sources is not None:
        incoming = routine_inbox.snapshot(s, box, owner, day.isoformat(), incoming_sources)
        incoming = IncomingSection.model_validate(incoming).public()
        snapshot = {"snapshot_version": 2, "generic": snapshot, "incoming": incoming}
        bounded(snapshot, 524288)
    # The flag can be revoked while source reads take place. No output is
    # published without this final check; no remote effect has occurred.
    _local(s)
    current_team = provider_team.current(s, box, owner)
    if current_team is None:
        raise ws.WorkspaceError("team_revision_conflict")
    _, _, current_bot_config = provider_team.active_bot(s, box, owner, address,
        current_team.revision)
    if provider_team.blocked(current_bot_config, "practice_work_brief"):
        raise ws.WorkspaceError("bot_capability_restricted")
    if incoming_sources is not None:
        checked = routine_inbox.reauthorize(s, box, owner, snapshot["incoming"], day.isoformat(), incoming_sources)
        if checked != snapshot["incoming"]:
            raise ws.WorkspaceError("routine_sources_changed")
    _local(s)
    if settings.workspace_enrollment_managed:
        require_worker_admission(s, settings, box=box, owner=owner, operation_id=revision.id,
                                 approval_sha256=revision.request_hash)
    row = RoutineRun(agent_id=bot.agent_id, box_id=box, owner_id=owner,
        routine_revision_id=revision.id, local_date=day, scheduled_at=scheduled,
        completed_at=_now(s), snapshot=snapshot, snapshot_hash=payload_hash(snapshot))
    s.add(row)
    s.flush()
    s.add(AuditEvent(box_id=box, aggregate_type="private_routine", aggregate_id=row.id,
        actor_principal_id=bot.agent_id, initiated_by_principal_id=owner,
        event_type="routine.brief_completed", outcome="completed",
        detail={"routine_revision_id": revision.id}))
    s.commit()
    return {"status": "completed", "run": _metadata(row)}


def read_run(s, box, owner, address, run_id, *, contract=1, incoming_sources=None):
    bot = _bot(s, box, owner, address)
    row = s.scalar(select(RoutineRun).where(RoutineRun.id == run_id,
        RoutineRun.agent_id == bot.agent_id, RoutineRun.box_id == box, RoutineRun.owner_id == owner))
    if row is None:
        raise ws.WorkspaceError("routine_run_unavailable", 404)
    if row.snapshot_hash != payload_hash(row.snapshot):
        raise ws.WorkspaceError("routine_result_unavailable")
    version = row.snapshot.get("snapshot_version", 1)
    if type(version) is not int or version not in {1, 2}:
        raise ws.WorkspaceError("routine_contract_required", 426)
    if contract not in {1, 2} or version == 2 and contract != 2:
        raise ws.WorkspaceError("routine_contract_required", 426)
    generic = row.snapshot if version == 1 else row.snapshot["generic"]
    items, withheld = [], False
    # Historical reports do not bypass current source or tenant authority.
    for item in generic["items"]:
        try:
            current = shared_work.read(s, box, owner, item["ticket_id"], vendor=True,
                                       _routine_read=True)
            if (current["revision_id"], current["payload_hash"]) != (item["revision_id"], item["payload_hash"]):
                withheld = True
                continue
        except ws.WorkspaceError:
            withheld = True
            continue
        items.append(item)
    _local(s)
    items.sort(key=lambda item: (item["state"] not in {"sent", "approved"}, item["due_date"], item["ticket_id"]))
    section = {"items": items, "matching_items": len(items),
        "counts": _counts(items, row.local_date.isoformat()), "withheld_sources": withheld,
        "truncated": generic["truncated"]}
    if contract == 1:
        return {**_metadata(row), "kind": "practice_work_brief", **section,
            "items": items[:10], "model_used": False}
    incoming = routine_inbox.legacy(row.local_date.isoformat()) if version == 1 else routine_inbox.reauthorize(
        s, box, owner, IncomingSection.model_validate(row.snapshot["incoming"]).public(),
        row.local_date.isoformat(), incoming_sources or routine_inbox.Sources())
    incoming = IncomingSection.model_validate(incoming).public()
    authorized_incoming = incoming
    incoming = {**incoming}
    generic_limit = min(len(items), 5 + max(0, 5 - len(incoming["items"])))
    incoming_limit = min(len(incoming["items"]), 10 - generic_limit)
    section["items"] = items[:generic_limit]
    incoming["items"] = incoming["items"][:incoming_limit]
    _local(s)
    callback = s.info.get("routine_final_authority")
    if callback:
        callback()
    if version == 2:
        final_incoming = routine_inbox.reauthorize(s, box, owner,
            IncomingSection.model_validate(row.snapshot["incoming"]).public(), row.local_date.isoformat(),
            incoming_sources or routine_inbox.Sources())
        if IncomingSection.model_validate(final_incoming).public() != authorized_incoming:
            raise ws.WorkspaceError("routine_sources_changed")
    _local(s)
    return bounded({**_metadata(row), "contract_version": 2, "snapshot_version": version,
        "kind": "practice_work_brief", "generic": section, "incoming": incoming,
        "model_used": False}, 32768)


def process_batch(factory, after=None, *, incoming_sources=None):
    """Visit a bounded page; the caller advances so unavailable bots cannot starve others."""
    with factory() as s:
        _local(s)
        query = select(ProviderBot.agent_id, ProviderBot.box_id, ProviderBot.owner_id,
                       ProviderBot.instance_id, ProviderBot.role).where(
                           ProviderBot.agent_id.in_(select(RoutineRevision.agent_id)))
        if after is not None:
            query = query.where(ProviderBot.agent_id > after)
        bots = list(s.execute(query.order_by(ProviderBot.agent_id).limit(20)))
    for _agent_id, box, owner, instance, role in bots:
        with factory() as s:
            try:
                run_once(s, box, owner, instance or role, incoming_sources=incoming_sources)
            except Exception:
                # Atomic rollback leaves this read-only computation retryable.
                # Do not expose patient data through SQL or provider exceptions.
                s.rollback()
    return bots[-1][0] if len(bots) == 20 else None


async def run_worker(factory, stop, *, incoming_sources=None, progress=None):
    cursor = None
    try:
        while not stop.is_set():
            try:
                cursor = await asyncio.to_thread(process_batch, factory, cursor, incoming_sources=incoming_sources)
            except Exception:
                if progress is not None:
                    progress.failed()
            else:
                if progress is not None:
                    progress.succeeded()
            try:
                await asyncio.wait_for(stop.wait(), timeout=10)
            except TimeoutError:
                pass
    finally:
        if progress is not None:
            progress.stopped()
