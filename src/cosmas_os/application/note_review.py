"""Human-owned private note versions and review, never clinical sign-off."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmas_os.application import core_note_review
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import (
    ModelWorkAdmission,
    WorkspaceEntry,
    WorkspaceNote,
    WorkspaceNoteReview,
    WorkspaceReply,
)
from cosmas_os.ports.capture_gap_review import GapAcknowledgment
from cosmas_os.ports.core_notes import CoreDraftReceipt


def source_fingerprint(s: Session, wid: str, revision: int) -> str:
    sources = list(
        s.scalars(
            select(WorkspaceEntry)
            .where(
                WorkspaceEntry.workspace_id == wid,
                WorkspaceEntry.revision <= revision,
                WorkspaceEntry.kind.in_(("synthetic_source", "evidence", "scratchpad")),
            )
            .order_by(WorkspaceEntry.revision)
        )
    )
    return fingerprint_for_sources(sources)


def fingerprint_for_sources(sources: list[WorkspaceEntry]) -> str:
    """Hash already-selected, revision-ordered clinical sources without I/O."""
    latest_notebook = next((e.id for e in reversed(sources) if e.kind == "scratchpad"), None)
    return payload_hash(
        [
            {"id": e.id, "revision": e.revision, "content": e.content}
            for e in sources
            if e.kind != "scratchpad" or e.id == latest_notebook
        ]
    )


def _require_note_lineage(s: Session, w, reply_id):
    if not reply_id:
        return
    admission = s.scalar(select(ModelWorkAdmission).where(
        ModelWorkAdmission.request_entry_id == reply_id,
        ModelWorkAdmission.workspace_id == w.id,
        ModelWorkAdmission.box_id == w.box_id,
        ModelWorkAdmission.owner_id == w.owner_id,
    ))
    if admission is None:
        return
    from cosmas_os.adapters.gpt41 import _context

    for source in _context(admission.prepared_envelope["context"]).sources:
        entry = s.get(WorkspaceEntry, source.entry_id)
        if entry is not None and entry.kind in {"google_message", "google_calendar", "efax_inbound_source", "fax_inbound_source", "ehr_read_source"}:
            # Selected connector work has independent custody and cannot enter
            # the clinical-note fingerprint through a derived draft.
            raise ws.WorkspaceError(entry.kind + "_note_import_unavailable", 409)


def read(s: Session, w, revision: int) -> dict:
    notes = list(
        s.scalars(
            select(WorkspaceNote)
            .where(
                WorkspaceNote.workspace_id == w.id,
                WorkspaceNote.box_id == w.box_id,
                WorkspaceNote.owner_id == w.owner_id,
                WorkspaceNote.workspace_revision <= revision,
            )
            .order_by(WorkspaceNote.workspace_revision)
        )
    )
    reviews = {
        r.note_id: r
        for r in s.scalars(
            select(WorkspaceNoteReview).where(
                WorkspaceNoteReview.workspace_id == w.id,
                WorkspaceNoteReview.box_id == w.box_id,
                WorkspaceNoteReview.owner_id == w.owner_id,
                WorkspaceNoteReview.workspace_revision <= revision,
            )
        )
    }
    current = source_fingerprint(s, w.id, revision)
    history = []
    for n in notes:
        review = reviews.get(n.id)
        core_source = core_note_review.source_for(s, n)
        history.append(
            {
                "id": n.id,
                "version": n.version,
                "workspace_revision": n.workspace_revision,
                "content": n.content,
                "content_hash": n.content_hash,
                "source_reply_id": n.source_reply_id,
                "core_source": {**core_note_review.reference(core_source).model_dump(mode="json"),
                    "note_type": core_source.note_type} if core_source else None,
                "source_revision": n.source_revision,
                "source_fingerprint": n.source_fingerprint,
                "sources_changed": n.source_fingerprint != current,
                "created_at": n.created_at.isoformat(),
                "review": {
                    "id": review.id,
                    "reviewer_id": review.owner_id,
                    "created_at": review.created_at.isoformat(),
                    **({"capture_gap_review_sha256": review.capture_gap_review_sha256}
                       if review.capture_gap_review_sha256 else {}),
                }
                if review
                else None,
            }
        )
    return {"latest": history[-1] if history else None, "history": history}


def _response(s, w, revision):
    return {
        "entry_revision": revision,
        "workspace": ws.read(s, w.box_id, w.owner_id, w.id, at_revision=revision),
    }


def _latest(s, wid):
    return s.scalar(
        select(WorkspaceNote)
        .where(WorkspaceNote.workspace_id == wid)
        .order_by(WorkspaceNote.version.desc())
        .limit(1)
    )


def _advance(w, expected):
    if expected != w.revision:
        raise ws.WorkspaceError("workspace_revision_conflict")
    if w.revision >= 500:
        raise ws.WorkspaceError("workspace_history_limit")
    w.revision += 1


def save(
    s: Session,
    box: str,
    actor: str,
    wid: str,
    *,
    expected: int,
    key: str,
    base_note_id: str | None,
    source_reply_id: str | None,
    content: str,
    sources_reconciled: bool = False,
):
    w = ws._workspace(s, box, actor, wid, writing=True)
    request_hash = payload_hash(
        {
            "expected": expected,
            "base": base_note_id,
            "source": source_reply_id,
            "content": content,
            "reconciled": sources_reconciled,
        }
    )
    replay = s.scalar(
        select(WorkspaceNote).where(
            WorkspaceNote.workspace_id == wid, WorkspaceNote.idempotency_key == key
        )
    )
    if replay:
        if replay.request_hash != request_hash:
            raise ws.WorkspaceError("idempotency_conflict")
        return _response(s, w, replay.workspace_revision)
    if not isinstance(content, str) or not content.strip() or len(content) > 20000:
        raise ws.WorkspaceError("invalid_note", 400)
    if type(sources_reconciled) is not bool:
        raise ws.WorkspaceError("invalid_note", 400)
    previous = _latest(s, wid)
    if previous and core_note_review.source_for(s, previous):
        raise ws.WorkspaceError("core_note_edit_required", 409)
    if base_note_id != (previous.id if previous else None):
        raise ws.WorkspaceError("note_revision_conflict")
    if previous and previous.version >= 50:
        raise ws.WorkspaceError("note_history_limit")
    source_revision = previous.source_revision if previous else w.revision
    _require_note_lineage(s, w, source_reply_id)
    if source_reply_id:
        reply = s.scalar(
            select(WorkspaceReply).where(
                WorkspaceReply.entry_id == source_reply_id,
                WorkspaceReply.workspace_id == wid,
                WorkspaceReply.box_id == box,
                WorkspaceReply.owner_id == actor,
                WorkspaceReply.role == "scribe",
            )
        )
        if (
            reply is None
            or not reply.backend.startswith("azure_gpt41")
            or reply.backend.endswith("unavailable")
        ):
            raise ws.WorkspaceError("note_source_unavailable", 404)
        if not previous or previous.source_reply_id != source_reply_id:
            source_revision = reply.context_revision
    elif previous and previous.source_reply_id:
        # Preserve generated-draft lineage through manual edits.
        raise ws.WorkspaceError("note_source_required", 400)
    if sources_reconciled:
        source_revision = w.revision
    fingerprint = source_fingerprint(s, wid, source_revision)
    _advance(w, expected)
    n = WorkspaceNote(
        workspace_id=wid,
        box_id=box,
        owner_id=actor,
        version=previous.version + 1 if previous else 1,
        workspace_revision=w.revision,
        parent_id=base_note_id,
        source_reply_id=source_reply_id,
        source_revision=source_revision,
        source_fingerprint=fingerprint,
        content=content,
        content_hash=payload_hash({"content": content}),
        idempotency_key=key,
        request_hash=request_hash,
    )
    s.add(n)
    ws._audit(s, w, "note_saved")
    s.commit()
    return _response(s, w, n.workspace_revision)


def review(
    s: Session,
    box: str,
    actor: str,
    wid: str,
    note_id: str,
    *,
    expected: int,
    key: str,
    content_hash: str,
    source_hash: str,
    core_checked: CoreDraftReceipt | None = None,
    gap_acknowledgment: GapAcknowledgment | None = None,
):
    w = ws._workspace(s, box, actor, wid, writing=True)
    acknowledgment = (GapAcknowledgment.model_validate(gap_acknowledgment.model_dump())
                      if gap_acknowledgment is not None else None)
    request_payload = {"expected": expected, "note": note_id, "content": content_hash, "sources": source_hash}
    if acknowledgment is not None:
        request_payload["gap_acknowledgment"] = acknowledgment.model_dump(mode="json")
    request_hash = payload_hash(request_payload)
    replay = s.scalar(
        select(WorkspaceNoteReview).where(
            WorkspaceNoteReview.workspace_id == wid, WorkspaceNoteReview.idempotency_key == key
        )
    )
    if replay:
        if replay.request_hash != request_hash:
            raise ws.WorkspaceError("idempotency_conflict")
        reviewed_note = s.get(WorkspaceNote, replay.note_id)
        assert reviewed_note is not None
        core_note_review.require_current(s, reviewed_note, core_checked)
        return _response(s, w, replay.workspace_revision)
    n = _latest(s, wid)
    if n is None or n.id != note_id:
        raise ws.WorkspaceError("note_revision_conflict")
    core_note_review.require_current(s, n, core_checked)
    _require_note_lineage(s, w, n.source_reply_id)
    gap_review = core_checked.capture_gap_review if core_checked else None
    if ((gap_review is None) != (acknowledgment is None)
        or (gap_review is not None and acknowledgment is not None
            and gap_review.recovery_sha256 != acknowledgment.recovery_sha256)):
        raise ws.WorkspaceError("capture_gap_acknowledgment_required", 409)
    if (
        n.content_hash != content_hash
        or n.source_fingerprint != source_hash
        or n.source_fingerprint != source_fingerprint(s, wid, w.revision)
    ):
        raise ws.WorkspaceError("note_sources_or_content_changed")
    if s.scalar(select(WorkspaceNoteReview.id).where(WorkspaceNoteReview.note_id == note_id)):
        raise ws.WorkspaceError("note_already_reviewed")
    _advance(w, expected)
    receipt = WorkspaceNoteReview(
        workspace_id=wid,
        box_id=box,
        owner_id=actor,
        note_id=n.id,
        workspace_revision=w.revision,
        content_hash=content_hash,
        source_fingerprint=source_hash,
        idempotency_key=key,
        request_hash=request_hash,
        capture_gap_review_sha256=acknowledgment.recovery_sha256 if acknowledgment else None,
    )
    s.add(receipt)
    ws._audit(s, w, "note_reviewed_privately")
    s.commit()
    return _response(s, w, receipt.workspace_revision)
