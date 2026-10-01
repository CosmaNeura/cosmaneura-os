"""An explicitly reviewed snapshot for saved team context, never a live mirror.

The capture boundary supplies a freshly authorized original creator review while
holding the final local scope lock. No renderer transcript text is accepted.
"""

import hashlib
import json
import re
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator
from sqlalchemy import select

from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import WorkspaceEntry
from cosmas_os.ports.creator_review import CreatorReviewView
from cosmas_os.ports.scribe_capture import ProtectedModel


class ScribeSourceSelection(ProtectedModel):
    version: Literal[1]
    session_id: UUID
    source_transcript_version: int = Field(strict=True, ge=1)
    working_transcript_id: UUID
    working_transcript_version: int = Field(strict=True, ge=1)
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)

    @field_validator("version", mode="before")
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("invalid version")
        return value


def selection(view: CreatorReviewView) -> ScribeSourceSelection | None:
    if view.status != "transcript_ready" or view.working is None or not view.working.note_ready:
        return None
    value = view.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()
    return ScribeSourceSelection(
        version=1,
        session_id=view.session_id,
        source_transcript_version=view.working.source_transcript_version,
        working_transcript_id=view.working.working_transcript_id,
        working_transcript_version=view.working.working_transcript_version,
        snapshot_sha256=digest,
    )


