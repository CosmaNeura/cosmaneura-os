"""Explicit synthetic installation bridge; no credential or live transport path."""

import asyncio
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from pydantic import SecretStr

from cosmas_os.adapters.elation_read import (
    ElationCredentials,
    ElationReadAdapter,
    ElationReadError,
    ElationReadScope,
)


class SyntheticElationReads:
    """A host/test installs exact invented scopes and an in-process HTTP fixture.

    This class cannot accept a real HTTP transport, provider credential or
    production scope. It exercises the documented adapter through application
    custody while vendor activation remains a separate unimplemented milestone.
    """

    transport_mode = "mock"

    def timezone_for(self, scope):
        if not self.current(scope):
            raise ElationReadError("connection_changed")
        return self.timezone

    def __init__(self, scopes: tuple[ElationReadScope, ...], transport: httpx.MockTransport, *,
                 enabled: Callable[[], bool], timezone: str = "UTC"):
        if (type(scopes) is not tuple or not 1 <= len(scopes) <= 20
                or any(type(scope) is not ElationReadScope or scope.environment != "sandbox" for scope in scopes)
                or len({scope.commitment() for scope in scopes}) != len(scopes)
                or type(transport) is not httpx.MockTransport or not callable(enabled)):
            raise ValueError("explicit_synthetic_ehr_installation_required")
        self._scopes, self._transport, self._enabled = scopes, transport, enabled
        ZoneInfo(timezone)
        self.timezone = timezone

    def current(self, scope: ElationReadScope) -> bool:
        return self._enabled() is True and scope in self._scopes

    def _adapter(self, scope, authorize):
        async def allowed(selected):
            return self.current(selected) and authorize() is True and self.current(selected)

        async def credentials(selected):
            return ElationCredentials(selected.commitment(), SecretStr("synthetic-elation-client"),
                                      SecretStr("synthetic-elation-secret"))

        return ElationReadAdapter(scope, credentials, enabled=self.current(scope),
            authorize_read=allowed, transport=self._transport)

    def window(self, scope: ElationReadScope, starts_at: datetime, ends_at: datetime, *, authorize):
        async def run():
            async with asyncio.timeout(30):
                adapter = self._adapter(scope, authorize)
                practice = await adapter.practice()
                appointments = await adapter.appointments(starts_at, ends_at)
                return practice, appointments
        return asyncio.run(run())

    def visit(self, scope: ElationReadScope, appointment_id: int, patient_id: int, *, authorize):
        async def run():
            async with asyncio.timeout(30):
                adapter = self._adapter(scope, authorize)
                appointment = await adapter.appointment(appointment_id)
                if getattr(appointment.rows[0], "patient_id", None) != patient_id:
                    raise ElationReadError("record_unavailable")
                patient = await adapter.patient(patient_id)
                return appointment, patient
        return asyncio.run(run())
