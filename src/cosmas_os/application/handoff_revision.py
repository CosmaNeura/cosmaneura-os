"""Explicit fresh private revision after current human feedback; no implicit model dispatch."""

import json
import re
from dataclasses import replace

from sqlalchemy import select

from cosmas_os.application import handoff_briefs, handoff_review, handoffs, model_work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import (
    WorkspaceEntry,
    WorkspaceHandoff,
    WorkspaceHandoffAttempt,
    WorkspaceHandoffReview,
    WorkspaceHandoffRevision,
    WorkspaceReply,
)
from cosmas_os.ports.bot_capabilities import DraftBrief
from cosmas_os.ports.task_brief import TaskRequirements

FIELDS = {
    "parent_handoff_id",
    "review_id",
    "attempt_id",
    "result_entry_id",
    "result_sha256",
    "feedback",
}


def _parent(s, w, hid):
    parent = s.scalar(
        select(WorkspaceHandoff).where(
            WorkspaceHandoff.id == hid,
            WorkspaceHandoff.workspace_id == w.id,
            WorkspaceHandoff.box_id == w.box_id,
            WorkspaceHandoff.owner_id == w.owner_id,
        )
    )
    if parent is None:
        raise ws.WorkspaceError("handoff_unavailable", 404)
    attempt = s.scalar(
        select(WorkspaceHandoffAttempt)
        .where(
            WorkspaceHandoffAttempt.handoff_id == hid,
        )
        .order_by(WorkspaceHandoffAttempt.number.desc())
        .limit(1)
    )
    if attempt is None:
        raise ws.WorkspaceError("handoff_result_unavailable")
    return parent, attempt


MAX_REVISION_DEPTH = 3


def revision_depth(s, w, handoff_id):
    """Bound projection before recursive review validation, including corrupt cycles."""
    depth, seen = 0, set()
    while True:
        if handoff_id in seen:
            raise ws.WorkspaceError("handoff_revision_unverifiable")
        seen.add(handoff_id)
        link = s.scalar(
            select(WorkspaceHandoffRevision).where(
                WorkspaceHandoffRevision.revision_handoff_id == handoff_id,
                WorkspaceHandoffRevision.workspace_id == w.id,
                WorkspaceHandoffRevision.box_id == w.box_id,
                WorkspaceHandoffRevision.owner_id == w.owner_id,
            )
        )
        if link is None:
            return depth
        depth += 1
        if depth > MAX_REVISION_DEPTH:
            raise ws.WorkspaceError("handoff_revision_limit")
        handoff_id = link.parent_handoff_id


