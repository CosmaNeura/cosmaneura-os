"""Durable evaluation artifacts and traces, not an application work/approval queue."""

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class LabError(Exception):
    pass


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.started = time.monotonic()
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS artifacts (episode TEXT, role TEXT, sha TEXT, value TEXT, PRIMARY KEY(episode, role))")
        self.events = root / "events.jsonl"

    def connect(self):
        return sqlite3.connect(self.root / "artifacts.sqlite3", timeout=10)

    def event(self, episode, role, kind, **values):
        record = {"episode": episode, "role": role, "kind": kind,
                  "elapsed_ms": round((time.monotonic() - self.started) * 1000), **values}
        with self.lock, self.events.open("a") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def save(self, episode, role, payload):
        sha = digest(payload)
        value = {"id": role, "role": role, "sha256": sha, **payload}
        with self.lock, self.connect() as db:
            prior = db.execute("SELECT sha, value FROM artifacts WHERE episode=? AND role=?", (episode, role)).fetchone()
            if prior:
                if prior[0] != sha:
                    raise LabError("artifact_already_saved_with_different_content; read the saved artifact")
                return json.loads(prior[1])
            db.execute("INSERT INTO artifacts VALUES (?, ?, ?, ?)", (episode, role, sha, json.dumps(value)))
        return value

    def read(self, episode, role, recipient, sha=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM artifacts WHERE episode=? AND role=?", (episode, role)).fetchone()
        if not row:
            raise LabError("artifact_not_found")
        value = json.loads(row[0])
        if digest({k: v for k, v in value.items() if k not in {"id", "role", "sha256"}}) != value["sha256"]:
            raise LabError("artifact_integrity_error")
        if recipient != role and recipient not in value["share_with"]:
            raise LabError("artifact_not_shared_with_this_agent")
        if sha is not None and sha != value["sha256"]:
            raise LabError("artifact_revision_mismatch")
        return value

    def visible(self, episode, recipient):
        with self.connect() as db:
            rows = db.execute("SELECT value FROM artifacts WHERE episode=? ORDER BY role", (episode,)).fetchall()
        return [{k: v[k] for k in ("id", "role", "sha256")} for row in rows
                if (v := json.loads(row[0]))["role"] == recipient or recipient in v["share_with"]]
