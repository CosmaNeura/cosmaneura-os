"""Per-run approval gate with single-use ledger and Azure monthly cap."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import RouterConfig
from .models import RouteDecision
from .router_types import batch_kind_for_lane


class ApprovalError(ValueError):
    """Raised when a local or Azure batch is started without a valid approval."""


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
) -> ApprovalRecord:
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

    if ledger_path is not None:
        _consume_approval_id(token, ledger_path)

    if batch_kind == "azure" and config is not None:
        spend = azure_month_spend_usd if azure_month_spend_usd is not None else 0.0
        if spend_ledger_path is not None:
            spend = _read_month_spend(spend_ledger_path)
        if spend >= config.azure_monthly_cap_usd:
            raise ApprovalError(
                f"Azure monthly cap ${config.azure_monthly_cap_usd:.0f} reached "
                f"(spend=${spend:.2f})."
            )

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
    if not path.exists():
        return 0.0
    raw = json.loads(path.read_text(encoding="utf-8"))
    month_key = datetime.now(UTC).strftime("%Y-%m")
    return float(raw.get("months", {}).get(month_key, 0.0))


def record_azure_spend(path: Path, amount_usd: float) -> float:
    """Append synthetic Azure spend for the current UTC month. Returns new total."""
    path.parent.mkdir(parents=True, exist_ok=True)
    months: dict[str, float] = {}
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        months = {k: float(v) for k, v in raw.get("months", {}).items()}
    month_key = datetime.now(UTC).strftime("%Y-%m")
    months[month_key] = months.get(month_key, 0.0) + float(amount_usd)
    path.write_text(
        json.dumps({"months": months}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return months[month_key]
