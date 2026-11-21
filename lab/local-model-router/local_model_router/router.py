"""Rule-based lane assignment for synthetic lab jobs."""

from __future__ import annotations

from .config import LaneConfig, RouterConfig, load_config
from .guards import any_abort, evaluate_guards
from .memory import MemoryReader
from .models import GuardResult, Job, RouteDecision
from .plan import build_plan_steps


LOG_TASK_TYPES = frozenset(
    {
        "ci_log_summary",
        "build_log_summary",
        "test_log_summary",
        "log_summary",
    }
)


def route_job(
    job: Job,
    config: RouterConfig | None = None,
    *,
    memory_reader: MemoryReader | None = None,
) -> RouteDecision:
    cfg = config or load_config()
    size = cfg.classify_size(job.file_count, job.token_estimate)

    # Long logs always force the 12B lane (amendment 1).
    if _is_long_log(job, cfg):
        lane = cfg.lanes[cfg.long_log_force_lane]
        return _finalize(
            job,
            cfg,
            lane=lane,
            reason=cfg.long_log_reason,
            size=size,
            memory_reader=memory_reader,
        )

    # Explicit multi-file / security / ambiguous work → Cursor cloud agent.
    if job.multi_file_feature or job.security_sensitive or job.ambiguous_spec:
        return _escalation_decision(
            job,
            cfg,
            reason=(
                "Multi-file feature, ambiguous spec, or security-sensitive code "
                "escalates to Cursor cloud agent."
            ),
            size=size,
            target=cfg.escalation_chain[-1],
            memory_reader=memory_reader,
            lane_is_heavy=False,
        )

    lane = cfg.lane_for_task(job.task_type)
    if lane is None:
        return _escalation_decision(
            job,
            cfg,
            reason=f"Unknown task_type {job.task_type!r}; escalate.",
            size=size,
            target=cfg.escalation_chain[0],
            memory_reader=memory_reader,
            lane_is_heavy=False,
        )

    # Size ceiling: Inkling / 26B stay at max_size (T3); larger → escalate.
    if lane.max_size and not cfg.size_fits(lane.max_size, job.file_count, job.token_estimate):
        return _escalation_decision(
            job,
            cfg,
            reason=(
                f"{lane.model} max size {lane.max_size} exceeded "
                f"(files={job.file_count}, tokens={job.token_estimate}); escalate."
            ),
            size=size,
            target=cfg.escalation_chain[0],
            memory_reader=memory_reader,
            lane_is_heavy=False,
        )

    # Single-file lane refuses multi-file jobs.
    if lane.name == "inkling_2_mini" and job.task_type == "single_file_fix" and job.file_count > 1:
        return _escalation_decision(
            job,
            cfg,
            reason="single_file_fix with file_count > 1 escalates to Azure codex-mini.",
            size=size,
            target=cfg.escalation_chain[0],
            memory_reader=memory_reader,
            lane_is_heavy=False,
        )

    reason = _lane_reason(job, lane, size)
    return _finalize(
        job,
        cfg,
        lane=lane,
        reason=reason,
        size=lane.starting_size or size,
        memory_reader=memory_reader,
    )


def next_escalation(current: str | None, config: RouterConfig) -> str | None:
    chain = config.escalation_chain
    if current is None:
        return chain[0]
    if current not in chain:
        return chain[0]
    index = chain.index(current)
    if index + 1 >= len(chain):
        return None
    return chain[index + 1]


def _is_long_log(job: Job, config: RouterConfig) -> bool:
    if job.task_type not in LOG_TASK_TYPES and job.log_kind not in {
        "ci",
        "build",
        "test",
        "long",
    }:
        return False
    if job.log_kind == "long":
        return True
    return job.token_estimate >= config.long_log_token_threshold


def _lane_reason(job: Job, lane: LaneConfig, size: str) -> str:
    if lane.name == "gemma4_12b":
        return f"Task {job.task_type} routes to {lane.model} (log summary / diff pre-review)."
    if lane.name == "inkling_2_mini":
        return (
            f"Task {job.task_type} routes to {lane.model} at starting size "
            f"{lane.starting_size or size} (unit tests / single-file / structured)."
        )
    if lane.name == "gemma4_26b":
        return (
            f"Task {job.task_type} routes to {lane.model} at starting size "
            f"{lane.starting_size or size} (lint/doc batches only)."
        )
    return f"Task {job.task_type} routes to {lane.model}."


def _finalize(
    job: Job,
    config: RouterConfig,
    *,
    lane: LaneConfig,
    reason: str,
    size: str | None,
    memory_reader: MemoryReader | None,
) -> RouteDecision:
    guards = evaluate_guards(
        job,
        config,
        lane_is_heavy=lane.heavy,
        memory_reader=memory_reader,
    )
    aborted = any_abort(guards)
    coding = lane.name in {"inkling_2_mini", "gemma4_26b"} or job.task_type == "diff_pre_review"
    plan = build_plan_steps(
        config,
        lane=lane.name,
        coding_lane=coding,
        aborted=aborted,
    )
    return RouteDecision(
        job_id=job.job_id,
        lane="aborted" if aborted else lane.name,
        reason=("ABORTED: " + reason) if aborted else reason,
        size=size,
        escalate=False,
        escalation_target=None,
        fable_review_required=True if coding else config.fable_review_required,
        plan_steps=plan,
        guards=guards,
        aborted=aborted,
    )


def _escalation_decision(
    job: Job,
    config: RouterConfig,
    *,
    reason: str,
    size: str | None,
    target: str,
    memory_reader: MemoryReader | None,
    lane_is_heavy: bool,
) -> RouteDecision:
    guards = evaluate_guards(
        job,
        config,
        lane_is_heavy=lane_is_heavy,
        memory_reader=memory_reader,
    )
    aborted = any_abort(guards)
    plan = build_plan_steps(
        config,
        lane=target,
        coding_lane=True,
        aborted=aborted,
        escalated=True,
    )
    return RouteDecision(
        job_id=job.job_id,
        lane="aborted" if aborted else target,
        reason=("ABORTED: " + reason) if aborted else reason,
        size=size,
        escalate=not aborted,
        escalation_target=None if aborted else target,
        fable_review_required=True,
        plan_steps=plan,
        guards=guards,
        aborted=aborted,
    )


def guard_summary(guards: tuple[GuardResult, ...]) -> str:
    parts = []
    for guard in guards:
        status = "OK" if guard.ok else ("ABORT" if guard.abort else "FAIL")
        parts.append(f"{guard.name}={status}")
    return "; ".join(parts)
