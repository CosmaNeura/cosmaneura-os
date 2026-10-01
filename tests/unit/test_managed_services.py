import asyncio
from dataclasses import replace
from types import MappingProxyType
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from starlette.requests import Request
from tests.unit.test_scheduling_runtime import configuration as configuration
from tests.unit.test_vendor_connector_foundation import selection

from cosmas_os.adapters.managed_services import (
    CurrentIdentity,
    ManagedServiceProfile,
    ManagedServices,
    configure_managed_services,
    managed_services,
    managed_services_lifespan,
)
from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.api import finance_setup_routes
from cosmas_os.application import finance_settings, vendor_settings
from cosmas_os.application.finance_settings_execution import FinanceSettingsExecution
from cosmas_os.application.vendor_settings_execution import VendorSettingsExecution
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.ports.vendor_connectors import VendorError


def profile(provider=None):
    vendor = []
    for name, capability in [('spruce', 'spruce_secure_message'), ('srfax', 'srfax_fax'), ('documo', 'documo_fax')]:
        selected = selection(name).model_copy(update={"connection_id": uuid4()})
        routing = {"internal_endpoint_id": "invented_endpoint"} if name == 'spruce' else {"caller_id": "2125550199"}
        if name == "srfax":
            routing["sender_email"] = "fax@example.invalid"
        vendor.append(vendor_settings.Installation(selected, "Invented " + name, "Invented sender", routing, (capability,)))
    finance = finance_settings.Installation(selection('stripe').model_copy(update={"connection_id": uuid4()}), "Invented Stripe")
    return ManagedServiceProfile(vendor_settings.Catalog(vendor), finance_settings.Catalog((finance,)), provider)


def active(config, vendor):
    catalog = config.finance_catalog if vendor == 'stripe' else config.vendor_catalog
    installed = next(x.selection for x in catalog.installations.values() if x.selection.vendor == vendor)
    return installed.model_copy(update={"connection_id": uuid4()})


def no_session():
    raise AssertionError("configuration must not open a database session")


def enable(configuration):
    configuration.vendor_work_enabled = configuration.vendor_io_enabled = True
    configuration.finance_work_enabled = configuration.finance_io_enabled = True


def proof(value):
    return Credential(selection_sha256=value.commitment(), credential_ref=str(value.credential_ref), secret=SecretStr('PRIVATE_invented'))


async def current():
    return True


@pytest.mark.parametrize('vendor', ['spruce', 'srfax', 'documo', 'stripe'])
def test_exact_managed_account_gets_fresh_bound_credentials(configuration, vendor):
    enable(configuration)
    calls = []
    async def provider(value):
        calls.append(value)
        return proof(value)
    config = profile(provider)
    managed = ManagedServices(configuration, config, no_session)
    selected = active(config, vendor)
    first = asyncio.run(managed._credentials(selected))
    second = asyncio.run(managed._credentials(selected))
    assert first == second == proof(selected) and calls == [selected, selected]
    execution = managed.finance_execution(current) if vendor == 'stripe' else managed.vendor_execution(current)
    assert type(execution) is (FinanceSettingsExecution if vendor == 'stripe' else VendorSettingsExecution)
    assert execution.identity_current is not None
    assert asyncio.run(execution.identity_current()) is True
    assert execution.installed_catalog() is (managed.finance_catalog if vendor == 'stripe' else managed.vendor_catalog)


@pytest.mark.parametrize('field', ['box_id', 'owner_id', 'credential_ref', 'configuration_sha256', 'remote_account_id', 'environment'])
def test_changed_account_selection_never_acquires_credentials(configuration, field):
    enable(configuration)
    calls = []
    async def provider(value):
        calls.append(value)
        return proof(value)
    config = profile(provider)
    selected = active(config, 'spruce')
    changes = {'configuration_sha256': 'b' * 64, 'remote_account_id': 'different_account', 'environment': 'sandbox'}
    selected = selected.model_copy(update={field: changes.get(field, uuid4())})
    managed = ManagedServices(configuration, config, no_session)
    with pytest.raises(VendorError, match='^connection_changed$'):
        asyncio.run(managed._credentials(selected))
    assert calls == []


def test_installation_identifier_cannot_replace_reviewed_account_version(configuration):
    enable(configuration)
    calls = []
    async def provider(value):
        calls.append(value)
        return proof(value)
    config = profile(provider)
    installed = next(iter(config.vendor_catalog.installations.values())).selection
    managed = ManagedServices(configuration, config, no_session)
    with pytest.raises(VendorError, match='^connection_changed$'):
        asyncio.run(managed._credentials(installed))
    assert calls == []


@pytest.mark.parametrize('fault', ['exception', 'raw_secret', 'wrong_commitment', 'wrong_reference'])
def test_bad_provider_result_is_redacted(configuration, fault):
    enable(configuration)
    async def provider(value):
        if fault == 'exception':
            raise RuntimeError('PRIVATE credential acquisition failure')
        if fault == 'raw_secret':
            return SecretStr('PRIVATE')
        change = {'selection_sha256': '0' * 64} if fault == 'wrong_commitment' else {'credential_ref': str(uuid4())}
        return proof(value).model_copy(update=change)
    config = profile(provider)
    managed = ManagedServices(configuration, config, no_session)
    with pytest.raises(VendorError, match='^connection_changed$') as error:
        asyncio.run(managed._credentials(active(config, 'stripe')))
    assert 'PRIVATE' not in str(error.value)


@pytest.mark.parametrize('vendor', ['spruce', 'stripe'])
def test_disable_during_credential_acquisition_refuses_result(configuration, vendor):
    enable(configuration)
    async def provider(value):
        setattr(configuration, 'finance_io_enabled' if vendor == 'stripe' else 'vendor_io_enabled', False)
        return proof(value)
    config = profile(provider)
    managed = ManagedServices(configuration, config, no_session)
    with pytest.raises(VendorError, match='^connection_changed$'):
        asyncio.run(managed._credentials(active(config, vendor)))


