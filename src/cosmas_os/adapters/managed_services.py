"""Host configuration for existing managed delivery and finance application ports."""

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI
from sqlalchemy.orm import Session

from cosmas_os.adapters.managed_event_routing import ManagedEventProfile, ManagedEventRoutes
from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.application import finance_settings, vendor_settings
from cosmas_os.application.finance_settings_execution import FinanceSettingsExecution
from cosmas_os.application.finance_work import FinancePolicy
from cosmas_os.application.vendor_settings_execution import VendorSettingsExecution
from cosmas_os.config import Settings
from cosmas_os.ports.vendor_artifacts import VendorArtifactStore
from cosmas_os.ports.vendor_connectors import ConnectionSelection, VendorError

CurrentIdentity = Callable[[], Awaitable[bool]]
CredentialProvider = Callable[[ConnectionSelection], Awaitable[Credential]]


@dataclass(frozen=True, repr=False)
class ManagedServiceProfile:
    """Installed accounts are configuration, never proof of reviewed activation.

    Optional credentials permit setup/catalog-only use. The host owns credential
    storage and artifact-store lifetime. A supplied transport factory is for
    explicitly scoped embedding/qualification; ordinary transport remains TLS.
    """

    vendor_catalog: vendor_settings.Catalog = field(default_factory=vendor_settings.Catalog)
    finance_catalog: finance_settings.Catalog = field(default_factory=finance_settings.Catalog)
    credentials: CredentialProvider | None = field(default=None, repr=False)
    artifact_store: VendorArtifactStore | None = field(default=None, repr=False)
    transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = field(default=None, repr=False)
    events: ManagedEventProfile | None = field(default=None, repr=False)


