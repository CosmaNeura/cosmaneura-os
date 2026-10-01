"""Provider qualification in the existing lab, with traceable shared lessons.

Provider cases run in separate lab processes for parallel qualification. Within
one process scenarios remain sequential because application feature gates are
process-wide. Model agents implement/review these cases; execution is replay.
"""

import importlib
import json
import time
from pathlib import Path

from lab.application import Application
from lab.cases import Case
from lab.connector_checks import failure_location

MODULES = {"spruce": "spruce_fax_sandbox", "srfax": "srfax_qualification", "documo": "documo_qualification"}
NAMES = {"spruce": "Spruce", "srfax": "SRFax", "documo": "Documo"}
CASES = {"fax_" + provider: Case("fax_" + provider, name + " fax qualification",
    "Exercise reviewed PDF custody, approvals, provider faults and persisted evidence.",
    "SYNTHETIC fax provider clinic", ()) for provider, name in NAMES.items()}


def run_provider(app, store, episode, provider):
    started = time.monotonic()
    module = importlib.import_module("lab." + MODULES[provider])
    scenarios = module.SCENARIOS
    outcomes = []
    for scenario in scenarios:
        tick = time.monotonic()
        try:
            isolated = Application(app.engine, app.case, app.event)
            result = module.exercise(isolated, store.root / episode / provider / scenario, scenario)
        except Exception as error:
            result = {"provider": provider, "scenario": scenario, "passed": False,
                "checks": {"scenario_completed": False}, "error": type(error).__name__,
                "location": failure_location(error)}
        result["duration_ms"] = round((time.monotonic() - tick) * 1000)
        outcomes.append(result)
        store.event(episode, "synthetic_provider", "fax_qualification", provider=provider,
            scenario=scenario, ok=result["passed"], duration_ms=result["duration_ms"])
    lesson_path = Path(__file__).parent / "provider-lessons" / (provider + ".json")
    ledger = json.loads(lesson_path.read_text())
    by_scenario = {r["scenario"]: r for r in outcomes}
    lessons = [{**lesson, "tested_scenarios": [{"scenario": key, "passed": by_scenario.get(key, {}).get("passed", False)}
        for key in lesson["applied_scenarios"]]} for lesson in ledger["lessons"]]
    checks = {"scenario_" + r["scenario"]: r["passed"] for r in outcomes}
    checks["complete_scenario_matrix"] = len(outcomes) == len(set(scenarios)) > 0
    checks["shared_lesson_scenarios_pass"] = all(s["passed"] for lesson in lessons for s in lesson["tested_scenarios"])
    return {"id": episode, "case": "fax_" + provider, "title": CASES["fax_" + provider].title,
        "passed": all(checks.values()), "checks": checks, "artifacts": [], "tool_calls": 0,
        "duration_ms": round((time.monotonic() - started) * 1000), "connector_scenarios": outcomes,
        "shared_lessons": lessons, "application": {"status": "fax_provider_qualification", "external_effects": 0},
        "evidence_level": "Deterministic replay of real application services with scripted humans and synthetic HTTP; no live fax or model inference.",
        "failures": [r for r in outcomes if not r["passed"]]}
