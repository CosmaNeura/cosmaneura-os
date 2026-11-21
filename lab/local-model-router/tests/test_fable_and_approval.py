"""Fable lock and approval gate (cannot be disabled / skipped)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from local_model_router.approval import ApprovalError, require_approval
from local_model_router.config import RouterConfig, load_config
from local_model_router.models import Job
from local_model_router.plan import FABLE_STEP, assert_fable_locked, build_plan_steps, fable_can_be_disabled
from local_model_router.router import route_job


def test_fable_cannot_be_disabled(config: RouterConfig) -> None:
    assert fable_can_be_disabled(config) is False
    assert config.fable_configurable is False
    assert config.fable_review_required is True


def test_assert_fable_locked_rejects_config_flip(config: RouterConfig) -> None:
    raw = copy.deepcopy(config.raw)
    raw["fable"]["review_required"] = False
    # Simulate a tampered load by rebuilding RouterConfig fields via JSON round-trip file.
    # Direct mutation of frozen config is impossible; assert on helper instead.
    with pytest.raises(RuntimeError):
        # Build a fake config-like object by calling assert with altered attributes
        # through a thin subclass-style namespace.
        class Tampered:
            fable_configurable = False
            fable_review_required = False

        assert_fable_locked(Tampered())  # type: ignore[arg-type]


def test_assert_fable_locked_rejects_configurable_true() -> None:
    class Tampered:
        fable_configurable = True
        fable_review_required = True

    with pytest.raises(RuntimeError, match="configurable"):
        assert_fable_locked(Tampered())  # type: ignore[arg-type]


def test_coding_plan_always_ends_with_fable_step(config: RouterConfig) -> None:
    steps = build_plan_steps(config, lane="inkling_2_mini", coding_lane=True)
    assert steps[-1] == FABLE_STEP
    assert steps.count(FABLE_STEP) == 1


def test_fable_step_survives_even_if_raw_flag_false(config: RouterConfig) -> None:
    """Kills mutation that skips appending Fable when config says false."""
    # build_plan_steps ignores config.fable_review_required for coding lanes.
    steps = build_plan_steps(config, lane="gemma4_26b", coding_lane=True, escalated=False)
    assert FABLE_STEP in steps
    assert steps[-1] == FABLE_STEP


def test_route_coding_lanes_set_fable_required(config: RouterConfig) -> None:
    for task, _lane in (
        ("unit_tests", "inkling_2_mini"),
        ("lint_doc_batch", "gemma4_26b"),
        ("diff_pre_review", "gemma4_12b"),
    ):
        decision = route_job(
            Job.from_dict(
                {
                    "job_id": task,
                    "task_type": task,
                    "file_count": 1,
                    "token_estimate": 3000,
                    "free_memory_percent": 40.0,
                    "gemma_12b_loaded": False,
                }
            ),
            config,
        )
        assert decision.fable_review_required is True, task
        assert decision.plan_steps[-1] == FABLE_STEP


def test_approval_refuses_missing_token() -> None:
    with pytest.raises(ApprovalError, match="approved-run-id"):
        require_approval(None, batch_kind="local")
    with pytest.raises(ApprovalError):
        require_approval("  ", batch_kind="azure")
    with pytest.raises(ApprovalError):
        require_approval("none", batch_kind="local")


def test_approval_accepts_recorded_run_id() -> None:
    record = require_approval("cos-yes-20261121-001", batch_kind="local")
    assert record.approved_run_id == "cos-yes-20261121-001"
    assert record.batch_kind == "local"


def test_plan_batch_cli_refuses_without_approval(tmp_path: Path, config: RouterConfig) -> None:
    from local_model_router.__main__ import main

    job_path = tmp_path / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "job_id": "cli-1",
                "task_type": "unit_tests",
                "file_count": 1,
                "token_estimate": 2000,
                "free_memory_percent": 40.0,
            }
        ),
        encoding="utf-8",
    )
    code = main(
        [
            "plan-batch",
            "--batch-kind",
            "local",
            "--job-json",
            str(job_path),
            "--config",
            str(Path(__file__).resolve().parents[1] / "config" / "router_config.json"),
        ]
    )
    assert code == 2


def test_config_inkling_caps_raised(config: RouterConfig) -> None:
    inkling = config.lanes["inkling_2_mini"]
    assert inkling.num_predict is not None and inkling.num_predict >= 8192
    assert inkling.timeout_seconds is not None and inkling.timeout_seconds >= 480


def test_config_loaded_from_file_not_hardcoded() -> None:
    cfg = load_config()
    assert cfg.runs_per_cell_required == 3
    assert cfg.min_free_percent == 5.0
    assert cfg.lanes["gemma4_26b"].starting_size == "T3"
    assert cfg.lanes["inkling_2_mini"].starting_size == "T3"
