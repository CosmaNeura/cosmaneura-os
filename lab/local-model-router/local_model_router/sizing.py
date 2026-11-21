"""Per-task-type size state with step-up / step-down rules (persisted)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

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
    cell_run_count: int = 0,
) -> str:
    """Step up only after enough consecutive passes AND can_promote_cell."""
    if consecutive_passes < config.step_up_after_consecutive_passes:
        return current
    if not can_promote_cell(cell_run_count, config):
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


def cell_key(task_type: str, size: str) -> str:
    return f"{task_type}:{size}"


@dataclass
class TaskSizeState:
    """Keeps the current size per task type and recent Fable outcomes."""

    current_sizes: dict[str, str] = field(default_factory=dict)
    consecutive_passes: dict[str, int] = field(default_factory=dict)
    fable_rejection_history: dict[str, list[bool]] = field(default_factory=dict)
    # Keyed by (task_type, size) via cell_key.
    cell_run_counts: dict[str, int] = field(default_factory=dict)

    def current_size(self, task_type: str, starting_size: str) -> str:
        return self.current_sizes.get(task_type, starting_size)

    def record_outcome(
        self,
        task_type: str,
        *,
        gates_and_fable_pass: bool,
        fable_rejected: bool,
        config: RouterConfig,
        max_size: str,
        min_size: str = "T1",
        starting_size: str | None = None,
    ) -> str:
        base = starting_size or self.current_sizes.get(task_type, "T3")
        current = self.current_sizes.get(task_type, base)
        key = cell_key(task_type, current)
        self.cell_run_counts[key] = self.cell_run_counts.get(key, 0) + 1

        history = self.fable_rejection_history.setdefault(task_type, [])
        history.append(bool(fable_rejected))
        window = config.step_down_window
        if len(history) > window:
            del history[:-window]
        rejections_in_window = sum(1 for item in history if item)

        if fable_rejected or not gates_and_fable_pass:
            self.consecutive_passes[task_type] = 0
            new_size = step_down_size(
                current,
                fable_rejections_in_window=rejections_in_window,
                config=config,
                min_size=min_size,
            )
        else:
            self.consecutive_passes[task_type] = self.consecutive_passes.get(task_type, 0) + 1
            new_size = step_up_size(
                current,
                consecutive_passes=self.consecutive_passes[task_type],
                config=config,
                max_size=max_size,
                cell_run_count=self.cell_run_counts[key],
            )
        self.current_sizes[task_type] = new_size
        # Clear rejection history after a size step.
        if new_size != current:
            self.fable_rejection_history[task_type] = []
            self.consecutive_passes[task_type] = 0
        return new_size

    def to_dict(self) -> dict:
        return {
            "current_sizes": dict(self.current_sizes),
            "consecutive_passes": dict(self.consecutive_passes),
            "fable_rejection_history": {
                key: list(values) for key, values in self.fable_rejection_history.items()
            },
            "cell_run_counts": dict(self.cell_run_counts),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> TaskSizeState:
        return cls(
            current_sizes={str(k): str(v) for k, v in raw.get("current_sizes", {}).items()},
            consecutive_passes={
                str(k): int(v) for k, v in raw.get("consecutive_passes", {}).items()
            },
            fable_rejection_history={
                str(k): [bool(x) for x in v]
                for k, v in raw.get("fable_rejection_history", {}).items()
            },
            cell_run_counts={str(k): int(v) for k, v in raw.get("cell_run_counts", {}).items()},
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> TaskSizeState:
        if not path.exists():
            return cls()
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _neighbor(
    current: str,
    *,
    direction: int,
    max_size: str,
    min_size: str = "T1",
) -> str:
    lo = SIZE_ORDER.index(min_size)
    hi = SIZE_ORDER.index(max_size)
    band = SIZE_ORDER[lo : hi + 1]
    if current not in band:
        return band[-1] if direction > 0 else band[0]
    index = band.index(current) + direction
    index = max(0, min(len(band) - 1, index))
    return band[index]
