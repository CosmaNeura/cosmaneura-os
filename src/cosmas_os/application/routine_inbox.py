"""Dated, owner-private incoming work observations through existing F8 authority.

This is a projection, not an ingestion path, responsibility engine or grant.
Every context-bearing observation uses the current handoff read. Saved context
is disclosed only while its exact work and receipt bindings remain current.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select

from cosmas_os.application import inbox_handoff as handoff
from cosmas_os.application import inbox_work as inbox
from cosmas_os.application import shared_work
from cosmas_os.application import workspace as ws
from cosmas_os.models import FollowUpReceipt


@dataclass(frozen=True)
class Sources:
    registry: Callable[[], inbox.InboxRegistry] = inbox.no_registry
    policy: Callable[[], handoff.Policy] = handoff.Policy


def counts(items, day):
    active = [v for v in items if v["state"] == "approved"]
    return {
        "pending_approval": sum(v["state"] == "pending_approval" for v in items),
        "open": len(active),
        "overdue": sum(v["due_date"] is not None and v["due_date"] < day for v in active),
        "awaiting_acceptance": sum(v["pending_offer"] for v in active),
        "responsible_unavailable": sum(not v["responsible"]["available"] for v in items),
        "awaiting_review": sum(v["ready_for_review"] for v in active),
        "verified_complete": sum(v["state"] == "closed" and v["verified_current"] for v in items),
        "source_unavailable": sum(v["state"] == "source_unavailable" for v in items),
        "work_changed": sum(v["state"] == "work_changed" for v in items),
    }


def order(item):
    return (item["state"] not in {"source_unavailable", "work_changed", "pending_approval"}
            and item["responsible"]["available"] and not item["ready_for_review"],
            item["state"] not in {"approved", "pending_approval", "source_unavailable", "work_changed"},
            item["due_date"] or "9999-12-31", item["ticket_id"])


def _receipts(s, box, tid):
    return {r.kind: r.id for r in s.scalars(select(FollowUpReceipt).where(
        FollowUpReceipt.box_id == box, FollowUpReceipt.ticket_id == tid,
        FollowUpReceipt.kind.in_(["internal_publication", "ready_for_review", "incoming_verification"])))}


def _item(s, box, actor, tid, sources):
    # Suppliers are intentionally called for each read, not captured at startup.
    detail = handoff.read(s, box, actor, tid, registry=sources.registry, policy=sources.policy())
    available = detail["state"] != "source_unavailable"
    context = available and (detail["publication_active"] or (
        detail["originator_id"] == actor and detail["state"] == "pending_approval"))
    receipts = _receipts(s, box, tid)
    person = shared_work._person(s, box, detail["responsible_id"])
    return {
        "ticket_id": tid, "revision_id": detail["revision_id"], "payload_hash": detail["payload_hash"],
        "version": detail["version"], "state": detail["state"],
        "body": detail["instructions"][:180] if context and detail["instructions"] else None,
        "due_date": detail["due_date"] if context else None,
        "responsible": {**person, "name": person["name"][:80]},
        "originator_id": detail["originator_id"], "requires_owner_attention": detail["requires_owner_attention"],
        "pending_offer": bool(available and detail["state"] == "approved" and detail["result"] is None
                              and detail["handoffs"] and detail["handoffs"][-1]["kind"] == "offer"),
        "ready_for_review": bool(available and detail["state"] == "approved" and detail["result"]),
        "verified_current": bool(available and detail["verified_current"]),
        "publication_receipt_id": receipts.get("internal_publication") if available else None,
        "result_receipt_id": receipts.get("ready_for_review") if available else None,
        "verification_receipt_id": receipts.get("incoming_verification") if available else None,
        "changed_since_report": False,
    }


def _configured(s, box, actor, sources):
    if not sources.policy().enabled:
        return False
    installed = sources.registry()
    if type(installed) is not inbox.InboxRegistry:
        raise ws.WorkspaceError("routine_source_unavailable")
    for grant in installed.grants.values():
        if (str(grant.binding.selection.box_id), str(grant.binding.selection.owner_id)) != (box, actor):
            continue
        try:
            inbox.grant_current(s, box, actor, grant, registry=sources.registry)
            return True
        except ws.WorkspaceError:
            continue
    return False


def _section(items, coverage, reason, day, *, withheld=False):
    return {"coverage": coverage, "reason": reason, "items": sorted(items, key=order),
            "matching_items": len(items), "counts": None if coverage in {"unavailable", "not_included"}
            else counts(items, day), "withheld_sources": withheld}


def snapshot(s, box, actor, day, sources):
    try:
        catalog = handoff.catalog(s, box, actor, registry=sources.registry, policy=sources.policy())
        items = [_item(s, box, actor, summary["ticket_id"], sources) for summary in catalog["items"]]
        configured = any(v["state"] != "source_unavailable" for v in items) or _configured(s, box, actor, sources)
    except ws.WorkspaceError as exc:
        # A failed read grants no counts, prefix or context access. The generic
        # section remains independently useful, with honest missing coverage.
        reason = "collection_limit" if exc.code == "inbox_handoff_history_limit" else "source_unavailable"
        return _section([], "unavailable", reason, day, withheld=True)
    missing = any(v["state"] == "source_unavailable" for v in items)
    if not items and not configured:
        return _section([], "unavailable", "source_unavailable", day, withheld=True)
    return _section(items, "partial" if missing else "complete", "source_unavailable" if missing else None,
                    day, withheld=missing)


def reauthorize(s, box, actor, saved, day, sources):
    if saved["coverage"] in {"unavailable", "not_included"}:
        # A later grant does not turn an earlier unknown observation into zero.
        return _section([], saved["coverage"], saved["reason"], day, withheld=saved["withheld_sources"])
    items, withheld = [], saved["withheld_sources"]
    keys = ("revision_id", "payload_hash", "version", "publication_receipt_id", "result_receipt_id",
            "verification_receipt_id")
    for observed in saved["items"]:
        try:
            current = _item(s, box, actor, observed["ticket_id"], sources)
        except ws.WorkspaceError:
            withheld = True
            continue
        exact = all(current[k] == observed[k] for k in keys)
        if not exact or current["state"] == "source_unavailable":
            # The current read, not the historical snapshot, authorizes this
            # minimal responsibility signal. Never restore old private text.
            source_missing = current["state"] == "source_unavailable"
            changed = observed["changed_since_report"] or not exact or observed["state"] != current["state"]
            current.update(body=None, due_date=None, state="source_unavailable" if source_missing else "work_changed",
                requires_owner_attention=source_missing, pending_offer=False, ready_for_review=False,
                verified_current=False, publication_receipt_id=None, result_receipt_id=None,
                verification_receipt_id=None, changed_since_report=changed)
            items.append(current)
            withheld = True
        else:
            # Dated state remains dated, while current human availability is
            # checked now so an offboarded responsible person cannot disappear.
            items.append({**observed, "responsible": current["responsible"],
                "verified_current": observed["verified_current"] and current["verified_current"]})
    return _section(items, "partial" if withheld else saved["coverage"],
        "source_unavailable" if any(v["state"] == "source_unavailable" for v in items) or withheld and not items
        else "work_changed" if withheld else saved["reason"], day, withheld=withheld)


def legacy(day):
    return _section([], "not_included", "legacy_report", day)
