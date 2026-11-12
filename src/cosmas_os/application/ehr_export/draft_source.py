"""Load a workspace note into an export draft. Metadata logs only; never note text."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmas_os.application.ehr_export.types import ExportDraft
from cosmas_os.models import WorkspaceCoreNoteSource, WorkspaceNote, WorkspaceNoteReview

logger = logging.getLogger("cosmas_os.ehr_export.draft_source")

_DRAFT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_FIELD_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_ ]{0,79}$")

_OpenSession = Callable[[], AbstractContextManager[Session]]
_FindNote = Callable[[Session, str], tuple[WorkspaceNote, bool] | None]


def fields_from_note_content(content: str) -> tuple[list[str], dict[str, str]]:
    """Read Core's ``field\\ntext`` blocks. Anything else is one ``note`` field."""
    text = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    blocks = [block for block in text.split("\n\n") if block.strip()]
    order: list[str] = []
    fields: dict[str, str] = {}
    for block in blocks:
        key, separator, body = block.partition("\n")
        key = key.strip()
        if not separator or not _FIELD_KEY.fullmatch(key) or key in fields:
            return ["note"], {"note": text}
        fields[key] = body.strip()
        order.append(key)
    if not order:
        return ["note"], {"note": text}
    return order, fields


def export_draft_from_note(
    *,
    draft_id: str,
    version: int,
    content: str,
    reviewed: bool,
) -> ExportDraft | None:
    if not isinstance(content, str) or not content.strip():
        return None
    order, fields = fields_from_note_content(content)
    return ExportDraft(
        draft_id=draft_id,
        draft_revision=str(version),
        field_order=tuple(order),
        fields=fields,
        review_state="reviewed" if reviewed else "unreviewed",
    )


def find_workspace_note(session: Session, draft_id: str) -> tuple[WorkspaceNote, bool] | None:
    """Resolve a note id or a Core ``note_ref``. Returns the note and whether it is reviewed."""
    note = session.get(WorkspaceNote, draft_id)
    if note is None:
        note = session.scalar(
            select(WorkspaceNote)
            .join(WorkspaceCoreNoteSource, WorkspaceCoreNoteSource.note_id == WorkspaceNote.id)
            .where(WorkspaceCoreNoteSource.note_ref == draft_id)
            .order_by(WorkspaceNote.version.desc())
            .limit(1)
        )
    if note is None:
        return None
    reviewed = session.scalar(
        select(WorkspaceNoteReview.id).where(WorkspaceNoteReview.note_id == note.id).limit(1)
    )
    return note, reviewed is not None


def _log_load_failed() -> None:
    logger.info(
        "copy_to_ehr.draft_load_failed",
        extra={"event": "copy_to_ehr.draft_load_failed", "outcome": "unavailable"},
    )


def load_export_draft(
    open_session: _OpenSession,
    draft_id: str,
    *,
    find_note: _FindNote = find_workspace_note,
) -> ExportDraft | None:
    if not isinstance(draft_id, str) or _DRAFT_ID.fullmatch(draft_id) is None:
        return None
    try:
        with open_session() as session:
            found = find_note(session, draft_id)
            if found is None:
                return None
            note, reviewed = found
            return export_draft_from_note(
                draft_id=draft_id,
                version=note.version,
                content=note.content,
                reviewed=reviewed,
            )
    except Exception:
        _log_load_failed()
        return None
