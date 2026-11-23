"""Fable lock (non-tautological) and approval ledger / batch-kind / cap."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_model_router.approval import ApprovalError, require_approval, record_azure_spend
from local_model_router.config import RouterConfig, assert_fable_locked, load_config
from local_model_router.memory import MemorySnapshot
from local_model_router.models import Job, RouteDecision
from local_model_router.plan import FABLE_STEP, build_plan_steps, fable_can_be_disabled
from local_model_router.router import route_job
from local_model_router.router_types import is_coding_task


def test_fable_cannot_be_disabled(config: RouterConfig) -> None:
    assert fable_can_be_disabled(config) is False
    assert config.fable_configurable is False
    assert config.fable_review_required is True


def test_load_config_asserts_fable_locked(tmp_path: Path, config: RouterConfig) -> None:
    """assert_fable_locked runs inside load_config."""
    bad = dict(config.raw)
    bad["fable"] = {"review_required": False, "configurable": False}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(RuntimeError, match="review_required"):
        load_config(path)


def test_load_config_rejects_configurable_true(tmp_path: Path, config: RouterConfig) -> None:
    bad = dict(config.raw)
    bad["fable"] = {"review_required": True, "configurable": True}
    path = tmp_path / "bad2.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(RuntimeError, match="configurable"):
        load_config(path)


def test_coding_plan_ends_with_fable_from_task_type(config: RouterConfig) -> None:
    """Non-tautological: derive coding from task_type, not a caller bool."""
    steps = build_plan_steps(
        config, lane="inkling_2_mini", task_type="single_file_fix", heavy=True
    )
    assert steps[-1] == FABLE_STEP
    assert "aider_attempt_1" in steps
    assert is_coding_task("single_file_fix") is True


def test_log_summary_plan_has_no_aider_and_no_fable(config: RouterConfig) -> None:
    steps = build_plan_steps(
        config, lane="gemma4_12b", task_type="ci_log_summary", heavy=False
    )
    assert FABLE_STEP not in steps
    assert "aider_attempt_1" not in steps
    assert "summarize_log" in steps


def test_route_coding_lanes_set_fable_required(config: RouterConfig) -> None:
    for task in ("unit_tests", "lint_doc_batch", "diff_pre_review"):
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
            dry_run=True,
            memory_reader=lambda: MemorySnapshot(40.0, False, False, True),
        )
        assert decision.fable_review_required is True, task
        assert decision.plan_steps[-1] == FABLE_STEP


def test_approval_refuses_missing_token() -> None:
    with pytest.raises(ApprovalError, match="approved-run-id"):
        require_approval(None, batch_kind="local")
    with pytest.raises(ApprovalError):
        require_approval("none", batch_kind="local")


def test_approval_accepts_recorded_run_id(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    record = require_approval(
        "cos-yes-20261121-001",
        batch_kind="local",
        ledger_path=ledger,
    )
    assert record.approved_run_id == "cos-yes-20261121-001"
    # Single-use: second attempt fails.
    with pytest.raises(ApprovalError, match="already used"):
        require_approval(
            "cos-yes-20261121-001",
            batch_kind="local",
            ledger_path=ledger,
        )


def test_batch_kind_mismatch_refused(config: RouterConfig) -> None:
    decision = RouteDecision(
        job_id="x",
        lane="azure_codex_mini",
        reason="escalate",
        escalate=True,
        escalation_target="azure_codex_mini",
        batch_kind="azure",
        vendor="azure",
    )
    with pytest.raises(ApprovalError, match="mismatch"):
        require_approval("cos-yes-1", batch_kind="local", decision=decision, config=config)


def test_azure_monthly_cap_enforced(config: RouterConfig, tmp_path: Path) -> None:
    spend = tmp_path / "spend.json"
    record_azure_spend(spend, 200.0)
    decision = RouteDecision(
        job_id="x",
        lane="azure_codex_mini",
        reason="escalate",
        batch_kind="azure",
        vendor="azure",
    )
    with pytest.raises(ApprovalError, match="exceeded"):
        require_approval(
            "cos-yes-cap",
            batch_kind="azure",
            decision=decision,
            config=config,
            ledger_path=tmp_path / "ledger.json",
            spend_ledger_path=spend,
            azure_run_estimate_usd=1.0,
        )


def test_plan_batch_cli_refuses_without_approval(tmp_path: Path) -> None:
    from local_model_router.__main__ import main
    from local_model_router.memory import MemorySnapshot

    job_path = tmp_path / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "job_id": "cli-1",
                "task_type": "unit_tests",
                "file_count": 1,
                "token_estimate": 2000,
            }
        ),
        encoding="utf-8",
    )
    healthy = lambda: MemorySnapshot(40.0, False, False, True, "not_loaded")
    code = main(
        [
            "plan-batch",
            "--batch-kind",
            "local",
            "--job-json",
            str(job_path),
            "--config",
            str(Path(__file__).resolve().parents[1] / "config" / "router_config.json"),
            "--state-dir",
            str(tmp_path / "state"),
        ],
        memory_reader=healthy,
    )
    assert code == 2


def test_plan_batch_exits_nonzero_on_guard_abort(tmp_path: Path) -> None:
    from local_model_router.__main__ import main
    from local_model_router.memory import MemorySnapshot

    job_path = tmp_path / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "job_id": "cli-abort",
                "task_type": "unit_tests",
                "file_count": 1,
                "token_estimate": 2000,
            }
        ),
        encoding="utf-8",
    )
    low = lambda: MemorySnapshot(3.0, False, False, True, "not_loaded")
    code = main(
        [
            "plan-batch",
            "--approved-run-id",
            "cos-yes-abort",
            "--job-json",
            str(job_path),
            "--config",
            str(Path(__file__).resolve().parents[1] / "config" / "router_config.json"),
            "--state-dir",
            str(tmp_path / "state"),
        ],
        memory_reader=low,
    )
    assert code == 3


def test_config_inkling_caps_raised(config: RouterConfig) -> None:
    inkling = config.lanes["inkling_2_mini"]
    assert inkling.num_predict == 8192
    assert inkling.timeout_seconds == 480


def test_config_26b_num_ctx_covers_t3(config: RouterConfig) -> None:
    lane = config.lanes["gemma4_26b"]
    assert lane.num_ctx is not None and lane.num_ctx >= 12288
    inkling = config.lanes["inkling_2_mini"]
    assert inkling.num_ctx is not None and inkling.num_ctx >= 18432


def test_assert_fable_locked_helper() -> None:
    class Ok:
        fable_configurable = False
        fable_review_required = True

    assert_fable_locked(Ok())  # type: ignore[arg-type]
