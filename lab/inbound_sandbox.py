"""Offline event replay and explicitly reviewed source import, not a vendor inbox.

The lab ledger records immutable delivery fixtures and import intents. Workspace
entries and all subsequent work use real PostgreSQL application services. This
does not grant mail-body access, implement a webhook, or download attachments.
"""

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from cosmas_os.application import workspace
from cosmas_os.models import EncounterWorkspace
from lab.store import LabError, digest


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    attachment_id: str = Field(min_length=1, max_length=128)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")
    byte_length: int = Field(gt=0, le=65536)
    media_type: Literal["application/pdf"]


class InboundEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    event_id: UUID
    message_id: UUID
    thread_id: UUID
    account_id: UUID
    workspace_id: UUID
    patient_link_id: UUID
    provider: Literal["google", "microsoft", "documo", "srfax"]
    modified_at: datetime
    text: str = Field(min_length=1, max_length=4000)
    attachments: tuple[Attachment, ...] = Field(max_length=4)

    def source_hash(self):
        return digest(self.model_dump(mode="json", exclude={"event_id"}))


class InboundSandbox:
    def __init__(self, app, root: Path):
        self.app, self.root = app, root
        root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, sha TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS imports (source TEXT PRIMARY KEY, request TEXT NOT NULL, entry TEXT)")

    def connect(self):
        return sqlite3.connect(self.root / "inbound-fixtures.sqlite3", timeout=10)

    def arrive(self, event):
        event = InboundEvent.model_validate(event)
        if event.modified_at.tzinfo is None:
            raise LabError("event_timezone_required")
        with Session(self.app.engine) as session:
            current = session.get(EncounterWorkspace, self.app.workspace)
            if (str(event.workspace_id), str(event.patient_link_id)) != (current.id, current.patient_link_id):
                raise LabError("reviewed_encounter_mapping_required")
        payload = event.model_dump(mode="json")
        with self.connect() as db:
            prior = db.execute("SELECT sha FROM events WHERE id=?", (str(event.event_id),)).fetchone()
            if prior:
                if prior[0] != digest(payload):
                    raise LabError("immutable_event_conflict")
                return "duplicate"
            db.execute("INSERT INTO events VALUES (?, ?, ?)", (str(event.event_id), digest(payload), json.dumps(payload)))
        return self.classify(event)

    def classify(self, event):
        with self.connect() as db:
            rows = db.execute("SELECT payload, sha FROM events").fetchall()
        peers = []
        for raw, sha in rows:
            value = json.loads(raw)
            if digest(value) != sha:
                raise LabError("event_integrity_error")
            other = InboundEvent.model_validate_json(raw)
            if (other.provider, other.account_id, other.message_id) != (event.provider, event.account_id, event.message_id):
                continue
            if (other.thread_id, other.workspace_id, other.patient_link_id) != (event.thread_id, event.workspace_id, event.patient_link_id):
                raise LabError("immutable_message_identity_conflict")
            peers.append(other)
        latest = max((e.modified_at for e in peers), default=event.modified_at)
        heads = [e for e in peers if e.modified_at == latest]
        if len({e.source_hash() for e in heads}) > 1:
            return "conflict"
        return "older" if event.modified_at < latest else "current"

    def import_reviewed(self, event, blobs, *, reviewed=False, lose_reply=False):
        if reviewed is not True:
            raise LabError("human_source_review_required")
        if self.classify(event) != "current":
            raise LabError("source_not_current")
        with self.connect() as db:
            received = db.execute("SELECT sha FROM events WHERE id=?", (str(event.event_id),)).fetchone()
        if received != (digest(event.model_dump(mode="json")),):
            raise LabError("exact_arrival_required")
        if set(blobs) != {a.attachment_id for a in event.attachments}:
            raise LabError("attachment_missing_or_extra")
        for attachment in event.attachments:
            raw = blobs[attachment.attachment_id]
            if (len(raw), hashlib.sha256(raw).hexdigest()) != (attachment.byte_length, attachment.sha256):
                raise LabError("attachment_integrity_error")
        source = event.source_hash()
        with self.connect() as db:
            row = db.execute("SELECT request FROM imports WHERE source=?", (source,)).fetchone()
            if row:
                request = json.loads(row[0])
            else:
                with Session(self.app.engine) as session:
                    current = workspace.read(session, self.app.box, self.app.owner, self.app.workspace)
                request = dict(expected=current["revision"], key="inbound-" + source, kind="evidence",
                    source_label="Synthetic reviewed " + event.provider + " arrival — lab import",
                    content="SYNTHETIC LAB IMPORT. Human matched the encounter and inspected attached files. "
                    "Attachment bytes are verified; no OCR or attachment text extraction is claimed.\n" + event.text
                    + "\nExact source identity: " + json.dumps(event.model_dump(mode="json", exclude={"text"}), sort_keys=True))
                db.execute("INSERT INTO imports VALUES (?, ?, NULL)", (source, json.dumps(request)))
        with Session(self.app.engine) as session:
            result = workspace.append(session, self.app.box, self.app.owner, self.app.workspace, **request)
        if lose_reply:
            raise LabError("injected_lost_import_reply")
        with self.connect() as db:
            db.execute("UPDATE imports SET entry=? WHERE source=?", (result["entry_id"], source))
        return {"source_sha256": source, "entry_id": result["entry_id"], "entry_revision": result["entry_revision"]}
