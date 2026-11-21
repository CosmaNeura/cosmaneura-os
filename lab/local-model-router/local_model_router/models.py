"""Typed job and decision records for the lab router."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Job:
    """Queued synthetic work item for CoS dry-runs and routing."""

    job_id: str
    task_type: str
    file_count: int
    token_estimate: int
    log_kind: str | None = None
    # Optional fields for guard evaluation / dry-run scenarios.
    tokens_sent: int | None = None
    tokens_processed: int | None = None
    summary_text: str | None = None
    source_text: str | None = None
    gemma_12b_loaded: bool = False
    free_memory_percent: float | None = None
    swap_watchdog_tripped: bool = False
    cell_run_count: int | None = None
    security_sensitive: bool = False
    multi_file_feature: bool = False
    ambiguous_spec: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Job:
        return cls(
            job_id=str(raw["job_id"]),
            task_type=str(raw["task_type"]),
            file_count=int(raw.get("file_count", 0)),
            token_estimate=int(raw.get("token_estimate", 0)),
            log_kind=raw.get("log_kind"),
            tokens_sent=_optional_int(raw.get("tokens_sent")),
            tokens_processed=_optional_int(raw.get("tokens_processed")),
            summary_text=raw.get("summary_text"),
            source_text=raw.get("source_text"),
            gemma_12b_loaded=bool(raw.get("gemma_12b_loaded", False)),
            free_memory_percent=_optional_float(raw.get("free_memory_percent")),
            swap_watchdog_tripped=bool(raw.get("swap_watchdog_tripped", False)),
            cell_run_count=_optional_int(raw.get("cell_run_count")),
            security_sensitive=bool(raw.get("security_sensitive", False)),
            multi_file_feature=bool(raw.get("multi_file_feature", False)),
            ambiguous_spec=bool(raw.get("ambiguous_spec", False)),
        )


@dataclass(frozen=True)
class GuardResult:
    name: str
    ok: bool
    detail: str
    abort: bool = False


@dataclass(frozen=True)
class RouteDecision:
    job_id: str
    lane: str
    reason: str
    size: str | None = None
    escalate: bool = False
    escalation_target: str | None = None
    fable_review_required: bool = True
    plan_steps: tuple[str, ...] = field(default_factory=tuple)
    guards: tuple[GuardResult, ...] = field(default_factory=tuple)
    aborted: bool = False


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
