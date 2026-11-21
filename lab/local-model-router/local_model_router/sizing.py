"""Step-up / step-down helpers driven by config (promotion after N runs/cell)."""

from __future__ import annotations

from .config import RouterConfig


SIZE_ORDER = ("T1", "T2", "T3", "T4", "T5")


def can_promote_cell(run_count: int, config: RouterConfig) -> bool:
    return run_count >= config.runs_per_cell_required


def step_up_size(
    current: str,
    *,
    consecutive_passes: int,
    config: RouterConfig,
    max_size: str,
) -> str:
    if consecutive_passes < config.step_up_after_consecutive_passes:
        return current
    return _neighbor(current, direction=1, max_size=max_size)


def step_down_size(
    current: str,
    *,
    fable_rejections_in_window: int,
    config: RouterConfig,
    min_size: str = "T1",
) -> str:
    if fable_rejections_in_window < config.step_down_after_fable_rejections_in_window:
        return current
    return _neighbor(current, direction=-1, max_size="T5", min_size=min_size)


def _neighbor(
    current: str,
    *,
    direction: int,
    max_size: str,
    min_size: str = "T1",
) -> str:
    order = [size for size in SIZE_ORDER if size in {min_size, *SIZE_ORDER, max_size}]
    # Clamp to configured band.
    lo = SIZE_ORDER.index(min_size)
    hi = SIZE_ORDER.index(max_size)
    band = SIZE_ORDER[lo : hi + 1]
    if current not in band:
        return band[-1] if direction > 0 else band[0]
    index = band.index(current) + direction
    index = max(0, min(len(band) - 1, index))
    return band[index]
