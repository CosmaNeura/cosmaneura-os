"""Athena reads through the already pinned Core service and fresh human session."""

import json
from datetime import timedelta
from zoneinfo import ZoneInfoNotFoundError

from cosmas_os.adapters.core_encounters import CoreDiscoveryDenied
from cosmas_os.ports.athena_schedule import AthenaScheduleRequest, AthenaScheduleResponse
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable

PATH = "/embed/v1/athena/appointments/read"


def read_athena(connection, request: AthenaScheduleRequest, bearer) -> AthenaScheduleResponse:
    connection.budget.check()
    token = bearer.get_secret_value()
    if not 1 <= len(token) <= 8192 or not token.isascii() or any(c.isspace() for c in token):
        raise CoreDiscoveryDenied("core_connection_access_denied")
    raw = request.model_dump_json().encode("utf-8")
    if len(raw) > 2048:
        raise ValueError("invalid_athena_request")
    try:
        response = connection.http.request("POST", connection.origin + PATH, headers={
            "Authorization": "Bearer " + token, "X-Cosmaneura-Athena-Version": "1",
            "Content-Type": "application/json", "Accept": "application/json",
        }, content=raw)
        try:
            if response.status_code in (401, 403):
                raise CoreDiscoveryDenied("core_connection_access_denied")
            if (response.status_code != 200
                or response.headers.get_list("x-cosmaneura-athena-version") != ["1"]
                or response.headers.get("content-type", "").split(";", 1)[0] != "application/json"
                or "no-store" not in response.headers.get("cache-control", "").split(",")
                or str(response.request.url) != connection.origin + PATH):
                raise ValueError("invalid_athena_response")
            def pairs(values):
                result = {}
                for key, value in values:
                    if key in result:
                        raise ValueError("duplicate_field")
                    result[key] = value
                return result
            value = json.loads(response.content.decode("utf-8"), object_pairs_hook=pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_number")))
            result = AthenaScheduleResponse.model_validate(value)
            if (result.action != request.action or result.request_nonce != request.request_nonce
                or result.connection.tenant_ref != request.expected_tenant_ref
                or result.connection.actor_ref != request.expected_actor_ref
                or result.connection.connection_sha256 != request.connection_sha256
                or not connection.now()-timedelta(seconds=30) <= result.checked_at <= connection.now()+timedelta(seconds=5)):
                raise ValueError("athena_connection_changed")
            if request.action == "appointments":
                if result.account is None or result.account.account_sha256 != request.account_sha256 or result.total_count is None:
                    raise ValueError("athena_account_changed")
                if request.start_date is None or request.end_date is None or any(not request.start_date <= row.source_local_start.date() <= request.end_date for row in result.appointments):
                    raise ValueError("athena_window_changed")
                after = request.offset + len(result.appointments)
                if (result.appointments and after > result.total_count) or (not result.appointments and request.offset < result.total_count):
                    raise ValueError("athena_page_changed")
                more = after < result.total_count
                expected_next = after if more and after <= 10_000 else None
                if result.next_offset != expected_next or result.complete != (not more) or result.truncated != (more and expected_next is None):
                    raise ValueError("athena_page_changed")
            connection.budget.check()
            return result
        finally:
            response.close()
    except CoreDiscoveryDenied:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, ZoneInfoNotFoundError):
        raise ConnectorUnavailable("core_connection_unavailable") from None
