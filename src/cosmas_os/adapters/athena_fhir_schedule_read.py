"""athena Preview today's schedule from Certified FHIR Encounter reads (C9).

Replaces the missing Core ``/embed/v1/athena/appointments/read`` dependency with
Encounter search on practice 195900. Never calls FHIR Appointment and never
requests an Appointment scope. Sandbox / mock transport only; C14 stays on.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from cosmas_os.adapters.athena_fhir_r4 import (
    ATHENA_PRACTICE_VALUE,
    ATHENA_PREVIEW_PRACTICE_ID,
    FORBIDDEN_FHIR_RESOURCES,
    AthenaFhirR4Adapter,
    AthenaFhirR4Error,
)
from cosmas_os.application.ehr_fhir_us_core_mapping import map_encounter_to_schedule
from cosmas_os.ports.athena_schedule import (
    PAGE_SIZE,
    AthenaAppointment,
    AthenaScheduleAccount,
    AthenaScheduleRequest,
    AthenaScheduleResponse,
)
from cosmas_os.ports.core_encounters import ConnectionSnapshot, digest

logger = logging.getLogger(__name__)

# Stable synthetic Preview schedule account. Public practice identity only — no PHI.
PREVIEW_ACCOUNT_REF = UUID("01959000-1959-4000-8000-000000195900")
PREVIEW_DEPARTMENT_LABEL = "athena Preview 195900"
PREVIEW_DEPARTMENT_TIMEZONE = "America/New_York"


class AthenaFhirScheduleError(Exception):
    """Closed schedule failures; messages never carry tokens or secrets."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"AthenaFhirScheduleError(code={self.code!r})"


def preview_schedule_account() -> AthenaScheduleAccount:
    """Deterministic Preview account echoed by connection and appointment reads."""
    label = PREVIEW_DEPARTMENT_LABEL
    zone = PREVIEW_DEPARTMENT_TIMEZONE
    account_sha256 = digest(
        {
            "contract": "athena-fhir-preview-schedule-account.v1",
            "practice_id": ATHENA_PREVIEW_PRACTICE_ID,
            "ah_practice": ATHENA_PRACTICE_VALUE,
            "department_label": label,
            "department_timezone": zone,
            "environment": "preview",
            "account_ref": str(PREVIEW_ACCOUNT_REF),
        }
    )
    return AthenaScheduleAccount(
        account_ref=PREVIEW_ACCOUNT_REF,
        account_sha256=account_sha256,
        department_label=label,
        department_timezone=zone,
        environment="preview",
    )


def _map_adapter_error(exc: AthenaFhirR4Error) -> AthenaFhirScheduleError:
    if exc.code in {
        "sandbox_flag_required",
        "real_data_required",
        "resource_unsupported",
        "action_refused",
        "practice_override_refused",
        "off_origin_refused",
        "synthetic_transport_required",
        "not_configured",
        "auth_unavailable",
        "unsupported_scope",
        "invalid_request",
        "unknown_ehr_origin",
        "invalid_ehr_origin",
        "invalid_ehr_gate_flags",
        "scope_wildcard_refused",
    }:
        return AthenaFhirScheduleError(exc.code)
    return AthenaFhirScheduleError("transport_unconfirmed")


def _require_ready(result: Any) -> tuple[dict[str, Any], ...]:
    if getattr(result, "ok", False) is not True or getattr(result, "state", None) != "ready":
        state = getattr(result, "state", None)
        if state in {"timeout", "not_connected"}:
            raise AthenaFhirScheduleError("transport_unconfirmed")
        if state == "throttled":
            raise AthenaFhirScheduleError("provider_throttled")
        if state in {"expired", "wrong_practice"}:
            raise AthenaFhirScheduleError("access_denied")
        if state == "empty":
            return ()
        raise AthenaFhirScheduleError("provider_rejected")
    resources = getattr(result, "resources", ())
    if type(resources) is not tuple:
        raise AthenaFhirScheduleError("response_invalid")
    return resources


def _date_bound(day: date, *, end: bool) -> str:
    if end:
        instant = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=UTC)
    else:
        instant = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return instant.strftime("%Y-%m-%dT%H:%M:%SZ")


def _appointment_row(
    mapped,
    *,
    account: AthenaScheduleAccount,
) -> AthenaAppointment:
    content = {
        "appointment_ref": mapped.appointment_ref,
        "patient_ref": mapped.patient_ref,
        "source_local_start": mapped.source_local_start.isoformat(timespec="seconds"),
        "department_timezone": account.department_timezone,
        "duration_minutes": mapped.duration_minutes,
        "source_status": mapped.source_status,
    }
    return AthenaAppointment(
        appointment_ref=mapped.appointment_ref,
        patient_ref=mapped.patient_ref,
        source_local_start=mapped.source_local_start,
        department_timezone=account.department_timezone,
        duration_minutes=mapped.duration_minutes,
        source_status=mapped.source_status,
        source_sha256=digest({"account_sha256": account.account_sha256, **content}),
    )


