"""Named portal installations and request-owned adapters at ordinary startup."""

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from types import MappingProxyType

from fastapi import FastAPI
from sqlalchemy.orm import Session

from cosmas_os.adapters.vendor_connectors.portals import (
    PortalBinding,
    PortalImplementation,
    PortalProfile,
    PortalRegistry,
)
from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.application import portal_setup as setup
from cosmas_os.application import portal_work as work
from cosmas_os.application.capture_deadline import CaptureBudget, capture_budget, current_budget
from cosmas_os.application.portal_work_execution import Invocation, PortalWorkExecution
from cosmas_os.config import Settings
from cosmas_os.ports.vendor_artifacts import VendorArtifactStore
from cosmas_os.ports.vendor_connectors import ConnectionSelection, PortalIntent, VendorError

CurrentIdentity = Callable[[], Awaitable[bool]]
CredentialProvider = Callable[[ConnectionSelection], Awaitable[Credential]]


@dataclass(frozen=True, repr=False)
class PortalAdapterContext:
    """A named adapter uses these guards before every credential/network action."""

    profile: PortalProfile
    credentials: CredentialProvider
    identity_current: CurrentIdentity
    deadline: float


AdapterFactory = Callable[[PortalAdapterContext], AbstractAsyncContextManager[PortalImplementation]]

ADAPTER_CLOSE_SECONDS = 5


@asynccontextmanager
async def owned_adapter(resource):
    adapter = await resource.__aenter__()
    try:
        yield adapter
    finally:
        # Cleanup has its own finite allowance after an operation timeout.
        # A provider context cannot suppress the original operation failure.
        with_error = sys.exc_info()
        async with asyncio.timeout(ADAPTER_CLOSE_SECONDS):
            await resource.__aexit__(*with_error)


@dataclass(frozen=True, repr=False)
class PortalServiceProfile:
    installations: tuple[setup.Installation, ...] = ()
    adapters: Mapping[str, AdapterFactory] = field(default_factory=dict, repr=False)
    credentials: CredentialProvider | None = field(default=None, repr=False)
    artifact_store: VendorArtifactStore | None = field(default=None, repr=False)
    allow_live_profiles: bool = False


class CatalogOnlyAdapter:
    """Profile description only; catalog discovery cannot instantiate live clients."""

    def __init__(self, profile):
        self.profile = profile

    def prepare(self, command, document=None):
        raise VendorError("connector_disabled")

    async def submit(self, prepared, approval):
        raise VendorError("connector_disabled")

    async def observe(self, command, reference):
        raise VendorError("connector_disabled")


class ScopedPortalExecution:
    def __init__(self, services, current):
        self.services, self.current = services, current

    async def invoke(self, invocation, *, deadline=None):
        return await self.services.invoke(invocation, self.current, deadline=deadline)