@pytest.mark.parametrize('vendor', ['spruce', 'stripe'])
def test_disabled_or_stopped_profile_never_checks_identity_or_credentials(configuration, vendor):
    calls = []
    async def provider(value):
        calls.append('credential')
        return proof(value)
    async def identity():
        calls.append('identity')
        return True
    config = profile(provider)
    managed = ManagedServices(configuration, config, no_session)
    execution = managed.finance_execution(identity) if vendor == 'stripe' else managed.vendor_execution(identity)
    assert execution.identity_current is not None
    assert asyncio.run(execution.identity_current()) is False
    with pytest.raises(VendorError):
        asyncio.run(managed._credentials(active(config, vendor)))
    enable(configuration)
    managed.close()
    assert asyncio.run(execution.identity_current()) is False
    with pytest.raises(VendorError):
        asyncio.run(managed._credentials(active(config, vendor)))
    with pytest.raises(VendorError, match='connector_disabled'):
        managed.vendor_execution(identity)
    assert calls == []


def test_identity_must_still_be_current_after_async_check(configuration):
    enable(configuration)
    async def provider(value):
        return proof(value)
    managed = ManagedServices(configuration, profile(provider), no_session)
    async def revoked_during_check():
        configuration.finance_io_enabled = False
        return True
    execution = managed.finance_execution(revoked_during_check)
    assert execution.identity_current is not None
    assert asyncio.run(execution.identity_current()) is False


def test_configuration_and_startup_leave_gates_and_external_resources_untouched(configuration, monkeypatch):
    from cosmas_os.api import app as api
    monkeypatch.setattr(api, 'settings', configuration)
    calls = []
    async def provider(value):
        calls.append('credential')
        return proof(value)
    config = profile(provider)
    app = FastAPI()
    configure_managed_services(app, config)
    before = configuration.model_dump()
    request = Request({'type': 'http', 'app': app})
    held = []
    async def exercise():
        async with api.lifespan(app):
            managed = managed_services(app)
            assert managed is not None
            held.append(managed)
            assert api._vendor_installed_catalog(request) is managed.vendor_catalog
            assert finance_setup_routes.installed_catalog(request) is managed.finance_catalog
            assert api._vendor_artifact_store(request) is None
            assert api._vendor_execution_factory(request) == managed.vendor_execution
            assert api._finance_execution_factory(request) == managed.finance_execution
            assert app.dependency_overrides == {} and calls == []
    asyncio.run(exercise())
    assert configuration.model_dump() == before and calls == []
    assert managed_services(app) is None and not held[0].has_credentials
    assert api._vendor_execution_factory(request) is api._finance_execution_factory(request) is None
    assert api._vendor_installed_catalog(request) is vendor_settings.EMPTY_CATALOG
    assert finance_setup_routes.installed_catalog(request) is finance_settings.EMPTY_CATALOG


def test_setup_only_profile_has_catalogs_without_execution_credentials(configuration):
    config = profile()
    app = FastAPI()
    configure_managed_services(app, config)
    with managed_services_lifespan(app, configuration, no_session):
        managed = managed_services(app)
        assert managed is not None and not managed.has_credentials
        assert len(managed.vendor_catalog.installations) == 3
        with pytest.raises(VendorError, match='connector_disabled'):
            managed.vendor_execution(current)


def test_catalog_copy_preserves_owner_boundary_and_cannot_be_replaced_by_host_mutation(configuration):
    config = profile()
    managed = ManagedServices(configuration, config, no_session)
    item = next(iter(managed.vendor_catalog.installations.values()))
    with pytest.raises(WorkspaceError):
        managed.vendor_catalog.require(str(item.selection.box_id), str(uuid4()), str(item.selection.connection_id), item.public()['installation_sha256'])
    config.vendor_catalog.installations = MappingProxyType({})
    assert len(managed.vendor_catalog.installations) == 3


def test_runtime_rejects_ambiguous_installed_account_before_credentials(configuration):
    enable(configuration)
    calls = []
    async def provider(value):
        calls.append(value)
        return proof(value)
    config = profile(provider)
    first = next(iter(config.vendor_catalog.installations.values()))
    duplicate = replace(first, selection=first.selection.model_copy(update={'connection_id': uuid4()}))
    config = replace(config, vendor_catalog=vendor_settings.Catalog((first, duplicate)))
    managed = ManagedServices(configuration, config, no_session)
    with pytest.raises(VendorError):
        asyncio.run(managed._credentials(active(config, first.selection.vendor)))
    assert calls == []


def test_profile_is_installable_only_once_before_startup(configuration):
    app = FastAPI()
    config = profile()
    configure_managed_services(app, config)
    with pytest.raises(ValueError):
        configure_managed_services(app, config)
    with managed_services_lifespan(app, configuration, no_session):
        first = managed_services(app)
        with pytest.raises(RuntimeError), managed_services_lifespan(app, configuration, no_session):
            pytest.fail('overlapping lifespan')
        assert managed_services(app) is first
    with pytest.raises(ValueError):
        configure_managed_services(app, config)


def test_unsupported_identity_callback_does_not_construct_transport(configuration):
    calls = []
    async def provider(value):
        return proof(value)
    config = replace(profile(provider), transport_factory=lambda: calls.append('transport'))
    managed = ManagedServices(configuration, config, no_session)
    with pytest.raises(ValueError):
        managed.vendor_execution(cast(CurrentIdentity, None))
    with pytest.raises(ValueError):
        managed.finance_execution(cast(CurrentIdentity, None))
    assert calls == []
