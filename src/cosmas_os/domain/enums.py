from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum


class PrincipalType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"


class PrincipalState(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    TOMBSTONED = "tombstoned"


class TicketState(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    SENT = "sent"
    CONFIRMED = "confirmed"
    CLOSED = "closed"
    FAILED = "failed"


class DecisionKind(StrEnum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"
    ESCALATE = "escalate"


class OperationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class CoverageStatus(StrEnum):
    UNKNOWN = "unknown"
    MISSING = "missing"
    STALE = "stale"
    IMAGE_ON_FILE = "image_on_file"
    VERIFIED = "verified"
    INACTIVE = "inactive"
    NEEDS_HUMAN = "needs_human"


class AutomationClass(StrEnum):
    AUTO_TEMPLATE = "auto_template"
    AUTO_DRAFT = "auto_draft"
    HITL_REQUIRED = "hitl_required"
    NEVER_AUTO = "never_auto"


class CapabilityKey(StrEnum):
    ATHENA = "athena"
    ACUITY = "acuity"
    REAL_EMAIL_SMS = "real_email_sms"
    A2P = "a2p"
    TEAMS = "teams"
    PATIENT_PAYMENT = "patient_payment"
    EVIDENCE = "evidence"
    WORKBOOK = "workbook"
    APPLICATION_LLM = "application_llm"


# Legal F-8 ticket transitions (representative set for L0).
LEGAL_TICKET_TRANSITIONS: dict[TicketState, set[TicketState]] = {
    TicketState.DRAFT: {TicketState.PENDING_APPROVAL},
    TicketState.PENDING_APPROVAL: {
        TicketState.APPROVED,
        TicketState.REJECTED,
        TicketState.ESCALATED,
        TicketState.PENDING_APPROVAL,  # edit keeps pending with new revision
    },
    TicketState.APPROVED: {TicketState.SENT, TicketState.FAILED},
    TicketState.SENT: {TicketState.CONFIRMED, TicketState.FAILED},
    TicketState.CONFIRMED: {TicketState.CLOSED},
    TicketState.REJECTED: {TicketState.CLOSED},
    TicketState.ESCALATED: {TicketState.PENDING_APPROVAL, TicketState.CLOSED},
    TicketState.FAILED: {TicketState.PENDING_APPROVAL, TicketState.CLOSED},
    TicketState.CLOSED: set(),
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def assert_ticket_transition(current: TicketState, target: TicketState) -> None:
    allowed = LEGAL_TICKET_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(f"illegal F-8 transition {current} -> {target}")
