"""Plan steps for a routed job. Fable review is mandatory for coding tasks."""

from __future__ import annotations

from .config import RouterConfig
from .router_types import is_coding_task

FABLE_STEP = "fable_review_required: true"
UNLOAD_12B_STEP = "unload_and_verify_12b"


def build_plan_steps(
    config: RouterConfig,
    *,
    lane: str,
    task_type: str,
    aborted: bool = False,
    escalated: bool = False,
    heavy: bool = False,
) -> tuple[str, ...]:
    """Build the harness plan. Never runs a model; CI-safe command planning only.

    Coding is derived from task_type (not lane name). Log summaries get no Aider.
    """
    coding = is_coding_task(task_type)

    if aborted:
        steps = ["abort_batch", "record_abort"]
        return _seal_fable(steps, coding=coding)

    steps: list[str] = [
        f"assign_lane:{lane}",
        "require_approval_token",
    ]
    if heavy and config.unload_12b_before_heavy:
        steps.append(UNLOAD_12B_STEP)

    if escalated:
        steps.append(f"escalate_to:{lane}")
    elif coding:
        steps.extend(
            [
                "aider_attempt_1",
                "run_pytest",
                "run_ruff",
                "aider_follow_up_1_if_needed",
                "escalate_if_still_failing",
            ]
        )
    else:
        # Log-summary lane: summarize only, never Aider.
        steps.extend(["summarize_log", "verify_truncation", "verify_summary_ids"])

    return _seal_fable(steps, coding=coding)


def _seal_fable(steps: list[str], *, coding: bool) -> tuple[str, ...]:
    """Ensure every non-log-summary plan ends with a non-disableable Fable step."""
    if not coding:
        cleaned = [step for step in steps if step != FABLE_STEP]
        return tuple(cleaned)
    cleaned = [step for step in steps if step != FABLE_STEP]
    cleaned.append(FABLE_STEP)
    return tuple(cleaned)


def unrouted_plan_steps(*, task_type: str) -> tuple[str, ...]:
    """Minimal refuse plan for unknown task types (still seals Fable when coding)."""
    return _seal_fable(
        ["assign_lane:unrouted", "refuse_batch"],
        coding=is_coding_task(task_type),
    )


def fable_can_be_disabled(_config: RouterConfig | None = None) -> bool:
    """Fable is never config-disableable for coding tasks."""
    return False
