"""Repeatable capability matrices using the existing application and owned lab.

Each scenario receives a fresh application. Complete underlying receipts are
retained; display summaries and shared lessons never replace those receipts.
"""

import importlib
import json
import time
from pathlib import Path

from lab.application import Application
from lab.cases import Case
from lab.connector_checks import failure_location
from lab.store import LabError, digest

MODULES = {"research": "research_capability", "documentation": "documentation_capability",
           "operations": "operations_capability"}
NAMES = {"research": "Research source handoffs", "documentation": "Scribe and Visit Prep source review",
         "operations": "Inbox, Follow-up, Scheduling and Billing work"}
CASES = {"bot_" + team: Case("bot_" + team, title,
    "Exercise real source custody, exact review and service-specific recovery with invented inputs.",
    "SYNTHETIC ONLY. No real patient, account, public source or external action.", ()) for team, title in NAMES.items()}
LESSON_ROOT = Path(__file__).parent / "bot-lessons"
EVIDENCE = ("Deterministic virtual execution of actual application services and saved receipts; "
            "scripted synthetic humans and offline source/provider responses. No model inference or live actions.")


def dependencies(result, team):
    """Link exact exposed record/receipt commitments without changing their type."""
    values = []
    for item in result.get("artifacts", []):
        if item.get("sha256"):
            values.append({"role": item.get("role", team), "artifact_id": item.get("id"), "sha256": item["sha256"]})
    for item in result.get("persistent_artifacts", []):
        if item.get("sha256"):
            values.append({"role": team, "record_id": item["record_id"], "kind": item["kind"],
                "revision": item.get("revision"), "sha256": item["sha256"], "review_id": item.get("review_id")})
    for stage in result.get("stages", []):
        if stage.get("evidence", {}).get("commitment"):
            values.append({"role": result.get("role", team), "record_id": stage["record_id"],
                "kind": stage["kind"], "sha256": stage["evidence"]["commitment"]})
    return values


def display_body(result):
    if result.get("material"):
        return result["material"]
    if result.get("artifacts"):
        return "\n\n".join(item["body"] for item in result["artifacts"] if item.get("body"))
    if result.get("stages"):
        return "\n".join(str(index) + ". " + stage["next_step"]["label"]
            + " — " + stage["evidence"]["external_outcome"].replace("_", " ")
            for index, stage in enumerate(result["stages"], 1))
    return "The scenario did not complete; inspect its retained checks and failure location."


def persist_result(store, episode, team, result):
    """One evaluation wrapper preserves every field of the exact service result."""
    result_sha = digest(result)
    artifact = store.save(episode, team + "-" + result["scenario"] + "-evidence", {
        "body": display_body(result), "display_label": "virtual capability evidence",
        "dependencies": dependencies(result, team), "share_with": ["chief", "provider", "nurse", "pa"],
        "underlying_result": result, "underlying_result_sha256": result_sha,
        "evidence_level": result.get("evidence_level", EVIDENCE),
    })
    return artifact, result_sha


def aggregate_lessons(episodes):
    """Link every declared scenario to actual runs, keeping unrun work visible."""
    outcomes = {}
    for episode in episodes:
        team = episode.get("capability_team")
        for row in episode.get("capability_scenarios", []):
            outcomes.setdefault((team, row["scenario"]), []).append({
                "episode": episode["id"], "scenario": row["scenario"], "passed": row["passed"],
                "result_sha256": row["result_sha256"], "evidence_artifact_sha256": row["evidence_artifact_sha256"],
            })
    lessons = []
    for path in sorted(LESSON_ROOT.glob("*.json")):
        ledger = json.loads(path.read_text())
        if ledger.get("version") != 1 or not isinstance(ledger.get("lessons"), list):
            raise LabError("invalid_bot_lesson_ledger")
        for lesson in ledger["lessons"]:
            applied = lesson["applied_scenarios"]
            tested = []
            for scenario in applied:
                runs = outcomes.get((path.stem, scenario), [])
                tested.append({"scenario": scenario, "status": "not_run" if not runs else
                    "passed" if all(row["passed"] for row in runs) else "failed",
                    "passed": bool(runs) and all(row["passed"] for row in runs), "runs": runs})
            lessons.append({**lesson, "team": path.stem, "ledger": "lab/bot-lessons/" + path.name,
                "ledger_sha256": digest(ledger), "tested_scenarios": tested})
    return lessons


def run_capabilities(app, store, episode, team):
    started = time.monotonic()
    if team not in MODULES:
        raise LabError("unknown_bot_capability_team")
    module = importlib.import_module("lab." + MODULES[team])
    scenarios = module.SCENARIOS
    if (type(scenarios) is not tuple or not 1 <= len(scenarios) <= 24
            or any(type(scenario) is not str for scenario in scenarios) or len(set(scenarios)) != len(scenarios)):
        raise LabError("invalid_bot_capability_matrix")
    outcomes, artifacts = [], []
    for scenario in scenarios:
        tick = time.monotonic()
        candidate = None
        try:
            isolated = Application(app.engine, app.case, app.event)
            candidate = module.exercise(isolated, store, episode, scenario)
            result = candidate
            if (result.get("scenario") != scenario or type(result.get("checks")) is not dict or not result["checks"]
                    or any(type(value) is not bool for value in result["checks"].values())
                    or type(result.get("passed")) is not bool or result["passed"] != all(result["checks"].values())):
                raise LabError("invalid_bot_capability_result")
        except Exception as error:
            result = {"scenario": scenario, "passed": False, "checks": {"scenario_completed": False},
                "error": type(error).__name__, "location": failure_location(error), "evidence_level": EVIDENCE,
                **({"unvalidated_result": candidate} if candidate is not None else {})}
        result = {**result, "duration_ms": round((time.monotonic() - tick) * 1000)}
        artifact, result_sha = persist_result(store, episode, team, result)
        artifacts.append(artifact)
        outcomes.append({**result, "result_sha256": result_sha, "evidence_artifact_sha256": artifact["sha256"]})
        store.event(episode, team, "bot_capability_scenario", scenario=scenario, passed=result["passed"],
            result_sha256=result_sha, evidence_artifact_sha256=artifact["sha256"], duration_ms=result["duration_ms"])
    checks = {"scenario_" + row["scenario"]: row["passed"] for row in outcomes}
    checks["complete_scenario_matrix"] = len(outcomes) == len(set(scenarios)) > 0
    result = {"id": episode, "case": "bot_" + team, "capability_team": team, "title": NAMES[team],
        "passed": all(checks.values()), "checks": checks, "artifacts": artifacts, "tool_calls": 0,
        "duration_ms": round((time.monotonic() - started) * 1000), "capability_scenarios": outcomes,
        "phases": [{"name": row["scenario"].replace("_", " "), "passed": row["passed"]} for row in outcomes],
        "application": {"status": "bot_capability_qualification", "external_effects": 0},
        "evidence_level": EVIDENCE, "failures": [row for row in outcomes if not row["passed"]]}
    result["shared_lessons"] = [lesson for lesson in aggregate_lessons([result]) if lesson["team"] == team]
    result["checks"]["shared_lesson_scenarios_pass"] = all(
        checked["passed"] for lesson in result["shared_lessons"] for checked in lesson["tested_scenarios"])
    result["passed"] = all(result["checks"].values())
    return result
