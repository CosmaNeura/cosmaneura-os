"""Receipt/report contracts only; these test doubles do not qualify real services."""

import json
from types import SimpleNamespace

import pytest
from lab import bot_capabilities as lab
from lab.store import Store, digest


def result(**extra):
    return {"scenario": "invented", "passed": True, "checks": {"exact_receipt": True}, **extra}


@pytest.mark.parametrize("team,underlying", [
    ("documentation", result(material="Invented revised note.", persistent_artifacts=[
        {"kind": "draft_note", "record_id": "note-1", "revision": 1, "sha256": "a" * 64, "content": "First draft", "review_id": None},
        {"kind": "draft_note", "record_id": "note-2", "revision": 2, "sha256": "b" * 64, "content": "Revised draft", "review_id": "review-2"}],
        review_steps=[{"review_id": "review-2", "content_hash": "c" * 64}])),
    ("research", result(artifacts=[{"role": "research", "id": "packet-1", "sha256": "d" * 64,
        "body": "Invented selected source.", "saved": {"entry_id": "entry-1", "entry_revision": 3,
            "run_id": "run-1", "request_sha256": "e" * 64}}])),
    ("operations", result(stages=[{"kind": "scheduling", "record_id": "booking-1",
        "next_step": {"label": "Check calendar synchronization"}, "evidence": {
            "commitment": "f" * 64, "external_outcome": "appointment_saved_calendar_unconfirmed", "version": 4}}])),
])
def test_display_wrapper_preserves_complete_underlying_receipts(tmp_path, team, underlying):
    store = Store(tmp_path)
    artifact, sha = lab.persist_result(store, "test-1", team, underlying)
    recovered = store.read("test-1", artifact["role"], "chief", artifact["sha256"])
    assert recovered["underlying_result"] == underlying
    assert sha == recovered["underlying_result_sha256"] == digest(underlying)
    assert recovered["display_label"] == "virtual capability evidence"
    assert recovered["body"] and recovered["dependencies"]
    if team == "documentation":
        assert len(recovered["dependencies"]) == 2
        assert recovered["dependencies"][1]["review_id"] == "review-2"
    elif team == "operations":
        assert "calendar unconfirmed" in recovered["body"]


def ledger(path, team="research", scenarios=("invented",)):
    (path / (team + ".json")).write_text(json.dumps({"version": 1, "lessons": [{
        "id": "exact-lineage", "finding": "Preserve exact saved evidence.",
        "evidence": ["synthetic-test"], "applies_to": [team], "applied_scenarios": list(scenarios)}]}))


def test_lessons_link_each_round_and_keep_unrun_or_failed_scenarios_visible(tmp_path, monkeypatch):
    ledger(tmp_path, scenarios=("invented", "unrun"))
    monkeypatch.setattr(lab, "LESSON_ROOT", tmp_path)
    empty = lab.aggregate_lessons([])[0]["tested_scenarios"]
    assert all(item["status"] == "not_run" and item["passed"] is False and item["runs"] == [] for item in empty)
    episodes = [{"id": "bot_research-1", "capability_team": "research", "capability_scenarios": [{
        "scenario": "invented", "passed": True, "result_sha256": "a" * 64, "evidence_artifact_sha256": "b" * 64}]}]
    passed = lab.aggregate_lessons(episodes)[0]["tested_scenarios"]
    assert passed[0]["status"] == "passed" and passed[0]["runs"][0]["episode"] == "bot_research-1"
    assert passed[1]["status"] == "not_run"
    episodes.append({"id": "bot_research-2", "capability_team": "research", "capability_scenarios": [{
        "scenario": "invented", "passed": False, "result_sha256": "c" * 64, "evidence_artifact_sha256": "d" * 64}]})
    failed = lab.aggregate_lessons(episodes)[0]["tested_scenarios"][0]
    assert failed["status"] == "failed" and failed["passed"] is False and len(failed["runs"]) == 2


def test_matrix_uses_fresh_application_and_never_reports_model_calls(tmp_path, monkeypatch):
    ledger(tmp_path, scenarios=("first", "second"))
    monkeypatch.setattr(lab, "LESSON_ROOT", tmp_path)
    instances = []

    def application(*args):
        value = object()
        instances.append(value)
        return value

    def exercise(app, store, episode, scenario):
        assert app is instances[-1]
        return {"scenario": scenario, "passed": True, "checks": {"isolated": True},
                "material": "Invented display material.", "application_number": len(instances)}

    monkeypatch.setattr(lab, "Application", application)
    monkeypatch.setattr(lab.importlib, "import_module", lambda _: SimpleNamespace(SCENARIOS=("first", "second"), exercise=exercise))
    parent = SimpleNamespace(engine=None, case=None, event=None)
    outcome = lab.run_capabilities(parent, Store(tmp_path / "store"), "test-1", "research")
    assert outcome["passed"] and len(instances) == 2 and instances[0] is not instances[1]
    assert outcome["tool_calls"] == 0 and "No model inference" in outcome["evidence_level"]
    assert len(outcome["artifacts"]) == 2
    assert [item["underlying_result"]["application_number"] for item in outcome["artifacts"]] == [1, 2]


def test_misreported_success_is_failed_but_original_result_is_retained(tmp_path, monkeypatch):
    ledger(tmp_path)
    monkeypatch.setattr(lab, "LESSON_ROOT", tmp_path)
    original = {"scenario": "invented", "passed": True, "checks": {"actual_check": False},
                "persistent_receipt": {"record_id": "receipt-1", "hash": "a" * 64}}
    monkeypatch.setattr(lab, "Application", lambda *_: None)
    monkeypatch.setattr(lab.importlib, "import_module", lambda _: SimpleNamespace(
        SCENARIOS=("invented",), exercise=lambda *_: original))
    outcome = lab.run_capabilities(SimpleNamespace(engine=None, case=None, event=None),
                                   Store(tmp_path / "store"), "test-1", "research")
    assert outcome["passed"] is False
    assert outcome["artifacts"][0]["underlying_result"]["unvalidated_result"] == original
