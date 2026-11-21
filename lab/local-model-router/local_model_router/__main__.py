"""CLI: dry-run and approval-gated batch planner (never runs models in CI)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .approval import ApprovalError, require_approval
from .config import PACKAGE_ROOT, load_config
from .dry_run import format_table, run_dry_run
from .harness import build_harness_plan
from .metrics import MetricsEvent, MetricsLogger
from .plan import assert_fable_locked
from .router import route_job
from .models import Job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="local_model_router",
        description="Lab-only local-model job router (developer tool under lab/).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    dry = sub.add_parser("dry-run", help="Route synthetic jobs; print lane table.")
    dry.add_argument(
        "jobs",
        nargs="?",
        default=str(PACKAGE_ROOT / "fixtures" / "synthetic_jobs.json"),
        help="Path to synthetic jobs JSON.",
    )
    dry.add_argument(
        "--config",
        default=str(PACKAGE_ROOT / "config" / "router_config.json"),
        help="Path to router config JSON.",
    )

    batch = sub.add_parser(
        "plan-batch",
        help="Plan a local/Azure batch (requires --approved-run-id). Does not run models.",
    )
    batch.add_argument("--approved-run-id", required=False, default=None)
    batch.add_argument("--batch-kind", choices=("local", "azure"), default="local")
    batch.add_argument(
        "--job-json",
        required=True,
        help="Single job JSON object (synthetic).",
    )
    batch.add_argument(
        "--config",
        default=str(PACKAGE_ROOT / "config" / "router_config.json"),
    )

    args = parser.parse_args(argv)
    if args.command == "dry-run":
        return _cmd_dry_run(args)
    if args.command == "plan-batch":
        return _cmd_plan_batch(args)
    parser.error(f"Unknown command {args.command}")
    return 2


def _cmd_dry_run(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    assert_fable_locked(config)
    decisions = run_dry_run(Path(args.jobs), config)
    print(format_table(decisions))
    return 0


def _cmd_plan_batch(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    assert_fable_locked(config)
    try:
        approval = require_approval(args.approved_run_id, batch_kind=args.batch_kind)
    except ApprovalError as exc:
        print(f"approval_gate: {exc}", file=sys.stderr)
        return 2
    job = Job.from_dict(json.loads(Path(args.job_json).read_text(encoding="utf-8")))
    decision = route_job(job, config)
    plan = None
    if not decision.aborted and not decision.escalate:
        lane = config.lanes.get(decision.lane)
        model = lane.model if lane else decision.lane
        plan = build_harness_plan(
            config,
            model=model,
            message=f"Synthetic job {job.job_id}",
            files=["synthetic_module.py"],
        )
    metrics = MetricsLogger()
    metrics.log(
        MetricsEvent(
            event="plan_batch",
            vendor="local" if args.batch_kind == "local" else "azure",
            activity=job.task_type,
            tokens=job.token_estimate,
            escalated=decision.escalate,
            job_id=job.job_id,
            extra={"approved_run_id": approval.approved_run_id},
        )
    )
    payload = {
        "approval": {
            "approved_run_id": approval.approved_run_id,
            "batch_kind": approval.batch_kind,
        },
        "decision": {
            "job_id": decision.job_id,
            "lane": decision.lane,
            "reason": decision.reason,
            "size": decision.size,
            "escalate": decision.escalate,
            "escalation_target": decision.escalation_target,
            "fable_review_required": decision.fable_review_required,
            "plan_steps": list(decision.plan_steps),
            "aborted": decision.aborted,
            "guards": [
                {
                    "name": g.name,
                    "ok": g.ok,
                    "detail": g.detail,
                    "abort": g.abort,
                }
                for g in decision.guards
            ],
        },
        "harness": None
        if plan is None
        else {
            "env": plan.env,
            "aider_attempt": plan.aider_attempt,
            "pytest_cmd": plan.pytest_cmd,
            "ruff_cmd": plan.ruff_cmd,
            "aider_follow_up": plan.aider_follow_up,
            "escalate_after_follow_up": plan.escalate_after_follow_up,
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
