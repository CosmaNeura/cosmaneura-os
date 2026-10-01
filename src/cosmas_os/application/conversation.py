"""Atomic human turns and attributed local tool replies; no external dispatch."""

from typing import Any

from sqlalchemy.orm import Session

from cosmas_os.adapters.workspace_review import WorkspaceReviewConnector
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings as runtime_settings
from cosmas_os.models import WorkspaceEntry, WorkspaceReply
from cosmas_os.ports.bot_capabilities import (
    BotContext,
    FollowUpStatus,
    SourcePassage,
    supports_skill,
)


def build_context(
    snapshot,
    version,
    settings,
    role,
    content,
    *,
    handoff_roles=(),
    include_history=True,
    draft_only=False,
    agent_id=None,
    handoff_targets=(),
    additional_sources=(),
    session_prep_analysis=None,
):
    # Only the latest typed draft is current. Evidence remains explicitly attributed.
    notes = [e for e in snapshot["entries"] if e["kind"] == "scratchpad"][-1:]
    evidence = [e for e in snapshot["entries"] if e["kind"] in {"evidence", "synthetic_source"}]
    selected = (notes if settings["include_notebook"] else []) + (
        evidence if settings["include_evidence"] else []
    )
    if not supports_skill(settings, "saved_context"):
        selected = []
    can_read_work = supports_skill(settings, "work_status")
    sources = tuple(
        SourcePassage(
            e["id"],
            e["revision"],
            e["source_label"] or "Your jotted notes",
            e["kind"],
            e["content"],
        )
        for e in selected
    )
    latest_source_revision = max((source.revision for source in sources), default=0)
    sources += tuple(additional_sources)
    from cosmas_os.application.scribe_source import require_complete_context
    require_complete_context(sources)
    source_ids = {source.entry_id for source in sources}
    follow_ups = tuple(
        FollowUpStatus(
            item["ticket_id"],
            item["state"],
            item["due_date"],
            item["source_changed"],
            any(receipt["kind"] == "local_delivery" for receipt in item["receipts"]),
            any(receipt["kind"] == "human_completion" for receipt in item["receipts"]),
        )
        for item in snapshot.get("follow_ups", ())
        if can_read_work
    )
    follow_up_ids = {item.ticket_id for item in follow_ups}
    history = []
    for past in snapshot["entries"] if include_history else ():
        response = past.get("reply")
        if (
            past["kind"] not in {"conversation", "handoff_result"}
            or not response
            or response["role"] != role
            or agent_id is not None
            and response.get("agent_id") != agent_id
        ):
            continue
        if (
            response.get("team_revision_id") != version.id
            or response["context_revision"] < latest_source_revision
        ):
            continue
        # A prior answer must not reintroduce a source excluded by new settings or a superseded draft.
        prior_prep = past.get("model_request", {}).get("request", {}).get("session_prep_analysis")
        if prior_prep is not None and prior_prep != session_prep_analysis:
            continue  # Even an uncited answer can contain a now-excluded brief.
        if not {c["entry_id"] for c in response["citations"]} <= source_ids:
            continue
        history.extend([("user", past["content"]), ("assistant", response["content"])])
    return BotContext(
        snapshot["id"],
        snapshot["revision"],
        role,
        content,
        settings["response_style"],
        sources,
        tuple(
            (e["ticket"]["lane"], e["ticket"]["state"])
            for e in snapshot["entries"]
            if can_read_work
            and e["kind"] == "work_link"
            and e["ticket"]
            and e["ticket"]["id"] not in follow_up_ids
        ),
        tuple(history[-8:]),
        version.configuration["practice_context"],
        tuple(handoff_roles),
        draft_only,
        follow_ups,
        settings.get("job_focus", ""),
        settings.get("working_preferences", ""),
        tuple(handoff_targets),
        tuple(settings.get("skills", ())),
    )


def generate_reply(context):
    """Deterministic local renderer; model dispatch requires a saved admission."""
    return WorkspaceReviewConnector().review(context)