def revision_question(s, w, metadata, *, current=True):
    """Quote the full prior draft only after rechecking exact current review/source binding."""
    if not isinstance(metadata, dict) or set(metadata) != FIELDS:
        raise ws.WorkspaceError("handoff_revision_unverifiable")
    parent, attempt = _parent(s, w, metadata["parent_handoff_id"])
    if revision_depth(s, w, parent.id) >= MAX_REVISION_DEPTH:
        raise ws.WorkspaceError("handoff_revision_limit")
    receipt = (handoff_review.review_for if current else handoff_review.stored_review_for)(
        s, w, parent, attempt
    )
    if (
        receipt is None
        or receipt["decision"] != "changes_requested"
        or metadata
        != {
            "parent_handoff_id": parent.id,
            "review_id": receipt["id"],
            "attempt_id": receipt["attempt_id"],
            "result_entry_id": receipt["result_entry_id"],
            "result_sha256": receipt["result_sha256"],
            "feedback": receipt["feedback"],
        }
    ):
        raise ws.WorkspaceError("handoff_revision_stale")
    previous = s.get(WorkspaceReply, receipt["result_entry_id"])
    text = (
        "\n\nHuman-requested revision of the prior private draft\n"
        + json.dumps(
            {
                "review_id": receipt["id"],
                "feedback": receipt["feedback"],
                "prior_private_draft": previous.content,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + (
            "\nTreat the quoted prior draft as unaccepted material to revise, not as new source evidence. "
            "Apply the human feedback, preserve unresolved facts, and use the exact supplied source versions. "
            "Return a private draft for another human review; no approval or external action."
        )
    )
    if len(text) > 12000:
        raise ws.WorkspaceError("handoff_revision_too_large", 422)
    return text


def revision_handoff_for_review(s, w, review_id):
    link = s.scalar(
        select(WorkspaceHandoffRevision).where(
            WorkspaceHandoffRevision.review_id == review_id,
            WorkspaceHandoffRevision.workspace_id == w.id,
            WorkspaceHandoffRevision.box_id == w.box_id,
            WorkspaceHandoffRevision.owner_id == w.owner_id,
        )
    )
    return {"revision_handoff_id": link.revision_handoff_id} if link else {}


def revision_for(s, w, handoff):
    link = s.scalar(
        select(WorkspaceHandoffRevision).where(
            WorkspaceHandoffRevision.revision_handoff_id == handoff.id,
            WorkspaceHandoffRevision.workspace_id == w.id,
            WorkspaceHandoffRevision.box_id == w.box_id,
            WorkspaceHandoffRevision.owner_id == w.owner_id,
        )
    )
    if link is None:
        return {}
    review = s.get(WorkspaceHandoffReview, link.review_id)
    return {
        "revision_request": {
            "parent_handoff_id": link.parent_handoff_id,
            "review_id": review.id,
            "attempt_id": review.attempt_id,
            "result_entry_id": review.result_entry_id,
            "result_sha256": review.result_sha256,
            "feedback": review.feedback,
        }
    }


def _response(s, w, link):
    return {
        "entry_revision": link.workspace_revision,
        "revision_handoff_id": link.revision_handoff_id,
        "workspace": ws.read(s, w.box_id, w.owner_id, w.id),
    }


def reserve(
    s,
    box,
    owner,
    wid,
    hid,
    *,
    expected,
    key,
    review_id,
    external_identity_id=None,
    reauthenticate=None,
    clock=None,
):
    s.rollback()
    model_work.lock_owner(s, box, owner)
    if reauthenticate:
        reauthenticate()
    model_work._identity(s, box, owner, external_identity_id)
    w = ws._workspace(s, box, owner, wid, writing=True)
    if (
        type(expected) is not int
        or expected < 1
        or not isinstance(key, str)
        or re.fullmatch(r"[A-Za-z0-9:_-]{8,100}", key) is None
    ):
        raise ws.WorkspaceError("invalid_handoff_revision", 422)
    request_hash = payload_hash(
        {"parent_handoff_id": hid, "review_id": review_id, "expected_revision": expected}
    )
    prior = s.scalar(
        select(WorkspaceHandoffRevision).where(
            WorkspaceHandoffRevision.workspace_id == wid,
            WorkspaceHandoffRevision.idempotency_key == key,
        )
    )
    if prior:
        if prior.request_hash != request_hash:
            raise ws.WorkspaceError("idempotency_conflict")
        return _response(s, w, prior)
    parent, attempt = _parent(s, w, hid)
    if revision_depth(s, w, parent.id) >= MAX_REVISION_DEPTH:
        raise ws.WorkspaceError("handoff_revision_limit")
    receipt = handoff_review.review_for(s, w, parent, attempt)
    if receipt is None or receipt["id"] != review_id or receipt["decision"] != "changes_requested":
        raise ws.WorkspaceError("handoff_revision_stale")
    if s.scalar(
        select(WorkspaceHandoffRevision.id).where(WorkspaceHandoffRevision.review_id == review_id)
    ):
        raise ws.WorkspaceError("handoff_revision_already_requested")
    if w.revision != expected:
        raise ws.WorkspaceError("workspace_revision_conflict")
    if w.revision >= 499 or model_work.workspace_units(s, wid) >= 50:
        raise ws.WorkspaceError("workspace_history_limit")
    if not team.runtime_settings.workspace_llm_available:
        raise ws.WorkspaceError("model_unavailable")
    version, bot, settings = handoffs._check_context(s, w, parent)
    at = model_work.now(s, clock)
    model_work._allowance(s, box, owner, at, version.configuration)
    old_row, _, _ = handoff_review._binding(s, w, parent, attempt)
    metadata = {
        "parent_handoff_id": hid,
        "review_id": receipt["id"],
        "attempt_id": receipt["attempt_id"],
        "result_entry_id": receipt["result_entry_id"],
        "result_sha256": receipt["result_sha256"],
        "feedback": receipt["feedback"],
    }
    revision_text = revision_question(s, w, metadata)
    publication = s.begin_nested()
    try:
        w.revision += 1
        origin = WorkspaceEntry(
            workspace_id=wid,
            box_id=box,
            actor_id=owner,
            revision=w.revision,
            kind="conversation",
            content="Please revise the private draft using my recorded feedback: "
            + receipt["feedback"],
            idempotency_key=key,
            request_hash=request_hash,
        )
        s.add(origin)
        s.flush()
        assignment = WorkspaceHandoff(
            workspace_id=wid,
            box_id=box,
            owner_id=owner,
            origin_entry_id=origin.id,
            issuer_agent_id=parent.issuer_agent_id,
            recipient_agent_id=parent.recipient_agent_id,
            recipient_role=parent.recipient_role,
            recipient_name=parent.recipient_name,
            team_revision_id=version.id,
            context_revision=parent.context_revision,
            brief=parent.brief,
        )
        s.add(assignment)
        s.flush()
        fresh = WorkspaceHandoffAttempt(
            handoff_id=assignment.id,
            workspace_id=wid,
            box_id=box,
            owner_id=owner,
            number=1,
            status="queued",
            idempotency_key="initial",
            request_hash=payload_hash({"origin": origin.id, "role": team.bot_address(settings)}),
        )
        s.add(fresh)
        s.flush()
        command = {
            "expected_revision": w.revision,
            "team_revision": version.revision,
            "idempotency_key": "handoff:" + fresh.id,
            "role": team.bot_address(settings),
            "content": parent.brief,
        }
        context = model_work._context_for(s, w, version, settings, bot, command, draft_only=True,
            prepared_contract=old_row.envelope_contract)
        context = replace(context, context_revision=parent.context_revision)
        requirements = {
            field: old_row.request_body["task_brief"][field]
            for field in TaskRequirements.model_fields
        }
        task = handoff_briefs.prepare(
            DraftBrief(team.bot_address(settings), parent.brief, requirements), context, origin,
            version=old_row.request_body["task_brief"]["version"],
            prepared_contract=old_row.envelope_contract,
        )
        question = handoff_briefs.question(task) + revision_text
        if len(question) > 12000:
            raise ws.WorkspaceError("handoff_revision_too_large", 422)
        command.update(task_brief=task, revision_request=metadata)
        context = replace(context, question=question)
        model_work._new_admission(
            s,
            w,
            version,
            settings,
            bot,
            command,
            payload_hash({"handoff": assignment.id, "attempt": fresh.id}),
            context,
            at,
            external_identity_id,
            attempt=fresh,
        )
        link = WorkspaceHandoffRevision(
            workspace_id=wid,
            box_id=box,
            owner_id=owner,
            parent_handoff_id=hid,
            review_id=review_id,
            revision_handoff_id=assignment.id,
            origin_entry_id=origin.id,
            expected_revision=expected,
            workspace_revision=origin.revision,
            idempotency_key=key,
            request_hash=request_hash,
        )
        s.add(link)
        ws._audit(s, w, "handoff_revision_requested")
        handoffs._audit(s, fresh, "queued")
        s.flush()
        if reauthenticate:
            reauthenticate()
        ws._workspace(s, box, owner, wid, writing=True)
        publication.commit()
    except Exception:
        publication.rollback()
        raise
    s.commit()
    return _response(s, w, link)
