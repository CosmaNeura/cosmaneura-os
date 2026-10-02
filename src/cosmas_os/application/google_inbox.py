"""Private metadata custody and explicit human admission to existing F8 work.

Gmail is never coerced into a Spruce inbox snapshot or a Core preparation
receipt. Before human review there are only private workspace entries. After
human metadata-only review, the existing reviewed-note F8 family owns approval,
local synthetic handoff, and responsibility. No full-message review/completion
or external Gmail action is implemented here.
"""

import hashlib
import json
from datetime import date, datetime

from sqlalchemy import select

from cosmas_os.application import follow_up, note_review, shared_work
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.models import (
    ActionRevision,
    FollowUpSource,
    Ticket,
    WorkspaceEntry,
    WorkspaceNote,
    WorkspaceNoteReview,
)

SOURCE = "google_inbox_metadata_v1"
DRAFT = "google_inbox_metadata_review_draft_v1"
REVIEW = "google_inbox_human_metadata_review_v1"
BODY = ("Review the selected Gmail Subject/From metadata and obtain the full message through an authorized human channel. "
        "The message is incomplete: needs_human. Do not infer clinical urgency, patient matching, consent, or completion from headers.")
OUTCOME = "A responsible human obtains the full message and determines the appropriate next action; no completion is recorded here."
FLAGS = {"metadata_only": True, "incomplete_message": True, "classification": "needs_human",
         "clinical_priority": None, "whole_message_reviewed": False, "completed": False,
         "external_effects": 0, "clinical_approval": False}


def _body(value):
    return (BODY + "\nSelected untrusted metadata, for identifying the message only: "
        + canonical_json({"gmail_message_id": value["message"]["id"],
            "account_email": value["account"]["email"], "subject": value["message"]["subject"],
            "sender": value["message"]["sender"], "received_at": value["message"]["received_at"]}))


def _entry(s, w, identifier, schema):
    row = s.scalar(select(WorkspaceEntry).where(WorkspaceEntry.id == identifier,
        WorkspaceEntry.workspace_id == w.id, WorkspaceEntry.box_id == w.box_id,
        WorkspaceEntry.actor_id == w.owner_id))
    if row is None:
        raise ws.WorkspaceError("google_inbox_source_unavailable", 404)
    if row.request_hash != payload_hash({"expected": row.revision - 1, "kind": row.kind,
            "content": row.content, "source_label": row.source_label, "ticket_id": row.ticket_id}):
        raise ws.WorkspaceError("google_inbox_source_integrity")
    try:
        value = json.loads(row.content)
    except (ValueError, TypeError):
        raise ws.WorkspaceError("google_inbox_source_unavailable", 404) from None
    if not isinstance(value, dict) or value.get("schema") != schema or not all(value.get(k) == v for k, v in FLAGS.items()):
        raise ws.WorkspaceError("google_inbox_source_integrity")
    return row, value


def source(s, w, identifier, binding):
    row, value = _entry(s, w, identifier, SOURCE)
    if value["account_binding_sha256"] != binding:
        raise ws.WorkspaceError("google_inbox_account_changed")
    message = value["message"]
    if payload_hash(message) != value["message_sha256"]:
        raise ws.WorkspaceError("google_inbox_source_integrity")
    candidates = []
    for other in s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == w.id,
            WorkspaceEntry.box_id == w.box_id, WorkspaceEntry.kind == "evidence")):
        try:
            captured = json.loads(other.content)
        except (ValueError, TypeError):
            continue
        if (isinstance(captured, dict) and captured.get("schema") == SOURCE
                and captured.get("account_binding_sha256") == binding
                and captured.get("message", {}).get("id") == message["id"]):
            _entry(s, w, other.id, SOURCE)
            if payload_hash(captured["message"]) != captured["message_sha256"]:
                raise ws.WorkspaceError("google_inbox_source_integrity")
            candidates.append((datetime.fromisoformat(captured["observed_at"]), captured["message_sha256"]))
    newest = max(t for t, _ in candidates)
    hashes = {sha for t, sha in candidates if t == newest}
    state = "source_conflict" if len(hashes) != 1 else (
        "current" if value["message_sha256"] in hashes else "superseded")
    return row, value, state


