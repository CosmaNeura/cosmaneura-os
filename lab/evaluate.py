"""Rescore saved synthetic outputs without repeating paid model work."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from lab.cases import CASES, Case

VERSION = "synthetic-outcome-heuristics.v4"
ALIASES = {
    "date_of_birth": r"\bDOB\b|date[ _]of[ _]birth|birth date",
    "unassigned": r"\bunassigned\b|\bunowned\b|no assigned owner|missing.{0,20}owner",
    "missing": r"\bmissing\b|\babsent\b|not (?:provided|supplied|documented|available)",
    "conflict": r"\bconflict\w*\b|\bcontradict\w*\b|inconsistent|disagree",
    "unknown": r"\bunknown\b|not (?:provided|supplied|stated|specified)|\bunspecified\b",
}


def grade(case: Case, text: str) -> dict[str, bool]:
    return {"required_concepts": all(re.search(ALIASES.get(term, re.escape(term)), text, re.I) is not None for term in case.required),
            "no_known_false_claim": not any(term.lower() in text.lower() for term in case.forbidden)}


def rescore(path):
    from lab.runner import write_report

    report = json.loads((path / "report.json").read_text())
    if report["status"] == "running" or not report.get("finished_at"):
        raise ValueError("Wait for the run to finish before rescoring")
    before = json.loads(json.dumps(report))
    for episode in report["episodes"]:
        if episode["case"] in {"journey", "clinic", "connectors"}:
            continue  # Durable handoff receipts are not text-rescorable.
        follow = next((a for a in episode["artifacts"] if a["role"] == "follow_up"), None)
        previous = {key: episode["checks"][key] for key in ("required_concepts", "no_known_false_claim")}
        episode["checks"].update(grade(CASES[episode["case"]], follow["body"] if follow else ""))
        episode.setdefault("original_text_checks", previous)
        episode["passed"] = all(episode["checks"].values())
    # Completion and application evidence are immutable inputs to rescoring.
    # A scorer cannot repair missing agents, an incomplete run or failed contracts.
    complete = len(report["episodes"]) == report.get("expected_episode_count", -1)
    report["status"] = "passed" if complete and all(e["passed"] for e in report["episodes"]) and report.get("application_checks", {}).get("exit_code", 0) == 0 and all(s["passed"] for s in report.get("capture_checks", {}).get("suites", [])) else "failed"
    for row in report["coverage"]:
        row["agent_passes"] = sum(e["case"] == row["case"] and e["passed"] for e in report["episodes"])
    report["grading"] = {"version": VERSION, "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    history = path / f"report-before-{VERSION}.json"
    if not history.exists():
        history.write_text(json.dumps(before, indent=2) + "\n")
    write_report(path, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    result = rescore(parser.parse_args().run)
    print(json.dumps({"status": result["status"], "grading": result["grading"]}))
