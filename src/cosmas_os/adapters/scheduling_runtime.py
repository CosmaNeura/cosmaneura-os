"""Explicit, lifespan-owned Scheduling connections for the ordinary ASGI app.

The host supplies an already qualified staff-token source. Nothing here discovers
accounts, exchanges a Clerk token, reads ambient credentials, or grants access.
The receiver still verifies the token and current staff membership on every call.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
from fastapi import FastAPI
from pydantic import AwareDatetime, SecretStr

from cosmas_os.adapters.scheduling import HttpSchedulingAvailability
from cosmas_os.adapters.scheduling_actions import HttpSchedulingAppointments
from cosmas_os.config import Settings
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling import SchedulingSelection
from cosmas_os.ports.scribe_capture import ProtectedModel


class SchedulingStaffCredential(ProtectedModel):
    """Short-lived staff proof, bound by its trusted provider to this selection.

    The family is a provider contract, not JWT verification. The token is sent
    only to the configured Scheduling receiver, which owns that verification.
    No patient identity is part of credential acquisition.
    """

    selection: SchedulingSelection
    family: Literal["microsoft_staff_access", "google_staff_identity"]
    token: SecretStr
    expires_at: AwareDatetime


@dataclass(frozen=True, repr=False)
class SchedulingServiceProfile:
    origin: str
    staff_credential: Callable[[SchedulingSelection], SchedulingStaffCredential] = field(repr=False)


class SchedulingRuntime:
    """Own both HTTP clients; never cache staff tokens across requests."""

    def __init__(
        self,
        settings: Settings,
        profile: SchedulingServiceProfile,
        *,
        transport_factory: Callable[[], httpx.BaseTransport] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        if not settings.workspace_scheduling_available:
            raise ValueError("Scheduling service requires the authenticated workspace gate")
        if not isinstance(profile, SchedulingServiceProfile) or not callable(profile.staff_credential):
            raise ValueError("Scheduling requires an explicit staff credential provider")
        self._settings = settings
        self._profile = profile
        self._now = now
        self._closed = False
        self.availability = HttpSchedulingAvailability(
            profile.origin, lambda selection: self._credential(selection, appointments=False),
            transport=transport_factory() if transport_factory else None, now=now,
        )
        try:
            self.appointments = HttpSchedulingAppointments(
                profile.origin, lambda selection: self._credential(selection, appointments=True),
                transport=transport_factory() if transport_factory else None, now=now,
                execution_allowed=lambda: not self._closed and self._settings.workspace_appointment_execution_available,
            )
        except BaseException:
            self._closed = True
            self.availability.close()
            raise

    def _require_current(self, *, appointments: bool) -> None:
        if (self._closed or not self._settings.workspace_scheduling_available
                or appointments and not self._settings.workspace_appointments_enabled):
            raise ConnectorUnavailable("scheduling_identity_unavailable")

    def _credential(self, selection: SchedulingSelection, *, appointments: bool) -> SecretStr:
        try:
            self._require_current(appointments=appointments)
            selected = SchedulingSelection.model_validate({
                name: getattr(selection, name) for name in SchedulingSelection.model_fields
            })
            if selected.expected_actor_id is None:
                raise ValueError
            supplied = self._profile.staff_credential(selected)
            if not isinstance(supplied, SchedulingStaffCredential):
                raise ValueError
            supplied = SchedulingStaffCredential.model_validate(supplied.model_dump(warnings=False))
            now = self._now()
            if (not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None
                    or supplied.selection != selected
                    or not now + timedelta(seconds=30) <= supplied.expires_at <= now + timedelta(days=1)):
                raise ValueError
            self._require_current(appointments=appointments)
            return supplied.token
        except Exception:
            raise ConnectorUnavailable("scheduling_identity_unavailable") from None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.appointments.close()
        finally:
            self.availability.close()


def configure_scheduling(app: FastAPI, profile: SchedulingServiceProfile) -> None:
    """Host bootstrap only, before first startup; no route can install a profile."""
    if (not isinstance(profile, SchedulingServiceProfile)
            or getattr(app.state, "scheduling_startup_seen", False)
            or getattr(app.state, "scheduling_profile", None) is not None):
        raise ValueError("Scheduling profile must be installed once before startup")
    app.state.scheduling_profile = profile


@contextmanager
def scheduling_lifespan(app: FastAPI, settings: Settings) -> Iterator[None]:
    if getattr(app.state, "scheduling_lifespan_active", False):
        raise RuntimeError("Scheduling lifespan is already active")
    app.state.scheduling_startup_seen = True
    app.state.scheduling_lifespan_active = True
    runtime = None
    try:
        profile = getattr(app.state, "scheduling_profile", None)
        runtime = SchedulingRuntime(settings, profile) if profile is not None else None
        app.state.scheduling_runtime = runtime
        yield
    finally:
        app.state.scheduling_runtime = None
        app.state.scheduling_lifespan_active = False
        if runtime is not None:
            runtime.close()


def scheduling_runtime(app: FastAPI) -> SchedulingRuntime | None:
    value = getattr(app.state, "scheduling_runtime", None)
    return value if isinstance(value, SchedulingRuntime) else None
