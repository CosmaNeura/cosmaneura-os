"""Exact-version simulated reviewer decisions over real application drafts.

This is evaluation state, never a second product approval queue. Reviewer
personas are agents and cannot approve clinical work or external operations.
"""

import json
import sqlite3
import threading
from pathlib import Path

from lab.store import LabError, digest

PERSONAS = {
    "provider": {"name": "Family practice doctor", "role": "scribe",
        "profile": "Nontechnical, time-pressed, conscientious. Wants a clear accurate draft, planned actions kept distinct, and no unexplained controls."},
    "nurse": {"name": "Nurse practitioner", "role": "visit_prep",
        "profile": "Nontechnical, practical, attentive to missing information and continuity. Wants a short actionable prep list and clear responsibility."},
    "pa": {"name": "Physician assistant", "role": "research",
        "profile": "Nontechnical, curious, careful with evidence. Wants readable trial conditions and uncertainty, without unsupported eligibility or treatment claims."},
}


class ReviewGraph:
    def __init__(self, root):
        self.path = Path(root) / "review-graph.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS edges (origin TEXT, target TEXT, relation TEXT, PRIMARY KEY(origin,target,relation))")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def add(self, key, *, kind, scope, role, body, application_receipt=None, dependencies=()):
        value = {"id": key, "kind": kind, "scope": scope, "role": role, "body": body,
            "sha256": digest(body), "application_receipt": application_receipt,
            "dependencies": list(dependencies), "review_state": "draft", "decisions": []}
        with self.lock, self.connect() as db:
            prior = db.execute("SELECT data FROM nodes WHERE id=?", (key,)).fetchone()
            if prior:
                saved = json.loads(prior[0])
                if any(saved[k] != value[k] for k in value if k not in {"review_state", "decisions"}):
                    raise LabError("graph_node_changed")
                return saved
            for dependency in dependencies:
                row = db.execute("SELECT data FROM nodes WHERE id=?", (dependency,)).fetchone()
                if not row or json.loads(row[0])["scope"] != scope:
                    raise LabError("graph_dependency_unavailable")
            db.execute("INSERT INTO nodes VALUES (?,?)", (key, json.dumps(value)))
            for dependency in dependencies:
                db.execute("INSERT INTO edges VALUES (?,?,?)", (dependency, key, "depends_on"))
        return value

    def decide(self, key, *, persona, scope, expected_sha256, choice, feedback, request_id):
        if persona not in PERSONAS or choice not in {"request_edits", "sign_off"} or not request_id or not feedback.strip():
            raise LabError("graph_review_invalid")
        with self.lock, self.connect() as db:
            row = db.execute("SELECT data FROM nodes WHERE id=?", (key,)).fetchone()
            if not row:
                raise LabError("graph_node_unavailable")
            value = json.loads(row[0])
            if (value["scope"] != scope or value["sha256"] != expected_sha256
                    or value["role"] != PERSONAS[persona]["role"] or value["kind"] != "material"):
                raise LabError("graph_review_binding_changed")
            decision = {"persona": persona, "choice": choice, "feedback": feedback,
                "material_sha256": expected_sha256, "request_id": request_id,
                "authority": "simulated_reviewer_agent_only"}
            prior = next((d for d in value["decisions"] if d["request_id"] == request_id), None)
            if prior:
                if prior != decision:
                    raise LabError("graph_review_replay_changed")
                return value
            if value["review_state"] != "draft":
                raise LabError("graph_review_already_decided")
            value["decisions"].append(decision)
            value["review_state"] = "edits_requested" if choice == "request_edits" else "signed_off"
            db.execute("UPDATE nodes SET data=? WHERE id=?", (json.dumps(value), key))
        return value

    def supersede(self, original, revised):
        with self.lock, self.connect() as db:
            values = [db.execute("SELECT data FROM nodes WHERE id=?", (key,)).fetchone() for key in (original, revised)]
            if not all(values):
                raise LabError("graph_revision_unavailable")
            old, new = [json.loads(row[0]) for row in values]
            if (old["scope"] != new["scope"] or old["role"] != new["role"]
                    or old["review_state"] != "edits_requested" or original not in new["dependencies"]
                    or old["sha256"] == new["sha256"]):
                raise LabError("graph_revision_binding_changed")
            db.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?)", (original, revised, "revised_after_feedback"))

    def snapshot(self):
        with self.connect() as db:
            nodes = [json.loads(row[0]) for row in db.execute("SELECT data FROM nodes ORDER BY id")]
            edges = [{"from": row[0], "to": row[1], "relation": row[2]} for row in db.execute("SELECT origin,target,relation FROM edges ORDER BY origin,target,relation")]
        superseded = {e["from"] for e in edges if e["relation"] == "revised_after_feedback"}
        materials = [node for node in nodes if node["kind"] == "material" and node["id"] not in superseded]
        complete = bool(materials) and all(node["review_state"] == "signed_off" for node in materials)
        return {"nodes": nodes, "edges": edges, "complete": complete,
            "completed_scope": "simulated review of latest private drafts",
            "real_clinical_signoff": False, "external_effects": 0}
