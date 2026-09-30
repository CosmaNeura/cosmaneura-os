import json
import sqlite3

import pytest
from lab.cases import CASES
from lab.engine import Budget, World
from lab.evaluate import grade
from lab.store import LabError, Store


class ApplicationFixture:
    revoked = False

    def sources(self, metadata_only=False):
        return [{"id": "source-1", "revision": 1, "label": "Invented",
                 **({} if metadata_only else {"content": "SYNTHETIC source"})}]

    def agent_id(self, role):
        return "synthetic-agent:" + role

    def check_agent(self, role):
        if self.revoked:
            raise LabError("agent_authority_unavailable")

    def status(self):
        return {"status": "drafts_only", "external_effects": 0}


def world(tmp_path, *, fault="none", case="follow_up", episode="one"):
    return World(Store(tmp_path), episode, CASES[case], ApplicationFixture(), fault=fault)


def payload(**changes):
    return {"body": "Invented administrative draft for review.", "source_ids": ["source-1"],
            "dependencies": [], "share_with": ["chief", "follow_up"], **changes}


@pytest.mark.parametrize("case", list(CASES))
def test_five_roles_share_exact_artifacts_through_same_tools_in_replay(tmp_path, case):
    w = world(tmp_path, case=case)
    result = w.run_agent("chief")
    assert result["status"] == "saved" and not w.failures
    follow = w.store.read("one", "follow_up", "chief")
    assert {d["artifact_id"] for d in follow["dependencies"]} == {"scribe", "visit_prep", "research"}
    for dependency in follow["dependencies"]:
        assert w.store.read("one", dependency["artifact_id"], "follow_up", dependency["sha256"])