def select_message(s, box, actor, wid, *, expected, key, captured, message_id, binding):
    w = ws._workspace(s, box, actor, wid, writing=True)
    matches = [row for row in captured["observation"]["items"] if row["id"] == message_id]
    if len(matches) != 1:
        raise ws.WorkspaceError("google_inbox_message_not_observed")
    value = {"schema": SOURCE, **FLAGS, "provider": "google", "message": matches[0],
        "account": captured["observation"]["account"],
        "message_sha256": payload_hash(matches[0]), "observed_at": captured["observation"]["observed_at"],
        "account_binding_sha256": binding, "read_key": captured["request"]["idempotency_key"],
        "read_receipt_id": captured["id"], "read_receipt_sha256": captured["sha256"],
        "source_sha256": captured["observation"]["source_sha256"],
        "provider_revision": None, "limits": captured["observation"]["limits"]}
    replay = s.scalar(select(WorkspaceEntry.id).where(WorkspaceEntry.workspace_id == wid,
        WorkspaceEntry.idempotency_key == key))
    result = ws.append(s, box, actor, wid, expected=expected, key=key, kind="evidence",
        content=canonical_json(value), source_label="Synthetic Gmail selected metadata — incomplete, needs human")
    w = ws._workspace(s, box, actor, wid)
    row, _, state = source(s, w, result["entry_id"], binding)
    return {**FLAGS, "status": "saved", "entry_id": row.id, "entry_revision": row.revision,
        "workspace_revision": w.revision, "content_sha256": hashlib.sha256(row.content.encode()).hexdigest(),
        "message_sha256": value["message_sha256"], "source_sha256": value["source_sha256"],
        "source_state": state, "idempotent_replay": replay is not None,
        "next_action": "Prepare a private metadata-review draft from this exact saved entry; a human must obtain the full message."}


def prepare(s, box, actor, wid, *, entry_id, expected, key, review_key, requester_role, episode, binding):
    w = ws._workspace(s, box, actor, wid, writing=True)
    # The short review key is discoverable by Chief and Follow-up, so it must
    # identify one draft across both roles, serialized by the workspace lock.
    for prior in s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == wid,
            WorkspaceEntry.box_id == box, WorkspaceEntry.kind == "scratchpad")):
        try:
            captured = json.loads(prior.content)
        except (ValueError, TypeError):
            continue
        if (isinstance(captured, dict) and captured.get("schema") == DRAFT
                and captured.get("episode") == episode and captured.get("review_key") == review_key
                and prior.idempotency_key != key):
            raise ws.WorkspaceError("google_inbox_review_key_conflict")
    row, value, state = source(s, w, entry_id, binding)
    if state != "current":
        raise ws.WorkspaceError("google_inbox_" + state)
    content = {"schema": DRAFT, **FLAGS, "source_entry_id": row.id,
        "review_key": review_key, "requester_role": requester_role, "episode": episode,
        "source_content_sha256": hashlib.sha256(row.content.encode()).hexdigest(),
        "message_sha256": value["message_sha256"], "account_binding_sha256": binding,
        "body": _body(value), "expected_outcome": OUTCOME, "responsibility": "human workspace owner until an explicit offer is accepted"}
    replay = s.scalar(select(WorkspaceEntry.id).where(WorkspaceEntry.workspace_id == wid,
        WorkspaceEntry.idempotency_key == key))
    result = ws.append(s, box, actor, wid, expected=expected, key=key, kind="scratchpad",
        content=canonical_json(content), source_label=None)
    return {**FLAGS, "status": "private_draft", "draft_entry_id": result["entry_id"],
        "entry_id": result["entry_id"], "workspace_revision": result["entry_revision"],
        "source_entry_id": row.id, "source_content_sha256": content["source_content_sha256"],
        "idempotent_replay": replay is not None,
        "next_action": "A separate human reviews metadata limitations and explicitly admits administrative work to F8; agents cannot approve or assign."}


