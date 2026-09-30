"""Repeatable connector fault matrix reported alongside the agent episodes."""

import time
import traceback

from lab.application import Application
from lab.fax_sandbox import FAX_SCENARIOS, exercise_fax
from lab.mail_sandbox import MAIL_SCENARIOS, exercise_mail


def failure_location(error):
    frame = traceback.extract_tb(error.__traceback__)[-1]
    return {"file": frame.filename, "line": frame.lineno, "function": frame.name}


def run_connectors(app, store, episode):
    started = time.monotonic()
    outcomes = []
    for provider, kind in (("microsoft", "mail"), ("microsoft", "calendar"), ("google", "mail"), ("google", "calendar")):
        scenarios = list(MAIL_SCENARIOS)
        if provider == "microsoft" and kind == "mail":
            scenarios.append("invalid_timezone")
        for scenario in scenarios:
            tick = time.monotonic()
            try:
                isolated = Application(app.engine, app.case, app.event)
                result = exercise_mail(isolated, provider, scenario, kind)
            except Exception as error:
                result = {"provider": provider, "scenario": scenario, "passed": False,
                          "checks": {"scenario_completed": False}, "error": type(error).__name__, "location": failure_location(error)}
            result["scenario"] = ("calendar_" if kind == "calendar" else "") + scenario
            result["duration_ms"] = round((time.monotonic() - tick) * 1000)
            outcomes.append(result)
            store.event(episode, "synthetic_provider", "connector_scenario", provider=provider,
                        scenario=result["scenario"], ok=result["passed"], duration_ms=result["duration_ms"])
    for provider, scenarios in FAX_SCENARIOS.items():
        for scenario in scenarios:
            tick = time.monotonic()
            try:
                isolated = Application(app.engine, app.case, app.event)
                result = exercise_fax(isolated, store.root / episode / provider / scenario, scenario, provider=provider)
            except Exception as error:
                result = {"provider": provider, "scenario": scenario, "passed": False,
                          "checks": {"scenario_completed": False}, "error": type(error).__name__, "location": failure_location(error)}
            result["duration_ms"] = round((time.monotonic() - tick) * 1000)
            outcomes.append(result)
            store.event(episode, "synthetic_provider", "connector_scenario", provider=provider,
                        scenario=scenario, ok=result["passed"], duration_ms=result["duration_ms"])
    checks = {r["provider"] + "_" + r["scenario"]: r["passed"] for r in outcomes}
    return {"id": episode, "case": "connectors", "title": "Email, calendar and fax fault laboratory",
            "passed": all(checks.values()), "checks": checks, "artifacts": [], "tool_calls": 0,
            "duration_ms": round((time.monotonic() - started) * 1000), "connector_scenarios": outcomes,
            "application": {"status": "connector_fault_matrix", "external_effects": 0},
            "failures": [r for r in outcomes if not r["passed"]]}
