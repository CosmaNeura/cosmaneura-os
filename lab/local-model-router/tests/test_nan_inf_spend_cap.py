"""NaN/inf must fail closed on every Azure spend-cap path (never disable the cap)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from local_model_router.approval import ApprovalError, record_azure_spend, require_approval
from local_model_router.config import RouterConfig
from local_model_router.models import RouteDecision


def _azure_decision() -> RouteDecision:
    return RouteDecision(
        job_id="x",
        lane="azure_codex_mini",
        reason="escalate",
        batch_kind="azure",
        vendor="azure",
    )


def _finite_spend_ledger(tmp_path: Path, amount: float = 10.0) -> Path:
    spend = tmp_path / "spend.json"
    record_azure_spend(spend, amount)
    return spend


# --- (a) job cost estimate ----------------------------------------------------


def test_a_non_finite_run_estimate_blocks_azure_batch(
    config: RouterConfig, tmp_path: Path
) -> None:
    spend = _finite_spend_ledger(tmp_path)
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ApprovalError, match="finite"):
            require_approval(
                f"cos-yes-est-{bad}",
                batch_kind="azure",
                decision=_azure_decision(),
                config=config,
                ledger_path=tmp_path / f"ledger-est-{bad}.json",
                spend_ledger_path=spend,
                azure_run_estimate_usd=bad,
            )


# --- (b) job spend ------------------------------------------------------------


def test_b_non_finite_job_spend_blocks_azure_batch(
    config: RouterConfig, tmp_path: Path
) -> None:
    spend = _finite_spend_ledger(tmp_path)
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ApprovalError, match="finite"):
            require_approval(
                f"cos-yes-jobspend-{bad}",
                batch_kind="azure",
                decision=_azure_decision(),
                config=config,
                ledger_path=tmp_path / f"ledger-job-{bad}.json",
                spend_ledger_path=spend,
                azure_month_spend_usd=bad,
                azure_run_estimate_usd=5.0,
            )


# --- (c) ledger spend read + record_azure_spend -------------------------------


def test_c_non_finite_ledger_spend_blocks_read_and_record(
    config: RouterConfig, tmp_path: Path
) -> None:
    month_key = datetime.now(UTC).strftime("%Y-%m")
    for bad in (float("nan"), float("inf"), float("-inf")):
        spend = tmp_path / f"spend-ledger-{bad}.json"
        # Python json allows NaN/Infinity literals; write them explicitly.
        spend.write_text(
            json.dumps({"months": {month_key: bad}}, allow_nan=True) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ApprovalError, match="finite"):
            require_approval(
                f"cos-yes-ledger-{bad}",
                batch_kind="azure",
                decision=_azure_decision(),
                config=config,
                ledger_path=tmp_path / f"ledger-read-{bad}.json",
                spend_ledger_path=spend,
                azure_run_estimate_usd=5.0,
            )
        with pytest.raises(ApprovalError, match="finite"):
            record_azure_spend(tmp_path / f"record-amount-{bad}.json", bad)
        # Existing non-finite month total must also block append.
        with pytest.raises(ApprovalError, match="finite"):
            record_azure_spend(spend, 1.0)


# --- (d) CLI --amount-usd -----------------------------------------------------


def test_d_cli_amount_usd_rejects_nan_and_inf(tmp_path: Path) -> None:
    from local_model_router.__main__ import main

    config = str(
        Path(__file__).resolve().parents[1] / "config" / "router_config.json"
    )
    # Use --amount-usd=VALUE so argparse does not treat leading '-' as a flag.
    for token in ("nan", "NaN", "inf", "Infinity", "-inf", "-Infinity"):
        state = tmp_path / f"state-{token.replace('-', 'neg')}"
        code = main(
            [
                "record-azure-spend",
                f"--amount-usd={token}",
                "--state-dir",
                str(state),
                "--config",
                config,
            ]
        )
        assert code == 2
        spend_file = state / "azure_spend.json"
        assert not spend_file.exists()
