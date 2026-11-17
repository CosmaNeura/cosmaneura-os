"""Metadata-only copy-to-EHR audit events. Note text never enters logs or audit."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from secrets import token_hex
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from cosmas_os.application.ehr_export.types import (
    AUDIT_EVENTS,
    CopyToEhrAuditEvent,
    EhrExportProfileId,
)
from cosmas_os.models import AuditEvent

# Keys that must never appear in audit detail (note text / clipboard content).
_FORBIDDEN_DETAIL_KEYS = frozenset({
    "text",
    "note",
    "note_text",
    "full_note",
    "section_text",
    "label",
    "body",
    "content",
    "fields",
    "sections",
    "extras",
    "clipboard",
    "rendered",
})


def new_correlation_id() -> str:
    return token_hex(8)


def build_audit_event(
    event: str,
    *,
    profile_id: EhrExportProfileId | None = None,
    outcome: str = "ok",
    duration_ms: int | None = None,
    correlation_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> CopyToEhrAuditEvent:
    """Build a metadata-only audit event. Raises if note-text keys sneak in."""
    if event not in AUDIT_EVENTS:
        raise ValueError("unknown_copy_to_ehr_audit_event")
    safe_detail = dict(detail or {})
    if any(key in _FORBIDDEN_DETAIL_KEYS for key in safe_detail):
        raise ValueError("note_text_forbidden_in_audit")
    return CopyToEhrAuditEvent(
        event=event,
        profile_id=profile_id,
        outcome=outcome,
        duration_ms=duration_ms,
        correlation_id=correlation_id or new_correlation_id(),
        detail=safe_detail,
    )


def record_audit(
    session: Session,
    *,
    box_id: str,
    aggregate_id: str,
    event: str,
    profile_id: EhrExportProfileId | None = None,
    outcome: str = "ok",
    duration_ms: int | None = None,
    correlation_id: str | None = None,
    actor_principal_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> CopyToEhrAuditEvent:
    """Persist a metadata-only ``AuditEvent``. Never stores note text."""
    built = build_audit_event(
        event,
        profile_id=profile_id,
        outcome=outcome,
        duration_ms=duration_ms,
        correlation_id=correlation_id,
        detail=detail,
    )
    meta: dict[str, Any] = {
        "event": built.event,
        "outcome": built.outcome,
        "correlation_id": built.correlation_id,
    }
    if built.profile_id is not None:
        meta["profile_id"] = built.profile_id
    if built.duration_ms is not None:
        meta["duration_ms"] = built.duration_ms
    meta.update(built.detail)
    if any(key in _FORBIDDEN_DETAIL_KEYS for key in meta):
        raise ValueError("note_text_forbidden_in_audit")
    session.add(
        AuditEvent(
            id=str(uuid4()),
            box_id=box_id,
            aggregate_type="copy_to_ehr",
            aggregate_id=aggregate_id,
            event_type=built.event,
            actor_principal_id=actor_principal_id,
            correlation_id=built.correlation_id,
            outcome=built.outcome,
            detail=meta,
        )
    )
    return built


def audit_contains_note_text(detail: object, note_snippets: Sequence[str]) -> bool:
    """Return True if any note snippet appears anywhere in serialised audit detail."""
    blob = _flatten(detail).lower()
    return any(snippet and snippet.lower() in blob for snippet in note_snippets)


def _flatten(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(f"{key} {_flatten(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return " ".join(_flatten(item) for item in value)
    return str(value)
