"""Bounded signed control-plane admission; no runtime or clinical database import."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain import EnrollmentError

ADMISSION_CONTRACT = "cosmas-enrollment-admission.v1"
ADMISSION_HEADER = "X-Cosmas-Enrollment-Signature"
MAX_AGE_SECONDS = 30


class AdmissionRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    contract_version: Literal["cosmas-enrollment-admission.v1"] = ADMISSION_CONTRACT
    practice_id: str
    box_id: str
    organization_id: str = Field(min_length=5, max_length=255, pattern=r"^org_[A-Za-z0-9]+$")
    issuer: str = Field(min_length=8, max_length=255)
    subject: str = Field(min_length=6, max_length=255)
    purpose: Literal["workspace", "qualification", "worker"]
    nonce: str
    issued_at: int
    token_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    operation_id: str | None = None
    approval_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def retained_worker_scope(self):
        if self.purpose == "worker":
            if not self.operation_id or str(UUID(self.operation_id)) != self.operation_id or not self.approval_sha256:
                raise ValueError("retained human request identity required")
            if self.token_sha256 != hashlib.sha256(b"").hexdigest():
                raise ValueError("workers never carry human tokens")
        elif self.operation_id is not None or self.approval_sha256 is not None:
            raise ValueError("unexpected worker authority")
        return self

    @field_validator("practice_id", "box_id", "nonce")
    @classmethod
    def exact_uuid(cls, value: str) -> str:
        if str(UUID(value)) != value:
            raise ValueError("canonical UUID required")
        return value


def derive_runtime_admission_key(master: str, practice_id: str, box_id: str, organization_id: str) -> str:
    if len(master) < 32:
        raise EnrollmentError("runtime_admission_not_configured", "Runtime admission is not configured.", 503)
    if str(UUID(practice_id)) != practice_id or str(UUID(box_id)) != box_id or not organization_id.startswith("org_"):
        raise ValueError("immutable practice scope required")
    scope = json.dumps([ADMISSION_CONTRACT, practice_id, box_id, organization_id], separators=(",", ":")).encode()
    return hmac.new(master.encode(), b"cosmas-box-admission-key.v1\x00" + scope, hashlib.sha256).hexdigest()


def encode(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def signature(key: str, raw: bytes, *, direction: Literal["request", "response"], nonce: str) -> str:
    return hmac.new(key.encode(), direction.encode() + b"\x00" + nonce.encode() + b"\x00" + raw, hashlib.sha256).hexdigest()


def verify_request(key: str, request: AdmissionRequest, raw: bytes, token: str, supplied: str) -> None:
    if (len(key) < 32 or abs(int(time.time()) - request.issued_at) > MAX_AGE_SECONDS
            or (request.purpose != "worker" and not token) or len(token) > 8192
            or not hmac.compare_digest(request.token_sha256, hashlib.sha256(token.encode()).hexdigest())
            or not hmac.compare_digest(signature(key, raw, direction="request", nonce=request.nonce), supplied)):
        raise EnrollmentError("runtime_admission_signature_invalid", "Runtime admission could not be verified.", 401)


def proof(request: AdmissionRequest) -> dict:
    return {"contract_version": ADMISSION_CONTRACT, "enforced": True,
            "practice_id": request.practice_id, "purpose": request.purpose}