class ManagedServices:
    def __init__(self, settings: Settings, profile: ManagedServiceProfile, sessions: Callable[[], Session]):
        if (not settings.workspace_available or not settings.workspace_authenticated_enabled
                or settings.auth_mode != "clerk_jwt"):
            raise ValueError("Managed services require the authenticated workspace gate")
        if (not isinstance(profile, ManagedServiceProfile) or not callable(sessions)
                or not isinstance(profile.vendor_catalog, vendor_settings.Catalog)
                or not isinstance(profile.finance_catalog, finance_settings.Catalog)
                or profile.credentials is not None and not callable(profile.credentials)
                or profile.transport_factory is not None and not callable(profile.transport_factory)):
            raise ValueError("Explicit managed service configuration required")
        if profile.artifact_store is not None and not all(callable(getattr(profile.artifact_store, name, None))
                for name in ("put_verified", "read_verified")):
            raise ValueError("A verified private artifact store is required")
        # Revalidate/copy configuration so later host object mutation cannot
        # silently replace the installations reviewed for this process.
        self.vendor_catalog = vendor_settings.Catalog(profile.vendor_catalog.installations.values())
        self.finance_catalog = finance_settings.Catalog(profile.finance_catalog.installations.values())
        self.events = ManagedEventRoutes(profile.events, self.vendor_catalog, self.finance_catalog) if profile.events is not None else None
        self.artifact_store = profile.artifact_store
        self._settings, self._profile, self._sessions = settings, profile, sessions
        self._closed = False

    def _available(self) -> bool:
        return bool(not self._closed and self._settings.workspace_available
            and self._settings.workspace_authenticated_enabled and self._settings.auth_mode == "clerk_jwt")

    def _io_available(self, finance: bool) -> bool:
        if not self._available():
            return False
        return bool(self._settings.finance_work_enabled and self._settings.finance_io_enabled) if finance else bool(
            self._settings.vendor_work_enabled and self._settings.vendor_io_enabled)

    def _identity(self, current: CurrentIdentity, *, finance: bool) -> CurrentIdentity:
        if not callable(current):
            raise ValueError("Current request identity is required")

        async def checked() -> bool:
            try:
                if not self._io_available(finance):
                    return False
                return await current() is True and self._io_available(finance)
            except Exception:
                return False
        return checked

    async def _credentials(self, supplied: ConnectionSelection) -> Credential:
        try:
            selected = ConnectionSelection.model_validate(supplied.model_dump(mode="python"))
            finance = selected.vendor == "stripe"
            if not self._io_available(finance) or self._profile.credentials is None:
                raise ValueError
            catalog = self.finance_catalog if finance else self.vendor_catalog
            matched = [item for item in catalog.installations.values()
                if item.selection.model_copy(update={"connection_id": selected.connection_id}) == selected]
            # Active managed account versions are independently created by the
            # reviewed setup flow; an installation selector is never that version.
            if len(matched) != 1 or matched[0].selection.connection_id == selected.connection_id:
                raise ValueError
            value = await self._profile.credentials(selected)
            if not isinstance(value, Credential):
                raise ValueError
            value = Credential.model_validate(value.model_dump(mode="python"))
            if (value.selection_sha256 != selected.commitment()
                    or value.credential_ref != str(selected.credential_ref)
                    or not self._io_available(finance)):
                raise ValueError
            return value
        except Exception:
            raise VendorError("connection_changed") from None

    def vendor_execution(self, identity_current: CurrentIdentity) -> VendorSettingsExecution:
        if not self._available() or self._profile.credentials is None:
            raise VendorError("connector_disabled")
        current = self._identity(identity_current, finance=False)
        return VendorSettingsExecution(self._sessions, self._credentials, artifact_store=self.artifact_store,
            transport=self._profile.transport_factory() if self._profile.transport_factory else None,
            identity_current=current, installed_catalog=lambda: self.vendor_catalog)

    def finance_execution(self, identity_current: CurrentIdentity) -> FinanceSettingsExecution:
        if not self._available() or self._profile.credentials is None:
            raise VendorError("connector_disabled")
        current = self._identity(identity_current, finance=True)
        policy = FinancePolicy(enabled=self._settings.workspace_available and self._settings.finance_work_enabled,
            io_enabled=self._settings.workspace_available and self._settings.finance_io_enabled,
            events_enabled=self._settings.workspace_available and self._settings.finance_events_enabled)
        return FinanceSettingsExecution(self._sessions, self._credentials, policy=policy,
            transport=self._profile.transport_factory() if self._profile.transport_factory else None,
            identity_current=current, installed_catalog=lambda: self.finance_catalog)

    @property
    def has_credentials(self) -> bool:
        return self._available() and self._profile.credentials is not None

    def vendor_event(self, vendor: str, route_id: str):
        if not self._available() or not self._settings.vendor_events_enabled or self.events is None:
            return None
        return self.events.vendor(vendor, route_id)

    def finance_event(self, route_id: str):
        if not self._available() or not self._settings.finance_events_enabled or self.events is None:
            return None
        return self.events.finance(route_id)

    def close(self) -> None:
        # Existing invocations may retain private late observations. Closing
        # blocks fresh credentials/dispatch; it never deletes durable evidence.
        self._closed = True


def configure_managed_services(app: FastAPI, profile: ManagedServiceProfile) -> None:
    if (not isinstance(profile, ManagedServiceProfile)
            or getattr(app.state, "managed_startup_seen", False)
            or getattr(app.state, "managed_profile", None) is not None):
        raise ValueError("Managed profile must be installed once before startup")
    app.state.managed_profile = profile


@contextmanager
def managed_services_lifespan(app: FastAPI, settings: Settings, sessions: Callable[[], Session]) -> Iterator[None]:
    if getattr(app.state, "managed_lifespan_active", False):
        raise RuntimeError("Managed service lifespan is already active")
    app.state.managed_startup_seen = True
    app.state.managed_lifespan_active = True
    runtime = None
    try:
        profile = getattr(app.state, "managed_profile", None)
        configured_json = settings.managed_services_config_json
        if (settings.managed_services_config_path or settings.managed_services_config_sha256
                or configured_json and configured_json.get_secret_value()):
            if profile is not None:
                raise ValueError("Configured and explicit host managed profiles cannot be combined")
            from cosmas_os.adapters.managed_service_configuration import load_managed_profile

            profile = load_managed_profile(settings)
        runtime = ManagedServices(settings, profile, sessions) if profile is not None else None
        app.state.managed_services = runtime
        yield
    finally:
        app.state.managed_services = None
        app.state.managed_lifespan_active = False
        if runtime is not None:
            runtime.close()


def managed_services(app: FastAPI) -> ManagedServices | None:
    value = getattr(app.state, "managed_services", None)
    return value if isinstance(value, ManagedServices) and value._available() else None
