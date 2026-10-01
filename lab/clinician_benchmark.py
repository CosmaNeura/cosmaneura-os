"""Capture six observed UI inputs, then repeat them through owned services.

The repeat measures system latency, never another clinician usability run.
"""

import argparse
import hashlib
import json
import re
import statistics
from pathlib import Path

import httpx

from lab.clinician_session import PERSONAS, TRANSCRIPT


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def capture(root):
    packet = (root / "scribe-packet.txt").read_text()
    if not packet.startswith(TRANSCRIPT):
        raise ValueError("expected the invented clinician packet")
    rows = []
    with httpx.Client(base_url="http://127.0.0.1:5195", trust_env=False,
                      follow_redirects=False, timeout=15) as client:
        for persona in PERSONAS:
            for round_number in (1, 2):
                episode = f"{persona}-{round_number}"
                result = json.loads((root / (episode + ".json")).read_text())
                if not result["passed"] or not all(result["checks"].values()):
                    raise ValueError("six completed baseline service runs required")
                response = client.get(f"/lab-api/{persona}/{round_number}/workspace")
                response.raise_for_status()
                entries = response.json()["entries"]
                note = [entry["content"] for entry in entries if entry["kind"] == "scratchpad"][-1]
                request = [entry["content"] for entry in entries if entry["kind"] == "conversation"][0]
                if note != packet.strip() or sha(request) != result["request_sha256"]:
                    raise ValueError("saved UI input differs from baseline evidence")
                rows.append({"persona": persona, "round": round_number, "request": request,
                             "request_sha256": sha(request), "baseline_duration_ms": result["duration_ms"]})
    value = {"schema": "cosmabot-clinician-benchmark.v1", "synthetic_only": True,
             "packet": packet, "packet_sha256": sha(packet), "rows": rows}
    (root / "benchmark-input.json").write_text(json.dumps(value, indent=2) + "\n")
    return value


def read_inputs(path):
    value = json.loads(path.read_text())
    if (set(value) != {"schema", "synthetic_only", "packet", "packet_sha256", "rows"}
            or value["schema"] != "cosmabot-clinician-benchmark.v1" or value["synthetic_only"] is not True
            or not isinstance(value["packet"], str) or not value["packet"].startswith(TRANSCRIPT)
            or not len(TRANSCRIPT) < len(value["packet"]) < 12000 or sha(value["packet"]) != value["packet_sha256"]
            or not isinstance(value["rows"], list) or len(value["rows"]) != 6):
        raise ValueError("invalid fixed synthetic benchmark input")
    seen = set()
    for row in value["rows"]:
        if (set(row) != {"persona", "round", "request", "request_sha256", "baseline_duration_ms"}
                or row["persona"] not in PERSONAS or type(row["round"]) is not int or row["round"] not in (1, 2)
                or not isinstance(row["request"], str) or not 15 <= len(row["request"]) <= 4000
                or sha(row["request"]) != row["request_sha256"]
                or type(row["baseline_duration_ms"]) is not int or row["baseline_duration_ms"] <= 0):
            raise ValueError("invalid benchmark case")
        seen.add((row["persona"], row["round"]))
    if seen != {(persona, round_number) for persona in PERSONAS for round_number in (1, 2)}:
        raise ValueError("six distinct clinician inputs required")
    return value


