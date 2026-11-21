"""CLI: dry-run and approval-gated batch planner (never runs models in CI)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .approval import ApprovalError, record_azure_spend, require_approval
from .config import PACKAGE_ROOT, load_config
from .dry_run import format_table, run_dry_run
from .harness import build_harness_plan
from .memory import MemoryReader, MemorySnapshot
from .metrics import MetricsEvent, MetricsLogger
from .models import Job
from .router import route_job
from .router_types import is_coding_task
from .sizing import TaskSizeState


def main(
    argv: list[str] | None = None,
    *,
    memory_reader: MemoryReader | None = None,
) -> int:
    """CLI entry. Tests inject memory_reader (and thus Ollama status) — no network."""
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
    )
    dry.add_argument(
        "--config",
        default=str(PACKAGE_ROOT / "config" / "router_config.json"),
    )

    batch = sub.add_parser(
        "plan-batch",
        help="Plan a local/Azure batch (requires --approved-run-id). Does not run models.",
    )
    batch.add_argument("--approved-run-id", required=False, default=None)
    batch.add_argument("--batch-kind", choices=("local", "azure", "cloud"), default=None)
    batch.add_argument("--job-json", required=True)
    batch.add_argument(
        "--config",
        default=str(PACKAGE_ROOT / "config" / "router_config.json"),
    )
    batch.add_argument("--state-dir", default=None)

    spend_cmd = sub.add_parser(
        "record-azure-spend",
        help="Record synthetic Azure spend (USD) into the local spend ledger.",
    )
    spend_cmd.add_argument("--amount-usd", type=float, required=True)
    spend_cmd.add_argument("--state-dir", default=None)
    spend_cmd.add_argument(
        "--config",
        default=str(PACKAGE_ROOT / "config" / "router_config.json"),
    )

    outcome = sub.add_parser(
        "record-outcome",
        help="Record gates/Fable outcome and persist TaskSizeState.",
    )
    outcome.add_argument("--task-type", required=True)
    outcome.add_argument("--gates-and-fable-pass", action="store_true")
    outcome.add_argument("--fable-rejected", action="store_true")
    outcome.add_argument("--max-size", default="T3")
    outcome.add_argument("--starting-size", default="T3")
    outcome.add_argument("--state-dir", default=None)
    outcome.add_argument(
        "--config",
        default=str(PACKAGE_ROOT / "config" / "router_config.json"),
    )

    args = parser.parse_args(argv)
    if args.command == "dry-run":
        return _cmd_dry_run(args)
    if args.command == "plan-batch":
        return _cmd_plan_batch(args, memory_reader=memory_reader)
    if args.command == "record-azure-spend":
        return _cmd_record_azure_spend(args)
    if args.command == "record-outcome":
        return _cmd_record_outcome(args)
    parser.error(f"Unknown command {args.command}")
    return 2


def _state_dir(args: argparse.Namespace) -> Path:
    return Path(args.state_dir) if getattr(args, "state_dir", None) else PACKAGE_ROOT / "state"


def _cmd_dry_run(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    decisions = run_dry_run(Path(args.jobs), config)
    print(format_table(decisions))
    return 0


def _cmd_plan_batch(
    args: argparse.Namespace,
    *,
    memory_reader: MemoryReader | None,
) -> int:
    config = load_config(Path(args.config))
    state_dir = _state_dir(args)
    ledger_path = state_dir / Path(config.approval_ledger_path).name
    spend_path = state_dir / Path(config.azure_spend_ledger_path).name
    metrics_path = state_dir / Path(config.metrics_jsonl_path).name
    size_path = state_dir / Path(config.size_state_path).name
    settings_dir = state_dir / "aider"

    size_state = TaskSizeState.load(size_path)
    job = Job.from_dict(json.loads(Path(args.job_json).read_text(encoding="utf-8")))

    reader = memory_reader
    if reader is None:
        # Default live path: real reader. Tests must inject.
        from .memory import default_memory_reader

        reader = default_memory_reader

    decision = route_job(
        job,
        config,
        dry_run=False,
        size_state=size_state,
        memory_reader=reader,
    )

    if decision.aborted:
        print(f"guards_abort: {decision.reason}", file=sys.stderr)
        return 3

    derived_kind = decision.batch_kind
    cli_kind = args.batch_kind if args.batch_kind is not None else derived_kind
    try:
        approval = require_approval(
            args.approved_run_id,
            batch_kind=cli_kind,
            decision=decision,
            config=config,
            ledger_path=ledger_path,
            spend_ledger_path=spend_path if cli_kind == "azure" else None,
            azure_month_spend_usd=job.azure_month_spend_usd,
            azure_run_estimate_usd=job.azure_run_estimate_usd,
        )
    except ApprovalError as exc:
        print(f"approval_gate: {exc}", file=sys.stderr)
        return 2

    # N1: harness only for coding task types.
    plan = None
    if (
        is_coding_task(job.task_type)
        and not decision.escalate
        and decision.lane in config.lanes
    ):
        lane = config.lanes[decision.lane]
        plan = build_harness_plan(
            config,
            model=lane.model,
            message=f"Synthetic job {job.job_id}",
            files=["synthetic_module.py"],
            lane=lane,
            model_settings_dir=settings_dir,
        )

    metrics = MetricsLogger(path=metrics_path)
    metrics.log(
        MetricsEvent(
            event="plan_batch",
            vendor=decision.vendor,
            activity=job.task_type,
            tokens=job.token_estimate,
            review_rounds=0,
            fable_rejection_after_gates=False,
            escalated=decision.escalate,
            merged_pr=None,
            job_id=job.job_id,
            extra={"approved_run_id": approval.approved_run_id},
        )
    )
    payload: dict[str, Any] = {
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
            "batch_kind": decision.batch_kind,
            "vendor": decision.vendor,
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
            "num_predict": plan.num_predict,
            "timeout_seconds": plan.timeout_seconds,
            "num_ctx": plan.num_ctx,
            "model_settings_text": plan.model_settings_text,
            "model_settings_path": plan.model_settings_path,
        },
        "paths": {
            "approval_ledger": str(ledger_path),
            "azure_spend_ledger": str(spend_path),
            "metrics_jsonl": str(metrics_path),
            "size_state": str(size_path),
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _cmd_record_azure_spend(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    state_dir = _state_dir(args)
    spend_path = state_dir / Path(config.azure_spend_ledger_path).name
    total = record_azure_spend(spend_path, float(args.amount_usd))
    print(json.dumps({"path": str(spend_path), "month_total_usd": total}, sort_keys=True))
    return 0


def _cmd_record_outcome(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    state_dir = _state_dir(args)
    size_path = state_dir / Path(config.size_state_path).name
    state = TaskSizeState.load(size_path)
    new_size = state.record_outcome(
        args.task_type,
        gates_and_fable_pass=bool(args.gates_and_fable_pass),
        fable_rejected=bool(args.fable_rejected),
        config=config,
        max_size=args.max_size,
        starting_size=args.starting_size,
    )
    state.save(size_path)
    print(
        json.dumps(
            {
                "task_type": args.task_type,
                "size": new_size,
                "path": str(size_path),
                "state": state.to_dict(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
