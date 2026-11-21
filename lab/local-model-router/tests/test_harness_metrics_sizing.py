"""Harness planner, metrics JSONL, and step-up/step-down rules."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from local_model_router.config import RouterConfig
from local_model_router.dry_run import format_table, run_dry_run
from local_model_router.harness import build_aider_command, build_harness_plan
from local_model_router.metrics import MetricsEvent, MetricsLogger
from local_model_router.sizing import can_promote_cell, step_down_size, step_up_size


def test_aider_command_sets_map_tokens_zero_and_ollama_env(config: RouterConfig) -> None:
    plan = build_harness_plan(
        config,
        model="inkling-2-mini",
        message="fix synthetic module",
        files=["synthetic_module.py"],
    )
    assert plan.env["OLLAMA_API_BASE"] == "http://127.0.0.1:11434"
    assert "--map-tokens" in plan.aider_attempt
    idx = plan.aider_attempt.index("--map-tokens")
    assert plan.aider_attempt[idx + 1] == "0"
    assert plan.max_attempts == 1
    assert plan.max_follow_ups == 1
    assert plan.escalate_after_follow_up is True
    assert plan.pytest_cmd[0] == "pytest"
    assert plan.ruff_cmd[0] == "ruff"


def test_aider_forbids_full_access_and_bypass(config: RouterConfig) -> None:
    from local_model_router.harness import _assert_no_forbidden_flags

    for flag in ("--full-access", "--bypass", "--codex-full-access", "--dangerously-skip-permissions"):
        with pytest.raises(ValueError, match="Forbidden"):
            _assert_no_forbidden_flags(["aider", flag], config)
    # Happy path still builds without forbidden flags.
    cmd = build_aider_command(config, model="x", message="m", files=["a.py"])
    assert "--full-access" not in cmd
    assert "--bypass" not in cmd


def test_metrics_jsonl_records_vendor_activity_and_rates(tmp_path: Path) -> None:
    path = tmp_path / "metrics.jsonl"
    logger = MetricsLogger(path=path)
    logger.log(
        MetricsEvent(
            event="coding_complete",
            vendor="local",
            activity="unit_tests",
            tokens=1200,
            review_rounds=1,
            merged_pr="lab-only-0",
        )
    )
    logger.log(
        MetricsEvent(
            event="coding_complete",
            vendor="azure",
            activity="single_file_fix",
            tokens=8000,
            review_rounds=2,
            fable_rejection_after_gates=True,
            escalated=True,
            merged_pr="lab-only-1",
        )
    )
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["vendor"] == "local"
    assert first["activity"] == "unit_tests"
    assert first["tokens"] == 1200
    assert logger.escalation_rate() == 0.5
    assert logger.fable_rejection_rate() == 0.5


def test_metrics_stream_logger() -> None:
    buf = StringIO()
    logger = MetricsLogger(stream=buf)
    logger.log(
        MetricsEvent(event="review", vendor="fable", activity="diff_pre_review", review_rounds=1)
    )
    assert "diff_pre_review" in buf.getvalue()


def test_promotion_requires_three_runs(config: RouterConfig) -> None:
    assert can_promote_cell(2, config) is False
    assert can_promote_cell(3, config) is True


def test_step_up_after_ten_consecutive_passes(config: RouterConfig) -> None:
    assert step_up_size("T2", consecutive_passes=9, config=config, max_size="T3") == "T2"
    assert step_up_size("T2", consecutive_passes=10, config=config, max_size="T3") == "T3"
    # Cannot exceed max_size.
    assert step_up_size("T3", consecutive_passes=10, config=config, max_size="T3") == "T3"


def test_step_down_after_two_fable_rejections(config: RouterConfig) -> None:
    assert (
        step_down_size("T3", fable_rejections_in_window=1, config=config) == "T3"
    )
    assert (
        step_down_size("T3", fable_rejections_in_window=2, config=config) == "T2"
    )


def test_dry_run_table_includes_all_task_types_and_guards(
    config: RouterConfig, fixtures_dir: Path
) -> None:
    decisions = run_dry_run(fixtures_dir / "synthetic_jobs.json", config)
    by_id = {d.job_id: d for d in decisions}
    assert by_id["job-ci-log"].lane == "gemma4_12b"
    assert by_id["job-unit-tests"].lane == "inkling_2_mini"
    assert by_id["job-lint-doc"].lane == "gemma4_26b"
    assert by_id["job-large-single-file"].lane == "azure_codex_mini"
    assert by_id["job-multi-file-feature"].lane == "cursor_cloud_agent"
    assert by_id["job-truncation-fail"].aborted is True
    assert by_id["job-low-memory"].aborted is True
    table = format_table(decisions)
    assert "job-truncation-fail" in table
    assert "job-low-memory" in table
    assert "truncation=ABORT" in table or "truncation=FAIL" in table or "ABORT" in table
