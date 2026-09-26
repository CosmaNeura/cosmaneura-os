"""Link a saved Core version into the existing private review/F-8 workflow.

Checked receipts are supplied only by the current signed capture boundary, whose
final OS authority locks surround these local mutations. This module makes no
network calls and never edits the canonical clinical note.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import FollowUpSource, WorkspaceCoreNoteSource, WorkspaceNote
from cosmas_os.ports.core_notes import CoreDraftReceipt, CoreDraftReference


def reference(source: WorkspaceCoreNoteSource) -> CoreDraftReference:
    return CoreDraftReference.model_validate({key: getattr(source, key) for key in CoreDraftReference.model_fields})


def source_for(s: Session, note: WorkspaceNote) -> WorkspaceCoreNoteSource | None:
    return s.scalar(select(WorkspaceCoreNoteSource).where(
        WorkspaceCoreNoteSource.note_id == note.id,
        WorkspaceCoreNoteSource.workspace_id == note.workspace_id,
        WorkspaceCoreNoteSource.box_id == note.box_id,
        WorkspaceCoreNoteSource.owner_id == note.owner_id,
    ))


def selected_source(s: Session, box: str, actor: str, wid: str, *, note_id: str | None = None,
                    ticket_id: str | None = None) -> CoreDraftReference | None:
    ws._workspace(s, box, actor, wid)
    if ticket_id is not None:
        linked = s.scalar(select(FollowUpSource).where(
            FollowUpSource.ticket_id == ticket_id, FollowUpSource.workspace_id == wid,
            FollowUpSource.box_id == box, FollowUpSource.owner_id == actor,
            FollowUpSource.source_kind == "reviewed_note",
        ))
        if linked is None:
            raise ws.WorkspaceError("follow_up_unavailable", 404)
        note_id = linked.note_id
    note = s.scalar(select(WorkspaceNote).where(WorkspaceNote.id == note_id,
        WorkspaceNote.workspace_id == wid, WorkspaceNote.box_id == box, WorkspaceNote.owner_id == actor))
    if note is None:
        raise ws.WorkspaceError("note_source_unavailable", 404)
    source = source_for(s, note)
    result = reference(source) if source else None
    s.rollback()  # No local lock may span the subsequent Core request.
    return result


def require_current(s: Session, note: WorkspaceNote, checked: CoreDraftReceipt | None) -> None:
    source = source_for(s, note)
    if source is None:
        return
    if checked is None:
        raise ws.WorkspaceError("core_note_check_required", 409)
    compare(reference(source), checked)
    from cosmas_os.application.workspace_capture import require_notebook_current
    require_notebook_current(s, note.workspace_id, checked.notebook_source)


def compare(expected: CoreDraftReference, checked: CoreDraftReceipt) -> None:
    try:
        current = CoreDraftReference.from_draft(checked)
    except ValueError:
        raise ws.WorkspaceError("core_note_changed", 409) from None
    if current != expected:
        raise ws.WorkspaceError("core_note_changed", 409)


def import_saved(s: Session, box: str, actor: str, wid: str, *, expected: int, key: str,
                 base_note_id: str | None, selected: CoreDraftReference, checked: CoreDraftReceipt | None):
    from cosmas_os.application import note_review as notes

    w = ws._workspace(s, box, actor, wid, writing=True)
    if checked is None:
        raise ws.WorkspaceError("core_note_check_required", 409)
    compare(selected, checked)
    from cosmas_os.application.workspace_capture import require_notebook_current
    require_notebook_current(s, wid, checked.notebook_source)
    request_hash = payload_hash({"kind": "saved_core_note", "expected": expected,
        "base": base_note_id, "source": selected.model_dump(mode="json")})
    prior = s.scalar(select(WorkspaceNote).where(WorkspaceNote.workspace_id == wid, WorkspaceNote.idempotency_key == key))
    if prior is not None:
        if prior.request_hash != request_hash:
            raise ws.WorkspaceError("idempotency_conflict")
        require_current(s, prior, checked)
        return notes._response(s, w, prior.workspace_revision)
    previous = notes._latest(s, wid)
    if base_note_id != (previous.id if previous else None):
        raise ws.WorkspaceError("note_revision_conflict")
    if previous and previous.version >= 50:
        raise ws.WorkspaceError("note_history_limit")
    assert checked.fields is not None and checked.field_order is not None
    content = "\n\n".join(f"{field}\n{checked.fields[field]}" for field in checked.field_order)
    if not content.strip() or len(content) > 270336:
        raise ws.WorkspaceError("invalid_note", 400)
    source_revision = w.revision
    fingerprint = notes.source_fingerprint(s, wid, source_revision)
    notes._advance(w, expected)
    note = WorkspaceNote(workspace_id=wid, box_id=box, owner_id=actor,
        version=previous.version + 1 if previous else 1, workspace_revision=w.revision,
        parent_id=base_note_id, source_reply_id=None, source_revision=source_revision,
        source_fingerprint=fingerprint, content=content, content_hash=payload_hash({"content": content}),
        idempotency_key=key, request_hash=request_hash)
    s.add(note)
    s.flush()
    s.add(WorkspaceCoreNoteSource(note_id=note.id, workspace_id=wid, box_id=box, owner_id=actor,
        content_hash=note.content_hash, source_fingerprint=fingerprint, note_type=checked.note_type,
        **selected.model_dump(mode="json")))
    ws._audit(s, w, "saved_core_note_linked")
    s.commit()
    return notes._response(s, w, note.workspace_revision)
