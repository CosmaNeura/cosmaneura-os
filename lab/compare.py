"""Compare measured runs while refusing mismatched tasks, models or faults."""

import argparse
import json
import statistics
from pathlib import Path


def compare(baseline, candidate):
    for key in ("mode", "model", "fault"):
        if baseline[key] != candidate[key]:
            raise ValueError(f"Mismatched {key}; comparison would be confounded")
    a, b = baseline["episodes"], candidate["episodes"]
    if sorted(e["case"] for e in a) != sorted(e["case"] for e in b):
        raise ValueError("Use the same cases and repeat count")
    if baseline["source"]["source_sha256"] != candidate["source"]["source_sha256"]:
        raise ValueError("Use the same source to compare execution settings")
    if (baseline["status"] != "passed" or candidate["status"] != "passed"
            or len(a) != baseline.get("expected_episode_count", len(a))
            or len(b) != candidate.get("expected_episode_count", len(b))
            or not a or not all(e["passed"] for e in [*a, *b])):
        raise ValueError("Only passing runs qualify for a performance recommendation")
    before, after = (statistics.median(e["duration_ms"] for e in items) for items in (a, b))
    return {"baseline_workers": baseline["concurrency"], "candidate_workers": candidate["concurrency"],
            "baseline_input_mode": baseline.get("journey_input_mode", "tool"),
            "candidate_input_mode": candidate.get("journey_input_mode", "tool"),
            "samples_each": len(a), "baseline_median_ms": before, "candidate_median_ms": after,
            "observed_reduction_percent": round((before - after) / before * 100, 1),
            "baseline_tokens": baseline["usage"]["tokens"], "candidate_tokens": candidate["usage"]["tokens"],
            "baseline_model_calls": baseline["usage"]["model_calls"], "candidate_model_calls": candidate["usage"]["model_calls"],
            "baseline_max_queue_median_ms": statistics.median(max(e["timing"]["recipient_queue_ms"].values()) for e in a) if all(e.get("timing", {}).get("recipient_queue_ms") for e in a) else None,
            "candidate_max_queue_median_ms": statistics.median(max(e["timing"]["recipient_queue_ms"].values()) for e in b) if all(e.get("timing", {}).get("recipient_queue_ms") for e in b) else None,
            "recommendation": "candidate" if after < before else "baseline",
            "limit": "Small synthetic sample; no production latency or statistical significance claim."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(json.loads((args.baseline / "report.json").read_text()),
                             json.loads((args.candidate / "report.json").read_text())), indent=2))