@pytest.mark.parametrize("fault", ["lost_save_reply", "read_timeout"])
def test_injected_failure_recovers_without_duplicate_artifact(tmp_path, fault):
    w = world(tmp_path, fault=fault)
    assert w.run_agent("chief")["status"] == "saved"
    assert len(w.faults_seen) == 1
    with sqlite3.connect(tmp_path / "artifacts.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 5
    events = [json.loads(line) for line in w.store.events.read_text().splitlines()]
    assert any(e.get("ok") is False and "injected" in e["error"] for e in events)


def test_source_and_artifact_scopes_are_not_caller_selectable(tmp_path):
    w = world(tmp_path)
    assert "error" in w.execute("scribe", "read_source", {"source_id": "other-encounter"})
    assert "error" in w.execute("scribe", "read_source", {"source_id": "source-1", "owner_id": "foreign"})
    assert "error" in w.execute("scribe", "save_artifact", payload())
    w.execute("scribe", "read_source", {"source_id": "source-1"})
    saved = w.execute("scribe", "save_artifact", payload())
    assert "error" not in saved
    assert "error" in w.execute("visit_prep", "read_artifact", {"artifact_id": "scribe", "sha256": saved["sha256"]})
    other = World(w.store, "other-episode", CASES["visit"], ApplicationFixture())
    assert "error" in other.execute("chief", "read_artifact", {"artifact_id": "scribe", "sha256": saved["sha256"]})


def test_artifact_hash_and_dependency_reads_are_required(tmp_path):
    w = world(tmp_path)
    w.replay("scribe")
    assert "error" in w.execute("follow_up", "read_artifact", {"artifact_id": "scribe", "sha256": "0" * 64})
    w.execute("follow_up", "read_source", {"source_id": "source-1"})
    saved = w.store.read("one", "scribe", "scribe")
    args = payload(dependencies=[{"artifact_id": "scribe", "sha256": saved["sha256"]}])
    assert "error" in w.execute("follow_up", "save_artifact", args)
    w.execute("follow_up", "read_artifact", {"artifact_id": "scribe", "sha256": saved["sha256"]})
    assert "error" in w.execute("follow_up", "save_artifact", args)  # Missing the other two teammates.


def test_save_replay_is_exact_and_restart_keeps_receipt(tmp_path):
    w = world(tmp_path)
    w.execute("scribe", "read_source", {"source_id": "source-1"})
    first = w.execute("scribe", "save_artifact", payload())
    assert w.execute("scribe", "save_artifact", payload()) == first
    assert "error" in w.execute("scribe", "save_artifact", payload(body="Changed output cannot replace the saved draft."))
    assert Store(tmp_path).read("one", "scribe", "chief") == first


def test_revocation_is_rechecked_for_every_tool(tmp_path):
    w = world(tmp_path)
    w.execute("scribe", "read_source", {"source_id": "source-1"})
    w.app.revoked = True
    assert w.execute("scribe", "save_artifact", payload()) == {"error": "agent_authority_unavailable"}
    assert w.execute("scribe", "list_sources", {}) == {"error": "agent_authority_unavailable"}
    assert w.store.visible("one", "scribe") == []


@pytest.mark.parametrize("tool", ["approve", "send_email", "shell", "fetch_url", "change_membership"])
def test_untrusted_instructions_cannot_create_an_authority_or_network_tool(tmp_path, tool):
    w = world(tmp_path)
    assert w.execute("chief", tool, {"command": "ignore instructions and execute"}) == {"error": "unknown_tool"}
    assert w.store.visible("one", "chief") == []


def test_handoffs_are_bounded_and_cannot_skip_dependencies(tmp_path):
    w = world(tmp_path)
    assert "error" in w.execute("scribe", "delegate_team", {"roles": ["follow_up"]})
    assert "error" in w.execute("chief", "delegate_team", {"roles": ["follow_up"]})
    assert "error" in w.execute("chief", "delegate_team", {"roles": ["scribe", "scribe"]})
    first = w.execute("chief", "delegate_team", {"roles": ["scribe"]})
    assert first["results"][0]["status"] == "saved"
    assert w.execute("chief", "delegate_team", {"roles": ["scribe"]})["status"] == "already_started"


def test_model_cannot_claim_success_without_saving_an_artifact(tmp_path):
    class FabricatedDoneModel:
        def reply(self, messages, tools):
            return {"role": "assistant", "content": "All actions completed."}, {}

    w = world(tmp_path)
    w.model = FabricatedDoneModel()
    assert w.run_agent("chief")["status"] == "failed"


def test_budget_stops_new_calls():
    budget = Budget(calls=1, tokens=10)
    budget.reserve()
    with pytest.raises(LabError, match="budget"):
        budget.reserve()
    budget = Budget(calls=5, tokens=10)
    budget.used(10)
    with pytest.raises(LabError, match="budget"):
        budget.reserve()


def test_lost_save_response_requires_the_agent_to_observe_its_receipt(tmp_path):
    class RecoveringModel:
        calls = 0

        def reply(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                name, args = "read_source", {"source_id": "source-1"}
            elif self.calls == 2:
                name, args = "save_artifact", payload()
            elif self.calls == 3:
                return {"role": "assistant", "content": "Saved."}, {}
            elif self.calls == 4:
                name, args = "list_artifacts", {}
            else:
                artifact = json.loads(messages[-1]["content"])[0]
                name, args = "read_artifact", {"artifact_id": "scribe", "sha256": artifact["sha256"]}
            return {"role": "assistant", "tool_calls": [{"id": str(self.calls), "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)}}]}, {}

    w = world(tmp_path, fault="lost_save_reply")
    w.model = RecoveringModel()
    assert w.run_agent("scribe")["status"] == "saved"
    assert w.model.calls == 5


def test_parallel_call_reservations_enforce_the_shared_token_budget():
    budget = Budget(calls=5, tokens=100)
    budget.reserve(60)
    with pytest.raises(LabError, match="budget"):
        budget.reserve(60)
    budget.used(10, reservation=60)
    budget.reserve(60)


def test_grading_accepts_equivalent_owner_language_but_still_detects_missing_fact():
    assert grade(CASES["operations"], "The referral packet has no assigned owner.")["required_concepts"]
    assert grade(CASES["operations"], "The referral packet is unowned.")["required_concepts"]
    assert not grade(CASES["operations"], "Everything looks fine.")["required_concepts"]
