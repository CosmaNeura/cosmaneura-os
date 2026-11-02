"""Plain EHR read error states shared with CosmaBot connector plugins.

State names and message templates match the Athena / Elation / Tebra plugin
tools, plus ehr_fhir-lane additions for rate limits and write refusal. Callers
pass a display label (for example ``Athena`` or ``EHR``) so the shared FHIR
client stays vendor-neutral while users still see familiar wording.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

ErrorState = Literal[
    "not_connected",
    "expired",
    "wrong_practice",
    "malformed",
    "timeout",
    "stale",
    "rate_limited",
    "refused",
]

READY: Final = "ready"
ERROR_STATES: Final[frozenset[str]] = frozenset(
    {
        "not_connected",
        "expired",
        "wrong_practice",
        "malformed",
        "timeout",
        "stale",
        "rate_limited",
        "refused",
    }
)

# OperationOutcome.issue.code values that map to a closed user-facing state.
_EXPIRED_CODES = frozenset({"login", "expired", "unknown"})
_WRONG_PRACTICE_CODES = frozenset({"multiple-matches"})
_NOT_CONNECTED_CODES = frozenset({"not-found", "not-supported", "informational"})
_MALFORMED_CODES = frozenset(
    {
        "invalid",
        "structure",
        "required",
        "value",
        "invariant",
        "duplicate",
        "too-long",
        "code-invalid",
        "extension",
        "too-costly",
        "business-rule",
        "conflict",
        "incomplete",
        "processing",
    }
)
_TIMEOUT_CODES = frozenset({"timeout", "transient"})
_STALE_CODES = frozenset({"deleted", "superseded"})
_SECURITY_CODES = frozenset({"security", "forbidden"})

# HTTP statuses with an explicit plain-state mapping. These win over any
# OperationOutcome issue code in the response body.
_HTTP_STATUS_STATES: Final[dict[int, ErrorState]] = {
    401: "expired",
    403: "expired",
    404: "not_connected",
    408: "timeout",
    409: "stale",
    412: "stale",
    421: "wrong_practice",
    400: "malformed",
    422: "malformed",
    429: "rate_limited",
    504: "timeout",
    524: "timeout",
    0: "timeout",
}


def messages_for(label: str) -> dict[str, str]:
    """Return the plain messages users already see, with a display label filled in."""
    if type(label) is not str or not 1 <= len(label) <= 64 or any(ord(c) < 32 for c in label):
        raise ValueError("display_label_required")
    return {
        "not_connected": (
            f"{label} is not connected. Connect {label} for this practice in CosmaBot, "
            "then try this read again."
        ),
        "wrong_practice": (
            f"That request is for a different practice than the {label} account "
            "connected to this sign-in."
        ),
        "expired": (
            f"{label} access expired or was revoked. Reconnect {label} in CosmaBot "
            "before reading again."
        ),
        "malformed": (
            f"{label} returned a response CosmaBot could not read. No chart data is shown."
        ),
        "timeout": (
            f"The {label} read timed out before a result was confirmed. "
            "Repeat this same request to recover it. A different request is not sent automatically."
        ),
        "stale": (
            f"The {label} account changed while this was being read. The result was discarded. "
            "Check the connected practice and read again."
        ),
        "rate_limited": (
            f"{label} is limiting reads right now. Wait a moment, then try this same read again."
        ),
        "refused": (
            f"This {label} client only reads chart data. Writes are refused and were not sent."
        ),
        "ready_page": (
            f"Showing returned {label} records for this page. This is not a complete chart."
        ),
        "ready_more": (
            f"More {label} records are available; only the returned pages were read."
        ),
        "ready_empty": (
            "No rows were returned on this page. That does not mean the chart is empty."
        ),
        "write_refused": (
            f"This {label} client only reads chart data. Writes are refused and were not sent."
        ),
        "production_refused": (
            f"{label} is not connected. Connect {label} for this practice in CosmaBot, "
            "then try this read again."
        ),
    }


@dataclass(frozen=True, slots=True)
class FhirReadError:
    """Closed result for a refused or failed FHIR read. Never carries provider text."""

    state: ErrorState
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"state": self.state, "message": self.message}


def error_result(state: ErrorState, label: str) -> FhirReadError:
    if state not in ERROR_STATES:
        raise ValueError("unknown_error_state")
    return FhirReadError(state, messages_for(label)[state])


def map_http_status(status: int, label: str, *, outcome_code: str | None = None) -> FhirReadError:
    """Map HTTP status and an optional OperationOutcome issue code to a plain state.

    An explicit HTTP status mapping always wins over a body error code. Body
    codes are consulted only when the status has no dedicated mapping.
    """
    mapped_state = _HTTP_STATUS_STATES.get(status)
    if mapped_state is not None:
        return error_result(mapped_state, label)
    if outcome_code is not None:
        mapped = map_operation_outcome_code(outcome_code, label)
        if mapped is not None:
            return mapped
    return error_result("malformed", label)


def map_operation_outcome_code(code: str, label: str) -> FhirReadError | None:
    if type(code) is not str:
        return error_result("malformed", label)
    if code in _SECURITY_CODES or code in _EXPIRED_CODES:
        return error_result("expired", label)
    if code in _WRONG_PRACTICE_CODES:
        return error_result("wrong_practice", label)
    if code in _NOT_CONNECTED_CODES:
        return error_result("not_connected", label)
    if code in _TIMEOUT_CODES:
        return error_result("timeout", label)
    if code in _STALE_CODES:
        return error_result("stale", label)
    if code in _MALFORMED_CODES:
        return error_result("malformed", label)
    return None


def map_operation_outcome(payload: dict[str, Any], label: str) -> FhirReadError | None:
    """Return a plain error when an OperationOutcome carries a blocking issue."""
    if payload.get("resourceType") != "OperationOutcome":
        return None
    issues = payload.get("issue")
    if type(issues) is not list or not issues:
        return error_result("malformed", label)
    for issue in issues:
        if type(issue) is not dict:
            return error_result("malformed", label)
        severity = issue.get("severity")
        if severity not in {"fatal", "error", "warning", "information"}:
            return error_result("malformed", label)
        if severity in {"warning", "information"}:
            continue
        code = issue.get("code")
        mapped = map_operation_outcome_code(code if type(code) is str else "", label)
        return mapped if mapped is not None else error_result("malformed", label)
    return None
