"""Injected athena FHIR schedule runtime for Core connection route (C9).

When C8 flags are on, today's schedule uses Encounter FHIR via this port and
never calls Core ``/embed/v1/athena/appointments/read``. Mock transport + vault
secret refs only. Connection identity still comes from the existing Core
companion read (which exists); only the missing appointments route is replaced.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from pydantic import SecretStr

from cosmas_os.adapters.athena_fhir_r4 import AthenaFhirR4Adapter
from cosmas_os.adapters.athena_fhir_schedule_read import (
    AthenaFhirScheduleError,
    preview_schedule_account,
    read_athena_fhir_schedule,
)
from cosmas_os.adapters.core_encounters import CoreDiscoveryDenied
from cosmas_os.adapters.ehr_auth import ClientCredentialsTokenClient
from cosmas_os.application.ehr_export.fallback import note_adapter_failure
from cosmas_os.ports.athena_schedule import AthenaScheduleRequest, AthenaScheduleResponse
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_encounters import ConnectionRequest


class AthenaFhirScheduleReads:
    """Synthetic Preview schedule reader. Refusals run before token mint / FHIR HTTP."""

    def __init__(
        self,
        *,
        token_client: ClientCredentialsTokenClient,
        transport: httpx.MockTransport,
        sandbox_enabled: bool | Callable[[], bool] = False,
        real_data_enabled: bool = False,
        practice_baa_recorded: bool = False,
        enabled: bool | Callable[[], bool] = True,
    ):
        if type(transport) is not httpx.MockTransport:
            raise AthenaFhirScheduleError("synthetic_transport_required")
        if type(token_client) is not ClientCredentialsTokenClient:
            raise AthenaFhirScheduleError("not_configured")
        if type(real_data_enabled) is not bool or type(practice_baa_recorded) is not bool:
            raise AthenaFhirScheduleError("invalid_ehr_gate_flags")
        self._token_client = token_client
        self._transport = transport
        self._sandbox_enabled = sandbox_enabled
        self._real_data_enabled = real_data_enabled
        self._practice_baa_recorded = practice_baa_recorded
        self._enabled = enabled

    def _flag(self, value: bool | Callable[[], bool]) -> bool:
        return bool(value() if callable(value) else value)

    def _adapter(self) -> AthenaFhirR4Adapter:
        return AthenaFhirR4Adapter(
            token_client=self._token_client,
            transport=self._transport,
            sandbox_enabled=self._flag(self._sandbox_enabled),
            real_data_enabled=self._real_data_enabled,
            practice_baa_recorded=self._practice_baa_recorded,
        )

    def read_schedule(
        self,
        core_port,
        request: AthenaScheduleRequest,
        bearer: SecretStr,
        *,
        now: datetime | None = None,
    ) -> AthenaScheduleResponse:
        if not self._flag(self._enabled):
            raise ConnectorUnavailable("core_connection_unavailable")
        if not self._flag(self._sandbox_enabled):
            # Refuse before companion auth reuse or FHIR token mint.
            raise ConnectorUnavailable("core_connection_unavailable")
        if type(request) is not AthenaScheduleRequest:
            raise ConnectorUnavailable("core_connection_unavailable")

        # Reuse the existing Core companion connection snapshot (route exists).
        # Never call /embed/v1/athena/appointments/read.
        discovery = core_port.read(
            ConnectionRequest(
                expected_tenant_ref=request.expected_tenant_ref,
                request_nonce=request.request_nonce,
            ),
            bearer,
        )
        connection = discovery.connection
        if (
            connection.connection_sha256 != request.connection_sha256
            or connection.actor_ref != request.expected_actor_ref
            or connection.tenant_ref != request.expected_tenant_ref
        ):
            raise ConnectorUnavailable("core_connection_unavailable")

        account = preview_schedule_account()
        try:
            if request.action == "connection":
                return read_athena_fhir_schedule(
                    self._adapter(),
                    request,
                    connection=connection,
                    account=account,
                    now=now or datetime.now(UTC),
                )
            return read_athena_fhir_schedule(
                self._adapter(),
                request,
                connection=connection,
                account=account,
                now=now or datetime.now(UTC),
            )
        except AthenaFhirScheduleError as exc:
            if exc.code in {"connection_changed", "account_changed"}:
                note_adapter_failure(None, "athena", kind="disconnect", error_code=exc.code)
            else:
                note_adapter_failure(None, "athena", kind="error", error_code=exc.code)
            if exc.code in {"sandbox_flag_required", "real_data_required", "not_configured",
                            "synthetic_transport_required", "auth_unavailable"}:
                raise ConnectorUnavailable("core_connection_unavailable") from None
            if exc.code in {"connection_changed", "account_changed"}:
                raise ConnectorUnavailable("core_connection_unavailable") from None
            if exc.code == "access_denied":
                raise CoreDiscoveryDenied("core_connection_access_denied") from None
            raise ConnectorUnavailable("core_connection_unavailable") from None
