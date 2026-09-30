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
        raise ValueError("Use the same source to compare concurrency")
    if not a or not all(e["passed"] for e in [*a, *b]):
        raise ValueError("Only passing runs qualify for a performance recommendation")
    before, after = (statistics.median(e["duration_ms"] for e in items) for items in (a, b))
    return {"baseline_workers": baseline["concurrency"], "candidate_workers": candidate["concurrency"],
            "samples_each": len(a), "baseline_median_ms": before, "candidate_median_ms": after,
            "observed_reduction_percent": round((before - after) / before * 100, 1),
            "baseline_tokens": baseline["usage"]["tokens"], "candidate_tokens": candidate["usage"]["tokens"],
            "recommendation": "candidate" if after < before else "baseline",
            "limit": "Small synthetic sample; no production latency or statistical significance claim."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(json.loads((args.baseline / "report.json").read_text()),
                             json.loads((args.candidate / "report.json").read_text())), indent=2))
