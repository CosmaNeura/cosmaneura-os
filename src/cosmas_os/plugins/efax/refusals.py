"""Closed refusal errors for the eFax / fax connector scaffold."""

from __future__ import annotations

PRODUCTION_TARGET_MESSAGE = (
    "CosmaBot can only use the synthetic fax sandbox right now."
)
HOSTED_TARGET_MESSAGE = (
    "Fax connectors stay off for scaffold send and non-sandbox read in hosted workspaces."
)
SEND_REFUSED_MESSAGE = (
    "CosmaBot cannot send faxes through this scaffold; no live fax send is active."
)
READ_REFUSED_MESSAGE = "That fax sandbox read isn't allowed."
SANDBOX_FLAG_MESSAGE = (
    "The synthetic fax sandbox scaffold is not enabled for this workspace."
)


class EFaxCapabilityError(ValueError):
    """Base error for fax scaffold failures. Safe to show ``code`` only."""

    def __init__(self, code: str):
        if type(code) is not str or not code or len(code) > 64:
            raise ValueError("refusal_code_required")
        self.code = code
        super().__init__(code)


class EFaxSendRefused(EFaxCapabilityError):
    """Raised when any fax send action is requested through this scaffold."""

    def __init__(self, action: str = "send", message: str | None = None):
        self.action = action
        self.message = SEND_REFUSED_MESSAGE if message is None else message
        super().__init__("efax_send_refused")


class EFaxTargetRefused(EFaxCapabilityError):
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
                message = "That fax target is not allowed."
        self.message = message
        super().__init__("efax_target_refused")


class EFaxReadRefused(EFaxCapabilityError):
    """Raised when a fax sandbox read is not allowed."""

    def __init__(self, code: str = "efax_read_refused", message: str | None = None):
        if message is None:
            message = (
                SANDBOX_FLAG_MESSAGE
                if code == "efax_sandbox_flag_required"
                else READ_REFUSED_MESSAGE
            )
        self.message = message
        super().__init__(code)
