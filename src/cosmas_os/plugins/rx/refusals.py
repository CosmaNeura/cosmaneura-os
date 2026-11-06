"""Closed refusal errors for the prescription connector scaffold."""

from __future__ import annotations

PRODUCTION_TARGET_MESSAGE = (
    "CosmaBot can only use the synthetic prescription sandbox right now."
)
HOSTED_TARGET_MESSAGE = (
    "Prescription connectors stay off in hosted and production workspaces."
)
SEND_REFUSED_MESSAGE = (
    "CosmaBot cannot send prescriptions; no prescribing connector is active."
)
READ_REFUSED_MESSAGE = "That prescription read isn't allowed."
SANDBOX_FLAG_MESSAGE = (
    "The synthetic prescription sandbox is not enabled for this workspace."
)


class RxCapabilityError(ValueError):
    """Base error for prescription scaffold failures. Safe to show ``code`` only."""

    def __init__(self, code: str):
        if type(code) is not str or not code or len(code) > 64:
            raise ValueError("refusal_code_required")
        self.code = code
        super().__init__(code)


class RxSendRefused(RxCapabilityError):
    """Raised when any prescription send / transmit action is requested."""

    def __init__(self, action: str = "send", message: str | None = None):
        self.action = action
        self.message = SEND_REFUSED_MESSAGE if message is None else message
        super().__init__("rx_send_refused")


class RxTargetRefused(RxCapabilityError):
    """Raised when the target environment is not allowed (fail closed)."""

    def __init__(self, target: str, message: str | None = None):
        self.target = target
        if message is None:
            if target in {"production", "hosted"}:
                message = (
                    HOSTED_TARGET_MESSAGE
                    if target == "hosted"
                    else PRODUCTION_TARGET_MESSAGE
                )
            else:
                message = "That prescription target is not allowed."
        self.message = message
        super().__init__("rx_target_refused")


class RxReadRefused(RxCapabilityError):
    """Raised when a prescription read is not allowed."""

    def __init__(self, code: str = "rx_read_refused", message: str | None = None):
        if message is None:
            message = (
                SANDBOX_FLAG_MESSAGE
                if code == "rx_sandbox_flag_required"
                else READ_REFUSED_MESSAGE
            )
        self.message = message
        super().__init__(code)