def bound_draft(s, w, identifier, binding):
    draft, value = _entry(s, w, identifier, DRAFT)
    original, captured, state = source(s, w, value["source_entry_id"], binding)
    if (value["account_binding_sha256"] != binding
            or value["source_content_sha256"] != hashlib.sha256(original.content.encode()).hexdigest()
            or value["body"] != _body(captured) or value["expected_outcome"] != OUTCOME):
        raise ws.WorkspaceError("google_inbox_draft_integrity")
    return draft, value, state


def _stage(s, w, draft_id):
    rows = s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == w.id,
        WorkspaceEntry.box_id == w.box_id, WorkspaceEntry.kind == "conversation"))
    for row in rows:
        try:
            value = json.loads(row.content)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and value.get("schema") == REVIEW and value.get("draft_entry_id") == draft_id:
            return row, value
    return None, None


def status(s, box, actor, wid, *, draft_entry_id, binding):
    w = ws._workspace(s, box, actor, wid)
    draft, value, state = bound_draft(s, w, draft_entry_id, binding)
    _, stage = _stage(s, w, draft.id)
    result = {**FLAGS, "status": "private_draft", "draft_entry_id": draft.id,
        "source_entry_id": value["source_entry_id"], "source_content_sha256": value["source_content_sha256"],
        "source_state": state, "workspace_revision": w.revision, "metadata_reviewed_by_human": False,
        "responsible_id": actor, "f8": None,
        "next_action": "Human metadata review and explicit assignment remain pending; obtain the full message before triage."}
    if stage is not None:
        b = s.scalar(select(FollowUpSource).where(FollowUpSource.workspace_id == wid,
            FollowUpSource.idempotency_key == stage["prefix"] + "-f8"))
        if b is not None:
            t, r = s.get(Ticket, b.ticket_id), s.get(ActionRevision, b.action_revision_id)
            if (t is None or r is None or payload_hash(r.payload) != b.payload_hash
                    or r.content != value["body"] or r.payload.get("expected_outcome") != OUTCOME):
                raise ws.WorkspaceError("google_inbox_handoff_integrity")
            shared = shared_work.read(s, box, actor, t.id)
            result.update(status="human_handoff" if t.state == "sent" else "human_f8_pending",
                metadata_reviewed_by_human=True, responsible_id=shared["responsible"]["id"], f8=shared,
                next_action="The responsible human obtains and reviews the full message. Receiving this handoff does not complete triage.")
            latest_note = note_review._latest(s, wid)
            if (latest_note is None or latest_note.id != b.note_id
                    or b.source_fingerprint != note_review.source_fingerprint(s, wid, w.revision)):
                state = "review_sources_changed"
                result["source_state"] = state
    if state != "current":
        result.update(status="needs_human", metadata_review_current=False,
            next_action="Selected metadata changed or conflicts. Obtain the current full message and explicitly review a new draft; historical handoff is not current triage.")
    else:
        result["metadata_review_current"] = result["metadata_reviewed_by_human"]
    return result


