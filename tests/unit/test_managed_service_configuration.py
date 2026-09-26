import asyncio
import hashlib
import json
import socket
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from tests.unit.test_hosted_workspace_config import hosted
from tests.unit.test_scheduling_runtime import configuration as configuration
from tests.unit.test_vendor_connector_foundation import selection

from cosmas_os.adapters import managed_service_configuration as configured
from cosmas_os.adapters.managed_services import (
    ManagedServiceProfile,
    ManagedServices,
    configure_managed_services,
    managed_services,
    managed_services_lifespan,
)
from cosmas_os.ports.vendor_artifacts import ArtifactStoreError, VendorArtifactScope
from cosmas_os.ports.vendor_connectors import DocumentBinding, VendorError


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Configuration qualification must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def secret_ref(name, value="PRIVATE_invented"):
    return {
        "environment": "COSMAS_MANAGED_SECRET_" + name,
        "sha256": hashlib.sha256(value.encode()).hexdigest(),
    }


def document(settings, vendor="documo", *, credential=True):
    selected = selection(vendor).model_copy(update={"box_id": UUID(settings.beta_box_id)})
    item = {"selection": selected.model_dump(mode="json"), "label": "Invented " + vendor}
    if credential:
        item["credential"] = secret_ref("API")
    if vendor != "stripe":
        item.update(
            sender_label="Invented sender",
            capabilities=[
                {"spruce": "spruce_secure_message", "srfax": "srfax_fax", "documo": "documo_fax"}[
                    vendor
                ]
            ],
            routing={"internal_endpoint_id": "invented_endpoint"}
            if vendor == "spruce"
            else {"caller_id": "2125550199"},
        )
    return {
        "version": 1,
        "box_id": settings.beta_box_id,
        "payments" if vendor == "stripe" else "delivery": [item],
    }


def install(tmp_path, settings, doc, *, raw=None):
    path = tmp_path.resolve() / "managed.json"
    body = raw if raw is not None else json.dumps(doc).encode()
    path.write_bytes(body)
    settings.managed_services_config_path = str(path)
    settings.managed_services_config_sha256 = hashlib.sha256(body).hexdigest()
    return path


def no_session():
    raise AssertionError("Configured startup must not read or mutate account rows")


def active(profile, vendor):
    catalog = profile.finance_catalog if vendor == "stripe" else profile.vendor_catalog
    return next(iter(catalog.installations.values())).selection.model_copy(
        update={"connection_id": uuid4()}
    )


@pytest.mark.parametrize("vendor", ["spruce", "srfax", "documo", "stripe"])
def test_deployment_catalog_and_fresh_exact_secret(tmp_path, configuration, monkeypatch, vendor):
    install(tmp_path, configuration, document(configuration, vendor))
    profile = configured.load_managed_profile(configuration)
    configuration.vendor_work_enabled = configuration.vendor_io_enabled = True
    configuration.finance_work_enabled = configuration.finance_io_enabled = True
    runtime = ManagedServices(configuration, profile, no_session)
    selected = active(profile, vendor)
    # Catalog loading needed neither credentials nor database/network access.
    with pytest.raises(VendorError, match="^connection_changed$"):
        asyncio.run(runtime._credentials(selected))
    monkeypatch.setenv("COSMAS_MANAGED_SECRET_API", "PRIVATE_invented")
    result = asyncio.run(runtime._credentials(selected))
    assert result.selection_sha256 == selected.commitment()
    assert result.secret.get_secret_value() == "PRIVATE_invented"
    assert "PRIVATE_invented" not in repr(result)
    monkeypatch.setenv("COSMAS_MANAGED_SECRET_API", "PRIVATE_rotated_without_review")
    with pytest.raises(VendorError, match="^connection_changed$"):
        asyncio.run(runtime._credentials(selected))
    runtime.close()


