"""Dormant client for the proposed guarded Scheduling appointment receiver.

Only explicit dependency injection can use it. There is no legacy-write fallback,
ambient activation, identity acquisition, automatic retry or inferred completion.
The receiver must retain its operation journal independently of HTTP retry TTLs.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import httpx
from pydantic import AwareDatetime, SecretStr, field_validator

from cosmas_os.adapters.scheduling import HttpSchedulingAvailability
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling_actions import (
    AppointmentOperation,
    AppointmentResult,
    AppointmentSelection,
    AppointmentSnapshot,
    ObservedAppointment,
)
from cosmas_os.ports.scribe_capture import ProtectedModel

MAX_APPOINTMENT_BYTES = 32_768


class _ReadReceipt(ProtectedModel):
    contract_version: Literal["1"]
    request_nonce: UUID
    practice_id: UUID
    actor_id: UUID
    checked_at: AwareDatetime
    appointment: AppointmentSnapshot

    @field_validator("checked_at", mode="before")
    @classmethod
    def timestamp(cls, value):
        if not isinstance(value, str):
            raise ValueError("Scheduling receipt requires an ISO timestamp")
        result = datetime.fromisoformat(value)
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("Scheduling receipt requires a UTC offset")
        return result.astimezone(UTC)


class _OperationReceipt(_ReadReceipt):
    operation_id: UUID
    request_hash: str
    calendar_state: Literal["pending", "synced", "failed", "disconnected"]


class HttpSchedulingAppointments(HttpSchedulingAvailability):
    """Shares the existing fixed-origin transport and explicit staff provider."""

    def _clock(self) -> datetime:
        try:
            now = self._now()
            if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
                raise ValueError
            return now.astimezone(UTC)
        except Exception:
            raise ConnectorUnavailable("scheduling_clock_unavailable") from None

    def _selection(self, value) -> AppointmentSelection:
        try:
            if not isinstance(value, AppointmentSelection):
                raise ValueError
            return AppointmentSelection.model_validate(value.model_dump(warnings=False))
        except (ValueError, TypeError, AttributeError):
            raise ConnectorUnavailable("scheduling_scope_invalid") from None

    def _operation(self, value) -> AppointmentOperation:
        try:
            if not isinstance(value, AppointmentOperation):
                raise ValueError
            return AppointmentOperation.model_validate(value.model_dump(warnings=False))
        except (ValueError, TypeError, AttributeError):
            raise ConnectorUnavailable("scheduling_approval_changed") from None

    def _exchange(self, selection, method, path, *, payload=None):
        # The read/operation validators run before any credential or network use.
        try:
            credential = self._staff_credential(selection)
            if not isinstance(credential, SecretStr):
                raise ValueError
            token = credential.get_secret_value()
            if not 1 <= len(token) <= 16_384 or not token.isascii() or not token.isprintable() or any(c.isspace() for c in token):
                raise ValueError
        except Exception:
            raise ConnectorUnavailable("scheduling_identity_unavailable") from None
        nonce = uuid4()
        request = self._client.build_request(
            method, self._origin + path, params={"requestNonce": str(nonce)}, json=payload,
            headers={"Authorization": "Bearer " + token, "X-Practice-ID": str(selection.practice_id),
                     "Accept": "application/json", "Accept-Encoding": "identity", "Cache-Control": "no-store",
                     **({"Idempotency-Key": "os-appointment:" + payload["operation_id"]} if payload else {})},
        )
        request.headers.pop("Cookie", None)
        try:
            response = self._client.send(request, stream=True, follow_redirects=False)
            try:
                if response.status_code in {401, 403, 404, 410}:
                    # Includes a missing operation: absence is not proof of no effect.
                    raise ConnectorUnavailable("scheduling_access_or_result_unavailable")
                if response.status_code in {409, 412}:
                    raise ConnectorUnavailable("scheduling_action_conflict")
                if response.status_code != 200:
                    raise ConnectorUnavailable("scheduling_action_unconfirmed")
                if (response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"
                    or "no-store" not in {d.strip().lower() for d in response.headers.get("cache-control", "").split(",")}
                    or response.headers.get("content-encoding", "identity").strip().lower() != "identity"):
                    raise ValueError
                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > MAX_APPOINTMENT_BYTES:
                        raise ValueError
                    data.extend(chunk)
                receipt = (_OperationReceipt if "/appointment-operations" in path else _ReadReceipt).model_validate(json.loads(data))
            finally:
                response.close()
            now = self._clock()
            if (receipt.request_nonce != nonce or receipt.practice_id != selection.practice_id
                or receipt.actor_id != selection.expected_actor_id
                or not now - timedelta(seconds=30) <= receipt.checked_at <= now + timedelta(seconds=5)
                or not receipt.appointment.matches(selection)):
                raise ValueError
            return receipt, now
        except ConnectorUnavailable:
            raise
        except httpx.HTTPError:
            raise ConnectorUnavailable("scheduling_action_unconfirmed") from None
        except (ValueError, TypeError, AttributeError, RecursionError):
            raise ConnectorUnavailable("scheduling_receipt_invalid") from None

    def read_appointment(self, selection: AppointmentSelection, appointment_id: UUID) -> ObservedAppointment:
        selected = self._selection(selection)
        if not isinstance(appointment_id, UUID):
            raise ConnectorUnavailable("scheduling_scope_invalid")
        self._clock()
        receipt, now = self._exchange(selected, "GET", f"/v1/appointments/{appointment_id}/verified")
        if receipt.appointment.id != appointment_id:
            raise ConnectorUnavailable("scheduling_receipt_invalid")
        return ObservedAppointment(selection=selected, appointment=receipt.appointment, observed_at=now)

    def submit(self, operation: AppointmentOperation) -> AppointmentResult:
        checked = self._operation(operation)
        now = self._clock()
        if not now < checked.intent.expires_at <= now + timedelta(minutes=5):
            raise ConnectorUnavailable("scheduling_approval_expired")
        if checked.intent.google and checked.intent.google.checked_at > now + timedelta(seconds=5):
            raise ConnectorUnavailable("scheduling_scope_invalid")
        return self._result(checked, "POST", "/v1/appointment-operations", checked.request_payload())

    def reconcile(self, operation: AppointmentOperation) -> AppointmentResult:
        checked = self._operation(operation)
        self._clock()
        # Even after expiry, read the SAME journal entry. Never recreate a booking
        # from a search result, an expired HTTP key or an unknown response.
        return self._result(checked, "GET", f"/v1/appointment-operations/{checked.operation_id}")

    def _result(self, operation, method, path, payload=None) -> AppointmentResult:
        receipt, now = self._exchange(operation.intent.selection, method, path, payload=payload)
        try:
            assert isinstance(receipt, _OperationReceipt)
            result = AppointmentResult(operation_id=receipt.operation_id, request_hash=receipt.request_hash,
                appointment=receipt.appointment, observed_at=now, calendar_state=receipt.calendar_state)
            result.require_operation(operation)
            return result
        except (ValueError, TypeError, AttributeError):
            raise ConnectorUnavailable("scheduling_receipt_invalid") from None
