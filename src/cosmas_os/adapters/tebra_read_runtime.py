"""Explicit, mock-only Tebra installation; never constructs a live transport."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from zoneinfo import ZoneInfo

import httpx
from pydantic import SecretStr

from cosmas_os.adapters.tebra_read import (
    TebraCredentials,
    TebraReadAdapter,
    TebraReadError,
    TebraReadScope,
)
from cosmas_os.domain.hashing import payload_hash


@dataclass(frozen=True, repr=False)
class TebraWorkspaceScope(TebraReadScope):
    timezone: str = "UTC"

    def commitment(self):
        return payload_hash(dict(contract="tebra-read-scope.v1", box_id=str(self.box_id),
            owner_id=str(self.owner_id), connection_id=str(self.connection_id),
            credential_generation=str(self.credential_generation), customer_id=self.customer_id,
            practice_id=self.practice_id, practice_name=self.practice_name, timezone=self.timezone))


class SyntheticTebraReads:
    transport_mode = "mock"

    def __init__(self, scopes: tuple[TebraWorkspaceScope, ...], transport: httpx.MockTransport, *,
                 enabled: Callable[[], bool]):
        if (type(scopes) is not tuple or not 1 <= len(scopes) <= 20
                or any(type(scope) is not TebraWorkspaceScope for scope in scopes)
                or len({scope.commitment() for scope in scopes}) != len(scopes)
                or type(transport) is not httpx.MockTransport or not callable(enabled)):
            raise ValueError("explicit_synthetic_tebra_installation_required")
        for scope in scopes:
            scope.validate()
            if len(scope.practice_name) > 200:
                raise ValueError("bounded_practice_label_required")
            ZoneInfo(scope.timezone)
        self._scopes, self._transport, self._enabled = scopes, transport, enabled

    def current(self, scope):
        return self._enabled() is True and type(scope) is TebraWorkspaceScope and scope in self._scopes

    def timezone_for(self, scope):
        if not self.current(scope):
            raise TebraReadError("scope_changed")
        return scope.timezone

    def _adapter(self, scope, authorize):
        return TebraReadAdapter(enabled=self.current(scope), transport=self._transport,
            authorize_read=lambda selected: self.current(selected) and authorize() is True and self.current(selected))

    @staticmethod
    def _credentials():
        return TebraCredentials(SecretStr("synthetic-user"), SecretStr("synthetic-password"), SecretStr("synthetic-key"))

    def window(self, scope, starts_at, ends_at, *, authorize):
        adapter, credentials = self._adapter(scope, authorize), self._credentials()
        return (adapter.read_practice(scope, credentials),
            adapter.read_appointments(scope, credentials, starts_at=starts_at, ends_at=ends_at))

    def visit(self, scope, appointment_id, patient_id, *, starts_at, ends_at, last_name, birth_date, authorize):
        adapter, credentials = self._adapter(scope, authorize), self._credentials()
        patients = adapter.find_patients(scope, credentials, last_name=last_name, birth_date=birth_date)
        patient = tuple(row for row in patients.rows if getattr(row, "patient_id", None) == patient_id)
        if len(patient) != 1:
            raise TebraReadError("response_invalid")
        appointments = adapter.read_appointments(scope, credentials, starts_at=starts_at, ends_at=ends_at)
        appointment = tuple(row for row in appointments.rows
            if getattr(row, "appointment_id", None) == appointment_id and getattr(row, "patient_id", None) == patient_id)
        if len(appointment) != 1:
            raise TebraReadError("response_invalid")
        return replace(appointments, rows=appointment), replace(patients, rows=patient)
