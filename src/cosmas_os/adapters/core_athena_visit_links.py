"""Reviewed Athena visit links at the pinned Core origin; never retry a write."""

import json
from datetime import timedelta

from cosmas_os.adapters.core_appointment_setup import CoreSetupChanged
from cosmas_os.adapters.core_encounters import CoreDiscoveryDenied
from cosmas_os.ports.athena_schedule import AthenaScheduleResponse
from cosmas_os.ports.athena_visit_links import (
    MAX_RESPONSE_BYTES,
    AthenaVisitLinkRequest,
    AthenaVisitLinkResponse,
    command_digest,
)
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable

PATH = "/embed/v1/athena/visit-links"


def athena_visit_link(
    connection, request: AthenaVisitLinkRequest, bearer
) -> AthenaVisitLinkResponse:
    connection.budget.check()
    token = bearer.get_secret_value()
    if not 1 <= len(token) <= 8192 or not token.isascii() or any(c.isspace() for c in token):
        raise CoreDiscoveryDenied("core_connection_access_denied")
    raw = request.model_dump_json().encode("utf-8")
    if len(raw) > 2048:
        raise ValueError("invalid_appointment_setup_request")
    try:
        response = connection.http.request(
            "POST",
            connection.origin + PATH,
            headers={
                "Authorization": "Bearer " + token,
                "X-Cosmaneura-Athena-Link-Version": "1",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            content=raw,
        )
        try:
            if response.status_code in (401, 403):
                raise CoreDiscoveryDenied("core_connection_access_denied")
            if response.status_code == 409:
                raise CoreSetupChanged("core_connection_changed")
            if (
                response.status_code != 200
                or response.headers.get_list("x-cosmaneura-athena-link-version") != ["1"]
                or response.headers.get("content-type", "").split(";", 1)[0] != "application/json"
                or "no-store" not in response.headers.get("cache-control", "").split(",")
                or str(response.request.url) != connection.origin + PATH
                or len(response.content) > MAX_RESPONSE_BYTES
            ):
                raise ValueError("invalid_appointment_setup_response")

            def pairs(values):
                result = {}
                for key, value in values:
                    if key in result:
                        raise ValueError("duplicate_field")
                    result[key] = value
                return result

            value = json.loads(
                response.content.decode("utf-8"),
                object_pairs_hook=pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_number")),
            )
            result = AthenaVisitLinkResponse.model_validate(value)
            if (
                result.action != request.action
                or result.request_nonce != request.request_nonce
                or result.connection.tenant_ref != request.expected_tenant_ref
                or result.connection.actor_ref != request.expected_actor_ref
                or result.connection.connection_sha256 != request.connection_sha256
                or result.account.account_sha256 != request.account_sha256
                or not connection.now() - timedelta(seconds=30)
                <= result.checked_at
                <= connection.now() + timedelta(seconds=5)
            ):
                raise ValueError("appointment_setup_changed")
            validate_reply(result, request)
            connection.budget.check()
            return result
        finally:
            response.close()
    except (CoreDiscoveryDenied, CoreSetupChanged):
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ConnectorUnavailable("core_connection_unavailable") from None


def validate_reply(result, request):
    def require(condition):
        if not condition:
            raise ValueError("athena_visit_link_response_changed")

    require(result.command_key == request.command_key)
    # Reuse the existing account/timezone/source-digest checks, without a vendor call.
    AthenaScheduleResponse(
        action="appointments" if result.source else "connection",
        request_nonce=result.request_nonce,
        checked_at=result.checked_at,
        connection=result.connection,
        account=result.account,
        appointments=(result.source,) if result.source else (),
        total_count=1 if result.source else None,
    )
    if result.encounter is not None:
        require(result.encounter.connection_sha256 == request.connection_sha256)
    if result.source is not None:
        require(
            request.source is not None
            and result.source.appointment_ref == request.source.appointment_ref
            and result.source.source_sha256 == request.source.source_sha256
            and request.source.start_date
            <= result.source.source_local_start.date()
            <= request.source.end_date
        )
    if request.action in {"link", "unlink", "status"}:
        expected = request.command_sha256 if request.action == "status" else command_digest(request)
        require(result.command_sha256 == expected)
        if result.applied:
            require(
                result.link_ref is not None
                and result.operation in {"link", "unlink"}
                and result.state in {"linked", "removed", "review_required"}
            )
            if request.action != "status":
                require(result.operation == request.action)
        else:
            require(
                request.action == "status"
                and result.state == "not_found"
                and result.operation is None
                and result.link_ref is None
                and result.encounter is None
            )
        if request.action == "unlink":
            require(result.state == "removed" and result.link_ref == request.link_ref)
    else:
        require(not result.applied)
        if request.action == "lookup":
            require(
                result.state in {"linked", "not_linked", "review_required"}
                and result.source is not None
                and result.plan_sha256 is None
                and result.command_sha256 is None
                and result.operation is None
            )
        elif result.state in {"ready", "removed"}:
            require(result.plan_sha256 is not None)
            action = "link" if request.action == "preview" else "unlink"
            planned = request.model_copy(
                update={"action": action, "plan_sha256": result.plan_sha256, "confirmed": True}
            )
            require(result.command_sha256 == command_digest(planned) and result.operation == action)
            if action == "link":
                require(
                    result.source is not None
                    and result.encounter is not None
                    and result.encounter.appointment.appointment_ref == request.appointment_ref
                    and result.encounter.source_sha256 == request.core_source_sha256
                )
            else:
                require(result.link_ref == request.link_ref)
        else:
            require(
                request.action == "preview"
                and result.state == "review_required"
                and result.plan_sha256 is None
                and result.command_sha256 is None
            )
    if result.state == "linked":
        require(result.link_ref is not None and result.encounter is not None)