def ask(
    s: Session,
    box: str,
    owner: str,
    wid: str,
    *,
    expected: int,
    team_revision: int,
    key: str,
    role: str,
    content: str,
    model_contract=False,
    research_analysis=None,
    inbox_analysis=None,
    membership_analysis=None,
    session_prep_analysis=None,
    external_identity_id=None,
    reauthenticate=None,
):
    from cosmas_os.application import model_work

    command: dict[str, Any] = dict(
        expected=expected, team_revision=team_revision, key=key, role=role, content=content
    )
    if research_analysis is not None:
        from cosmas_os.application.research_analysis import selection

        command["research_analysis"] = selection(research_analysis)
        if not model_contract:
            raise ws.WorkspaceError("model_contract_required", 426)
    if inbox_analysis is not None:
        from cosmas_os.application.inbox_analysis import selection

        command["inbox_analysis"] = selection(inbox_analysis)
        if not model_contract:
            raise ws.WorkspaceError("model_contract_required", 426)
    if membership_analysis is not None:
        from cosmas_os.application.membership_analysis import selection

        command["membership_analysis"] = selection(membership_analysis)
        if not model_contract:
            raise ws.WorkspaceError("model_contract_required", 426)
    if session_prep_analysis is not None:
        from cosmas_os.application.session_prep_analysis import selection

        command["session_prep_analysis"] = selection(session_prep_analysis)
        if not model_contract:
            raise ws.WorkspaceError("model_contract_required", 426)
    s.rollback()
    model_work.lock_owner(s, box, owner)
    if reauthenticate:
        reauthenticate()
    model_work._identity(s, box, owner, external_identity_id)
    w = ws._workspace(s, box, owner, wid, writing=True)
    digest = model_work.conversation_request_hash(
        expected=expected, team_revision=team_revision, role=role, content=content,
        research_analysis=research_analysis, inbox_analysis=inbox_analysis, membership_analysis=membership_analysis,
        session_prep_analysis=session_prep_analysis,
    )
    prior = model_work.conversation_observation(
        s, w, key=key, request_hash=digest, as_of=model_work.now(s)
    )
    if prior["outcome"] != "not_found":
        if model_contract:
            s.commit()
            return prior
        if prior["outcome"] != "saved":
            raise ws.WorkspaceError("model_contract_required", 426)
        anchor = prior["saved_entry"]
        return {
            "entry_id": anchor["id"],
            "entry_revision": anchor["revision"],
            "workspace": ws.read(s, box, owner, wid, at_revision=anchor["revision"]),
        }
    version, bot, settings = team.active_bot(s, box, owner, role, team_revision)
    if settings["role"] == "custom" and settings.get("skills") == ["membership_review"] and membership_analysis is None:
        raise ws.WorkspaceError("membership_selection_required")
    use_model = runtime_settings.workspace_llm_available and not team.blocked(
        settings, "model_answer"
    )
    if any(value is not None for value in (research_analysis, inbox_analysis, membership_analysis, session_prep_analysis)) and not use_model:
        raise ws.WorkspaceError("model_unavailable")
    if use_model:
        if not model_contract:
            raise ws.WorkspaceError("model_contract_required", 426)
        return model_work.run_conversation(
            s,
            box,
            owner,
            wid,
            external_identity_id=external_identity_id,
            reauthenticate=reauthenticate,
            **command,
        )
    if expected != w.revision:
        raise ws.WorkspaceError("workspace_revision_conflict")
    if w.revision >= 500:
        raise ws.WorkspaceError("workspace_history_limit")
    if not content or len(content) > 4000:
        raise ws.WorkspaceError("invalid_entry", 400)
    snapshot = model_work.project_workspace(s, ws.read(s, box, owner, wid))
    context = build_context(
        snapshot,
        version,
        settings,
        settings["role"],
        content,
        agent_id=bot.agent_id,
    )
    if settings["role"] == "chief":
        from cosmas_os.adapters.chief_review import review
        from cosmas_os.application.operations_status import linked

        reply = review(context, operational_rows=linked(s, box, owner, wid, snapshot, settings))
    else:
        reply = generate_reply(context)
    w.revision += 1
    entry = WorkspaceEntry(
        workspace_id=wid,
        box_id=box,
        actor_id=owner,
        revision=w.revision,
        kind="conversation",
        content=content,
        idempotency_key=key,
        request_hash=digest,
    )
    s.add(entry)
    s.flush()
    record_reply(s, w, entry, version, bot, settings, context, reply)
    entry_id, entry_revision = entry.id, entry.revision
    s.commit()
    if model_contract:
        return model_work.resolve_conversation(
            s,
            box,
            owner,
            wid,
            external_identity_id=external_identity_id,
            reauthenticate=reauthenticate,
            **command,
        )
    return {
        "entry_id": entry_id,
        "entry_revision": entry_revision,
        "workspace": ws.read(s, box, owner, wid, at_revision=entry_revision),
    }


def record_reply(s, w, entry, version, bot, settings, context, reply):
    wid, box, owner = w.id, w.box_id, w.owner_id
    s.add(
        WorkspaceReply(
            entry_id=entry.id,
            workspace_id=wid,
            box_id=box,
            owner_id=owner,
            agent_id=bot.agent_id,
            team_revision_id=version.id,
            agent_name=settings["name"],
            role=context.role,
            backend=reply.backend,
            context_revision=context.context_revision,
            content=reply.content,
            citations=[
                {
                    "entry_id": source.entry_id,
                    "revision": source.revision,
                    "label": source.label,
                    "kind": source.kind,
                }
                for source in reply.citations
            ],
        )
    )
    ws._audit(
        s, w, "handoff_result_saved" if entry.kind == "handoff_result" else "conversation_saved"
    )
    if reply.backend.startswith("azure_gpt41"):
        from cosmas_os.models import AuditEvent

        s.add(
            AuditEvent(
                box_id=box,
                aggregate_type="workspace",
                aggregate_id=wid,
                event_type="workspace.model_usage",
                actor_principal_id=bot.agent_id,
                initiated_by_principal_id=owner,
                outcome="unavailable" if reply.backend.endswith("unavailable") else "completed",
                detail={
                    "model": "gpt-4.1",
                    "input_tokens": reply.input_tokens,
                    "output_tokens": reply.output_tokens,
                },
            )
        )
