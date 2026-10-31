"""Exact-origin runtime admission. No clinical state is sent to enrollment."""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Literal
from uuid import uuid4

import httpx

from cosmas_os.config import Settings
from cosmas_os.enrollment.admission import (
    ADMISSION_HEADER,
    MAX_AGE_SECONDS,
    AdmissionRequest,
    encode,
    proof,
    signature,
)

ACCESS_REQUIRED = "workspace_enrollment_access_required"
ADMISSION_UNAVAILABLE = "workspace_enrollment_admission_unavailable"
PUBLIC_ADMISSION_HEADER = "X-Cosmas-Enrollment-Admission"


class RuntimeAdmissionError(Exception):
    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.code, self.status = code, status


class EnrollmentAdmissionAdapter:
    def __init__(self, runtime: Settings, *, client: httpx.Client | None = None):
        self.runtime, self.client = runtime, client

    def authorize(self, token: str, subject: str, *, purpose: Literal["workspace", "qualification", "worker"] = "workspace",
                  operation_id: str | None = None, approval_sha256: str | None = None) -> dict:
        runtime = self.runtime
        if (not getattr(runtime, "workspace_enrollment_managed", False) or not isinstance(runtime, Settings)
                or runtime.workspace_enrollment_configuration_errors()):
            raise RuntimeAdmissionError(ADMISSION_UNAVAILABLE, 503)
        secret = runtime.workspace_enrollment_admission_secret
        assert secret
        key = secret.get_secret_value()
        try:
            request = AdmissionRequest(practice_id=runtime.workspace_enrollment_practice_id,
                box_id=runtime.beta_box_id or "", organization_id=runtime.clerk_organization_id or "",
                issuer=runtime.clerk_issuer or "", subject=subject, purpose=purpose, nonce=str(uuid4()),
                issued_at=int(time.time()), token_sha256=hashlib.sha256(token.encode()).hexdigest(),
                operation_id=operation_id, approval_sha256=approval_sha256)
        except (ValueError, TypeError):
            raise RuntimeAdmissionError(ADMISSION_UNAVAILABLE, 503) from None
        raw = encode(request.model_dump())
        headers = {"Authorization": "Cosmas-Worker" if purpose == "worker" else "Bearer " + token, "Content-Type": "application/json",
                   "X-Cosmas-Enrollment-Contract": "enrollment.v1",
                   ADMISSION_HEADER: signature(key, raw, direction="request", nonce=request.nonce)}
        owned = self.client is None
        client = self.client or httpx.Client(timeout=httpx.Timeout(10, connect=3), follow_redirects=False)
        try:
            response = client.post(runtime.workspace_enrollment_api_origin + "/enrollment/v1/runtime/admission", content=raw, headers=headers)
            response.raise_for_status()
            if (len(response.content) > 4096 or response.headers.get("cache-control") != "no-store"
                    or response.headers.get("content-type", "").split(";", 1)[0] != "application/json"
                    or not hmac.compare_digest(signature(key, response.content, direction="response", nonce=request.nonce),
                                               response.headers.get(ADMISSION_HEADER, ""))):
                raise ValueError("unverified admission")
            value = response.json()
            expected = request.model_dump(exclude={"issued_at", "token_sha256"})
            now = int(time.time())
            if (not isinstance(value, dict) or set(value) != set(expected) | {
                    "request_issued_at", "request_sha256", "decision", "reason", "issued_at", "expires_at", "member_role", "display_name"}
                    or any(value.get(k) != v for k, v in expected.items())
                    or value.get("request_issued_at") != request.issued_at
                    or value.get("request_sha256") != hashlib.sha256(raw).hexdigest()
                    or type(value.get("issued_at")) is not int or type(value.get("expires_at")) is not int
                    or not request.issued_at - 5 <= value["issued_at"] <= now + 5
                    or not now < value["expires_at"] <= value["issued_at"] + MAX_AGE_SECONDS
                    or value.get("decision") not in {"allow", "deny"}
                    or value.get("reason") not in {"membership_required", "agreement_required", "seat_registry_invalid",
                        "workspace_not_ready", "billing_required", "entitled", "setup_qualified", "identity_required"}):
                raise ValueError("stale or mismatched admission")
            if value["decision"] != "allow":
                raise RuntimeAdmissionError(ACCESS_REQUIRED, 403)
            if value["reason"] != ("setup_qualified" if purpose == "qualification" else "entitled"):
                raise ValueError("wrong admission purpose")
            if (value["member_role"] not in {"owner", "admin", "staff"} or not isinstance(value["display_name"], str)
                    or not 2 <= len(value["display_name"]) <= 120 or value["display_name"] != value["display_name"].strip()
                    or any(ord(c) < 32 or ord(c) == 127 for c in value["display_name"])):
                raise ValueError("invalid registered human")
            return {**proof(request), "member_role": value["member_role"], "display_name": value["display_name"]}
        except RuntimeAdmissionError:
            raise
        except Exception:
            raise RuntimeAdmissionError(ADMISSION_UNAVAILABLE, 503) from None
        finally:
            if owned:
                client.close()


def require_runtime_admission(runtime: Settings, authorization: str | None, subject: str, *,
                              purpose: Literal["workspace", "qualification"] = "workspace",
                              adapter: EnrollmentAdmissionAdapter | None = None) -> dict | None:
    if not getattr(runtime, "workspace_enrollment_managed", False):
        return None
    if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 8200:
        raise RuntimeAdmissionError(ACCESS_REQUIRED, 403)
    return (adapter or EnrollmentAdmissionAdapter(runtime)).authorize(authorization[7:], subject, purpose=purpose)
