"""Bounded read-only client for the existing Scheduling staff availability API.

This client acquires no identity and reads no credentials/settings. The local
qualification explicitly injects it; the default application factory is closed. The supplied per-selection credential provider must use a
separately qualified Scheduling staff identity. A Clerk session, workload token,
Google Calendar access token or OS principal ID is not interchangeable with it.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from pydantic import AwareDatetime, SecretStr

from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling import (
    MAX_AVAILABILITY_SLOTS,
    AvailabilitySlot,
    AvailabilityWindow,
    GoogleCalendarCoverage,
    GoogleSchedulingAvailability,
    SchedulingAvailability,
    SchedulingSelection,
)
from cosmas_os.ports.scribe_capture import ProtectedModel

MAX_AVAILABILITY_BYTES = 1_048_576


class _VerifiedReceipt(ProtectedModel):
    contract_version: Literal["1"]
    request_nonce: UUID
    practice_id: UUID
    actor_id: UUID
    practitioner_id: UUID
    location_id: UUID
    appointment_type_id: UUID
    range_start: AwareDatetime
    range_end: AwareDatetime
    google: GoogleCalendarCoverage
    slots: list[dict]


class HttpSchedulingAvailability:
    def __init__(
        self,
        origin: str,
        staff_credential: Callable[[SchedulingSelection], SecretStr],
        *,
        transport: httpx.BaseTransport | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        try:
            parsed = urlsplit(origin)
            valid = (
                parsed.scheme == "https" and bool(parsed.hostname)
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and parsed.path in ("", "/", "/api") and not parsed.query and not parsed.fragment
                and origin.isascii() and not any(c.isspace() or ord(c) < 32 for c in origin)
            )
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise ValueError("Scheduling requires a configured HTTPS origin")
        self._origin = origin.rstrip("/")
        self._staff_credential = staff_credential
        self._now = now
        self._client = httpx.Client(
            transport=transport, timeout=10, follow_redirects=False, trust_env=False,
        )

    def close(self) -> None:
        self._client.close()

    def availability(
        self, selection: SchedulingSelection, window: AvailabilityWindow,
    ) -> SchedulingAvailability:
        result = self._availability(selection, window, verified=False)
        assert isinstance(result, SchedulingAvailability)
        return result

    def verified_availability(self, selection: SchedulingSelection, window: AvailabilityWindow) -> GoogleSchedulingAvailability:
        result = self._availability(selection, window, verified=True)
        assert isinstance(result, GoogleSchedulingAvailability)
        return result

    def _availability(self, selection: SchedulingSelection, window: AvailabilityWindow, *, verified: bool) -> SchedulingAvailability | GoogleSchedulingAvailability:
        try:
            if not isinstance(selection, SchedulingSelection) or not isinstance(window, AvailabilityWindow):
                raise ValueError
            selection = SchedulingSelection.model_validate(selection.model_dump(warnings=False))
            window = AvailabilityWindow.model_validate(window.model_dump(warnings=False))
            if verified and selection.expected_actor_id is None:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ConnectorUnavailable("scheduling_scope_invalid") from None
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
            "GET",
            self._origin + f"/v1/practitioners/{selection.practitioner_id}/availability" + ("/verified" if verified else ""),
            params={
                "from": window.starts_at.isoformat(), "to": window.ends_at.isoformat(),
                "appointmentTypeId": str(selection.appointment_type_id),
                "locationId": str(selection.location_id),
                **({"requestNonce": str(nonce)} if verified else {}),
            },
            headers={
                "Authorization": "Bearer " + token,
                "X-Practice-ID": str(selection.practice_id),
                "Accept": "application/json", "Accept-Encoding": "identity",
                "Cache-Control": "no-store",
            },
        )
        # A response cookie must never become ambient authority for another
        # owner/practice using this client. Each request uses only its fresh token.
        request.headers.pop("Cookie", None)
        try:
            response = self._client.send(request, stream=True, follow_redirects=False)
            try:
                if response.status_code in {401, 403, 404, 410}:
                    raise ConnectorUnavailable("scheduling_access_unavailable")
                if response.status_code != 200:
                    raise ConnectorUnavailable("scheduling_availability_unavailable")
                if (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"
                    or "no-store" not in {d.strip().lower() for d in response.headers.get("cache-control", "").split(",")}
                    or response.headers.get("content-encoding", "identity").strip().lower() != "identity"
                ):
                    raise ConnectorUnavailable("scheduling_receipt_invalid")
                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > MAX_AVAILABILITY_BYTES:
                        raise ConnectorUnavailable("scheduling_receipt_invalid")
                    data.extend(chunk)
                payload = json.loads(data)
                receipt = _VerifiedReceipt.model_validate(payload) if verified else None
                if receipt is not None:
                    payload = receipt.slots
                if not isinstance(payload, list) or len(payload) > MAX_AVAILABILITY_SLOTS:
                    raise ValueError
                if not all(
                    isinstance(slot, dict) and isinstance(slot.get("starts_at"), str)
                    and isinstance(slot.get("ends_at"), str) for slot in payload
                ):
                    raise ValueError
                slots = tuple(AvailabilitySlot.model_validate(slot) for slot in payload)
            finally:
                response.close()
            try:
                observed_at = self._now()
                if not isinstance(observed_at, datetime) or observed_at.tzinfo is None or observed_at.utcoffset() is None:
                    raise ValueError
            except Exception:
                raise ConnectorUnavailable("scheduling_clock_unavailable") from None
            if receipt is not None:
                if (receipt.request_nonce != nonce or receipt.practice_id != selection.practice_id
                    or receipt.actor_id != selection.expected_actor_id
                    or receipt.practitioner_id != selection.practitioner_id
                    or receipt.location_id != selection.location_id
                    or receipt.appointment_type_id != selection.appointment_type_id
                    or receipt.range_start != window.starts_at or receipt.range_end != window.ends_at
                    or not observed_at - timedelta(seconds=30) <= receipt.google.checked_at <= observed_at + timedelta(seconds=5)):
                    raise ConnectorUnavailable("scheduling_scope_conflict")
                return GoogleSchedulingAvailability(selection=selection, window=window, slots=slots,
                                                     observed_at=observed_at, google=receipt.google)
            return SchedulingAvailability(
                selection=selection, window=window, slots=slots, observed_at=observed_at,
            )
        except ConnectorUnavailable:
            raise
        except httpx.HTTPError:
            raise ConnectorUnavailable("scheduling_request_unconfirmed") from None
        except (ValueError, TypeError, AttributeError, RecursionError):
            raise ConnectorUnavailable("scheduling_receipt_invalid") from None
