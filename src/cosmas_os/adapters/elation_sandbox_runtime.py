"""Explicit managed Elation sandbox reads; production and non-synthetic data stay unavailable."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx

from cosmas_os.adapters.elation_read import (
    ElationCredentials,
    ElationReadAdapter,
    ElationReadError,
    ElationReadScope,
)
from cosmas_os.application.elation_sandbox_quota import ElationSandboxQuotaBudget
from cosmas_os.domain.hashing import payload_hash


@dataclass(frozen=True, repr=False)
class ElationSandboxInstallation:
    id: UUID
    account_id: UUID
    scope: ElationReadScope
    timezone: str
    client_id_sha256: str
    client_secret_sha256: str
    data_classification: str = "synthetic_only"
    problems_enabled: bool = False
    medications_enabled: bool = False

    def __post_init__(self):
        import re
        if (type(self.id) is not UUID or type(self.account_id) is not UUID
                or type(self.scope) is not ElationReadScope or self.scope.environment != "sandbox"
                or any(type(value) is not UUID for value in (self.scope.box_id, self.scope.owner_id,
                    self.scope.connection_id, self.scope.credential_generation))
                or type(self.scope.practice_id) is not int or not 0 < self.scope.practice_id <= 2**63 - 1
                or type(self.scope.practice_name) is not str or not 1 <= len(self.scope.practice_name) <= 200
                or any(ord(c) < 32 or ord(c) == 127 for c in self.scope.practice_name)
                or self.data_classification != "synthetic_only" or type(self.problems_enabled) is not bool
                or type(self.medications_enabled) is not bool
                or any(re.fullmatch(r"[a-f0-9]{64}", value) is None
                    for value in (self.client_id_sha256, self.client_secret_sha256))):
            raise ValueError("exact_synthetic_sandbox_installation_required")
        ZoneInfo(self.timezone)

    def commitment(self):
        return payload_hash(dict(contract="elation-sandbox-installation.v1", id=str(self.id),
            account_id=str(self.account_id), scope_sha256=self.scope.commitment(), timezone=self.timezone,
            client_id_sha256=self.client_id_sha256, client_secret_sha256=self.client_secret_sha256,
            data_classification=self.data_classification,
            **({"clinical_scope": "system/problems.read"} if self.problems_enabled else {}),
            **({"medication_scope": "system/medications.read"} if self.medications_enabled else {})))


class ManagedElationSandboxReads:
    transport_mode = "vendor_sandbox"

    def __init__(self, installations: tuple[ElationSandboxInstallation, ...], *,
                 credentials: Callable[[ElationReadScope], Awaitable[ElationCredentials]],
                 credentials_current: Callable[[ElationReadScope], bool], sessions,
                 enabled: Callable[[], bool], transport_factory=None,
                 problems_enabled: Callable[[], bool] = lambda: False,
                 medications_enabled: Callable[[], bool] = lambda: False):
        if (type(installations) is not tuple or not 1 <= len(installations) <= 20
                or any(type(row) is not ElationSandboxInstallation for row in installations)
                or len({row.id for row in installations}) != len(installations)
                or len({row.scope.commitment() for row in installations}) != len(installations)
                or not all(callable(value) for value in (credentials, credentials_current, sessions, enabled))
                or transport_factory is not None and not callable(transport_factory)
                or not callable(problems_enabled) or not callable(medications_enabled)):
            raise ValueError("explicit_sandbox_runtime_required")
        self.installations = installations
        self._credentials, self._credentials_current = credentials, credentials_current
        self._problems_enabled = problems_enabled
        self._medications_enabled = medications_enabled
        self._enabled, self._transport_factory, self._closed = enabled, transport_factory, False
        self._quota = ElationSandboxQuotaBudget(sessions)

    def available(self):
        return not self._closed and self._enabled() is True

    def candidates(self, box, owner, account):
        return tuple(row for row in self.installations if
            (str(row.scope.box_id), str(row.scope.owner_id), str(row.account_id)) == (box, owner, account))

    def selected(self, scope):
        matches = [row for row in self.installations if row.scope == scope]
        return matches[0] if len(matches) == 1 else None

    def current(self, scope):
        try:
            return self.available() and self.selected(scope) is not None and self._credentials_current(scope) is True
        except Exception:
            return False

    def timezone_for(self, scope):
        selected = self.selected(scope)
        if selected is None:
            raise ElationReadError("connection_changed")
        return selected.timezone

    def close(self):
        self._closed = True

    def problems_available(self, scope):
        selected = self.selected(scope)
        return self.current(scope) and selected is not None and selected.problems_enabled and self._problems_enabled() is True

    def medications_available(self, scope):
        selected = self.selected(scope)
        return self.current(scope) and selected is not None and selected.medications_enabled and self._medications_enabled() is True

    def _adapter(self, scope, authorize, *, problems=False, medications=False):
        selected = self.selected(scope)
        if selected is None or not self.current(scope):
            raise ElationReadError("connection_changed")

        async def allowed(request_scope):
            return (self.current(request_scope) and (not problems or self.problems_available(request_scope))
                and (not medications or self.medications_available(request_scope))
                and authorize() is True and self.current(request_scope)
                and (not problems or self.problems_available(request_scope))
                and (not medications or self.medications_available(request_scope)))

        async def permit(request_scope):
            if request_scope != scope or not self.current(scope):
                raise ElationReadError("access_denied")
            return await self._quota.permit(selected.client_id_sha256)

        transport = self._transport_factory() if self._transport_factory is not None else None
        if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
            raise ElationReadError("not_configured")
        return ElationReadAdapter(scope, self._credentials, enabled=self.current(scope),
            authorize_read=allowed, permit_request=permit, transport=transport, problems_enabled=problems,
            medications_enabled=medications)

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


    def problem_list(self, scope: ElationReadScope, appointment_id: int, patient_id: int, *, authorize, verify_identity):
        async def run():
            async with asyncio.timeout(30):
                if not self.problems_available(scope):
                    raise ElationReadError("disabled")
                adapter = self._adapter(scope, authorize, problems=True)
                appointment = await adapter.appointment(appointment_id)
                if getattr(appointment.rows[0], "patient_id", None) != patient_id:
                    raise ElationReadError("record_unavailable")
                patient = await adapter.patient(patient_id)
                if verify_identity(appointment.rows[0], patient.rows[0]) is not True:
                    raise ElationReadError("record_unavailable")
                result = await adapter.problems(patient_id)
                return appointment, patient, result
        return asyncio.run(run())

    def medication_list(self, scope: ElationReadScope, appointment_id: int, patient_id: int, *, authorize, verify_identity):
        async def run():
            async with asyncio.timeout(30):
                if not self.medications_available(scope):
                    raise ElationReadError("disabled")
                adapter = self._adapter(scope, authorize, medications=True)
                appointment = await adapter.appointment(appointment_id)
                if getattr(appointment.rows[0], "patient_id", None) != patient_id:
                    raise ElationReadError("record_unavailable")
                patient = await adapter.patient(patient_id)
                if verify_identity(appointment.rows[0], patient.rows[0]) is not True:
                    raise ElationReadError("record_unavailable")
                result = await adapter.medications(patient_id)
                return appointment, patient, result
        return asyncio.run(run())
