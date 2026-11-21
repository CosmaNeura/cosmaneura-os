"""Amendment guards: truncation, number/ID, memory, promotion."""

from __future__ import annotations

import pytest

from local_model_router.config import RouterConfig
from local_model_router.guards import (
    check_memory,
    check_promotion,
    check_summary_numbers_and_ids,
    check_truncation,
    extract_numbers_and_ids,
    normalize_id_token,
)
from local_model_router.memory import MemorySnapshot, macos_memory_reader, is_gemma_12b_loaded
from local_model_router.models import Job
from local_model_router.router import route_job

from .conftest import make_job


def test_truncation_hard_fail_when_processed_lt_sent() -> None:
    result = check_truncation(make_job(tokens_sent=10960, tokens_processed=4099))
    assert result.ok is False
    assert result.abort is True


def test_truncation_ok_when_processed_ge_sent() -> None:
    result = check_truncation(make_job(tokens_sent=100, tokens_processed=100))
    assert result.ok is True


def test_truncation_mutation_equal_boundary() -> None:
    assert check_truncation(make_job(tokens_sent=50, tokens_processed=50)).ok is True
    assert check_truncation(make_job(tokens_sent=50, tokens_processed=49)).ok is False


def test_log_summary_missing_token_counts_fails() -> None:
    """(5) Truncation fails when a log-summary result lacks token counts."""
    result = check_truncation(make_job(task_type="log_summary"))
    assert result.ok is False
    assert result.abort is True


def test_log_summary_missing_source_fails() -> None:
    """(5) Number/ID guard fails when log-summary lacks source."""
    result = check_summary_numbers_and_ids(
        make_job(task_type="ci_log_summary", summary_text="Job 1 failed")
    )
    assert result.ok is False
    assert result.abort is True


def test_summary_fails_when_number_missing_from_source() -> None:
    result = check_summary_numbers_and_ids(
        make_job(
            summary_text="Job #999 failed after 42 tests.",
            source_text="Job #401 failed after 128 tests.",
        )
    )
    assert result.ok is False
    assert result.abort is True


def test_hash_401_matches_401_in_raw_source() -> None:
    """(5) #401 vs 401 after normalize."""
    assert normalize_id_token("#401") == "401"
    result = check_summary_numbers_and_ids(
        make_job(
            summary_text="Fixed #401 in suite.",
            source_text="ticket 401 closed in suite",
        )
    )
    assert result.ok is True


@pytest.mark.parametrize(
    "token",
    ["run42", "TS2345", "job_17", "abc1234", "#401"],
)
def test_extract_tokens_with_digits(token: str) -> None:
    """(5) extract any token containing a digit."""
    found = extract_numbers_and_ids(f"prefix {token} suffix")
    assert token in found


def test_extract_matches_against_raw_source_for_mixed_ids() -> None:
    source = "run42 failed with TS2345 on job_17 for abc1234 and ticket 401"
    summary = "run42 TS2345 job_17 abc1234 #401"
    result = check_summary_numbers_and_ids(
        make_job(summary_text=summary, source_text=source)
    )
    assert result.ok is True


def test_memory_abort_when_free_below_5_percent(config: RouterConfig) -> None:
    result = check_memory(
        make_job(free_memory_percent=4.9),
        config,
        lane_is_heavy=True,
        memory_reader=lambda: MemorySnapshot(4.9, False, False, True),
        dry_run=True,
    )
    assert result.abort is True


def test_memory_ok_at_exactly_5_percent(config: RouterConfig) -> None:
    result = check_memory(
        make_job(free_memory_percent=5.0),
        config,
        lane_is_heavy=True,
        memory_reader=lambda: MemorySnapshot(5.0, False, False, True),
        dry_run=True,
    )
    assert result.ok is True


def test_memory_abort_on_swap_watchdog(config: RouterConfig) -> None:
    result = check_memory(
        make_job(swap_watchdog_tripped=True),
        config,
        lane_is_heavy=True,
        memory_reader=lambda: MemorySnapshot(40.0, True, False, True),
        dry_run=True,
    )
    assert result.abort is True