def human_review(s, box, actor, wid, *, draft_entry_id, expected, key,
                 metadata_only_acknowledged, binding, ensure_current):
    """Separate human-only driver. Recover each committed stage by exact DB key."""
    if metadata_only_acknowledged is not True:
        raise ws.WorkspaceError("google_inbox_metadata_acknowledgment_required")
    w = ws._workspace(s, box, actor, wid, writing=True)
    draft, value, state = bound_draft(s, w, draft_entry_id, binding)
    if state != "current":
        raise ws.WorkspaceError("google_inbox_" + state)
    prefix = "google-human-" + payload_hash([wid, draft.id, key])[:64]
    request = {"schema": REVIEW, "draft_entry_id": draft.id, "source_content_sha256": value["source_content_sha256"],
        "expected_workspace_revision": expected, "idempotency_key": key,
        "actor_id": actor, "metadata_only_acknowledged": True, "prefix": prefix}
    prior, saved = _stage(s, w, draft.id)
    if prior is not None and saved != request:
        raise ws.WorkspaceError("idempotency_conflict")
    note_content = ("SYNTHETIC ADMINISTRATIVE METADATA NOTE. Human review covers selected Subject/From metadata only. "
        "No full message, clinical assessment or patient match. Source entry " + value["source_entry_id"]
        + " sha256 " + value["source_content_sha256"] + "\n" + value["body"])
    existing_notes = list(s.scalars(select(WorkspaceNote).where(WorkspaceNote.workspace_id == wid,
        WorkspaceNote.box_id == box, WorkspaceNote.owner_id == actor)))
    if any(n.idempotency_key != prefix + "-note" or n.content != note_content
            or n.content_hash != payload_hash({"content": note_content}) for n in existing_notes):
        raise ws.WorkspaceError("metadata_handoff_requires_separate_reviewed_note_context")
    if prior is None:
        ws.append(s, box, actor, wid, expected=expected, key=prefix + "-request", kind="conversation",
            content=canonical_json(request), source_label=None)
    ensure_current(s)
    w = ws._workspace(s, box, actor, wid, writing=True)
    n = s.scalar(select(WorkspaceNote).where(WorkspaceNote.workspace_id == wid,
        WorkspaceNote.idempotency_key == prefix + "-note"))
    if n is None:
        latest = note_review._latest(s, wid)
        note_review.save(s, box, actor, wid, expected=w.revision, key=prefix + "-note",
            base_note_id=latest.id if latest else None, source_reply_id=None,
            content=note_content, sources_reconciled=True)
        n = s.scalar(select(WorkspaceNote).where(WorkspaceNote.workspace_id == wid,
            WorkspaceNote.idempotency_key == prefix + "-note"))
    if n is None or n.content != note_content or n.content_hash != payload_hash({"content": note_content}):
        raise ws.WorkspaceError("google_inbox_human_note_integrity")
    ensure_current(s)
    if not s.scalar(select(WorkspaceNoteReview.id).where(WorkspaceNoteReview.note_id == n.id)):
        w = ws._workspace(s, box, actor, wid, writing=True)
        note_review.review(s, box, actor, wid, n.id, expected=w.revision, key=prefix + "-review",
            content_hash=n.content_hash, source_hash=n.source_fingerprint)
    ensure_current(s)
    b = s.scalar(select(FollowUpSource).where(FollowUpSource.workspace_id == wid,
        FollowUpSource.idempotency_key == prefix + "-f8"))
    if b is None:
        w = ws._workspace(s, box, actor, wid, writing=True)
        follow_up.propose(s, box, actor, wid, expected=w.revision, key=prefix + "-f8", note_id=n.id,
            body=value["body"], due_date=date(2026, 10, 2), expected_outcome=OUTCOME, share=True)
        b = s.scalar(select(FollowUpSource).where(FollowUpSource.workspace_id == wid,
            FollowUpSource.idempotency_key == prefix + "-f8"))
    if b is None or b.note_id != n.id:
        raise ws.WorkspaceError("google_inbox_handoff_integrity")
    ensure_current(s)
    follow_up._current(s, ws._workspace(s, box, actor, wid, writing=True), n.id)
    follow_up.decide(s, box, actor, wid, b.ticket_id, revision_id=b.action_revision_id,
        digest=b.payload_hash, choice="approve", defer_delivery=True)
    # Exact approval is durable first. Reacquire account custody before the
    # existing local effect, so revocation cannot slip between those commits.
    ensure_current(s)
    follow_up.deliver(s, box, actor, wid, b.ticket_id, revision_id=b.action_revision_id, digest=b.payload_hash)
    ensure_current(s)
    return status(s, box, actor, wid, draft_entry_id=draft.id, binding=binding)
