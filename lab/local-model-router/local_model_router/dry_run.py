"""Dry-run table over synthetic jobs. No model calls."""

from __future__ import annotations

import json
from pathlib import Path

from .config import RouterConfig, load_config
from .memory import MemorySnapshot
from .models import Job, RouteDecision
from .router import guard_summary, route_job
from .sizing import TaskSizeState


def load_jobs(path: Path) -> list[Job]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("synthetic jobs fixture must be a JSON list")
    return [Job.from_dict(item) for item in raw]


def run_dry_run(
    jobs_path: Path,
    config: RouterConfig | None = None,
    *,
    size_state: TaskSizeState | None = None,
) -> list[RouteDecision]:
    cfg = config or load_config()
    jobs = load_jobs(jobs_path)
    state = size_state or TaskSizeState()

    def fake_memory() -> MemorySnapshot:
        # Default healthy reader; job fields override in dry_run=True.
        return MemorySnapshot(
            free_percent=50.0,
            swap_watchdog_tripped=False,
            gemma_12b_loaded=False,
            readable=True,
        )

    return [
        route_job(
            job,
            cfg,
            memory_reader=fake_memory,
            dry_run=True,
            size_state=state,
        )
        for job in jobs
    ]


def format_table(decisions: list[RouteDecision]) -> str:
    headers = ("job", "lane", "reason", "guards")
    rows = [
        (
            decision.job_id,
            decision.lane,
            decision.reason,
            guard_summary(decision.guards),
        )
        for decision in decisions
    ]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def fmt(row: tuple[str, ...]) -> str:
        return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    lines = [
        fmt(headers),
        "-+-".join("-" * width for width in widths),
        *[fmt(row) for row in rows],
    ]
    return "\n".join(lines)
