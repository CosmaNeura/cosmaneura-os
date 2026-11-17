"""Visible copy offer when a read adapter reports an error or a disconnect.

The clinician sees that the note was not sent and can copy instead.
The offer never blocks or delays the visit or the note, and a failure
inside this module never raises into the read path.
"""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Literal
from uuid import UUID

from cosmas_os.application.ehr_export.audit import build_audit_event
from cosmas_os.application.ehr_export.profiles import copy_profile_for_vendor
from cosmas_os.application.ehr_export.types import (
    ABSOLUTE_EXPIRY_SECONDS,
    CopyToEhrAuditEvent,
    VisitCopyToEhrStatus,
)

logger = logging.getLogger("cosmas_os.ehr_export.fallback")

# Clinician-visible wording. Fixed product copy, never note text.
VISIBLE_OFFER = "not sent, Copy to EHR"
_NOT_SENT: VisitCopyToEhrStatus = "not_sent_copy_instead"
_UNSET: VisitCopyToEhrStatus = "unset"

_DISCONNECT_CODES = frozenset({
    "connection_changed",
    "disconnected",
    "account_changed",
    "scope_changed",
})
_ADAPTER_ERROR_TYPES = frozenset({
    "ElationReadError",
    "ElationLabError",
    "TebraFhirReadError",
    "TebraReadError",
    "AthenaAllergyError",
    "AthenaMedicationError",
    "AthenaFhirScheduleError",
    "ConnectorUnavailable",
    "CoreDiscoveryDenied",
    "EhrRealDataGateError",
})
_TOKEN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_EVENT_LIMIT = 500
_lock = Lock()
# visit id -> (status, monotonic time the mark was set)
_marks: dict[str, tuple[VisitCopyToEhrStatus, float]] = {}
_events: deque[CopyToEhrAuditEvent] = deque(maxlen=_EVENT_LIMIT)


def _now() -> float:
    """Clock for the mark window. Tests replace this; production uses monotonic time."""
    return time.monotonic()


@dataclass(frozen=True, slots=True)
class CopyFallbackOffer:
    """Visible copy offer for one visit. Both block flags stay false."""

    visit_id: str
    visit_copy_to_ehr_status: VisitCopyToEhrStatus
    offer: str
    blocks_visit: bool = False
    blocks_note: bool = False


def clear_fallback_state() -> None:
    """Drop in-memory marks and audit events. Tests use this between cases."""
    with _lock:
        _marks.clear()
        _events.clear()


def visit_view(visit_id: object) -> dict[str, str]:
    """Visit view field. ``unset`` until a failure marks ``not_sent_copy_instead``."""
    key = _visit_key(visit_id)
    if key is None:
        return {"visit_id": "", "visit_copy_to_ehr_status": _UNSET, "offer": ""}
    with _lock:
        _prune_marks_locked(_now())
        stored = _marks.get(key)
    status = stored[0] if stored is not None else _UNSET
    return {
        "visit_id": key,
        "visit_copy_to_ehr_status": status,
        "offer": VISIBLE_OFFER if status == _NOT_SENT else "",
    }


def fallback_audit_events() -> tuple[CopyToEhrAuditEvent, ...]:
    with _lock:
        return tuple(_events)


def note_adapter_failure(
    visit_id: object,
    vendor_id: object,
    *,
    kind: Literal["error", "disconnect"],
    error_code: object = None,
    visit_view_field: MutableMapping[str, str] | None = None,
) -> CopyFallbackOffer | None:
    """Mark one visit after an adapter error or a disconnect.

    Returns the visible offer when ``copy_to_ehr_fallback_enabled`` is on.
    Returns ``None`` when the flag is off or this visit cannot be named.
    Never raises. A failure here is logged as metadata only.
    """
    try:
        return _apply(
            visit_id,
            vendor_id,
            kind=kind,
            error_code=error_code,
            visit_view_field=visit_view_field,
        )
    except Exception:
        _log_hook_failure(vendor_id, kind)
        return None


@contextmanager
def visit_read(vendor_id: str, visit_id: object) -> Iterator[None]:
    """Read one visit. On an adapter error or disconnect, show the copy offer.

    The original return value and the original error are left unchanged.
    """
    try:
        yield
    except Exception as exc:
        _note_exception(vendor_id, visit_id, exc)
        raise


