"""Plan steps for a routed job. Fable review is mandatory for coding lanes."""

from __future__ import annotations

from .config import RouterConfig

FABLE_STEP = "fable_review_required: true"


def build_plan_steps(
    config: RouterConfig,
    *,
    lane: str,
    coding_lane: bool,
    aborted: bool = False,
    escalated: bool = False,
) -> tuple[str, ...]:
    """Build the harness plan. Never runs a model; CI-safe command planning only."""
    if aborted:
        steps = ["abort_batch", FABLE_STEP if coding_lane else "record_abort"]
        return _seal_fable(steps, coding_lane=coding_lane)

    steps: list[str] = [
        f"assign_lane:{lane}",
        "require_approval_token",
    ]
    if escalated:
        steps.append(f"escalate_to:{lane}")
    else:
        steps.extend(
            [
                "aider_attempt_1",
                "run_pytest",
                "run_ruff",
                "aider_follow_up_1_if_needed",
                "escalate_if_still_failing",
            ]
        )
    if coding_lane:
        steps.append(FABLE_STEP)
    return _seal_fable(steps, coding_lane=coding_lane)


def _seal_fable(steps: list[str], *, coding_lane: bool) -> tuple[str, ...]:
    """Ensure coding plans always end with a non-disableable Fable step."""
    if not coding_lane:
        return tuple(steps)
    cleaned = [step for step in steps if step != FABLE_STEP]
    cleaned.append(FABLE_STEP)
    return tuple(cleaned)


def fable_can_be_disabled(config: RouterConfig) -> bool:
    """Fable is never config-disableable for coding lanes."""
    # Even if a caller mutates raw config, the plan builder ignores the flag.
    return False


def assert_fable_locked(config: RouterConfig) -> None:
    if config.fable_configurable:
        raise RuntimeError("fable.configurable must be false; Fable cannot be turned off.")
    if not config.fable_review_required:
        raise RuntimeError("fable.review_required must be true.")