def test_memory_blocks_heavy_while_12b_loaded(config: RouterConfig) -> None:
    result = check_memory(
        make_job(gemma_12b_loaded=True),
        config,
        lane_is_heavy=True,
        memory_reader=lambda: MemorySnapshot(40.0, False, True, True),
        dry_run=True,
    )
    assert result.abort is True


def test_memory_unreadable_aborts(config: RouterConfig) -> None:
    """(4) Abort when memory can't be read."""
    result = check_memory(
        Job(job_id="x", task_type="unit_tests", file_count=1, token_estimate=1),
        config,
        lane_is_heavy=True,
        memory_reader=lambda: MemorySnapshot(0.0, False, False, readable=False),
        dry_run=False,
    )
    assert result.abort is True
    assert "could not be read" in result.detail


def test_job_memory_override_only_in_dry_run(config: RouterConfig) -> None:
    """(4) Job memory fields override only in dry-run."""
    job = make_job(free_memory_percent=4.0)

    def healthy() -> MemorySnapshot:
        return MemorySnapshot(40.0, False, False, True)

    dry = check_memory(job, config, lane_is_heavy=True, memory_reader=healthy, dry_run=True)
    live = check_memory(job, config, lane_is_heavy=True, memory_reader=healthy, dry_run=False)
    assert dry.abort is True
    assert live.ok is True


def test_macos_memory_reader_uses_injected_commands() -> None:
    """(4) macOS reader via mocked vm_stat / sysctl — no real Mac calls."""
    vm_stat = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               1000.
Pages active:                             2000.
Pages inactive:                           2000.
Pages speculative:                         100.
Pages wired down:                         1000.
Pages occupied by compressor:              900.
"""
    sysctl = "vm.swapusage: total = 1024.00M  used = 10.00M  free = 1014.00M"

    def runner(argv: list[str]) -> str:
        if argv[0] == "vm_stat":
            return vm_stat
        if argv[:2] == ["sysctl", "vm.swapusage"]:
            return sysctl
        raise AssertionError(argv)

    snap = macos_memory_reader(command_runner=runner)
    assert snap.readable is True
    assert snap.free_percent > 5.0
    assert snap.swap_watchdog_tripped is False


def test_ollama_loaded_check_uses_injected_http() -> None:
    """(4) Localhost Ollama loaded-model check is injectable (no network)."""
    assert (
        is_gemma_12b_loaded(
            http_get=lambda _url: {"models": [{"name": "gemma4:12b"}]}
        )
        is True
    )
    assert (
        is_gemma_12b_loaded(
            http_get=lambda _url: {"models": [{"name": "inkling-2-mini"}]}
        )
        is False
    )


def test_promotion_refuses_before_3_runs(config: RouterConfig) -> None:
    assert check_promotion(make_job(cell_run_count=2), config).ok is False


def test_promotion_ok_at_3_runs(config: RouterConfig) -> None:
    assert check_promotion(make_job(cell_run_count=3), config).ok is True
    assert check_promotion(make_job(cell_run_count=2), config).ok is False


def test_route_aborts_on_truncation(config: RouterConfig) -> None:
    decision = route_job(
        make_job(
            task_type="log_summary",
            log_kind="long",
            token_estimate=10960,
            tokens_sent=10960,
            tokens_processed=4099,
            source_text="10960 and 4099",
            summary_text="4099 of 10960",
        ),
        config,
        dry_run=True,
    )
    assert decision.aborted is True
    truncation = next(g for g in decision.guards if g.name == "truncation")
    assert truncation.ok is False


def test_route_aborts_on_low_memory(config: RouterConfig) -> None:
    decision = route_job(
        make_job(task_type="unit_tests", free_memory_percent=4.2),
        config,
        dry_run=True,
    )
    assert decision.aborted is True


@pytest.mark.parametrize("free_pct,expect_abort", [(4.999, True), (5.0, False), (5.001, False)])
def test_memory_threshold_boundary(
    config: RouterConfig, free_pct: float, expect_abort: bool
) -> None:
    result = check_memory(
        make_job(free_memory_percent=free_pct),
        config,
        lane_is_heavy=True,
        dry_run=True,
    )
    assert result.abort is expect_abort
