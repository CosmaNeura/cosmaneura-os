"""Phone remote highlight sessions for Copy to EHR.

Highlight messages carry section keys and draft revisions only. They never
carry note text, clinic labels, chart URLs, or page titles. Sessions live in
process memory, expire after 15 minutes idle or 60 minutes absolute, and end
on logout, visit change, or an explicit End call.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cosmas_os.application import workspace as ws

IDLE_LIMIT = timedelta(minutes=15)
ABSOLUTE_LIMIT = timedelta(minutes=60)
MAX_SECTION_KEYS = 32
MAX_EVENTS = 200


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class HighlightEvent:
    seq: int
    section_key: str
    draft_revision: int
    at: datetime


@dataclass
class RemoteSession:
    id: str
    box_id: str
    principal_id: str
    draft_id: str
    draft_revision: int
    section_keys: tuple[str, ...]
    visit_key: str
    created_at: datetime
    last_activity_at: datetime
    ended_at: datetime | None = None
    end_reason: str | None = None
    events: list[HighlightEvent] = field(default_factory=list)
    next_seq: int = 1


class RemoteSessionStore:
    """Process-local store for highlight-only remote sessions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, RemoteSession] = {}
        self._active_by_owner: dict[tuple[str, str], str] = {}

    def reset(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._active_by_owner.clear()

    def create(
        self,
        *,
        box_id: str,
        principal_id: str,
        draft_id: str,
        draft_revision: int,
        section_keys: list[str],
        visit_key: str,
        now: datetime | None = None,
    ) -> RemoteSession:
        clock = now or _now()
        keys = tuple(section_keys)
        if not keys or len(keys) > MAX_SECTION_KEYS or len(set(keys)) != len(keys):
            raise ws.WorkspaceError("invalid_copy_to_ehr_remote_request", 422)
        with self._lock:
            owner = (box_id, principal_id)
            previous_id = self._active_by_owner.get(owner)
            if previous_id is not None:
                previous = self._sessions.get(previous_id)
                if previous is not None and previous.ended_at is None:
                    previous.ended_at = clock
                    previous.end_reason = "replaced"
            session = RemoteSession(
                id=str(uuid4()),
                box_id=box_id,
                principal_id=principal_id,
                draft_id=draft_id,
                draft_revision=draft_revision,
                section_keys=keys,
                visit_key=visit_key,
                created_at=clock,
                last_activity_at=clock,
            )
            self._sessions[session.id] = session
            self._active_by_owner[owner] = session.id
            return self._snapshot(session)

    def current(
        self,
        *,
        box_id: str,
        principal_id: str,
        now: datetime | None = None,
    ) -> RemoteSession | None:
        clock = now or _now()
        with self._lock:
            session_id = self._active_by_owner.get((box_id, principal_id))
            if session_id is None:
                return None
            session = self._sessions.get(session_id)
            if session is None:
                return None
            self._expire_locked(session, clock)
            if session.ended_at is not None:
                return None
            return self._snapshot(session)

    def get_for_owner(
        self,
        *,
        session_id: str,
        box_id: str,
        principal_id: str,
        now: datetime | None = None,
    ) -> RemoteSession:
        clock = now or _now()
        with self._lock:
            session = self._require_owner_locked(session_id, box_id, principal_id)
            self._expire_locked(session, clock)
            if session.ended_at is not None:
                raise ws.WorkspaceError("copy_to_ehr_remote_session_ended", 409)
            session.last_activity_at = clock
            return self._snapshot(session)

    def highlight(
        self,
        *,
        session_id: str,
        box_id: str,
        principal_id: str,
        draft_revision: int,
        section_key: str,
        now: datetime | None = None,
    ) -> HighlightEvent:
        clock = now or _now()
        with self._lock:
            session = self._require_owner_locked(session_id, box_id, principal_id)
            self._expire_locked(session, clock)
            if session.ended_at is not None:
                raise ws.WorkspaceError("copy_to_ehr_remote_session_ended", 409)
            if section_key not in session.section_keys:
                raise ws.WorkspaceError("invalid_copy_to_ehr_remote_request", 422)
            if draft_revision != session.draft_revision:
                raise ws.WorkspaceError("copy_to_ehr_remote_revision_mismatch", 409)
            if len(session.events) >= MAX_EVENTS:
                raise ws.WorkspaceError("copy_to_ehr_remote_session_ended", 409)
            event = HighlightEvent(
                seq=session.next_seq,
                section_key=section_key,
                draft_revision=draft_revision,
                at=clock,
            )
            session.next_seq += 1
            session.events.append(event)
            session.last_activity_at = clock
            return HighlightEvent(
                seq=event.seq,
                section_key=event.section_key,
                draft_revision=event.draft_revision,
                at=event.at,
            )

    def events_after(
        self,
        *,
        session_id: str,
        box_id: str,
        principal_id: str,
        after: int,
        now: datetime | None = None,
    ) -> tuple[RemoteSession, list[HighlightEvent]]:
        clock = now or _now()
        if after < 0:
            raise ws.WorkspaceError("invalid_copy_to_ehr_remote_request", 422)
        with self._lock:
            session = self._require_owner_locked(session_id, box_id, principal_id)
            self._expire_locked(session, clock)
            if session.ended_at is None:
                session.last_activity_at = clock
            events = [
                HighlightEvent(
                    seq=event.seq,
                    section_key=event.section_key,
                    draft_revision=event.draft_revision,
                    at=event.at,
                )
                for event in session.events
                if event.seq > after
            ]
            return self._snapshot(session), events

    def end(
        self,
        *,
        session_id: str,
        box_id: str,
        principal_id: str,
        reason: str,
        now: datetime | None = None,
    ) -> RemoteSession:
        clock = now or _now()
        with self._lock:
            session = self._require_owner_locked(session_id, box_id, principal_id)
            self._expire_locked(session, clock)
            if session.ended_at is None:
                session.ended_at = clock
                session.end_reason = reason
                session.last_activity_at = clock
            owner = (box_id, principal_id)
            if self._active_by_owner.get(owner) == session.id:
                self._active_by_owner.pop(owner, None)
            return self._snapshot(session)

    def end_active_for_owner(
        self,
        *,
        box_id: str,
        principal_id: str,
        reason: str,
        now: datetime | None = None,
    ) -> RemoteSession | None:
        clock = now or _now()
        with self._lock:
            session_id = self._active_by_owner.get((box_id, principal_id))
            if session_id is None:
                return None
            session = self._sessions.get(session_id)
            if session is None:
                return None
            self._expire_locked(session, clock)
            if session.ended_at is None:
                session.ended_at = clock
                session.end_reason = reason
                session.last_activity_at = clock
            self._active_by_owner.pop((box_id, principal_id), None)
            return self._snapshot(session)

    def _require_owner_locked(self, session_id: str, box_id: str, principal_id: str) -> RemoteSession:
        session = self._sessions.get(session_id)
        if session is None or session.box_id != box_id or session.principal_id != principal_id:
            raise ws.WorkspaceError("copy_to_ehr_remote_session_unavailable", 404)
        return session

    def _expire_locked(self, session: RemoteSession, clock: datetime) -> None:
        if session.ended_at is not None:
            return
        idle = clock - session.last_activity_at >= IDLE_LIMIT
        absolute = clock - session.created_at >= ABSOLUTE_LIMIT
        if idle or absolute:
            session.ended_at = clock
            session.end_reason = "idle" if idle and not absolute else "absolute"
            owner = (session.box_id, session.principal_id)
            if self._active_by_owner.get(owner) == session.id:
                self._active_by_owner.pop(owner, None)

    @staticmethod
    def _snapshot(session: RemoteSession) -> RemoteSession:
        return RemoteSession(
            id=session.id,
            box_id=session.box_id,
            principal_id=session.principal_id,
            draft_id=session.draft_id,
            draft_revision=session.draft_revision,
            section_keys=session.section_keys,
            visit_key=session.visit_key,
            created_at=session.created_at,
            last_activity_at=session.last_activity_at,
            ended_at=session.ended_at,
            end_reason=session.end_reason,
            events=[
                HighlightEvent(
                    seq=event.seq,
                    section_key=event.section_key,
                    draft_revision=event.draft_revision,
                    at=event.at,
                )
                for event in session.events
            ],
            next_seq=session.next_seq,
        )


STORE = RemoteSessionStore()


def session_status(session: RemoteSession) -> str:
    if session.ended_at is None:
        return "open"
    if session.end_reason in {"idle", "absolute"}:
        return "expired"
    return "ended"


def public_session(session: RemoteSession) -> dict:
    """Wire shape with no note text and no clinic labels."""
    return {
        "session_id": session.id,
        "status": session_status(session),
        "draft_id": session.draft_id,
        "draft_revision": session.draft_revision,
        "section_keys": list(session.section_keys),
        "visit_key": session.visit_key,
        "created_at": session.created_at.isoformat().replace("+00:00", "Z"),
        "last_activity_at": session.last_activity_at.isoformat().replace("+00:00", "Z"),
        "ended_at": None if session.ended_at is None else session.ended_at.isoformat().replace("+00:00", "Z"),
        "end_reason": session.end_reason,
    }


def public_event(event: HighlightEvent) -> dict:
    return {
        "seq": event.seq,
        "section_key": event.section_key,
        "draft_revision": event.draft_revision,
        "at": event.at.isoformat().replace("+00:00", "Z"),
    }


def assert_no_note_text(payload: object) -> None:
    """Test helper: reject payloads that smuggle note body fields."""
    forbidden = {
        "text", "note", "note_text", "full_note", "content", "body",
        "clipboard", "patient", "chart_url", "page_title", "label", "labels",
    }
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in forbidden:
                raise AssertionError(f"forbidden remote field: {key}")
            assert_no_note_text(value)
    elif isinstance(payload, list):
        for item in payload:
            assert_no_note_text(item)
