"""Per-run approval gate. Recorded string from CoS after John's yes — not a secret."""

from __future__ import annotations

from dataclasses import dataclass


class ApprovalError(ValueError):
    """Raised when a local or Azure batch is started without an approval token."""


@dataclass(frozen=True)
class ApprovalRecord:
    approved_run_id: str
    batch_kind: str  # "local" | "azure"


def require_approval(approved_run_id: str | None, *, batch_kind: str) -> ApprovalRecord:
    if batch_kind not in {"local", "azure"}:
        raise ApprovalError(f"Unknown batch_kind {batch_kind!r}.")
    if approved_run_id is None or not str(approved_run_id).strip():
        raise ApprovalError(
            "Refusing to start a local or Azure batch without --approved-run-id "
            "(recorded CoS token after John's yes; not a secret)."
        )
    token = str(approved_run_id).strip()
    if token.lower() in {"none", "null", "undefined", "-"}:
        raise ApprovalError("Refusing placeholder approval token.")
    return ApprovalRecord(approved_run_id=token, batch_kind=batch_kind)
