"""Amendment guards for truncation, summary IDs, memory, and promotion."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .config import RouterConfig
from .memory import MemoryReader, MemorySnapshot, default_memory_reader
from .models import GuardResult, Job
from .router_types import LOG_TASK_TYPES

# Any token containing a digit (run42, TS2345, job_17, abc1234, #401, …).
_TOKEN_WITH_DIGIT = re.compile(r"[#A-Za-z0-9_-]*\d[#A-Za-z0-9_-]*")


def check_truncation(job: Job) -> GuardResult:
    """Hard fail when tokens processed < tokens sent.

    Log-summary results that omit token counts fail closed.
    """
    is_log = job.task_type in LOG_TASK_TYPES
    if job.tokens_sent is None or job.tokens_processed is None:
        if is_log:
            return GuardResult(
                name="truncation",
                ok=False,
                detail="FAIL: log-summary result missing tokens_sent/tokens_processed.",
                abort=True,
            )
        return GuardResult(
            name="truncation",
            ok=True,
            detail="No truncation signals provided; skipped (non-log task).",
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
    """Extract every token that contains a digit."""
    return set(_TOKEN_WITH_DIGIT.findall(text))


def normalize_id_token(token: str) -> str:
    """Strip a leading # so #401 and 401 compare equal."""
    return token[1:] if token.startswith("#") else token


def check_summary_numbers_and_ids(job: Job) -> GuardResult:
    """Every number/ID in the summary must appear in the raw source (after # normalize)."""
    is_log = job.task_type in LOG_TASK_TYPES
    if job.summary_text is None or job.source_text is None:
        if is_log:
            return GuardResult(
                name="summary_number_id",
                ok=False,
                detail="FAIL: log-summary result missing summary_text/source_text.",
                abort=True,
            )
        return GuardResult(
            name="summary_number_id",
            ok=True,
            detail="No summary/source pair provided; skipped (non-log task).",
        )
    summary_tokens = extract_numbers_and_ids(job.summary_text)
    source = job.source_text
    missing: list[str] = []
    for token in sorted(summary_tokens):
        if not _token_in_raw_source(token, source):
            missing.append(token)
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


def _token_in_raw_source(token: str, source: str) -> bool:
    """Match token against raw source text; #401 matches 401 and #401."""
    norm = normalize_id_token(token)
    if token in source or norm in source:
        return True
    if f"#{norm}" in source:
        return True
    return False


def check_memory(
    job: Job,
    config: RouterConfig,
    *,
    lane_is_heavy: bool,
    memory_reader: MemoryReader | None = None,
    dry_run: bool = False,
) -> GuardResult:
    """Abort when free memory < 5%, swap trips, 12B still loaded, or unreadable."""
    snapshot = _resolve_snapshot(job, memory_reader, dry_run=dry_run)
    if not snapshot.readable:
        return GuardResult(
            name="memory",
            ok=False,
            detail="ABORT: memory could not be read.",
            abort=True,
        )
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
    dry_run: bool = False,
) -> tuple[GuardResult, ...]:
    return (
        check_truncation(job),
        check_summary_numbers_and_ids(job),
        check_memory(
            job,
            config,
            lane_is_heavy=lane_is_heavy,
            memory_reader=memory_reader,
            dry_run=dry_run,
        ),
        check_promotion(job, config),
    )


def any_abort(guards: Iterable[GuardResult]) -> bool:
    return any(guard.abort for guard in guards)


def _resolve_snapshot(
    job: Job,
    memory_reader: MemoryReader | None,
    *,
    dry_run: bool,
) -> MemorySnapshot:
    snapshot = memory_reader() if memory_reader is not None else default_memory_reader()

    # Job memory fields override the reader ONLY in dry-run mode.
    if dry_run and (
        job.free_memory_percent is not None
        or job.swap_watchdog_tripped
        or job.gemma_12b_loaded
    ):
        return MemorySnapshot(
            free_percent=(
                job.free_memory_percent
                if job.free_memory_percent is not None
                else snapshot.free_percent
            ),
            swap_watchdog_tripped=job.swap_watchdog_tripped or snapshot.swap_watchdog_tripped,
            gemma_12b_loaded=job.gemma_12b_loaded or snapshot.gemma_12b_loaded,
            readable=True,
        )
    return snapshot
