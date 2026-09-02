from __future__ import annotations

from cosmas_os.domain.enums import (
    AutomationClass,
    CapabilityKey,
    PrincipalType,
    TicketState,
    assert_ticket_transition,
)


class DomainError(Exception):
    """Domain rule violation."""


class AuthorizationError(DomainError):
    pass


class PolicyDenied(DomainError):
    pass


def require_human_approver(principal_type: PrincipalType) -> None:
    if principal_type != PrincipalType.HUMAN:
        raise AuthorizationError("agents cannot approve, sign, or self-approve")


def resolve_policy(
    *,
    platform_allows: bool,
    charter_allows: bool,
    specialty_allows: bool,
    org_allows: bool,
) -> bool:
    """Deny wins: any False denies."""
    return platform_allows and charter_allows and specialty_allows and org_allows


def enforce_automation_send(automation_class: AutomationClass) -> None:
    if automation_class == AutomationClass.AUTO_DRAFT:
        raise PolicyDenied("AUTO_DRAFT cannot leave the staff surface")
    if automation_class == AutomationClass.AUTO_TEMPLATE:
        raise PolicyDenied("AUTO_TEMPLATE standing sends are dark in L0")
    if automation_class == AutomationClass.NEVER_AUTO:
        raise PolicyDenied("NEVER_AUTO cannot send")


def enforce_capability(enabled: set[str], key: CapabilityKey) -> None:
    if key.value not in enabled:
        raise PolicyDenied(f"dark capability rejected: {key.value}")


def transition_ticket(current: TicketState, target: TicketState) -> TicketState:
    assert_ticket_transition(current, target)
    return target
