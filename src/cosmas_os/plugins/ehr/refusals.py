"""Closed refusal errors for the EHR connector contract."""

from __future__ import annotations

PRODUCTION_TARGET_MESSAGE = "CosmaBot can only connect to sandbox EHRs right now."
WRITE_REFUSED_MESSAGE = "CosmaBot can only read from EHRs; it can't change records."
RESOURCE_UNSUPPORTED_MESSAGE = (
    "That EHR resource isn't available for this connection."
)
PRACTICE_SCOPE_REQUIRED_MESSAGE = (
    "A practice must be selected before this EHR read."
)
PRACTICE_SCOPE_REFUSED_MESSAGE = (
    "That practice isn't allowed for this EHR read."
)
READ_REFUSED_MESSAGE = "That EHR read isn't allowed."

_READ_REFUSED_MESSAGES = {
    "ehr_resource_unsupported": RESOURCE_UNSUPPORTED_MESSAGE,
    "ehr_practice_scope_required": PRACTICE_SCOPE_REQUIRED_MESSAGE,
    "ehr_practice_scope_refused": PRACTICE_SCOPE_REFUSED_MESSAGE,
    "ehr_read_refused": READ_REFUSED_MESSAGE,
}


class EhrCapabilityError(ValueError):
    """Base error for capability and gate failures. Safe to show ``code`` only."""

    def __init__(self, code: str):
        if type(code) is not str or not code or len(code) > 64:
            raise ValueError("refusal_code_required")
        self.code = code
        super().__init__(code)


class EhrWriteRefused(EhrCapabilityError):
    """Raised when any write / mutation action is requested."""

    def __init__(self, action: str = "write", message: str | None = None):
        self.action = action
        self.message = WRITE_REFUSED_MESSAGE if message is None else message
        super().__init__("ehr_write_refused")


class EhrTargetRefused(EhrCapabilityError):
    """Raised when the target environment is not allowed (fail closed)."""

    def __init__(self, target: str, message: str | None = None):
        self.target = target
        if message is None:
            if target == "production":
                message = PRODUCTION_TARGET_MESSAGE
            else:
                message = "That EHR target is not allowed."
        self.message = message
        super().__init__("ehr_target_refused")


class EhrReadRefused(EhrCapabilityError):
    """Raised when a read is not allowed for the declared capabilities or hooks."""

    def __init__(self, code: str = "ehr_read_refused", message: str | None = None):
        if message is None:
            message = _READ_REFUSED_MESSAGES.get(code, READ_REFUSED_MESSAGE)
        self.message = message
        super().__init__(code)
