from __future__ import annotations

import pytest

from cosmas_os.domain.enums import (
    AutomationClass,
    CapabilityKey,
    PrincipalType,
    TicketState,
    assert_ticket_transition,
)
from cosmas_os.domain.rules import (
    AuthorizationError,
    PolicyDenied,
    enforce_automation_send,
    enforce_capability,
    require_human_approver,
    resolve_policy,
)


def test_legal_transitions():
    assert_ticket_transition(TicketState.DRAFT, TicketState.PENDING_APPROVAL)
    assert_ticket_transition(TicketState.PENDING_APPROVAL, TicketState.APPROVED)
    assert_ticket_transition(TicketState.CONFIRMED, TicketState.CLOSED)


def test_illegal_transition():
    with pytest.raises(ValueError):
        assert_ticket_transition(TicketState.CLOSED, TicketState.APPROVED)


def test_agent_cannot_approve():
    with pytest.raises(AuthorizationError):
        require_human_approver(PrincipalType.AGENT)


def test_deny_wins():
    assert (
        resolve_policy(
            platform_allows=True,
            charter_allows=True,
            specialty_allows=True,
            org_allows=True,
        )
        is True
    )
    assert (
        resolve_policy(
            platform_allows=True,
            charter_allows=True,
            specialty_allows=False,
            org_allows=True,
        )
        is False
    )


def test_auto_draft_cannot_send():
    with pytest.raises(PolicyDenied):
        enforce_automation_send(AutomationClass.AUTO_DRAFT)


def test_dark_capability():
    with pytest.raises(PolicyDenied):
        enforce_capability(set(), CapabilityKey.ATHENA)
