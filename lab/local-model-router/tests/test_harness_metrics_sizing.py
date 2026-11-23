"""Harness planner, metrics JSONL, sizing state, dry-run table."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from local_model_router.config import HARDCODED_FORBIDDEN_AIDER_FLAGS, RouterConfig
from local_model_router.dry_run import format_table, run_dry_run
from local_model_router.harness import build_aider_command, build_harness_plan, _assert_no_forbidden_flags
from local_model_router.metrics import AMENDMENT6_FIELDS, MetricsEvent, MetricsLogger, assert_amendment6_fields
from local_model_router.plan import FABLE_STEP
from local_model_router.sizing import TaskSizeState, can_promote_cell, step_down_size, step_up_size


def test_aider_command_sets_map_tokens_zero_and_timeout(
    config: RouterConfig, tmp_path: Path
) -> None:
    lane = config.lanes["inkling_2_mini"]
    plan = build_harness_plan(
        config,
        model=lane.model,
        message="fix synthetic module",
        files=["synthetic_module.py"],
        lane=lane,
        model_settings_dir=tmp_path,
    )
    assert plan.env["OLLAMA_API_BASE"] == "http://127.0.0.1:11434"
    assert plan.num_predict == 8192
    assert plan.timeout_seconds == 480
    assert plan.num_ctx == 18432
    assert "--timeout" in plan.aider_attempt
    assert "num_predict: 8192" in (plan.model_settings_text or "")
    assert "num_ctx: 18432" in (plan.model_settings_text or "")
    assert "--map-tokens" in plan.aider_attempt
    idx = plan.aider_attempt.index("--map-tokens")
    assert plan.aider_attempt[idx + 1] == "0"


def test_26b_harness_num_ctx_at_least_12288(config: RouterConfig, tmp_path: Path) -> None:
    lane = config.lanes["gemma4_26b"]
    plan = build_harness_plan(
        config,
        model=lane.model,
        message="lint",
        files=["a.py"],
        lane=lane,
        model_settings_dir=tmp_path,
    )
    assert plan.num_ctx is not None and plan.num_ctx >= 12288
    assert "num_ctx: 12288" in (plan.model_settings_text or "")


def test_hardcoded_denylist_rejects_equals_forms(config: RouterConfig) -> None:
    assert "--yes-always" in HARDCODED_FORBIDDEN_AIDER_FLAGS
    with pytest.raises(ValueError, match="Forbidden"):
        _assert_no_forbidden_flags(["aider", "--yes-always=true"], config)
    with pytest.raises(ValueError, match="Forbidden"):
        _assert_no_forbidden_flags(["aider", "--dangerously-skip-permissions=x"], config)
    _assert_no_forbidden_flags(
        ["aider", "--message", "--yes-always=true is in the prompt"],
        config,
    )


def test_rejects_file_args_starting_with_dash(config: RouterConfig) -> None:
    with pytest.raises(ValueError, match="file arg"):
        build_aider_command(config, model="x", message="m", files=["-rf"])


def test_config_can_only_add_forbidden_flags(tmp_path: Path, config: RouterConfig) -> None:
    raw = dict(config.raw)
    raw["harness"] = dict(raw["harness"])
    raw["harness"]["forbidden_aider_flags"] = ["--extra-banned"]
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    from local_model_router.config import load_config

    cfg = load_config(path)
    assert "--yes-always" in cfg.merged_forbidden_flags()
    assert "--extra-banned" in cfg.merged_forbidden_flags()
    with pytest.raises(ValueError):
        _assert_no_forbidden_flags(["aider", "--extra-banned"], cfg)


def test_metrics_jsonl_writes_to_configured_path_with_vendor(
    tmp_path: Path, config: RouterConfig
) -> None:
    path = tmp_path / Path(config.metrics_jsonl_path).name
    logger = MetricsLogger(path=path)
    record = logger.log(
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
    assert_amendment6_fields(record)
    for field in AMENDMENT6_FIELDS:
        assert field in record
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["vendor"] == "azure"


def test_metrics_stream_logger() -> None:
    buf = StringIO()
    logger = MetricsLogger(stream=buf)
    logger.log(
        MetricsEvent(
            event="review",
            vendor="local",
            activity="diff_pre_review",
            review_rounds=1,
            merged_pr=None,
        )
    )
    assert "diff_pre_review" in buf.getvalue()


def test_promotion_requires_three_runs(config: RouterConfig) -> None:
    assert can_promote_cell(2, config) is False
    assert can_promote_cell(3, config) is True


def test_step_up_gated_on_can_promote_cell(config: RouterConfig) -> None:
    assert (
        step_up_size(
            "T2",
            consecutive_passes=10,
            config=config,
            max_size="T3",
            cell_run_count=2,
        )
        == "T2"
    )
    assert (
        step_up_size(
            "T2",
            consecutive_passes=10,
            config=config,
            max_size="T3",
            cell_run_count=3,
        )
        == "T3"
    )


def test_step_down_uses_window(config: RouterConfig) -> None:
    assert config.step_down_window == 10
    assert step_down_size("T3", fable_rejections_in_window=1, config=config) == "T3"
    assert step_down_size("T3", fable_rejections_in_window=2, config=config) == "T2"


def test_task_size_state_tracks_per_task_type(config: RouterConfig) -> None:
    state = TaskSizeState()
    assert state.current_size("unit_tests", "T3") == "T3"
    state.record_outcome(
        "unit_tests",
        gates_and_fable_pass=False,
        fable_rejected=True,
        config=config,
        max_size="T3",
        starting_size="T3",
    )
    size = state.record_outcome(
        "unit_tests",
        gates_and_fable_pass=False,
        fable_rejected=True,
        config=config,
        max_size="T3",
        starting_size="T3",
    )
    assert size == "T2"
    assert state.current_size("lint_doc_batch", "T3") == "T3"


def test_dry_run_table_includes_guards_fable_and_unrouted(
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
    long_sf = by_id["job-longlog-single-file-keeps-fable"]
    assert long_sf.lane == "inkling_2_mini"
    assert long_sf.plan_steps[-1] == FABLE_STEP
    assert by_id["job-unknown-unrouted"].lane == "unrouted"
    assert by_id["job-unknown-unrouted"].escalate is False
    table = format_table(decisions)
    assert "job-truncation-fail" in table
    assert "job-low-memory" in table
    assert "job-unknown-unrouted" in table
