"""Shared task-type sets for routing and guards (avoid circular imports)."""

from __future__ import annotations

LOG_TASK_TYPES = frozenset(
    {
        "ci_log_summary",
        "build_log_summary",
        "test_log_summary",
        "log_summary",
    }
)

AZURE_LANES = frozenset({"azure_codex_mini", "gpt_5_3_codex"})
CLOUD_LANES = frozenset({"cursor_cloud_agent"})


def is_coding_task(task_type: str) -> bool:
    """Every non-log-summary task is a coding lane for Fable sealing."""
    return task_type not in LOG_TASK_TYPES


def batch_kind_for_lane(lane: str) -> str:
    if lane in AZURE_LANES:
        return "azure"
    if lane in CLOUD_LANES:
        return "cloud"
    if lane in {"unrouted", "aborted", "none"}:
        return "none"
    return "local"


def vendor_for_lane(lane: str) -> str:
    kind = batch_kind_for_lane(lane)
    if kind == "azure":
        return "azure"
    if kind == "cloud":
        return "cursor"
    if kind == "none":
        return "none"
    return "local"