def packet_content(view, selected):
    # Retain original IDs/versions and the exact displayed receipt fingerprint.
    # This content is a snapshot, not a claim of ongoing remote authorization.
    lines = [
        "Reviewed Scribe transcript snapshot, explicitly shared with this encounter's team.",
        "Saved source evidence; not a live-synced transcript or a signed clinical note.",
        f"Original session: {selected.session_id}",
        f"Source transcript version: {selected.source_transcript_version}",
        f"Working transcript: {selected.working_transcript_id}; version {selected.working_transcript_version}",
        f"Reviewed snapshot SHA-256: {selected.snapshot_sha256}",
    ]
    if view.capture_continuity is not None:
        lines.append(
            "Recording continuity is unconfirmed. Speech may be missing; gap lengths are unknown."
        )
        lines.append(
            "Original continuity evidence: "
            + json.dumps(
                view.capture_continuity.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    for segment in view.working.segments:
        lines.append(
            f"\nSource segment: {segment.source_segment_id}; version {segment.source_segment_version}; "
            f"source language: {segment.source_locale}; resolution: {segment.resolution}"
        )
        if segment.resolution == "spanish_translation":
            lines.append(
                f"Reviewed translation: {segment.translation_id}; version {segment.translation_version}; "
                f"review: {segment.translation_review_id}"
            )
        lines.append(
            f"[{segment.start_ms}–{segment.end_ms} ms · {segment.speaker_role}] {segment.content}"
        )
    content = "\n".join(lines)
    if len(content) > 28000:
        raise ws.WorkspaceError("scribe_source_packet_too_large", 422)
    return content


def require_complete_context(sources):
    """A saved packet is indivisible at the existing model projection limits."""
    packets = {}
    for source in sources:
        match = re.fullmatch(
            r"Reviewed Scribe snapshot · ([a-f0-9]{64}) · ([1-9][0-9]*)/([1-9][0-9]*)", source.label
        )
        if match:
            digest, part, count = match.groups()
            packets.setdefault(digest, []).append((source, int(part), int(count)))
    if not packets:
        return
    remaining, complete = 30000, set()
    for source in reversed(list(sources)[-12:]):
        admitted = min(len(source.content), 5000, remaining)
        if admitted == len(source.content):
            complete.add(source.entry_id)
        remaining -= admitted
    for rows in packets.values():
        counts = {count for _, _, count in rows}
        if (
            len(counts) != 1
            or len(rows) != next(iter(counts))
            or {part for _, part, _ in rows} != set(range(1, len(rows) + 1))
            or any(source.entry_id not in complete for source, _, _ in rows)
        ):
            raise ws.WorkspaceError("scribe_source_context_too_large", 422)


def request_digest(expected, selected):
    return payload_hash(
        {
            "kind": "reviewed_scribe_snapshot",
            "expected": expected,
            "selection": selected.model_dump(mode="json"),
        }
    )


def part_keys(key, count):
    return [key] + [
        "scribe:" + hashlib.sha256(key.encode()).hexdigest() + ":" + str(i) for i in range(1, count)
    ]


def response(session, box, owner, workspace_id, selected, entries):
    from cosmas_os.application.model_work import project_workspace

    snapshot = ws.read(session, box, owner, workspace_id, at_revision=entries[-1].revision)
    return {
        "entry_id": entries[0].id,
        "entry_revision": entries[-1].revision,
        "entries": [
            {
                "entry_id": row.id,
                "entry_revision": row.revision,
                "content_sha256": hashlib.sha256(row.content.encode()).hexdigest(),
            }
            for row in entries
        ],
        "snapshot_sha256": selected.snapshot_sha256,
        "workspace": project_workspace(session, snapshot),
    }


def saved_snapshot(session, *, box, owner, workspace_id, expected, key, selected):
    """Recover exact saved intent before remote source freshness is consulted."""
    ws._workspace(session, box, owner, workspace_id)
    first = session.scalar(
        select(WorkspaceEntry).where(
            WorkspaceEntry.workspace_id == workspace_id, WorkspaceEntry.idempotency_key == key
        )
    )
    if first is None:
        session.rollback()
        return None
    digest = request_digest(expected, selected)
    prefix = f"Reviewed Scribe snapshot · {selected.snapshot_sha256} · "
    if (
        first.request_hash != digest
        or first.kind != "evidence"
        or not first.source_label
        or not first.source_label.startswith(prefix + "1/")
    ):
        raise ws.WorkspaceError("idempotency_conflict", 409)
    try:
        count = int(first.source_label.rsplit("/", 1)[1])
    except (ValueError, IndexError):
        raise ws.WorkspaceError("scribe_source_packet_unconfirmed", 409) from None
    if not 1 <= count <= 12:
        raise ws.WorkspaceError("scribe_source_packet_unconfirmed", 409)
    keys = part_keys(key, count)
    rows = list(
        session.scalars(
            select(WorkspaceEntry).where(
                WorkspaceEntry.workspace_id == workspace_id,
                WorkspaceEntry.idempotency_key.in_(keys),
            )
        )
    )
    indexed = {row.idempotency_key: row for row in rows}
    if set(indexed) != set(keys):
        raise ws.WorkspaceError("scribe_source_packet_unconfirmed", 409)
    entries = [indexed[k] for k in keys]
    if any(
        row.request_hash != digest
        or row.kind != "evidence"
        or row.source_label != prefix + f"{i + 1}/{count}"
        or row.revision != first.revision + i
        or len(row.content) > 5000
        for i, row in enumerate(entries)
    ):
        raise ws.WorkspaceError("scribe_source_packet_unconfirmed", 409)
    return response(session, box, owner, workspace_id, selected, entries)


def save_snapshot(session, *, box, owner, workspace_id, expected, key, selected, checked):
    view = checked.review
    if view is None or selection(view) != selected:
        raise ws.WorkspaceError("scribe_source_changed", 409)
    # Split complete text into bounded evidence passages; no model adapter will
    # shorten a single part. All parts commit atomically under one request.
    content = packet_content(view, selected)
    pieces = [content[start : start + 4500] for start in range(0, len(content), 4500)]
    parts = [
        f"Reviewed Scribe snapshot {selected.snapshot_sha256} · part {i + 1}/{len(pieces)}\n"
        + piece
        for i, piece in enumerate(pieces)
    ]
    if sum(map(len, parts)) > 30000 or len(parts) > 12:
        raise ws.WorkspaceError("scribe_source_packet_too_large", 422)
    w = ws._workspace(session, box, owner, workspace_id, writing=True)
    request_hash = request_digest(expected, selected)
    keys = part_keys(key, len(parts))
    existing = list(
        session.scalars(
            select(WorkspaceEntry).where(
                WorkspaceEntry.workspace_id == workspace_id,
                WorkspaceEntry.idempotency_key.in_(keys),
            )
        )
    )
    by_key = {row.idempotency_key: row for row in existing}
    if existing:
        if set(by_key) != set(keys) or any(
            by_key[k].request_hash != request_hash or by_key[k].content != text
            for k, text in zip(keys, parts, strict=True)
        ):
            raise ws.WorkspaceError("idempotency_conflict", 409)
        entries = [by_key[k] for k in keys]
    else:
        if w.revision != expected:
            raise ws.WorkspaceError("workspace_revision_conflict", 409)
        if w.revision + len(parts) > 500:
            raise ws.WorkspaceError("workspace_history_limit", 409)
        if (
            session.scalar(
                select(WorkspaceEntry.id)
                .where(
                    WorkspaceEntry.workspace_id == workspace_id,
                    WorkspaceEntry.source_label
                    == f"Reviewed Scribe snapshot · {selected.snapshot_sha256} · 1/{len(parts)}",
                )
                .limit(1)
            )
            is not None
        ):
            # A newly generated intent must not duplicate a whole packet and
            # make the existing indivisible source group ambiguous downstream.
            raise ws.WorkspaceError("scribe_source_already_saved", 409)
        entries = []
        for i, (part_key, text) in enumerate(zip(keys, parts, strict=True)):
            w.revision += 1
            row = WorkspaceEntry(
                workspace_id=workspace_id,
                box_id=box,
                actor_id=owner,
                revision=w.revision,
                kind="evidence",
                content=text,
                source_label=f"Reviewed Scribe snapshot · {selected.snapshot_sha256} · {i + 1}/{len(parts)}",
                idempotency_key=part_key,
                request_hash=request_hash,
            )
            session.add(row)
            entries.append(row)
        session.flush()
        ws._audit(session, w, "scribe_snapshot_saved")
        session.commit()
    return response(session, box, owner, workspace_id, selected, entries)
