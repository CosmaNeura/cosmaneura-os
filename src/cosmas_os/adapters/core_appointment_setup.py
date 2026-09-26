"""Reviewed appointment setup at the pinned Core origin; never retry a write."""

import json
from datetime import timedelta

from cosmas_os.adapters.core_encounters import CoreDiscoveryDenied
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_appointment_setup import (
    MAX_RESPONSE_BYTES,
    AppointmentSetupRequest,
    AppointmentSetupResponse,
)

PATH = "/embed/v1/companion/appointments/connect"


class CoreSetupChanged(ConnectorUnavailable):
    pass


def setup_appointments(connection, request: AppointmentSetupRequest, bearer) -> AppointmentSetupResponse:
    connection.budget.check()
    token = bearer.get_secret_value()
    if not 1 <= len(token) <= 8192 or not token.isascii() or any(c.isspace() for c in token):
        raise CoreDiscoveryDenied("core_connection_access_denied")
    raw = request.model_dump_json().encode("utf-8")
    if len(raw) > 2048:
        raise ValueError("invalid_appointment_setup_request")
    try:
        response = connection.http.request("POST", connection.origin + PATH, headers={
            "Authorization": "Bearer " + token, "X-Cosmaneura-Appointment-Setup-Version": "1",
            "Content-Type": "application/json", "Accept": "application/json",
        }, content=raw)
        try:
            if response.status_code in (401, 403):
                raise CoreDiscoveryDenied("core_connection_access_denied")
            if response.status_code == 409:
                raise CoreSetupChanged("core_connection_changed")
            if (response.status_code != 200
                or response.headers.get_list("x-cosmaneura-appointment-setup-version") != ["1"]
                or response.headers.get("content-type", "").split(";", 1)[0] != "application/json"
                or "no-store" not in response.headers.get("cache-control", "").split(",")
                or str(response.request.url) != connection.origin + PATH
                or len(response.content) > MAX_RESPONSE_BYTES):
                raise ValueError("invalid_appointment_setup_response")

            def pairs(values):
                result = {}
                for key, value in values:
                    if key in result:
                        raise ValueError("duplicate_field")
                    result[key] = value
                return result

            value = json.loads(response.content.decode("utf-8"), object_pairs_hook=pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_number")))
            result = AppointmentSetupResponse.model_validate(value)
            if (result.action != request.action or result.request_nonce != request.request_nonce
                or result.connection.tenant_ref != request.expected_tenant_ref
                or result.connection.actor_ref != request.expected_actor_ref
                or result.connection.connection_sha256 != request.connection_sha256
                or result.window != request.window
                or request.action == "connect" and result.plan_sha256 != request.plan_sha256
                or not connection.now()-timedelta(seconds=30) <= result.checked_at <= connection.now()+timedelta(seconds=5)):
                raise ValueError("appointment_setup_changed")
            if request.cursor is not None and result.next_cursor is not None and (
                result.next_cursor.appointment_date, result.next_cursor.appointment_ref
            ) <= (request.cursor.appointment_date, request.cursor.appointment_ref):
                raise ValueError("appointment_setup_page_changed")
            connection.budget.check()
            return result
        finally:
            response.close()
    except (CoreDiscoveryDenied, CoreSetupChanged):
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ConnectorUnavailable("core_connection_unavailable") from None
