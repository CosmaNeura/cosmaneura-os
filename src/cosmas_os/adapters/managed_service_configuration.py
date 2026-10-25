"""Closed deployment configuration for the existing managed-service adapters.

Loading creates no accounts or network clients. API credentials and private
artifact custody are acquired only by an already authorized operation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import stat
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qsl
from uuid import UUID

from azure.core.credentials import AzureSasCredential
from pydantic import Field, SecretStr

from cosmas_os.adapters.elation_read import ElationCredentials, ElationReadScope
from cosmas_os.adapters.elation_sandbox_runtime import ElationSandboxInstallation
from cosmas_os.adapters.managed_event_routing import (
    ManagedEventProfile,
    ManagedEventRoutes,
    installed_selection,
)
from cosmas_os.adapters.managed_services import ManagedServiceProfile
from cosmas_os.adapters.vendor_artifact_transport import BoundedAzureArtifactContainer
from cosmas_os.adapters.vendor_artifacts import AzureVendorArtifactStore
from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.application import finance_settings, inbox_work, vendor_settings
from cosmas_os.application.efax_inbound import Installation as EFaxInboundInstallation
from cosmas_os.application.fax_inbound import Installation as FaxInboundInstallation
from cosmas_os.application.finance_events import FinanceEventRoute
from cosmas_os.application.vendor_events import EventRoute
from cosmas_os.config import Settings
from cosmas_os.ports.scribe_capture import ProtectedModel
from cosmas_os.ports.vendor_artifacts import ArtifactStoreError, VendorArtifactScope
from cosmas_os.ports.vendor_connectors import ConnectionSelection, VendorError

Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
Label = Annotated[str, Field(strict=True, min_length=1, max_length=160)]
MAX_CONFIG_BYTES = 262_144


class SecretReference(ProtectedModel):
    environment: str = Field(strict=True, pattern=r"^COSMAS_MANAGED_SECRET_[A-Z][A-Z0-9_]{0,63}$")
    sha256: Digest


class DeliveryInstallation(ProtectedModel):
    selection: ConnectionSelection
    label: Label
    sender_label: Label
    routing: dict[str, str]
    capabilities: list[str] = Field(min_length=1, max_length=10)
    credential: SecretReference | None = None


class PaymentInstallation(ProtectedModel):
    selection: ConnectionSelection
    label: Label
    credential: SecretReference | None = None


class InboundInstallation(ProtectedModel):
    selection: ConnectionSelection
    label: str = Field(strict=True, min_length=1, max_length=80)
    metadata_enabled: bool = Field(strict=True)
    image_enabled: bool = Field(strict=True)
    credential: SecretReference | None = None


class FaxInstallation(ProtectedModel):
    selection: ConnectionSelection
    label: str = Field(strict=True, min_length=1, max_length=80)
    image_enabled: bool = Field(strict=True, default=False)
    account_timezone: str | None = None
    account_date_format: str | None = None
    received_status: str | None = None
    conversation_id: str | None = None
    internal_endpoint_id: str | None = None
    credential: SecretReference | None = None


class InstalledEvent(ProtectedModel):
    selection: ConnectionSelection
    route_id: UUID
    signing_secret: SecretReference | None = None


class ArtifactConfiguration(ProtectedModel):
    backend: Literal["azure_sas"]
    account_url: str = Field(
        strict=True, pattern=r"^https://[a-z0-9]{3,24}\.blob\.core\.windows\.net$"
    )
    container_name: str = Field(strict=True, pattern=r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
    credential: SecretReference


class ElationSandboxConfiguration(ProtectedModel):
    problems_enabled: bool = Field(default=False, strict=True)
    id: UUID
    owner_id: UUID
    account_id: UUID
    connection_id: UUID
    credential_generation: UUID
    practice_id: Annotated[str, Field(strict=True, pattern=r"^[1-9][0-9]{0,18}$")]
    practice_name: str = Field(strict=True, min_length=1, max_length=200)
    timezone: str = Field(strict=True, min_length=1, max_length=100)
    environment: Literal["sandbox"]
    data_classification: Literal["synthetic_only"]
    client_id: SecretReference
    client_secret: SecretReference


class Configuration(ProtectedModel):
    version: Literal[1]
    box_id: UUID
    delivery: list[DeliveryInstallation] = Field(default_factory=list, max_length=50)
    payments: list[PaymentInstallation] = Field(default_factory=list, max_length=50)
    events: list[InstalledEvent] = Field(default_factory=list, max_length=1000)
    artifacts: ArtifactConfiguration | None = None
    efax_inbound: list[InboundInstallation] = Field(default_factory=list, max_length=50)
    fax_inbound: list[FaxInstallation] = Field(default_factory=list, max_length=20)
    inbox_grants: list[inbox_work.InboxReadGrant] = Field(default_factory=list, max_length=100)
    elation_sandbox: list[ElationSandboxConfiguration] = Field(default_factory=list, max_length=20)


def _secret(reference: SecretReference) -> str:
    value = os.environ.get(reference.environment, "")
    raw = value.encode("utf-8")
    if (
        not 1 <= len(raw) <= 8192
        or any(ord(c) < 32 or ord(c) > 126 for c in value)
        or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), reference.sha256)
    ):
        raise ValueError("Configured managed secret is unavailable or changed")
    return value


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate configuration key")
        result[key] = value
    return result


def _read_configuration(settings: Settings) -> Configuration:
    expected = settings.managed_services_config_sha256
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise ValueError("Exact configuration digest required")
    supplied = settings.managed_services_config_json
    inline = supplied.get_secret_value() if supplied else ""
    if inline:
        if settings.managed_services_config_path or len(inline) > MAX_CONFIG_BYTES:
            raise ValueError("Only one bounded configuration source is permitted")
        raw = inline.encode("utf-8")
    else:
        path = Path(settings.managed_services_config_path)
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise ValueError("Exact configuration path required")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= MAX_CONFIG_BYTES:
                raise ValueError("Bounded regular configuration file required")
            raw = stream.read(MAX_CONFIG_BYTES + 1)
        if len(raw) != info.st_size:
            raise ValueError("Configuration changed")
    if not 1 <= len(raw) <= MAX_CONFIG_BYTES or not hmac.compare_digest(
        hashlib.sha256(raw).hexdigest(), expected
    ):
        raise ValueError("Configuration changed")
    value = json.loads(raw, object_pairs_hook=_object)
    if type(value) is not dict or type(value.get("version")) is not int:
        raise ValueError("Explicit configuration version required")
    return Configuration.model_validate(value)


class ConfiguredArtifactStore:
    """Reuse the bounded Azure store with a fresh, exact SAS for each operation."""

    def __init__(self, configuration: ArtifactConfiguration, box_id: UUID):
        self._configuration, self._box_id = configuration, box_id

    def __repr__(self):
        return "ConfiguredArtifactStore(<protected>)"

    def _container(self):
        config = self._configuration
        signature = _secret(config.credential)
        pairs = parse_qsl(signature, strict_parsing=True, max_num_fields=32)
        query = dict(pairs)
        expiry = datetime.fromisoformat(query.get("se", "").replace("Z", "+00:00"))
        permissions = query.get("sp", "")
        # A container-scoped SAS can read/create/write only; never list/delete.
        if (
            len(pairs) != len(query)
            or query.get("sr") != "c"
            or query.get("spr") != "https"
            or bool(query.keys() & {"ss", "srt", "si"})
            or not permissions
            or set(permissions) - set("rcw")
            or "r" not in permissions
            or not set(permissions) & set("cw")
            or expiry.tzinfo is None
            or expiry <= datetime.now(UTC)
        ):
            raise ValueError("Private artifact credential is not scoped for custody")
        container = BoundedAzureArtifactContainer(
            account_url=config.account_url,
            container_name=config.container_name,
            credential=AzureSasCredential(signature),
        )
        return container, time.monotonic() + (expiry - datetime.now(UTC)).total_seconds()

    def _execute(self, scope: VendorArtifactScope, data: bytes | None, deadline):
        if scope.box_id != self._box_id:
            raise ArtifactStoreError("artifact_changed")
        if deadline is not None and (
            type(deadline) not in (int, float)
            or not math.isfinite(deadline)
            or deadline <= time.monotonic()
        ):
            raise ArtifactStoreError("storage_unavailable")
        container = None
        try:
            container, expires = self._container()
            deadline = min(
                expires, container.deadline(), deadline if deadline is not None else expires
            )
            store = AzureVendorArtifactStore(container, box_id=self._box_id)
            if data is None:
                return store.read_verified(scope, deadline=deadline)
            store.put_verified(scope, data, deadline=deadline)
            return None
        except ArtifactStoreError:
            raise
        except Exception:
            raise ArtifactStoreError("storage_unavailable") from None
        finally:
            if container is not None:
                # The existing bounded transport has no persistent connections.
                # Cleanup must not replace a known custody result or leak SDK text.
                try:
                    container.close()
                except Exception:
                    pass

    def read_verified(self, scope: VendorArtifactScope, *, deadline: float | None = None) -> bytes:
        value = self._execute(scope, None, deadline)
        if not isinstance(value, bytes):
            raise ArtifactStoreError("storage_unavailable")
        return value

    def put_verified(
        self, scope: VendorArtifactScope, data: bytes, *, deadline: float | None = None
    ) -> None:
        scope.require_bytes(data)
        self._execute(scope, data, deadline)


def load_managed_profile(settings: Settings) -> ManagedServiceProfile:
    """Load only installed configuration, preserving all independent action gates."""
    try:
        if (
            not settings.workspace_available
            or not settings.workspace_authenticated_enabled
            or settings.auth_mode != "clerk_jwt"
        ):
            raise ValueError("Authenticated workspace required")
        config = _read_configuration(settings)
        if str(config.box_id) != settings.beta_box_id:
            raise ValueError("Configured Box differs")
        accounts = [*config.delivery, *config.payments, *config.efax_inbound, *config.fax_inbound]
        identifiers, credential_ids, secrets = set(), set(), {}
        credentials = []

        def register(reference: SecretReference | None):
            if reference is not None:
                previous = secrets.setdefault(reference.environment, reference.sha256)
                if previous != reference.sha256:
                    raise ValueError("Conflicting secret versions")

        for item in accounts:
            selected = item.selection
            if (
                selected.box_id != config.box_id
                or selected.connection_id in identifiers
                or selected.credential_ref in credential_ids
            ):
                raise ValueError("Distinct installed accounts for the exact Box required")
            identifiers.add(selected.connection_id)
            credential_ids.add(selected.credential_ref)
            register(item.credential)
            if item.credential is not None:
                credentials.append((selected, item.credential))
        sandbox = []
        sandbox_accounts = set()
        for item in config.elation_sandbox:
            if (item.account_id in sandbox_accounts or item.connection_id in identifiers
                    or int(item.practice_id) > 2**63 - 1):
                raise ValueError("Distinct exact sandbox practice installations required")
            sandbox_accounts.add(item.account_id)
            identifiers.add(item.connection_id)
            register(item.client_id)
            register(item.client_secret)
            sandbox.append(ElationSandboxInstallation(item.id, item.account_id,
                ElationReadScope(config.box_id, item.owner_id, item.connection_id, item.credential_generation,
                    int(item.practice_id), item.practice_name), item.timezone,
                item.client_id.sha256, item.client_secret.sha256, problems_enabled=item.problems_enabled))

        def sandbox_references(scope):
            matches = [configured for configured, installed in zip(config.elation_sandbox, sandbox, strict=True)
                if installed.scope == scope]
            if len(matches) != 1:
                raise ValueError("Sandbox installation changed")
            return matches[0]

        def sandbox_current(scope):
            try:
                configured = sandbox_references(scope)
                _secret(configured.client_id)
                _secret(configured.client_secret)
                return True
            except Exception:
                return False

        async def sandbox_credentials(scope):
            configured = sandbox_references(scope)
            return ElationCredentials(scope.commitment(), SecretStr(_secret(configured.client_id)),
                SecretStr(_secret(configured.client_secret)))
        vendor = vendor_settings.Catalog(
            vendor_settings.Installation(
                item.selection,
                item.label,
                item.sender_label,
                item.routing,
                tuple(item.capabilities),
            )
            for item in config.delivery
        )
        finance = finance_settings.Catalog(
            finance_settings.Installation(item.selection, item.label) for item in config.payments
        )
        inbox_registry = inbox_work.InboxRegistry(config.inbox_grants)
        for grant in inbox_registry.grants.values():
            if grant.binding.selection.box_id != config.box_id:
                raise ValueError("Inbox grant differs from configured Box")
            installed_selection(grant.binding.selection, vendor)
        inbound = tuple(EFaxInboundInstallation(item.selection, item.label,
            item.metadata_enabled, item.image_enabled) for item in config.efax_inbound)

        fax_inbound = tuple(FaxInboundInstallation(**item.model_dump(exclude={"credential", "selection"}),
            selection=item.selection) for item in config.fax_inbound)
        exact_inbound = (*inbound, *fax_inbound)

        async def acquire(supplied: ConnectionSelection) -> Credential:
            try:
                selected = ConnectionSelection.model_validate(supplied.model_dump(mode="python"))
                matches = [
                    ref
                    for original, ref in credentials
                    if (original == selected and any(item.selection == original for item in exact_inbound))
                    or (original.connection_id != selected.connection_id
                        and original.model_copy(update={"connection_id": selected.connection_id}) == selected
                        and not any(item.selection == original for item in exact_inbound))
                ]
                if len(matches) != 1:
                    raise ValueError("Account changed")
                return Credential(
                    selection_sha256=selected.commitment(),
                    credential_ref=str(selected.credential_ref),
                    secret=SecretStr(_secret(matches[0])),
                )
            except Exception:
                raise VendorError("connection_changed") from None

        delivery_events, payment_events = [], []
        for item in config.events:
            selected, _ = installed_selection(
                item.selection, finance if item.selection.vendor == "stripe" else vendor
            )
            register(item.signing_secret)
            secret = _secret(item.signing_secret).encode("ascii") if item.signing_secret else None
            if selected.vendor == "stripe":
                if secret is None:
                    raise ValueError("Stripe signing material required")
                payment_events.append(
                    FinanceEventRoute(
                        str(item.route_id), str(selected.connection_id), secret, selected
                    )
                )
            else:
                delivery_events.append(
                    EventRoute(
                        str(item.route_id),
                        str(selected.connection_id),
                        selected.vendor,
                        secret,
                        selected,
                    )
                )
        events = ManagedEventProfile(tuple(delivery_events), tuple(payment_events))
        ManagedEventRoutes(events, vendor, finance)
        artifact_store = None
        if config.artifacts is not None:
            artifact = config.artifacts
            register(artifact.credential)
            if (
                settings.blob_backend != "azure"
                or "--" in artifact.container_name
                or artifact.account_url != (settings.azure_storage_account_url or "").rstrip("/")
                or artifact.container_name != settings.azure_blob_container
            ):
                raise ValueError(
                    "Artifact store must match the configured private workspace storage"
                )
            artifact_store = ConfiguredArtifactStore(artifact, config.box_id)
        return ManagedServiceProfile(
            vendor_catalog=vendor,
            finance_catalog=finance,
            credentials=acquire if credentials else None,
            artifact_store=artifact_store,
            events=events if config.events else None,
            efax_inbound_installations=inbound, fax_inbound_installations=fax_inbound,
            inbox_grants=tuple(inbox_registry.grants.values()),
            elation_sandbox=tuple(sandbox), elation_credentials=sandbox_credentials if sandbox else None,
            elation_credentials_current=sandbox_current if sandbox else None,
        )
    except Exception:
        raise ValueError("Managed service configuration is invalid or unavailable") from None
