import json
import os
import shutil
import signal
import threading
from pathlib import Path

import pytest
from lab.mcp_runtime import MCPRuntime
from lab.store import Store


@pytest.fixture
def postgres_bin():
    found = shutil.which("pg_ctl")
    if not found:
        pytest.skip("Owned runtime qualification requires local PostgreSQL tools")
    return Path(found).resolve().parent


def body(source_id, **changes):
    return {"body": "Synthetic internal draft for human review. No external action has occurred.",
            "source_ids": [source_id], "dependencies": [], "share_with": ["chief", "follow_up"], **changes}


@pytest.mark.parametrize("fault", ["none", "lost_save_reply", "read_timeout"])
def test_owned_replay_team_shares_exact_artifacts_without_human_actions(tmp_path, postgres_bin, monkeypatch, fault):
    monkeypatch.setenv("DATABASE_URL", "synthetic_PRIVATE_external_database_must_be_ignored")
    root = tmp_path / "owned-mcp"
    with MCPRuntime(root, postgres_bin, fault=fault) as session:
        initial = session.status()
        assert initial["role"] == "chief" and initial["case"] == "walk_in"
        assert initial["mode"] == "replay" and initial["source"]["source_sha256"]
        sources = session.call("list_sources", {})
        source = session.call("read_source", {"source_id": sources[0]["id"]})
        assert "SYNTHETIC" in source["content"]
        assert session.call("read_source", {"source_id": "foreign-encounter"})["error"] == "source_outside_selected_encounter"
        upstream = session.call("delegate_team", {"roles": ["visit_prep", "scribe", "research"]})
        assert all(item["status"] == "saved" for item in upstream["results"])
        assert session.call("delegate_team", {"roles": ["follow_up"]})["results"][0]["status"] == "saved"
        follow = next(item for item in session.call("list_artifacts", {}) if item["role"] == "follow_up")
        saved = session.call("read_artifact", {"artifact_id": follow["id"], "sha256": follow["sha256"]})
        assert {item["artifact_id"] for item in saved["dependencies"]} == {"scribe", "research", "visit_prep"}
        command = body(source["id"], dependencies=[{"artifact_id": follow["id"], "sha256": follow["sha256"]}])
        chief = session.call("save_artifact", command)
        assert chief == session.call("save_artifact", command)
        assert "error" in session.call("save_artifact", {**command, "body": "Changed draft cannot replace the saved version."})
        status = session.status()
        assert status["artifact_count"] == 5 and status["failures"] == []
        assert status["usage"] == {"model_calls": 0, "tokens": 0}
        assert status["external_effects"] == 0
        assert status["faults_seen"] == ([] if fault == "none" else ["save_artifact"] if fault == "lost_save_reply" else ["read_source"])
        assert "body" not in json.dumps(status) and str(root) not in json.dumps(status)
        assert session.call("application_status", {})["workflow"]["status"] == "drafts_only"
    cleanup = json.loads((root / "cleanup.json").read_text())
    assert cleanup["successful"] and cleanup["worker_exited"] and cleanup["pg_stopped"]
    assert not (root / "temporary-postgres-password").exists()
    assert not (root / "postgres/postmaster.pid").exists()
    assert Store(root).read("mcp-walk_in", "chief", "chief") == chief
    assert session.status()["state"] == "closed"
    assert "synthetic_PRIVATE_external_database" not in (root / "events.jsonl").read_text()


def test_scribe_recovers_lost_write_receipt_and_cannot_choose_authority(tmp_path, postgres_bin):
    root = tmp_path / "scribe"
    with MCPRuntime(root, postgres_bin, role="scribe", case="follow_up", fault="lost_save_reply") as session:
        source = session.call("list_sources", {})[0]
        session.call("read_source", {"source_id": source["id"]})
        command = body(source["id"])
        assert "injected_lost_reply" in session.call("save_artifact", command)["error"]
        receipt = session.call("save_artifact", command)
        assert receipt["id"] == "scribe"
        assert session.call("read_artifact", {"artifact_id": "scribe", "sha256": receipt["sha256"]}) == receipt
        assert session.call("delegate_team", {"roles": ["research"]}) == {"error": "unknown_tool"}
        assert session.call("list_sources", {"role": "chief"}) == {"error": "invalid_tool_arguments"}
        assert session.call("exercise_follow_up", {}) == {"error": "unknown_tool"}
        assert session.call("application_status", {})["workflow"]["status"] == "drafts_only"
    assert session.close()["successful"]
    assert session.call("list_sources", {}) == {"error": "runtime_closed"}


def test_expired_session_stops_worker_and_database_without_new_work(tmp_path, postgres_bin):
    with MCPRuntime(tmp_path / "expired", postgres_bin) as session:
        session._deadline = 0
        assert session.call("list_sources", {}) == {"error": "run_budget_exhausted"}
        assert session.close()["successful"]
        assert session._worker is not None and session.output is not None
        assert session._worker.poll() is not None
        assert not os.path.exists(session.output / "postgres/postmaster.pid")


def test_close_interrupts_inflight_owned_worker_before_stopping_its_database(tmp_path, postgres_bin, monkeypatch):
    with MCPRuntime(tmp_path / "cancelled", postgres_bin, max_seconds=30) as session:
        assert session._worker is not None
        # Pause only this session's child to simulate a stuck operation. No
        # application source is replaced and no remote service is involved.
        os.kill(session._worker.pid, signal.SIGSTOP)
        waiting = threading.Event()
        receive = session._receive
        result = []

        def receive_when_ready(seconds):
            waiting.set()
            return receive(seconds)

        monkeypatch.setattr(session, "_receive", receive_when_ready)
        caller = threading.Thread(target=lambda: result.append(session.call("list_sources", {})))
        caller.start()
        assert waiting.wait(timeout=2)
        cleanup = session.close()
        caller.join(timeout=2)
        assert not caller.is_alive()
        assert result == [{"error": "runtime_worker_unavailable"}]
        assert cleanup["successful"] and cleanup["worker_exited"] and cleanup["pg_stopped"]
        assert session._worker.poll() is not None
        assert session.output is not None
        assert not (session.output / "postgres/postmaster.pid").exists()