def _note_exception(vendor_id: str, visit_id: object, exc: BaseException) -> None:
    try:
        kind = _failure_kind(exc)
        code = _error_code(exc)
        if kind == "disconnect":
            note_adapter_failure(visit_id, vendor_id, kind="disconnect", error_code=code)
        elif kind == "error":
            note_adapter_failure(visit_id, vendor_id, kind="error", error_code=code)
    except Exception:
        _log_hook_failure(vendor_id, "error")


def _apply(
    visit_id: object,
    vendor_id: object,
    *,
    kind: Literal["error", "disconnect"],
    error_code: object,
    visit_view_field: MutableMapping[str, str] | None,
) -> CopyFallbackOffer | None:
    if kind not in {"error", "disconnect"} or not _enabled():
        return None
    key = _visit_key(visit_id)
    if key is None:
        return None
    vendor = vendor_id if isinstance(vendor_id, str) else None
    profile = copy_profile_for_vendor(vendor)
    # Mark first so the clinician still sees the offer if audit construction fails.
    now = _now()
    with _lock:
        _prune_marks_locked(now)
        _marks[key] = (_NOT_SENT, now)
    if visit_view_field is not None:
        visit_view_field["visit_copy_to_ehr_status"] = _NOT_SENT
        visit_view_field["offer"] = VISIBLE_OFFER
    event = build_audit_event(
        "copy_to_ehr.fallback_shown",
        profile_id=profile.id,
        outcome=kind,
        detail=_metadata(vendor_id, error_code),
    )
    with _lock:
        _events.append(event)
    logger.info(
        "copy_to_ehr.fallback_shown",
        extra={
            "event": "copy_to_ehr.fallback_shown",
            "profile_id": profile.id,
            "outcome": kind,
            "correlation_id": event.correlation_id,
        },
    )
    return CopyFallbackOffer(
        visit_id=key,
        visit_copy_to_ehr_status=_NOT_SENT,
        offer=VISIBLE_OFFER,
    )


def _prune_marks_locked(now: float) -> None:
    """Drop marks whose 60-minute absolute window has elapsed. Caller holds ``_lock``."""
    expired = [
        visit_id for visit_id, (_status, set_at) in _marks.items()
        if now - set_at >= ABSOLUTE_EXPIRY_SECONDS
    ]
    for visit_id in expired:
        del _marks[visit_id]


def _enabled() -> bool:
    from cosmas_os.config import settings

    return bool(getattr(settings, "copy_to_ehr_fallback_enabled", False))


def _visit_key(visit_id: object) -> str | None:
    if visit_id is None or isinstance(visit_id, bool):
        return None
    if isinstance(visit_id, str):
        text = visit_id.strip()
        return text or None
    if isinstance(visit_id, int):
        return str(visit_id) if visit_id > 0 else None
    if isinstance(visit_id, UUID):
        return str(visit_id)
    return None


def _metadata(vendor_id: object, error_code: object) -> dict[str, str]:
    detail: dict[str, str] = {}
    if isinstance(vendor_id, str) and _TOKEN.fullmatch(vendor_id):
        detail["vendor_id"] = vendor_id
    if isinstance(error_code, str) and _TOKEN.fullmatch(error_code):
        detail["error_code"] = error_code
    return detail


def _error_code(exc: BaseException) -> str | None:
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code
    if exc.args and isinstance(exc.args[0], str):
        return exc.args[0]
    return None


def _failure_kind(exc: BaseException) -> Literal["error", "disconnect"] | None:
    code = _error_code(exc)
    if code in _DISCONNECT_CODES:
        return "disconnect"
    names = {cls.__name__ for cls in type(exc).__mro__}
    if names & _ADAPTER_ERROR_TYPES:
        return "error"
    return None


def _log_hook_failure(vendor_id: object, kind: object) -> None:
    vendor = vendor_id if isinstance(vendor_id, str) and _TOKEN.fullmatch(vendor_id) else "unknown"
    outcome = kind if kind in {"error", "disconnect"} else "hook_failed"
    logger.info(
        "copy_to_ehr.fallback_hook_failed",
        extra={
            "event": "copy_to_ehr.fallback_hook_failed",
            "outcome": outcome,
            "vendor_id": vendor,
        },
    )