def read_athena_fhir_schedule(
    adapter: AthenaFhirR4Adapter,
    request: AthenaScheduleRequest,
    *,
    connection: ConnectionSnapshot,
    account: AthenaScheduleAccount | None = None,
    now: datetime | None = None,
) -> AthenaScheduleResponse:
    """Build an ``AthenaScheduleResponse`` from Encounter search (never Appointment)."""
    if type(adapter) is not AthenaFhirR4Adapter:
        raise AthenaFhirScheduleError("not_configured")
    if type(request) is not AthenaScheduleRequest:
        raise AthenaFhirScheduleError("invalid_request")
    if type(connection) is not ConnectionSnapshot:
        raise AthenaFhirScheduleError("invalid_request")
    if connection.connection_sha256 != request.connection_sha256:
        raise AthenaFhirScheduleError("connection_changed")
    if connection.tenant_ref != request.expected_tenant_ref:
        raise AthenaFhirScheduleError("connection_changed")
    if connection.actor_ref != request.expected_actor_ref:
        raise AthenaFhirScheduleError("connection_changed")
    checked_at = now if now is not None else datetime.now(UTC)
    if checked_at.tzinfo is None:
        raise AthenaFhirScheduleError("invalid_request")
    schedule_account = account if account is not None else preview_schedule_account()
    if type(schedule_account) is not AthenaScheduleAccount:
        raise AthenaFhirScheduleError("invalid_request")

    if request.action == "connection":
        # Connection readiness does not mint a token or call FHIR.
        logger.info(
            "athena_fhir_schedule_connection",
            extra={
                "vendor": "athena",
                "resource_type": "Encounter",
                "practice_id": ATHENA_PREVIEW_PRACTICE_ID,
                "outcome": "ready",
                "result_count": 0,
            },
        )
        return AthenaScheduleResponse(
            action="connection",
            request_nonce=request.request_nonce,
            checked_at=checked_at,
            connection=connection,
            account=schedule_account,
        )

    if request.account_sha256 != schedule_account.account_sha256:
        raise AthenaFhirScheduleError("account_changed")
    if request.start_date is None or request.end_date is None:
        raise AthenaFhirScheduleError("invalid_request")
    # Hard rule: Appointment stays forbidden (C15 parked; C9 = Encounter only).
    if "Appointment" not in FORBIDDEN_FHIR_RESOURCES:
        raise AthenaFhirScheduleError("resource_unsupported")
    try:
        adapter.assert_resource_allowed("Appointment")
    except AthenaFhirR4Error as exc:
        if exc.code != "resource_unsupported":
            raise _map_adapter_error(exc) from None
    else:
        raise AthenaFhirScheduleError("resource_unsupported")

    params = {
        "date": f"ge{_date_bound(request.start_date, end=False)}",
        "_count": str(PAGE_SIZE),
    }
    # Second date bound as a separate FHIR search parameter name is not supported
    # by the shared client map (duplicate keys). Apply the inclusive end locally
    # after the practice-scoped Encounter search.
    try:
        result = adapter.search("Encounter", params, follow_paging=True)
        resources = _require_ready(result)
    except AthenaFhirR4Error as exc:
        raise _map_adapter_error(exc) from None

    rows: list[AthenaAppointment] = []
    for resource in resources:
        if type(resource) is not dict or resource.get("resourceType") != "Encounter":
            continue
        if resource.get("status") == "entered-in-error":
            continue
        try:
            mapped = map_encounter_to_schedule(
                resource,
                vendor="athena",
                read_time=checked_at,
                department_timezone=schedule_account.department_timezone,
            )
        except ValueError:
            continue
        local_day = mapped.source_local_start.date()
        if not request.start_date <= local_day <= request.end_date:
            continue
        rows.append(_appointment_row(mapped, account=schedule_account))

    rows.sort(key=lambda row: (row.source_local_start, row.appointment_ref))
    seen: set[str] = set()
    unique: list[AthenaAppointment] = []
    for row in rows:
        if row.appointment_ref in seen:
            continue
        seen.add(row.appointment_ref)
        unique.append(row)

    total = len(unique)
    offset = request.offset
    page = tuple(unique[offset : offset + PAGE_SIZE])
    after = offset + len(page)
    fhir_more = bool(getattr(result, "more_available", False))
    if after < total:
        next_offset: int | None = after if after <= 10_000 else None
        truncated = next_offset is None
        complete = False
    elif fhir_more:
        next_offset = None
        truncated = True
        complete = False
    else:
        next_offset = None
        truncated = False
        complete = True

    logger.info(
        "athena_fhir_schedule_search",
        extra={
            "vendor": "athena",
            "resource_type": "Encounter",
            "practice_id": ATHENA_PREVIEW_PRACTICE_ID,
            "outcome": "ready",
            "result_count": len(page),
            "total_count": total,
            "truncated": truncated,
            "window_days": (request.end_date - request.start_date).days + 1,
        },
    )
    return AthenaScheduleResponse(
        action="appointments",
        request_nonce=request.request_nonce,
        checked_at=checked_at,
        connection=connection,
        account=schedule_account,
        appointments=page,
        total_count=total,
        next_offset=next_offset,
        complete=complete,
        truncated=truncated,
    )


def assert_no_appointment_calls(urls: list[str]) -> None:
    """Test helper: fail if any URL path targeted FHIR Appointment."""
    for url in urls:
        if "/Appointment" in url:
            raise AssertionError("fhir_appointment_call_refused")
