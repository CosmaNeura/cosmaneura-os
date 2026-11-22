"""Per-run approval gate with single-use ledger and Azure monthly cap."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import RouterConfig
from .models import RouteDecision
from .router_types import batch_kind_for_lane


class ApprovalError(ValueError):
    """Raised when a local or Azure batch is started without a valid approval."""


def require_finite_usd(value: float, *, label: str) -> float:
    """Fail closed on NaN/inf (and non-numeric). Cap comparisons with NaN are false."""
    try:
        amount = float(value)
    except (TypeError, ValueError) as exc:
        raise ApprovalError(f"{label} must be a finite USD amount.") from exc
    if not math.isfinite(amount):
        raise ApprovalError(f"{label} must be a finite USD amount (got non-finite).")
    return amount


@dataclass(frozen=True)
class ApprovalRecord:
    approved_run_id: str
    batch_kind: str  # local | azure | cloud


def derive_batch_kind(decision: RouteDecision) -> str:
    """Batch kind is derived from the routing decision, not the CLI default."""
    if decision.escalate and decision.escalation_target:
        return batch_kind_for_lane(decision.escalation_target)
    if decision.lane == "aborted":
        return decision.batch_kind
    return batch_kind_for_lane(decision.lane)


def require_approval(
    approved_run_id: str | None,
    *,
    batch_kind: str,
    decision: RouteDecision | None = None,
    config: RouterConfig | None = None,
    ledger_path: Path | None = None,
    spend_ledger_path: Path | None = None,
    azure_month_spend_usd: float | None = None,
    azure_run_estimate_usd: float | None = None,
) -> ApprovalRecord:
    """Validate approval. Consumes the ID only after every check passes."""
    if batch_kind not in {"local", "azure", "cloud"}:
        raise ApprovalError(f"Unknown batch_kind {batch_kind!r}.")
    if decision is not None:
        expected = decision.batch_kind
        if expected == "none":
            raise ApprovalError("Refusing batch for unrouted decision.")
        if expected != batch_kind:
            raise ApprovalError(
                f"Batch kind mismatch: CLI={batch_kind!r} decision={expected!r}."
            )
    if approved_run_id is None or not str(approved_run_id).strip():
        raise ApprovalError(
            "Refusing to start a local or Azure batch without --approved-run-id "
            "(recorded CoS token after John's yes; not a secret)."
        )
    token = str(approved_run_id).strip()
    if token.lower() in {"none", "null", "undefined", "-"}:
        raise ApprovalError("Refusing placeholder approval token.")

    if batch_kind == "azure":
        if config is None:
            raise ApprovalError("Azure batch requires router config.")
        if spend_ledger_path is None:
            raise ApprovalError("Azure spend ledger required (fail closed).")
        if not spend_ledger_path.exists():
            raise ApprovalError("Azure spend ledger file missing (fail closed).")
        try:
            ledger_spend = _read_month_spend(spend_ledger_path)
        except ApprovalError:
            raise
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            raise ApprovalError(f"Azure spend ledger unreadable: {exc}") from exc

        if azure_month_spend_usd is not None:
            job_spend = require_finite_usd(
                azure_month_spend_usd, label="Azure month spend"
            )
            if job_spend < 0:
                raise ApprovalError("Azure month spend must not be negative.")
        else:
            job_spend = 0.0
        if azure_run_estimate_usd is None:
            raise ApprovalError("azure_run_estimate_usd required and must be > 0.")
        estimate = require_finite_usd(
            azure_run_estimate_usd, label="azure_run_estimate_usd"
        )
        if estimate <= 0:
            raise ApprovalError("azure_run_estimate_usd required and must be > 0.")

        effective = max(ledger_spend, job_spend)
        cap = require_finite_usd(config.azure_monthly_cap_usd, label="Azure monthly cap")
        if effective >= cap or effective + estimate >= cap:
            raise ApprovalError(
                f"Azure monthly cap ${cap:.0f} would be exceeded "
                f"(spend=${effective:.2f} + estimate=${estimate:.2f})."
            )

    # Consume only after all checks pass.
    if ledger_path is not None:
        _consume_approval_id(token, ledger_path)

    return ApprovalRecord(approved_run_id=token, batch_kind=batch_kind)


def _consume_approval_id(token: str, ledger_path: Path) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    used: list[str] = []
    if ledger_path.exists():
        raw = json.loads(ledger_path.read_text(encoding="utf-8"))
        used = list(raw.get("used_ids", []))
    if token in used:
        raise ApprovalError(f"Approval id already used: {token}")
    used.append(token)
    ledger_path.write_text(
        json.dumps({"used_ids": used}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_month_spend(path: Path) -> float:
    """Read current-month spend. Missing/unreadable/negative/non-finite => fail closed."""
    if not path.exists():
        raise ApprovalError("Azure spend ledger file missing (fail closed).")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        month_key = datetime.now(UTC).strftime("%Y-%m")
        spend = float(raw.get("months", {}).get(month_key, 0.0))
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ApprovalError(f"Azure spend ledger unreadable: {exc}") from exc
    spend = require_finite_usd(spend, label="Azure spend ledger month total")
    if spend < 0:
        raise ApprovalError("Azure spend ledger has negative spend (fail closed).")
    return spend


def record_azure_spend(path: Path, amount_usd: float) -> float:
    """Append synthetic Azure spend for the current UTC month. Returns new total."""
    amount = require_finite_usd(amount_usd, label="Azure spend amount")
    if amount < 0:
        raise ApprovalError("Azure spend amount must not be negative.")
    path.parent.mkdir(parents=True, exist_ok=True)
    months: dict[str, float] = {}
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        for key, value in raw.get("months", {}).items():
            months[str(key)] = require_finite_usd(
                float(value), label=f"Azure spend ledger month {key}"
            )
    month_key = datetime.now(UTC).strftime("%Y-%m")
    new_total = months.get(month_key, 0.0) + amount
    months[month_key] = require_finite_usd(
        new_total, label="Azure spend ledger month total"
    )
    path.write_text(
        json.dumps({"months": months}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return months[month_key]