@pytest.mark.parametrize(
    "field",
    [
        "box_id",
        "owner_id",
        "credential_ref",
        "remote_account_id",
        "configuration_sha256",
        "connection_id",
    ],
)
def test_changed_selection_never_reads_secret(tmp_path, configuration, monkeypatch, field):
    install(tmp_path, configuration, document(configuration))
    profile = configured.load_managed_profile(configuration)
    selected = active(profile, "documo")
    original = next(iter(profile.vendor_catalog.installations.values())).selection
    changes = {
        "remote_account_id": str(uuid4()),
        "configuration_sha256": "b" * 64,
        "connection_id": original.connection_id,
    }
    changed = selected.model_copy(update={field: changes.get(field, uuid4())})

    def fail(*args):
        raise AssertionError("A changed account must be refused before reading credentials")

    monkeypatch.setattr(configured, "_secret", fail)
    provider = profile.credentials
    assert provider is not None

    async def acquire():
        return await provider(changed)

    with pytest.raises(VendorError, match="^connection_changed$"):
        asyncio.run(acquire())


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate_key",
        "extra_key",
        "other_box",
        "duplicate_account",
        "digest",
        "link",
        "boolean_version",
        "arbitrary_secret",
        "production_stripe",
        "missing_digest",
    ],
)
def test_invalid_deployment_input_is_closed(tmp_path, configuration, fault):
    doc = document(configuration, "stripe" if fault == "production_stripe" else "documo")
    if fault == "extra_key":
        doc["python_module"] = "do_not_import"
    if fault == "other_box":
        doc["delivery"][0]["selection"]["box_id"] = str(uuid4())
    if fault == "duplicate_account":
        doc["delivery"].append(doc["delivery"][0])
    if fault == "boolean_version":
        doc["version"] = True
    if fault == "arbitrary_secret":
        doc["delivery"][0]["credential"]["environment"] = "DATABASE_URL"
    if fault == "production_stripe":
        doc["payments"][0]["selection"]["environment"] = "production"
    raw = b'{"version":1,"version":1}' if fault == "duplicate_key" else None
    path = install(tmp_path, configuration, doc, raw=raw)
    if fault == "digest":
        path.write_text("{}")
    if fault == "missing_digest":
        configuration.managed_services_config_sha256 = ""
    if fault == "link":
        link = path.with_name("linked.json")
        link.symlink_to(path)
        configuration.managed_services_config_path = str(link)
    with pytest.raises(
        ValueError, match="^Managed service configuration is invalid or unavailable$"
    ):
        configured.load_managed_profile(configuration)


def test_no_implicit_credentials_or_account_activation(tmp_path, configuration):
    install(tmp_path, configuration, document(configuration, credential=False))
    app = FastAPI()
    with managed_services_lifespan(app, configuration, no_session):
        runtime = managed_services(app)
        assert runtime is not None
        assert len(runtime.vendor_catalog.installations) == 1
        assert not runtime.has_credentials
        assert not configuration.vendor_io_enabled and not configuration.vendor_setup_enabled
    assert managed_services(app) is None
    # Restart reloads the same deployment document without replaying any action.
    with managed_services_lifespan(app, configuration, no_session):
        runtime = managed_services(app)
        assert runtime is not None and len(runtime.vendor_catalog.installations) == 1


def test_inline_secret_configuration_uses_same_pinned_catalog(configuration):
    raw = json.dumps(document(configuration, credential=False))
    configuration.managed_services_config_json = SecretStr(raw)
    configuration.managed_services_config_sha256 = hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in repr(configuration)
    app = FastAPI()
    with managed_services_lifespan(app, configuration, no_session):
        runtime = managed_services(app)
        assert runtime is not None and len(runtime.vendor_catalog.installations) == 1
        assert not runtime.has_credentials
    configuration.managed_services_config_json = SecretStr(raw + " ")
    with pytest.raises(
        ValueError, match="^Managed service configuration is invalid or unavailable$"
    ):
        configured.load_managed_profile(configuration)


def test_file_and_inline_configuration_cannot_be_combined(tmp_path, configuration):
    path = install(tmp_path, configuration, document(configuration))
    configuration.managed_services_config_json = SecretStr(path.read_text())
    with pytest.raises(
        ValueError, match="^Managed service configuration is invalid or unavailable$"
    ):
        configured.load_managed_profile(configuration)


def test_empty_inline_default_does_not_enable_a_profile(configuration):
    configuration.managed_services_config_json = SecretStr("")
    app = FastAPI()
    with managed_services_lifespan(app, configuration, no_session):
        assert managed_services(app) is None


def test_conflicting_host_configuration_and_partial_startup_clean_up(tmp_path, configuration):
    install(tmp_path, configuration, document(configuration))
    app = FastAPI()
    configure_managed_services(app, ManagedServiceProfile())
    with pytest.raises(ValueError, match="cannot be combined"):
        with managed_services_lifespan(app, configuration, no_session):
            pytest.fail("conflicting configuration started")
    assert managed_services(app) is None
    assert app.state.managed_lifespan_active is False


def test_ordinary_api_entrypoint_loads_and_reloads_configuration(
    tmp_path, configuration, monkeypatch
):
    from cosmas_os.api import app as module

    install(tmp_path, configuration, document(configuration, credential=False))
    configuration.workspace_scheduling_enabled = False
    monkeypatch.setattr(module, "settings", configuration)
    monkeypatch.setattr(module, "SessionLocal", no_session)

    async def run():
        for _ in range(2):
            async with module.app.router.lifespan_context(module.app):
                runtime = managed_services(module.app)
                assert runtime is not None
                assert len(runtime.vendor_catalog.installations) == 1
                assert not runtime.has_credentials
            assert managed_services(module.app) is None

    asyncio.run(run())


