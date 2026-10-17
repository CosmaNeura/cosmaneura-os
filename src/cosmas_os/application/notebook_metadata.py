"""Owner-scoped notebook projections and append-only display names. No audio writes."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cosmas_os.application import note_review
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import EncounterWorkspace, WorkspaceEntry, WorkspaceTitleRevision
from cosmas_os.private_recording_models import PrivateRecording, PrivateRecordingFinish


def latest_title(s: Session, w: EncounterWorkspace):
    return s.scalar(select(WorkspaceTitleRevision).where(
        WorkspaceTitleRevision.workspace_id == w.id,
        WorkspaceTitleRevision.box_id == w.box_id,
        WorkspaceTitleRevision.owner_id == w.owner_id,
    ).order_by(WorkspaceTitleRevision.version.desc()).limit(1))


def display(s: Session, w: EncounterWorkspace):
    latest = latest_title(s, w)
    return {"title": latest.title if latest else w.draft_title,
        "title_revision": latest.version if latest else 0, "created_at": w.created_at.isoformat()}


def _digest(title: str, expected: int, key: str):
    ws._draft_request(title, key)
    if any(ord(char) < 32 for char in title):
        raise ws.WorkspaceError("invalid_private_draft_request", 422)
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        raise ws.WorkspaceError("invalid_private_draft_request", 422)
    return payload_hash({"contract": "notebook-title.v1", "title": title, "expected_title_revision": expected})


def _receipt(row: WorkspaceTitleRevision):
    return {"contract_version": 1, "workspace_id": row.workspace_id, "title": row.title,
        "title_revision": row.version, "receipt_id": row.id}


def _find(s, w, title, expected, key):
    digest = _digest(title, expected, key)
    row = s.scalar(select(WorkspaceTitleRevision).where(
        WorkspaceTitleRevision.workspace_id == w.id, WorkspaceTitleRevision.idempotency_key == key))
    if row is not None and row.request_hash != digest:
        raise ws.WorkspaceError("idempotency_conflict")
    return row, digest


def resolve(s: Session, box: str, actor: str, wid: str, *, title: str, expected: int, key: str):
    # Wait behind the exact owner's writer before reporting absence.
    w = ws._workspace(s, box, actor, wid, writing=True, allow_private=True)
    if w.draft_title is None:
        raise ws.WorkspaceError("workspace_unavailable", 404)
    row, _ = _find(s, w, title, expected, key)
    return {"contract_version": 1, "outcome": "saved" if row else "not_found", "receipt": _receipt(row) if row else None}


def rename(s: Session, box: str, actor: str, wid: str, *, title: str, expected: int, key: str, fence=None):
    w = ws._workspace(s, box, actor, wid, writing=True, allow_private=True)
    if w.draft_title is None:
        raise ws.WorkspaceError("workspace_unavailable", 404)
    row, digest = _find(s, w, title, expected, key)
    if row:
        if fence:
            fence()
        return _receipt(row)
    previous = latest_title(s, w)
    if expected != (previous.version if previous else 0):
        raise ws.WorkspaceError("notebook_title_conflict")
    row = WorkspaceTitleRevision(workspace_id=w.id, box_id=box, owner_id=actor,
        title=title, version=expected + 1, idempotency_key=key, request_hash=digest)
    s.add(row)
    ws._audit(s, w, "title_renamed")
    s.flush()
    if fence:
        fence()
    s.commit()
    return _receipt(row)


def summaries(s: Session, box: str, actor: str):
    ws._human(s, box, actor)
    rows = list(s.scalars(select(EncounterWorkspace).where(
        EncounterWorkspace.box_id == box, EncounterWorkspace.owner_id == actor,
        EncounterWorkspace.draft_title.is_not(None)).order_by(
        EncounterWorkspace.created_at.desc(), EncounterWorkspace.id.desc()).limit(100)))
    items = []
    for w in rows:
        a = None
        if w.appointment_id is not None:
            try:
                a = ws._encounter(s, box, w.appointment_id, w.patient_link_id, owner=actor)
            except ws.WorkspaceError:
                continue  # A revoked link withholds identifying metadata as well as content.
        title = latest_title(s, w)
        note = note_review.read(s, w, w.revision)["latest"]
        changed = s.scalar(select(func.max(WorkspaceEntry.created_at)).where(WorkspaceEntry.workspace_id == w.id))
        dates = [w.created_at] + ([changed] if changed else []) + ([title.created_at] if title else [])
        if note:
            from datetime import datetime
            dates.append(datetime.fromisoformat(note["created_at"]))
            if note["review"]:
                dates.append(datetime.fromisoformat(note["review"]["created_at"]))
        recording = s.execute(select(PrivateRecordingFinish.frames, PrivateRecordingFinish.capture_state)
            .join(PrivateRecording, PrivateRecording.id == PrivateRecordingFinish.recording_id)
            .where(PrivateRecording.workspace_id == w.id, PrivateRecording.box_id == box, PrivateRecording.owner_id == actor)
            .order_by(PrivateRecording.started_at.desc()).limit(1)).first()
        items.append({"workspace_id": w.id, "title": title.title if title else w.draft_title,
            "title_revision": title.version if title else 0, "revision": w.revision,
            "created_at": w.created_at.isoformat(), "updated_at": max(dates).isoformat(),
            "link_state": "linked" if a else "unlinked", "appointment_id": w.appointment_id,
            "patient_label": a.patient_label if a else None, "visit_at": a.start_at.isoformat() if a and a.start_at is not None else None,
            "note_state": "needs_review" if note and (not note["review"] or note["sources_changed"]) else "reviewed" if note else "draft",
            "duration_seconds": round(recording.frames / 16000, 3) if recording and recording.frames else None,
            "recording_state": recording.capture_state if recording else "none"})
    items.sort(key=lambda row: (row["updated_at"], row["workspace_id"]), reverse=True)
    return {"contract_version": 2, "drafts": items[:50], "has_more": len(items) > 50}