def quality_checks(result, request):
    """Narrow regressions from this invented encounter; not clinical grading."""
    roles = {row["recipient_role"] for row in result.get("handoff_receipts", [])}
    follow = next((row for row in result.get("artifacts", []) if row["role"] == "follow_up"), {})
    text = follow.get("body", "")
    tasks = follow.get("structured_draft", {}).get("human_tasks", [])
    draft_texts = [row.get("draft_text", "") for row in result.get("handoff_receipts", [])]
    draft_texts.extend(row.get("structured_draft", {}).get("body", row.get("body", ""))
                      for row in result.get("artifacts", []) if row.get("role") != "chief_plan")
    return {
        "requested_visit_prep_honored": not re.search(r"\bvisit prep\b", request, re.I) or "visit_prep" in roles,
        "research_and_follow_up_saved": {"research", "follow_up"} <= roles,
        "birth_date_retained_in_follow_up": bool(re.search(r"\bDOB\b|date of birth|birth date", text, re.I)),
        "medication_gap_retained": bool(re.search(r"medication|medicines|\bmeds\b", text, re.I)),
        "contact_permission_retained": bool(re.search(r"consent|permission", text, re.I)),
        "contact_time_conflict_retained": bool(re.search(r"morning", text, re.I))
            and bool(re.search(r"15:00|afternoon|after.?3|after three", text, re.I)),
        "no_unsupported_negative_completion_claim": not any(re.search(
            r"\bno\s+[^.!?\n]{0,100}\b(?:actions?|requests?|tasks?)\s+"
            r"(?:(?:have|has)\s+been|were|was)\s+completed\b", draft_text, re.I) for draft_text in draft_texts),
        "human_role_and_review_for_each_suggested_task": bool(tasks) and all(
            task.get("proposed_human_role") in {"RN", "provider", "PA", "practice staff"}
            and task.get("review_needed") is True for task in tasks),
    }


def repeat(lab, inputs):
    from sqlalchemy.orm import Session

    from cosmas_os.api.team_schemas import ConversationRequest
    from cosmas_os.application import workspace

    (lab.root / "benchmark-input.json").write_text(json.dumps(inputs, indent=2) + "\n")
    (lab.root / "scribe-packet.txt").write_text(inputs["packet"])
    rows = []
    for row in inputs["rows"]:
        episode, state = lab.session(row["persona"], row["round"])
        app = state["app"]
        with Session(lab.engine) as session:
            view = workspace.read(session, app.box, app.owner, app.workspace)
            saved = workspace.append(session, app.box, app.owner, app.workspace,
                expected=view["revision"], key="benchmark-packet", kind="scratchpad", content=inputs["packet"].strip())
        lab.ask(episode, state, ConversationRequest(expected_revision=saved["workspace"]["revision"],
            team_revision=app.team_revision, idempotency_key="benchmark-request", role="chief", content=row["request"]))
        result = state["result"]
        quality = quality_checks(result, row["request"])
        rows.append({"persona": row["persona"], "round": row["round"],
                     "passed": result["passed"] and all(quality.values()), "targeted_regression_checks": quality,
                     "before_ms": row["baseline_duration_ms"], "after_ms": result["duration_ms"],
                     "same_request": result["request_sha256"] == row["request_sha256"]})
        if not rows[-1]["passed"] or not rows[-1]["same_request"]:
            break
    passed = len(rows) == 6 and all(row["passed"] and row["same_request"] for row in rows)
    before = statistics.median(row["before_ms"] for row in rows)
    after = statistics.median(row["after_ms"] for row in rows)
    comparison = {"schema": "cosmabot-clinician-comparison.v1", "passed": passed,
        "expected_cases": 6, "completed_cases": len(rows),
        "same_packet_sha256": inputs["packet_sha256"], "rows": rows,
        "median_before_ms": before, "median_after_ms": after,
        "observed_reduction_percent": round(100 * (before - after) / before, 1) if passed else None,
        "limits": ["Six service repeats, not six additional clinician UI runs or human dwell measurements.",
                   "Same saved packet and requests; fresh owned workspaces and source identifiers.",
                   "Observed change covers the optimization bundle, including routing and verification channel changes.",
                   "Targeted text/structure regressions are not clinical-quality certification; saved drafts still need human review.",
                   "A small synthetic sample does not establish production latency or clinical quality."]}
    (lab.root / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
    return comparison


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline_root", type=Path)
    args = parser.parse_args()
    value = capture(args.baseline_root)
    print(json.dumps({"captured_cases": len(value["rows"]), "packet_sha256": value["packet_sha256"]}))


if __name__ == "__main__":
    main()