@pytest.mark.parametrize("vendor", ["spruce", "stripe", "documo"])
def test_callbacks_bind_exact_reviewed_account(tmp_path, configuration, monkeypatch, vendor):
    doc = document(configuration, vendor)
    item = doc["payments" if vendor == "stripe" else "delivery"][0]
    rid = str(uuid4())
    if vendor != "stripe":
        item["routing"]["event_route_id"] = rid
    selected = dict(item["selection"], connection_id=str(uuid4()))
    event = {"selection": selected, "route_id": rid}
    if vendor in ("stripe", "spruce"):
        event["signing_secret"] = secret_ref("CALLBACK", "PRIVATE_signing")
        monkeypatch.setenv("COSMAS_MANAGED_SECRET_CALLBACK", "PRIVATE_signing")
    doc["events"] = [event]
    install(tmp_path, configuration, doc)
    profile = configured.load_managed_profile(configuration)
    assert profile.events is not None
    routes = configured.ManagedEventRoutes(
        profile.events, profile.vendor_catalog, profile.finance_catalog
    )
    route = routes.finance(rid) if vendor == "stripe" else routes.vendor(vendor, rid)
    assert route is not None and route.expected_selection is not None
    assert str(route.expected_selection.connection_id) == selected["connection_id"]
    # An installation ID cannot masquerade as a reviewed active version.
    event["selection"]["connection_id"] = item["selection"]["connection_id"]
    install(tmp_path, configuration, doc)
    with pytest.raises(
        ValueError, match="^Managed service configuration is invalid or unavailable$"
    ):
        configured.load_managed_profile(configuration)


def artifact_profile(tmp_path, settings, monkeypatch, *, permissions="rcw", query_suffix=""):
    expiry = (datetime.now(UTC) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    signature = f"sv=2025-01-05&sr=c&spr=https&sp={permissions}&se={expiry}&sig=invented"
    signature += query_suffix
    doc = document(settings, credential=False)
    doc["artifacts"] = {
        "backend": "azure_sas",
        "account_url": "https://inventedstore.blob.core.windows.net",
        "container_name": "vendor-artifacts",
        "credential": secret_ref("DOCUMENTS", signature),
    }
    settings.blob_backend = "azure"
    settings.azure_storage_account_url = doc["artifacts"]["account_url"]
    settings.azure_blob_container = doc["artifacts"]["container_name"]
    install(tmp_path, settings, doc)
    monkeypatch.setenv("COSMAS_MANAGED_SECRET_DOCUMENTS", signature)
    return configured.load_managed_profile(settings).artifact_store


def test_document_custody_uses_bound_store_and_closes_each_operation(
    tmp_path, configuration, monkeypatch
):
    configuration = hosted()
    store = artifact_profile(tmp_path, configuration, monkeypatch)
    assert store is not None
    data = b"%PDF-invented"
    scope = VendorArtifactScope(
        box_id=UUID(str(configuration.beta_box_id)),
        workspace_id=uuid4(),
        owner_id=uuid4(),
        document=DocumentBinding(
            artifact_id=uuid4(), byte_length=len(data), sha256=hashlib.sha256(data).hexdigest()
        ),
    )
    opened, closed, operations = [], [], []

    class Container:
        def __init__(self, **kwargs):
            opened.append(kwargs)

        def close(self):
            closed.append(True)

        def deadline(self):
            return time.monotonic() + 60

    class Store:
        def __init__(self, container, *, box_id):
            assert box_id == scope.box_id

        def put_verified(self, actual, content, *, deadline):
            assert actual == scope and content == data
            assert 0 < deadline - time.monotonic() <= 60
            operations.append("put")

        def read_verified(self, actual, *, deadline):
            assert actual == scope
            operations.append("read")
            return data

    monkeypatch.setattr(configured, "BoundedAzureArtifactContainer", Container)
    monkeypatch.setattr(configured, "AzureVendorArtifactStore", Store)
    store.put_verified(scope, data)
    assert store.read_verified(scope) == data
    assert operations == ["put", "read"] and len(opened) == len(closed) == 2
    with pytest.raises(ArtifactStoreError, match="^artifact_changed$"):
        store.read_verified(scope.model_copy(update={"box_id": uuid4()}))
    monkeypatch.setenv("COSMAS_MANAGED_SECRET_DOCUMENTS", "PRIVATE_changed")
    with pytest.raises(ArtifactStoreError, match="^storage_unavailable$"):
        store.read_verified(scope)
    assert len(opened) == 2


@pytest.mark.parametrize(
    "permissions,query_suffix",
    [("rcwdl", ""), ("rcw", "&ss=b"), ("rcw", "&srt=co"), ("rcw", "&si=broader-policy")],
)
def test_document_sas_with_broader_permissions_is_refused(
    tmp_path, configuration, monkeypatch, permissions, query_suffix
):
    configuration = hosted()
    store = artifact_profile(
        tmp_path, configuration, monkeypatch, permissions=permissions, query_suffix=query_suffix
    )
    assert isinstance(store, configured.ConfiguredArtifactStore)
    with pytest.raises(ValueError, match="not scoped"):
        store._container()
