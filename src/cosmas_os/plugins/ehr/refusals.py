"""Closed refusal errors for the EHR connector contract."""

from __future__ import annotations


class EhrCapabilityError(ValueError):
    """Base error for capability and gate failures. Safe to show ``code`` only."""

    def __init__(self, code: str):
        if type(code) is not str or not code or len(code) > 64:
            raise ValueError("refusal_code_required")
        self.code = code
        super().__init__(code)


class EhrWriteRefused(EhrCapabilityError):
    """Raised when any write / mutation action is requested."""

    def __init__(self, action: str = "write"):
        self.action = action
        super().__init__("ehr_write_refused")


class EhrTargetRefused(EhrCapabilityError):
    """Raised when the target environment is not allowed (fail closed)."""

    def __init__(self, target: str):
        self.target = target
        super().__init__("ehr_target_refused")


class EhrReadRefused(EhrCapabilityError):
    """Raised when a read is not allowed for the declared capabilities or hooks."""

    def __init__(self, code: str = "ehr_read_refused"):
        super().__init__(code)
