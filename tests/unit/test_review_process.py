"""The evaluation harness rejects model rubber-stamping incomplete material."""

import json
import threading
from types import SimpleNamespace

from lab.review_graph import ReviewGraph
from lab.review_process import review_material
from lab.store import Store


def test_model_signoff_without_explicit_workflow_fields_requires_edits(tmp_path):
    store = Store(tmp_path)
    graph = ReviewGraph(tmp_path)
    node = graph.add("draft", kind="material", scope="invented", role="scribe", body="Invented facts only.")
    replies = []

    class Model:
        def reply(self, messages, tools):
            input_hash = json.loads(messages[1]["content"])["input_sha256"]
            choice = "request_edits" if replies else "sign_off"
            replies.append(choice)
            values = {"input_sha256": input_hash, "material_id": node["id"], "material_sha256": node["sha256"],
                "choice": choice, "feedback": "Add an explicit owner, next action and done-when criterion."}
            return {"role": "assistant", "tool_calls": [{"id": str(len(replies)), "type": "function",
                "function": {"name": "submit", "arguments": json.dumps(values)}}]}, {"total_tokens": 1}

    app = SimpleNamespace(workspace="invented", check_agent=lambda role: None, sources=lambda: [])
    journey = SimpleNamespace(app=app, model=Model(), store=store, episode="test", round=1, lock=threading.RLock(), tool_count=0)
    result = review_material(journey, graph, node, "provider")
    assert replies == ["sign_off", "request_edits"]
    assert result["review_state"] == "edits_requested" and not graph.snapshot()["complete"]
    assert len(result["decisions"]) == 1 and journey.tool_count == 1
    assert "Sign-off refused" in store.events.read_text()
