"""Rule-based lane assignment for synthetic lab jobs."""

from __future__ import annotations

from .config import LaneConfig, RouterConfig, load_config
from .guards import any_abort, evaluate_guards
from .memory import MemoryReader
from .models import GuardResult, Job, RouteDecision
from .plan import build_plan_steps
from .router_types import (
    LOG_TASK_TYPES,
    batch_kind_for_lane,
    is_coding_task,
    vendor_for_lane,
)
from .sizing import TaskSizeState

# Re-export for callers/tests.
__all__ = [
    "LOG_TASK_TYPES",
    "guard_summary",
    "next_escalation",
    "route_job",
]


def route_job(
    job: Job,
    config: RouterConfig | None = None,
    *,
    memory_reader: MemoryReader | None = None,
    dry_run: bool = False,
    size_state: TaskSizeState | None = None,
) -> RouteDecision:
    cfg = config or load_config()
    state = size_state or TaskSizeState()
    classified = cfg.classify_size(job.file_count, job.token_estimate)

    # Explicit multi-file / security / ambiguous → cloud (before long-log).
    # Every escalation requires Fable (N2), including log_summary + multi_file.
    if job.multi_file_feature or job.security_sensitive or job.ambiguous_spec:
        return _escalation_decision(
            job,
            cfg,
            reason=(
                "Multi-file feature, ambiguous spec, or security-sensitive code "
                "escalates to Cursor cloud agent."
            ),
            size=classified,
            target="cursor_cloud_agent",
            memory_reader=memory_reader,
            dry_run=dry_run,
            lane_is_heavy=False,
        )

    # (1) Long-log override ONLY for LOG_TASK_TYPES.
    if _is_long_log(job, cfg):
        lane = cfg.lanes[cfg.long_log_force_lane]
        return _finalize(
            job,
            cfg,
            lane=lane,
            reason=cfg.long_log_reason,
            size=classified,
            memory_reader=memory_reader,
            dry_run=dry_run,
        )

    lane = cfg.lane_for_task(job.task_type)
    if lane is None:
        # (3) Unknown task types → unrouted, no escalation.
        return _unrouted_decision(
            job,
            cfg,
            reason=f"Unknown task_type {job.task_type!r}; unrouted.",
            size=classified,
            memory_reader=memory_reader,
            dry_run=dry_run,
        )

    starting = lane.starting_size or "T3"
    current_size = state.current_size(job.task_type, starting)
    max_size = lane.max_size or current_size

    # (2) file_count > 1 that does not fit a local lane → cursor_cloud_agent.
    if job.file_count > 1 and not _fits_local_lane(job, lane, cfg, max_size):
        return _escalation_decision(
            job,
            cfg,
            reason=(
                f"file_count={job.file_count} does not fit local lane {lane.name}; "
                "escalate to cursor_cloud_agent."
            ),
            size=classified,
            target="cursor_cloud_agent",
            memory_reader=memory_reader,
            dry_run=dry_run,
            lane_is_heavy=False,
        )

    # Size ceiling vs the per-task current size / max_size.
    if not cfg.size_fits(max_size, job.file_count, job.token_estimate):
        # Single-file oversize → Azure; multi-file oversize already handled above.
        target = "azure_codex_mini" if job.file_count <= 1 else "cursor_cloud_agent"
        return _escalation_decision(
            job,
            cfg,
            reason=(
                f"{lane.model} max size {max_size} exceeded "
                f"(files={job.file_count}, tokens={job.token_estimate}); escalate."
            ),
            size=classified,
            target=target,
            memory_reader=memory_reader,
            dry_run=dry_run,
            lane_is_heavy=False,
        )

    # Route against the per-task current size (must also fit that cell).
    if not cfg.size_fits(current_size, job.file_count, job.token_estimate):
        target = "azure_codex_mini" if job.file_count <= 1 else "cursor_cloud_agent"
        return _escalation_decision(
            job,
            cfg,
            reason=(
                f"Job exceeds current size {current_size} for {job.task_type}; escalate."
            ),
            size=current_size,
            target=target,
            memory_reader=memory_reader,
            dry_run=dry_run,
            lane_is_heavy=False,
        )

    reason = _lane_reason(job, lane, current_size)
    return _finalize(
        job,
        cfg,
        lane=lane,
        reason=reason,
        size=current_size,
        memory_reader=memory_reader,
        dry_run=dry_run,
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


def _fits_local_lane(
    job: Job,
    lane: LaneConfig,
    config: RouterConfig,
    max_size: str,
) -> bool:
    """Whether a multi-file job can stay on this local lane."""
    if job.task_type == "single_file_fix":
        return False
    if lane.name == "inkling_2_mini" and job.file_count > 1:
        # Inkling coding cells are single-file oriented beyond structured/unit at T3.
        if job.task_type == "unit_tests" and config.size_fits(
            max_size, job.file_count, job.token_estimate
        ):
            return True
        if job.task_type == "strict_structured_output":
            return config.size_fits(max_size, job.file_count, job.token_estimate)
        return False
    return config.size_fits(max_size, job.file_count, job.token_estimate)


def _is_long_log(job: Job, config: RouterConfig) -> bool:
    if job.task_type not in LOG_TASK_TYPES:
        return False
    if job.log_kind == "long":
        return True
    return job.token_estimate >= config.long_log_token_threshold


def _lane_reason(job: Job, lane: LaneConfig, size: str) -> str:
    if lane.name == "gemma4_12b":
        return f"Task {job.task_type} routes to {lane.model} (log summary / diff pre-review)."
    if lane.name == "inkling_2_mini":
        return (
            f"Task {job.task_type} routes to {lane.model} at size "
            f"{size} (unit tests / single-file / structured)."
        )
    if lane.name == "gemma4_26b":
        return (
            f"Task {job.task_type} routes to {lane.model} at size "
            f"{size} (lint/doc batches only)."
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
    dry_run: bool,
) -> RouteDecision:
    guards = evaluate_guards(
        job,
        config,
        lane_is_heavy=lane.heavy,
        memory_reader=memory_reader,
        dry_run=dry_run,
    )
    aborted = any_abort(guards)
    coding = is_coding_task(job.task_type)
    plan = build_plan_steps(
        config,
        lane=lane.name,
        task_type=job.task_type,
        aborted=aborted,
        heavy=lane.heavy,
    )
    lane_name = "aborted" if aborted else lane.name
    return RouteDecision(
        job_id=job.job_id,
        lane=lane_name,
        reason=("ABORTED: " + reason) if aborted else reason,
        size=size,
        escalate=False,
        escalation_target=None,
        fable_review_required=coding,
        plan_steps=plan,
        guards=guards,
        aborted=aborted,
        batch_kind=batch_kind_for_lane(lane_name if not aborted else lane.name),
        vendor=vendor_for_lane(lane.name),
    )


def _escalation_decision(
    job: Job,
    config: RouterConfig,
    *,
    reason: str,
    size: str | None,
    target: str,
    memory_reader: MemoryReader | None,
    dry_run: bool,
    lane_is_heavy: bool,
) -> RouteDecision:
    guards = evaluate_guards(
        job,
        config,
        lane_is_heavy=lane_is_heavy,
        memory_reader=memory_reader,
        dry_run=dry_run,
    )
    aborted = any_abort(guards)
    plan = build_plan_steps(
        config,
        lane=target,
        task_type=job.task_type,
        aborted=aborted,
        escalated=True,
        heavy=False,
    )
    lane_name = "aborted" if aborted else target
    return RouteDecision(
        job_id=job.job_id,
        lane=lane_name,
        reason=("ABORTED: " + reason) if aborted else reason,
        size=size,
        escalate=not aborted,
        escalation_target=None if aborted else target,
        fable_review_required=True,  # N2: every escalation requires Fable
        plan_steps=plan,
        guards=guards,
        aborted=aborted,
        batch_kind=batch_kind_for_lane(target),
        vendor=vendor_for_lane(target),
    )


def _unrouted_decision(
    job: Job,
    config: RouterConfig,
    *,
    reason: str,
    size: str | None,
    memory_reader: MemoryReader | None,
    dry_run: bool,
) -> RouteDecision:
    from .plan import unrouted_plan_steps

    guards = evaluate_guards(
        job,
        config,
        lane_is_heavy=False,
        memory_reader=memory_reader,
        dry_run=dry_run,
    )
    coding = is_coding_task(job.task_type)
    plan = unrouted_plan_steps(task_type=job.task_type)
    return RouteDecision(
        job_id=job.job_id,
        lane="unrouted",
        reason=reason,
        size=size,
        escalate=False,
        escalation_target=None,
        fable_review_required=coding,
        plan_steps=plan,
        guards=guards,
        aborted=False,
        batch_kind="none",
        vendor="none",
    )


def guard_summary(guards: tuple[GuardResult, ...]) -> str:
    parts = []
    for guard in guards:
        status = "OK" if guard.ok else ("ABORT" if guard.abort else "FAIL")
        parts.append(f"{guard.name}={status}")
    return "; ".join(parts)
