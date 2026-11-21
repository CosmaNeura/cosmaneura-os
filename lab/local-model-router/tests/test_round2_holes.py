"""Fable round-2 HOLES 4,5,6,7,9,10,N1,N2 + extras (injection, approval order)."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from local_model_router.approval import ApprovalError, record_azure_spend, require_approval
from local_model_router.config import HARDCODED_FORBIDDEN_AIDER_FLAGS, RouterConfig, load_config
from local_model_router.guards import check_memory, check_summary_numbers_and_ids, _token_in_raw_source
from local_model_router.harness import (
    ALLOWED_AIDER_FLAGS,
    build_aider_command,
    build_harness_plan,
    build_model_settings_yaml,
    _assert_no_forbidden_flags,
)
from local_model_router.memory import MemorySnapshot, probe_ollama_12b_status
from local_model_router.models import Job, RouteDecision
from local_model_router.plan import FABLE_STEP
from local_model_router.router import route_job
from local_model_router.sizing import TaskSizeState, cell_key

from .conftest import make_job


# --- (4) Ollama connection-refused vs unknown ---------------------------------


def test_ollama_connection_refused_is_not_loaded() -> None:
    def boom(_url: str) -> dict:
        raise urllib.error.URLError(ConnectionRefusedError("Connection refused"))

    assert probe_ollama_12b_status(http_get=boom) == "not_loaded"


def test_ollama_other_error_is_unknown() -> None:
    def boom(_url: str) -> dict:
        raise urllib.error.URLError(TimeoutError("timed out"))

    assert probe_ollama_12b_status(http_get=boom) == "unknown"


def test_ollama_unknown_aborts_heavy_lane(config: RouterConfig) -> None:
    result = check_memory(
        Job(job_id="u", task_type="unit_tests", file_count=1, token_estimate=100),
        config,
        lane_is_heavy=True,
        memory_reader=lambda: MemorySnapshot(
            40.0, False, False, True, ollama_12b_status="unknown"
        ),
        dry_run=False,
    )
    assert result.abort is True
    assert "unknown" in result.detail.lower()


# --- (5) boundary match -------------------------------------------------------


def test_token_boundary_five_fails_against_fifty_two() -> None:
    assert _token_in_raw_source("5", "52 passed") is False
    assert _token_in_raw_source("52", "52 passed") is True


def test_summary_rejects_substring_number_match() -> None:
    result = check_summary_numbers_and_ids(
        make_job(
            task_type="ci_log_summary",
            summary_text="5 failures",
            source_text="52 passed in suite",
            tokens_sent=1,
            tokens_processed=1,
        )
    )
    assert result.ok is False


# --- (6) allowlist + restored bypass tests (REGRESSION) -----------------------


def test_restored_bypass_full_access_codex_flags(config: RouterConfig) -> None:
    for flag in ("--bypass", "--full-access", "--codex-full-access"):
        with pytest.raises(ValueError, match="Forbidden"):
            _assert_no_forbidden_flags(["aider", flag], config)


@pytest.mark.parametrize(
    "flag",
    [
        "--dangerously-bypass-approvals-and-sandbox",
        "--bypass-permissions",
        "--yolo",
        "--full-auto",
        "--yes-always=true",
    ],
)
def test_allowlist_rejects_sandbox_bypass_forms(config: RouterConfig, flag: str) -> None:
    with pytest.raises(ValueError):
        _assert_no_forbidden_flags(["aider", flag], config)


def test_non_allowlisted_dash_arg_rejected(config: RouterConfig) -> None:
    assert "--model" in ALLOWED_AIDER_FLAGS
    with pytest.raises(ValueError, match="allowlisted|Forbidden"):
        _assert_no_forbidden_flags(["aider", "--edit-format", "diff"], config)


# --- (7) Azure spend fail-closed / max / estimate / CLI -----------------------


def test_azure_fails_closed_without_spend_ledger(config: RouterConfig) -> None:
    decision = RouteDecision(
        job_id="x", lane="azure_codex_mini", reason="e", batch_kind="azure", vendor="azure"
    )
    with pytest.raises(ApprovalError, match="spend ledger"):
        require_approval(
            "cos-yes-1",
            batch_kind="azure",
            decision=decision,
            config=config,
            ledger_path=None,
            spend_ledger_path=None,
        )


def test_azure_uses_max_of_ledger_and_job_spend(config: RouterConfig, tmp_path: Path) -> None:
    spend = tmp_path / "spend.json"
    record_azure_spend(spend, 50.0)
    decision = RouteDecision(
        job_id="x", lane="azure_codex_mini", reason="e", batch_kind="azure", vendor="azure"
    )
    # job spend 180 + estimate 30 = 210 > 200 even though ledger is 50
    with pytest.raises(ApprovalError, match="exceeded"):
        require_approval(
            "cos-yes-max",
            batch_kind="azure",
            decision=decision,
            config=config,
            ledger_path=tmp_path / "ledger.json",
            spend_ledger_path=spend,
            azure_month_spend_usd=180.0,
            azure_run_estimate_usd=30.0,
        )


def test_azure_refuses_when_spend_plus_estimate_exceeds_cap(
    config: RouterConfig, tmp_path: Path
) -> None:
    spend = tmp_path / "spend.json"
    record_azure_spend(spend, 190.0)
    decision = RouteDecision(
        job_id="x", lane="azure_codex_mini", reason="e", batch_kind="azure", vendor="azure"
    )
    with pytest.raises(ApprovalError, match="exceeded"):
        require_approval(
            "cos-yes-est",
            batch_kind="azure",
            decision=decision,
            config=config,
            ledger_path=tmp_path / "ledger.json",
            spend_ledger_path=spend,
            azure_run_estimate_usd=15.0,
        )


def test_record_azure_spend_cli(tmp_path: Path) -> None:
    from local_model_router.__main__ import main

    code = main(
        [
            "record-azure-spend",
            "--amount-usd",
            "12.5",
            "--state-dir",
            str(tmp_path / "state"),
            "--config",
            str(Path(__file__).resolve().parents[1] / "config" / "router_config.json"),
        ]
    )
    assert code == 0
    spend_file = tmp_path / "state" / "azure_spend.json"
    assert spend_file.exists()


def test_approval_id_consumed_only_after_checks_pass(
    config: RouterConfig, tmp_path: Path
) -> None:
    """Extras: consume only after checks; failed Azure check must not burn the ID."""
    ledger = tmp_path / "ledger.json"
    decision = RouteDecision(
        job_id="x", lane="azure_codex_mini", reason="e", batch_kind="azure", vendor="azure"
    )
    with pytest.raises(ApprovalError, match="spend ledger"):
        require_approval(
            "cos-yes-order",
            batch_kind="azure",
            decision=decision,
            config=config,
            ledger_path=ledger,
            spend_ledger_path=None,
        )
    assert not ledger.exists()


# --- (9) persisted TaskSizeState ---------------------------------------------


def test_step_down_survives_new_process(config: RouterConfig, tmp_path: Path) -> None:
    path = tmp_path / "task_size_state.json"
    state = TaskSizeState()
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
    # Rejection history cleared after the step.
    assert state.fable_rejection_history.get("unit_tests", []) == []
    state.save(path)

    reloaded = TaskSizeState.load(path)
    assert reloaded.current_size("unit_tests", "T3") == "T2"


def test_cell_run_counts_keyed_by_task_and_size(config: RouterConfig) -> None:
    state = TaskSizeState()
    state.record_outcome(
        "unit_tests",
        gates_and_fable_pass=True,
        fable_rejected=False,
        config=config,
        max_size="T3",
        starting_size="T3",
    )
    assert cell_key("unit_tests", "T3") in state.cell_run_counts


def test_record_outcome_cli_persists(tmp_path: Path) -> None:
    from local_model_router.__main__ import main

    cfg = str(Path(__file__).resolve().parents[1] / "config" / "router_config.json")
    state_dir = tmp_path / "state"
    for _ in range(2):
        code = main(
            [
                "record-outcome",
                "--task-type",
                "unit_tests",
                "--fable-rejected",
                "--state-dir",
                str(state_dir),
                "--config",
                cfg,
            ]
        )
        assert code == 0
    state = TaskSizeState.load(state_dir / "task_size_state.json")
    assert state.current_size("unit_tests", "T3") == "T2"


# --- (10) timeout + model settings -------------------------------------------


def test_aider_argv_includes_timeout_and_model_settings(
    config: RouterConfig, tmp_path: Path
) -> None:
    lane = config.lanes["inkling_2_mini"]
    plan = build_harness_plan(
        config,
        model=lane.model,
        message="fix",
        files=["a.py"],
        lane=lane,
        model_settings_dir=tmp_path,
    )
    assert "--timeout" in plan.aider_attempt
    assert plan.aider_attempt[plan.aider_attempt.index("--timeout") + 1] == "480"
    assert "--model-settings-file" in plan.aider_attempt
    assert "OLLAMA_NUM_PREDICT" not in plan.env
    assert "OLLAMA_NUM_CTX" not in plan.env
    assert plan.model_settings_text is not None
    assert "num_predict: 8192" in plan.model_settings_text
    assert "num_ctx: 18432" in plan.model_settings_text
    assert plan.num_ctx == 18432
    assert config.lanes["gemma4_26b"].num_ctx == 12288
    assert config.lanes["gemma4_26b"].num_ctx >= 12288


def test_model_settings_yaml_contents() -> None:
    text = build_model_settings_yaml(model="gemma4-26b", num_predict=2048, num_ctx=12288)
    assert "num_predict: 2048" in text
    assert "num_ctx: 12288" in text


# --- (N1) harness only for coding --------------------------------------------


def test_plan_batch_log_summary_has_null_harness(tmp_path: Path) -> None:
    from local_model_router.__main__ import main

    job_path = tmp_path / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "job_id": "log-1",
                "task_type": "ci_log_summary",
                "file_count": 0,
                "token_estimate": 100,
                "log_kind": "ci",
                "tokens_sent": 100,
                "tokens_processed": 100,
                "source_text": "ok 100",
                "summary_text": "ok 100",
            }
        ),
        encoding="utf-8",
    )
    healthy = lambda: MemorySnapshot(40.0, False, False, True, "not_loaded")
    # Capture stdout
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(
            [
                "plan-batch",
                "--approved-run-id",
                "cos-yes-log",
                "--job-json",
                str(job_path),
                "--config",
                str(Path(__file__).resolve().parents[1] / "config" / "router_config.json"),
                "--state-dir",
                str(tmp_path / "state"),
            ],
            memory_reader=healthy,
        )
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert payload["harness"] is None


# --- (N2) every escalation requires Fable ------------------------------------


def test_log_summary_with_multi_file_feature_escalates_with_fable(
    config: RouterConfig,
) -> None:
    decision = route_job(
        make_job(
            task_type="log_summary",
            multi_file_feature=True,
            tokens_sent=10,
            tokens_processed=10,
            source_text="10",
            summary_text="10",
        ),
        config,
        dry_run=True,
        memory_reader=lambda: MemorySnapshot(40.0, False, False, True, "not_loaded"),
    )
    assert decision.lane == "cursor_cloud_agent"
    assert decision.escalate is True
    assert decision.fable_review_required is True
    assert decision.plan_steps[-1] == FABLE_STEP


# --- extras: CLI injects memory reader ---------------------------------------


def test_plan_batch_cli_uses_injected_memory_reader(tmp_path: Path) -> None:
    from local_model_router.__main__ import main

    job_path = tmp_path / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "job_id": "inj",
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
            "cos-yes-inj",
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


def test_gitignore_covers_state_dir() -> None:
    text = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8")
    assert "state/" in text
