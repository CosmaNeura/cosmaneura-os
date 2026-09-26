"""Scribe/Core source-start receipt checks at the OS consumer boundary.

Reused from the W97 Core gateway. Core remains the authority for the configured
session and its consent record; OS additionally binds the native reply to its
current workspace actor, selected session, exact owner proof and lease.
"""

import hashlib
import hmac
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import BaseModel

from cosmas_os.ports.capture_native_start import (
    NativeSourceStart,
    NativeStartDecision,
    NativeStartReceipt,
    NativeUnstartedRetirement,
)


def validate_native_start(
    operation: NativeSourceStart,
    result: dict,
    session_id: UUID,
    creator_actor_id: str,
    now: datetime,
) -> BaseModel:
    try:
        if (
            operation.action == "stop"
            and result.get("state") == "unstarted"
        ):
            checked = NativeUnstartedRetirement.model_validate(
                result
            )
            receipt = checked
            if receipt.retired_at > now or not hmac.compare_digest(
                receipt.owner_proof_sha256,
                hashlib.sha256(
                    operation.payload.owner_proof.encode("ascii")
                ).hexdigest(),
            ):
                raise ValueError
        elif operation.action == "authorize":
            checked = NativeStartDecision.model_validate(result)
            receipt = checked.receipt
            if not hmac.compare_digest(checked.secret, operation.payload.owner_proof):
                raise ValueError
            if (
                receipt.state != "issued"
                or receipt.issued_at is None
                or receipt.expires_at is None
                or receipt.issued_at > now
                or receipt.expires_at <= now
                or receipt.expires_at <= receipt.issued_at
                or receipt.expires_at > receipt.issued_at + timedelta(seconds=15)
                or receipt.issued_at >= receipt.preparation_expires_at
                or receipt.expires_at > receipt.capture_authorized_until
            ):
                raise ValueError
        else:
            checked = NativeStartReceipt.model_validate(result)
            receipt = checked
            if operation.action == "prepare" and (
                receipt.state != "prepared"
                or receipt.preparation_expires_at <= now
                or receipt.preparation_expires_at > receipt.capture_authorized_until
                or receipt.issued_at is not None
                or receipt.expires_at is not None
            ):
                raise ValueError
            if operation.action == "cancel" and receipt.state != "cancelled":
                raise ValueError
            if operation.action == "stop" and receipt.state not in {
                "stopped",
                "cancelled",
                "expired",
            }:
                raise ValueError
        expected = operation.payload
        if (
            receipt.session_id != session_id
            or receipt.creator_actor_id != creator_actor_id
            or receipt.attempt_id != expected.attempt_id
            or receipt.source != expected.source
            or receipt.lease_id != expected.lease_id
            or receipt.lease_receipt_id != expected.lease_receipt_id
            or receipt.lease_generation != expected.lease_generation
            or receipt.first_sequence_number != expected.first_sequence_number
            or receipt.capture_authorized_until != expected.capture_authorized_until
            or (operation.action != "stop" and receipt.capture_authorized_until <= now)
        ):
            raise ValueError
        if isinstance(receipt, NativeUnstartedRetirement):
            return checked
        if receipt.preparation_expires_at > receipt.capture_authorized_until or (
            receipt.state not in {"issued", "stopped"}
            and (receipt.issued_at is not None or receipt.expires_at is not None)
        ):
            raise ValueError
        if receipt.state == "stopped" and (
            receipt.issued_at is None
            or receipt.expires_at is None
            or receipt.issued_at > now
            or receipt.expires_at <= receipt.issued_at
            or receipt.expires_at > receipt.issued_at + timedelta(seconds=15)
            or receipt.issued_at >= receipt.preparation_expires_at
            or receipt.expires_at > receipt.capture_authorized_until
        ):
            raise ValueError
        return checked
    except (ValueError, TypeError, AttributeError):
        raise ValueError("invalid_native_start_receipt") from None
