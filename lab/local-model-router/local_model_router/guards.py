"""Amendment guards for truncation, summary IDs, memory, and promotion."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .config import RouterConfig
from .memory import MemoryReader, MemorySnapshot, default_memory_reader
from .models import GuardResult, Job

# Numbers and ID-like tokens that must appear in the source for 12B summaries.
_NUMBER_OR_ID = re.compile(
    r"""
    (?<![A-Za-z0-9_])            # left boundary
    (?:
        \#?[A-Za-z]?[0-9]+[A-Za-z0-9_-]*   # numeric / ticket-ish IDs
      | [A-Fa-f0-9]{8,}                      # hex hashes (8+)
    )
    (?![A-Za-z0-9_])             # right boundary
    """,
    re.VERBOSE,
)


def check_truncation(job: Job) -> GuardResult:
    """Hard fail when tokens processed are fewer than tokens sent."""
    if job.tokens_sent is None or job.tokens_processed is None:
        return GuardResult(
            name="truncation",
            ok=True,
            detail="No truncation signals provided; skipped.",
        )
    if job.tokens_processed < job.tokens_sent:
        return GuardResult(
            name="truncation",
            ok=False,
            detail=(
                f"FAIL: tokens_processed ({job.tokens_processed}) "
                f"< tokens_sent ({job.tokens_sent})."
            ),
            abort=True,
        )
    return GuardResult(
        name="truncation",
        ok=True,
        detail=(
            f"OK: tokens_processed ({job.tokens_processed}) "
            f">= tokens_sent ({job.tokens_sent})."
        ),
    )


def extract_numbers_and_ids(text: str) -> set[str]:
    return {match.group(0) for match in _NUMBER_OR_ID.finditer(text)}


def check_summary_numbers_and_ids(job: Job) -> GuardResult:
    """12B summary check: every number/ID in the summary must appear in source."""
    if job.summary_text is None or job.source_text is None:
        return GuardResult(
            name="summary_number_id",
            ok=True,
            detail="No summary/source pair provided; skipped.",
        )
    summary_tokens = extract_numbers_and_ids(job.summary_text)
    source_tokens = extract_numbers_and_ids(job.source_text)
    missing = sorted(token for token in summary_tokens if token not in source_tokens)
    if missing:
        return GuardResult(
            name="summary_number_id",
            ok=False,
            detail=f"FAIL: summary numbers/IDs missing from source: {missing}.",
            abort=True,
        )
    return GuardResult(
        name="summary_number_id",
        ok=True,
        detail=f"OK: all {len(summary_tokens)} summary numbers/IDs appear in source.",
    )


def check_memory(
    job: Job,
    config: RouterConfig,
    *,
    lane_is_heavy: bool,
    memory_reader: MemoryReader | None = None,
) -> GuardResult:
    """Abort when free memory < 5% or swap watchdog trips; unload 12B first."""
    snapshot = _resolve_snapshot(job, memory_reader)
    if lane_is_heavy and config.unload_12b_before_heavy and snapshot.gemma_12b_loaded:
        return GuardResult(
            name="memory",
            ok=False,
            detail="ABORT: heavy model blocked until gemma4:12b is unloaded.",
            abort=True,
        )
    if snapshot.swap_watchdog_tripped:
        return GuardResult(
            name="memory",
            ok=False,
            detail="ABORT: swap watchdog tripped.",
            abort=True,
        )
    if snapshot.free_percent < config.min_free_percent:
        return GuardResult(
            name="memory",
            ok=False,
            detail=(
                f"ABORT: free memory {snapshot.free_percent:.2f}% "
                f"< {config.min_free_percent}%."
            ),
            abort=True,
        )
    return GuardResult(
        name="memory",
        ok=True,
        detail=(
            f"OK: free memory {snapshot.free_percent:.2f}% "
            f"(min {config.min_free_percent}%); swap clear; "
            f"12b_loaded={snapshot.gemma_12b_loaded}."
        ),
    )


def check_promotion(job: Job, config: RouterConfig) -> GuardResult:
    """Promotion only after N runs per cell (config-driven)."""
    required = config.runs_per_cell_required
    if job.cell_run_count is None:
        return GuardResult(
            name="promotion",
            ok=True,
            detail=f"No cell_run_count; promotion gated at {required} runs (not requested).",
        )
    if job.cell_run_count < required:
        return GuardResult(
            name="promotion",
            ok=False,
            detail=(
                f"REFUSE promotion: cell has {job.cell_run_count} runs; "
                f"need {required}."
            ),
            abort=False,
        )
    return GuardResult(
        name="promotion",
        ok=True,
        detail=f"OK: cell has {job.cell_run_count} runs (>= {required}).",
    )


def evaluate_guards(
    job: Job,
    config: RouterConfig,
    *,
    lane_is_heavy: bool,
    memory_reader: MemoryReader | None = None,
) -> tuple[GuardResult, ...]:
    return (
        check_truncation(job),
        check_summary_numbers_and_ids(job),
        check_memory(
            job,
            config,
            lane_is_heavy=lane_is_heavy,
            memory_reader=memory_reader,
        ),
        check_promotion(job, config),
    )


def any_abort(guards: Iterable[GuardResult]) -> bool:
    return any(guard.abort for guard in guards)


def _resolve_snapshot(job: Job, memory_reader: MemoryReader | None) -> MemorySnapshot:
    if memory_reader is not None:
        snapshot = memory_reader()
        # Job overrides win for dry-run / fixture scenarios.
        return MemorySnapshot(
            free_percent=(
                job.free_memory_percent
                if job.free_memory_percent is not None
                else snapshot.free_percent
            ),
            swap_watchdog_tripped=job.swap_watchdog_tripped or snapshot.swap_watchdog_tripped,
            gemma_12b_loaded=job.gemma_12b_loaded or snapshot.gemma_12b_loaded,
        )
    if (
        job.free_memory_percent is not None
        or job.swap_watchdog_tripped
        or job.gemma_12b_loaded
    ):
        return MemorySnapshot(
            free_percent=job.free_memory_percent if job.free_memory_percent is not None else 100.0,
            swap_watchdog_tripped=job.swap_watchdog_tripped,
            gemma_12b_loaded=job.gemma_12b_loaded,
        )
    return default_memory_reader()
