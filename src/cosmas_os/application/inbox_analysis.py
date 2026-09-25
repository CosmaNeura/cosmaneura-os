"""Resolve one current, human-triaged Inbox source; no provider read or send."""

from collections.abc import Callable
from dataclasses import dataclass

from cosmas_os.api import inbox_work_schemas as schema
from cosmas_os.api.inbox_analysis_schemas import InboxAnalysis
from cosmas_os.application import inbox_work as inbox
from cosmas_os.application import workspace as ws
from cosmas_os.ports.bot_capabilities import BotContext, SourcePassage, supports_skill


@dataclass(frozen=True)
class Sources:
    registry: Callable[[], inbox.InboxRegistry]
    policy: Callable[[], inbox.InboxPolicy]


def selection(value):
    try:
        return InboxAnalysis.model_validate(value).model_dump(mode="json")
    except (ValueError, TypeError, RecursionError):
        raise ws.WorkspaceError("invalid_inbox_analysis", 422) from None


def checked_event(event, row, kind):
    if event is None or (event.box_id, event.owner_id, event.item_id, event.kind, event.origin) != (
        row.box_id,
        row.owner_id,
        row.id,
        kind,
        "human",
    ):
        raise ws.WorkspaceError("source_changed")
    try:
        request = schema.COMMANDS[kind].model_validate(event.request)
        receipt = schema.Receipt.model_validate(inbox.response(event)).model_dump(mode="json")
    except (ValueError, TypeError, KeyError):
        raise ws.WorkspaceError("source_changed") from None
    if (
        schema.request_digest(kind, inbox.scope(row.box_id, row.owner_id), request)
        != event.request_sha256
        or receipt["request_sha256"] != event.request_sha256
        or receipt["outcome"] != "recorded"
        or request.item_id != row.id
        or request.source_id != row.current_source_id
        or receipt["receipt_id"] != event.id
    ):
        raise ws.WorkspaceError("source_changed")
    return request


def build_context(s, workspace, settings, command):
    if settings["role"] != "custom" or not supports_skill(settings, "inbox_review"):
        raise ws.WorkspaceError("inbox_bot_required")
    sources = s.info.get("inbox_analysis_sources")
    if not isinstance(sources, Sources) or sources.policy() != inbox.InboxPolicy(enabled=True):
        raise ws.WorkspaceError("inbox_analysis_unavailable")
    chosen = selection(command["inbox_analysis"])
    row = inbox.item(s, workspace.box_id, workspace.owner_id, chosen["item_id"])
    grant = inbox.InboxReadGrant.model_validate(row.grant)
    inbox.grant_current(s, workspace.box_id, workspace.owner_id, grant, sources.registry)
    current = inbox.head(s, row)
    review, triage, result, verified = inbox.chain(s, row)
    if (
        current is None
        or (row.version, current.id, current.source_sha256)
        != (chosen["item_version"], chosen["source_id"], chosen["source_sha256"])
        or row.patient_link_id != workspace.patient_link_id
        or row.read_issue
        or row.source_conflict
        or result is not None
        or verified is not None
        or review is None
        or triage is None
        or (review.id, review.receipt_sha256, triage.id, triage.receipt_sha256)
        != (
            chosen["review_receipt_id"],
            chosen["review_receipt_sha256"],
            chosen["triage_receipt_id"],
            chosen["triage_receipt_sha256"],
        )
    ):
        raise ws.WorkspaceError("source_changed")
    reviewed = checked_event(review, row, "review")
    triaged = checked_event(triage, row, "triage")
    if (
        reviewed.source_sha256 != current.source_sha256
        or triaged.source_sha256 != current.source_sha256
    ):
        raise ws.WorkspaceError("source_changed")
    if triaged.classification != "administrative_review":
        raise ws.WorkspaceError("inbox_human_review_required")
    # Admit before the question append; thereafter allow only that same append.
    expected = command["expected_revision"]
    if (
        reviewed.workspace_id != workspace.id
        or reviewed.patient_link_id != workspace.patient_link_id
        or reviewed.expected_workspace_revision != expected
        or workspace.revision not in {expected, expected + 1}
    ):
        raise ws.WorkspaceError("source_changed")
    snapshot = inbox.source_snapshot(current)
    if snapshot.incomplete_content or not snapshot.text:
        raise ws.WorkspaceError("inbox_human_review_required")
    if len(snapshot.text) > 5000 or len(snapshot.text.encode("utf-8")) > 20000:
        raise ws.WorkspaceError("inbox_analysis_too_large", 422)
    inbox.grant_current(s, workspace.box_id, workspace.owner_id, grant, sources.registry)
    return BotContext(
        workspace_id=workspace.id,
        context_revision=expected,
        role="custom",
        question=command["content"],
        response_style=settings["response_style"],
        sources=(
            SourcePassage(
                current.id,
                current.sequence,
                "Reviewed incoming message",
                "inbox_message",
                snapshot.text,
            ),
            SourcePassage(
                triage.id,
                triage.version,
                "Human administrative triage",
                "inbox_triage",
                triaged.instructions,
            ),
        ),
        linked_work=(),
        skills=("inbox_review",),
        handoff_limit=0,
    )
