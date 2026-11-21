"""CTO diff-confirm fixes: per-model Aider settings + Azure spend fail-closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from local_model_router.approval import ApprovalError, record_azure_spend, require_approval
from local_model_router.config import RouterConfig
from local_model_router.harness import build_harness_plan
from local_model_router.models import RouteDecision


def _azure_decision() -> RouteDecision:
    return RouteDecision(
        job_id="x",
        lane="azure_codex_mini",
        reason="escalate",
        batch_kind="azure",
        vendor="azure",
    )


# --- (A) per-model settings: planning one lane must not clobber another --------


def test_planning_inkling_then_26b_keeps_separate_caps(
    config: RouterConfig, tmp_path: Path
) -> None:
    inkling = config.lanes["inkling_2_mini"]
    plan_i = build_harness_plan(
        config,
        model=inkling.model,
        message="fix",
        files=["a.py"],
        lane=inkling,
        model_settings_dir=tmp_path,
    )
    lane_26 = config.lanes["gemma4_26b"]
    plan_26 = build_harness_plan(
        config,
        model=lane_26.model,
        message="lint",
        files=["b.py"],
        lane=lane_26,
        model_settings_dir=tmp_path,
    )
    assert plan_i.model_settings_path is not None
    assert plan_26.model_settings_path is not None
    assert plan_i.model_settings_path != plan_26.model_settings_path
    assert plan_i.model_settings_path in plan_i.aider_attempt
    assert plan_26.model_settings_path in plan_26.aider_attempt

    inkling_text = Path(plan_i.model_settings_path).read_text(encoding="utf-8")
    text_26 = Path(plan_26.model_settings_path).read_text(encoding="utf-8")
    assert "num_predict: 8192" in inkling_text
    assert "num_ctx: 18432" in inkling_text
    assert "num_predict: 2048" in text_26
    assert "num_ctx: 12288" in text_26
    # Inkling file still intact after 26B plan.
    assert "num_ctx: 18432" in Path(plan_i.model_settings_path).read_text(encoding="utf-8")


# --- (B) Azure spend: missing file / estimate / exact 200 / negatives ----------


def test_azure_refuses_missing_spend_ledger_file(config: RouterConfig, tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.json"
    assert not missing.exists()
    with pytest.raises(ApprovalError, match="missing"):
        require_approval(
            "cos-yes-missing-file",
            batch_kind="azure",
            decision=_azure_decision(),
            config=config,
            ledger_path=tmp_path / "ledger.json",
            spend_ledger_path=missing,
            azure_run_estimate_usd=5.0,
        )


def test_azure_refuses_missing_run_estimate(config: RouterConfig, tmp_path: Path) -> None:
    spend = tmp_path / "spend.json"
    record_azure_spend(spend, 10.0)
    with pytest.raises(ApprovalError, match="azure_run_estimate_usd"):
        require_approval(
            "cos-yes-no-est",
            batch_kind="azure",
            decision=_azure_decision(),
            config=config,
            ledger_path=tmp_path / "ledger.json",
            spend_ledger_path=spend,
            azure_run_estimate_usd=None,
        )


def test_azure_refuses_spend_exactly_200(config: RouterConfig, tmp_path: Path) -> None:
    spend = tmp_path / "spend.json"
    record_azure_spend(spend, 200.0)
    with pytest.raises(ApprovalError, match="exceeded"):
        require_approval(
            "cos-yes-exact-200",
            batch_kind="azure",
            decision=_azure_decision(),
            config=config,
            ledger_path=tmp_path / "ledger.json",
            spend_ledger_path=spend,
            azure_run_estimate_usd=1.0,
        )


def test_azure_refuses_negative_amount_and_estimate(
    config: RouterConfig, tmp_path: Path
) -> None:
    spend = tmp_path / "spend.json"
    with pytest.raises(ApprovalError, match="negative"):
        record_azure_spend(spend, -1.0)
    record_azure_spend(spend, 10.0)
    with pytest.raises(ApprovalError, match="azure_run_estimate_usd|> 0|negative"):
        require_approval(
            "cos-yes-neg-est",
            batch_kind="azure",
            decision=_azure_decision(),
            config=config,
            ledger_path=tmp_path / "ledger.json",
            spend_ledger_path=spend,
            azure_run_estimate_usd=-5.0,
        )
    with pytest.raises(ApprovalError, match="negative"):
        require_approval(
            "cos-yes-neg-spend",
            batch_kind="azure",
            decision=_azure_decision(),
            config=config,
            ledger_path=tmp_path / "ledger2.json",
            spend_ledger_path=spend,
            azure_month_spend_usd=-1.0,
            azure_run_estimate_usd=5.0,
        )


def test_azure_unreadable_ledger_blocks(config: RouterConfig, tmp_path: Path) -> None:
    spend = tmp_path / "spend.json"
    spend.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ApprovalError, match="unreadable"):
        require_approval(
            "cos-yes-bad-json",
            batch_kind="azure",
            decision=_azure_decision(),
            config=config,
            ledger_path=tmp_path / "ledger.json",
            spend_ledger_path=spend,
            azure_run_estimate_usd=5.0,
        )


def test_azure_refuses_spend_plus_estimate_at_cap(
    config: RouterConfig, tmp_path: Path
) -> None:
    spend = tmp_path / "spend.json"
    record_azure_spend(spend, 190.0)
    with pytest.raises(ApprovalError, match="exceeded"):
        require_approval(
            "cos-yes-at-cap",
            batch_kind="azure",
            decision=_azure_decision(),
            config=config,
            ledger_path=tmp_path / "ledger.json",
            spend_ledger_path=spend,
            azure_run_estimate_usd=10.0,  # 190 + 10 == 200
        )


def test_record_azure_spend_cli_rejects_negative(tmp_path: Path) -> None:
    from local_model_router.__main__ import main

    code = main(
        [
            "record-azure-spend",
            "--amount-usd",
            "-3.0",
            "--state-dir",
            str(tmp_path / "state"),
            "--config",
            str(Path(__file__).resolve().parents[1] / "config" / "router_config.json"),
        ]
    )
    assert code == 2