class PortalServices:
    def __init__(
        self, settings: Settings, profile: PortalServiceProfile, sessions: Callable[[], Session]
    ):
        if (
            not isinstance(profile, PortalServiceProfile)
            or not callable(sessions)
            or not settings.workspace_available
            or not settings.workspace_authenticated_enabled
            or settings.auth_mode != "clerk_jwt"
            or profile.allow_live_profiles
            and settings.cosmas_env != "early_adopter_beta"
            or profile.credentials is not None
            and not callable(profile.credentials)
        ):
            raise ValueError("Explicit authenticated portal service configuration required")
        if profile.artifact_store is not None and not all(
            callable(getattr(profile.artifact_store, name, None))
            for name in ("put_verified", "read_verified")
        ):
            raise ValueError("Verified private portal artifact custody required")
        descriptions = {}
        for item in profile.installations:
            previous = descriptions.get(item.profile.portal_id)
            if previous is not None and previous != item.profile:
                raise ValueError("One exact installed contract per named portal")
            descriptions[item.profile.portal_id] = item.profile
        registry = PortalRegistry(
            tuple(
                PortalBinding(value, CatalogOnlyAdapter(value)) for value in descriptions.values()
            )
        )
        self.catalog = setup.Catalog(
            registry, profile.installations, allow_live_profiles=profile.allow_live_profiles
        )
        factories = dict(profile.adapters)
        if set(factories) - descriptions.keys() or any(
            not callable(value) for value in factories.values()
        ):
            raise ValueError("Named portal adapters must match installed profiles")
        if profile.credentials is not None and set(factories) != descriptions.keys():
            raise ValueError("Configured credentials require every named portal adapter")
        self._factories = MappingProxyType(factories)
        self._credentials, self._store = profile.credentials, profile.artifact_store
        self._settings, self._sessions = settings, sessions
        self._closed = False
        self.pending: set[asyncio.Task] = set()

    def available(self):
        return bool(
            not self._closed
            and self._settings.workspace_available
            and self._settings.workspace_authenticated_enabled
            and self._settings.auth_mode == "clerk_jwt"
        )

    def policy(self):
        return work.PortalWorkPolicy(
            enabled=self.available() and self._settings.portal_work_enabled,
            io_enabled=self.available()
            and self._settings.portal_work_enabled
            and self._settings.portal_io_enabled,
        )

    @property
    def has_execution(self):
        return self.policy().io_enabled and self._credentials is not None and bool(self._factories)

    def execution(self, current: CurrentIdentity):
        if not self.has_execution or not callable(current):
            raise VendorError("connector_disabled")
        return ScopedPortalExecution(self, current)

    def installation(self, selected: ConnectionSelection, portal_id: str):
        selected = ConnectionSelection.model_validate(selected.model_dump(mode="python"))
        matched = [
            item
            for item in self.catalog.installations.values()
            if item.profile.portal_id == portal_id and item.selection == selected
        ]
        if len(matched) != 1:
            raise VendorError("connection_changed")
        return matched[0]

    async def _run(
        self, inv: Invocation, current: CurrentIdentity, deadline: float, request_budget
    ):
        executor = PortalWorkExecution(
            self._sessions,
            catalog=self.catalog,
            artifact_store=self._store,
            identity_current=current,
            policy_current=self.policy,
        )

        async def authority():
            try:
                if request_budget is not None:
                    request_budget.check()
                valid = bool(
                    time.monotonic() < deadline
                    and self.has_execution
                    and await current() is True
                    and self.has_execution
                )
                if request_budget is not None:
                    request_budget.check()
                return valid
            except Exception:
                return False

        async def credentials(supplied):
            try:
                if not isinstance(inv.command.intent, PortalIntent) or self._credentials is None:
                    raise ValueError
                selected = ConnectionSelection.model_validate(supplied.model_dump(mode="python"))
                if selected != inv.command.selection or not await authority():
                    raise ValueError
                self.installation(selected, inv.command.intent.portal_id)
                if not await asyncio.to_thread(executor._ready, inv):
                    raise ValueError
                value = await self._credentials(selected)
                value = Credential.model_validate(value.model_dump(mode="python"))
                if (
                    value.selection_sha256 != selected.commitment()
                    or value.credential_ref != str(selected.credential_ref)
                    or not await authority()
                    or not await asyncio.to_thread(executor._ready, inv)
                ):
                    raise ValueError
                return value
            except Exception:
                raise VendorError("connection_changed") from None

        executor.identity_current = authority
        try:
            async with asyncio.timeout_at(deadline):
                if not await authority():
                    raise VendorError("authority_required")
                if not isinstance(inv.command.intent, PortalIntent):
                    raise VendorError("request_invalid")
                item = self.installation(inv.command.selection, inv.command.intent.portal_id)
                context = PortalAdapterContext(item.profile, credentials, authority, deadline)
                async with owned_adapter(self._factories[item.profile.portal_id](context)) as adapter:
                    registry = PortalRegistry((PortalBinding(item.profile, adapter),))
                    executor.catalog = setup.Catalog(
                        registry, (item,), allow_live_profiles=self.catalog.allow_live_profiles
                    )
                    # This outer task owns invocation and adapter cleanup even if
                    # the HTTP caller loses its connection. It never replays work.
                    await executor.run_owned(inv, deadline=deadline)
        except asyncio.CancelledError:
            await asyncio.to_thread(
                executor._settle, inv, None, VendorError("transport_unconfirmed", attempted=True)
            )
            raise
        except Exception as exc:
            failure = (
                exc
                if isinstance(exc, VendorError)
                else VendorError("transport_unconfirmed", attempted=True)
            )
            await asyncio.to_thread(executor._settle, inv, None, failure)

    async def invoke(self, invocation, current, *, deadline=None):
        if not self.has_execution:
            raise VendorError("connector_disabled")
        limit = (
            min(deadline, time.monotonic() + 45) if deadline is not None else time.monotonic() + 45
        )
        request_budget = current_budget()

        async def owned():
            # Current request authority still gates dispatch. The owned budget
            # keeps already received evidence recordable after a lost caller.
            with capture_budget(CaptureBudget(50)):
                await self._run(invocation, current, limit, request_budget)

        task = asyncio.create_task(owned())
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)
        return await asyncio.shield(task)

    async def close(self):
        self._closed = True
        if self.pending:
            # Owned operations have a whole-operation deadline; retain late
            # observations and finish private adapter cleanup before shutdown.
            await asyncio.gather(*tuple(self.pending), return_exceptions=True)


def configure_portal_services(app: FastAPI, profile: PortalServiceProfile):
    if (
        not isinstance(profile, PortalServiceProfile)
        or getattr(app.state, "portal_startup_seen", False)
        or getattr(app.state, "portal_profile", None) is not None
    ):
        raise ValueError("Portal profile must be installed once before startup")
    app.state.portal_profile = profile


@asynccontextmanager
async def portal_services_lifespan(
    app: FastAPI, settings: Settings, sessions: Callable[[], Session]
):
    if getattr(app.state, "portal_lifespan_active", False):
        raise RuntimeError("Portal lifespan is already active")
    app.state.portal_startup_seen = True
    app.state.portal_lifespan_active = True
    runtime = None
    try:
        profile = getattr(app.state, "portal_profile", None)
        runtime = PortalServices(settings, profile, sessions) if profile is not None else None
        app.state.portal_services = runtime
        yield
    finally:
        app.state.portal_services = None
        app.state.portal_lifespan_active = False
        if runtime is not None:
            await runtime.close()


def portal_services(app: FastAPI):
    value = getattr(app.state, "portal_services", None)
    return value if isinstance(value, PortalServices) and value.available() else None
