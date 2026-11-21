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
)
from local_model_router.memory import MemorySnapshot
from local_model_router.models import Job
from local_model_router.router import route_job


def _job(**kwargs) -> Job:
    base = {
        "job_id": "g",
        "task_type": "unit_tests",
        "file_count": 1,
        "token_estimate": 2000,
        "free_memory_percent": 40.0,
        "gemma_12b_loaded": False,
    }
    base.update(kwargs)
    return Job.from_dict(base)


def test_truncation_hard_fail_when_processed_lt_sent() -> None:
    result = check_truncation(
        _job(tokens_sent=10960, tokens_processed=4099)
    )
    assert result.ok is False
    assert result.abort is True
    assert "FAIL" in result.detail


def test_truncation_ok_when_processed_ge_sent() -> None:
    result = check_truncation(_job(tokens_sent=100, tokens_processed=100))
    assert result.ok is True
    assert result.abort is False


def test_truncation_mutation_equal_boundary() -> None:
    """Kills mutation that changes < to <= (equal must pass)."""
    result = check_truncation(_job(tokens_sent=50, tokens_processed=50))
    assert result.ok is True
    result_fail = check_truncation(_job(tokens_sent=50, tokens_processed=49))
    assert result_fail.ok is False


def test_summary_fails_when_number_missing_from_source() -> None:
    result = check_summary_numbers_and_ids(
        _job(
            summary_text="Job #999 failed after 42 tests.",
            source_text="Job #401 failed after 128 tests.",
        )
    )
    assert result.ok is False
    assert result.abort is True
    assert "#999" in result.detail or "999" in result.detail


def test_summary_ok_when_all_numbers_present() -> None:
    result = check_summary_numbers_and_ids(
        _job(
            summary_text="Job #401 failed after 128 tests (sha abcdef12).",
            source_text="synth-ci job #401 failed on backend-2 after 128 tests; sha abcdef12",
        )
    )
    assert result.ok is True


def test_extract_numbers_and_ids_finds_tickets_and_hex() -> None:
    tokens = extract_numbers_and_ids("PR #400 sha deadbeef and 12 failures")
    assert "#400" in tokens or "400" in tokens
    assert "deadbeef" in tokens
    assert "12" in tokens


def test_memory_abort_when_free_below_5_percent(config: RouterConfig) -> None:
    result = check_memory(
        _job(free_memory_percent=4.9),
        config,
        lane_is_heavy=True,
        memory_reader=lambda: MemorySnapshot(4.9, False, False),
    )
    assert result.ok is False
    assert result.abort is True
    assert "4.9" in result.detail


def test_memory_ok_at_exactly_5_percent(config: RouterConfig) -> None:
    """Kills mutation that changes < to <= on the free-memory threshold."""
    result = check_memory(
        _job(free_memory_percent=5.0),
        config,
        lane_is_heavy=True,
        memory_reader=lambda: MemorySnapshot(5.0, False, False),
    )
    assert result.ok is True


def test_memory_abort_on_swap_watchdog(config: RouterConfig) -> None:
    result = check_memory(
        _job(free_memory_percent=40.0, swap_watchdog_tripped=True),
        config,
        lane_is_heavy=True,
        memory_reader=lambda: MemorySnapshot(40.0, True, False),
    )
    assert result.ok is False
    assert result.abort is True
    assert "swap" in result.detail.lower()


def test_memory_blocks_heavy_while_12b_loaded(config: RouterConfig) -> None:
    result = check_memory(
        _job(free_memory_percent=40.0, gemma_12b_loaded=True),
        config,
        lane_is_heavy=True,
        memory_reader=lambda: MemorySnapshot(40.0, False, True),
    )
    assert result.ok is False
    assert result.abort is True
    assert "unloaded" in result.detail.lower()


def test_memory_reader_is_injectable(config: RouterConfig) -> None:
    calls: list[str] = []

    def fake() -> MemorySnapshot:
        calls.append("read")
        return MemorySnapshot(free_percent=2.0, swap_watchdog_tripped=False)

    # Job does not override free_memory_percent so reader is used.
    job = Job(
        job_id="inject",
        task_type="unit_tests",
        file_count=1,
        token_estimate=1000,
    )
    result = check_memory(job, config, lane_is_heavy=True, memory_reader=fake)
    assert calls == ["read"]
    assert result.abort is True


def test_promotion_refuses_before_3_runs(config: RouterConfig) -> None:
    assert config.runs_per_cell_required == 3
    result = check_promotion(_job(cell_run_count=2), config)
    assert result.ok is False
    assert "2" in result.detail
    assert "3" in result.detail


def test_promotion_ok_at_3_runs(config: RouterConfig) -> None:
    """Kills mutation that changes >= 3 to > 3."""
    result = check_promotion(_job(cell_run_count=3), config)
    assert result.ok is True
    assert check_promotion(_job(cell_run_count=2), config).ok is False


def test_route_aborts_on_truncation(config: RouterConfig) -> None:
    decision = route_job(
        _job(
            task_type="log_summary",
            log_kind="long",
            token_estimate=10960,
            tokens_sent=10960,
            tokens_processed=4099,
        ),
        config,
    )
    assert decision.aborted is True
    assert decision.lane == "aborted"
    truncation = next(g for g in decision.guards if g.name == "truncation")
    assert truncation.ok is False


def test_route_aborts_on_low_memory(config: RouterConfig) -> None:
    decision = route_job(
        _job(task_type="unit_tests", free_memory_percent=4.2),
        config,
    )
    assert decision.aborted is True
    memory = next(g for g in decision.guards if g.name == "memory")
    assert memory.abort is True


@pytest.mark.parametrize("free_pct,expect_abort", [(4.999, True), (5.0, False), (5.001, False)])
def test_memory_threshold_boundary(
    config: RouterConfig, free_pct: float, expect_abort: bool
) -> None:
    result = check_memory(
        _job(free_memory_percent=free_pct),
        config,
        lane_is_heavy=True,
    )
    assert result.abort is expect_abort
