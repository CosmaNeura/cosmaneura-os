"""Explicit provider installation must not create credentials or network clients."""

import asyncio
from types import SimpleNamespace

import pytest
from tests.unit.test_vendor_portal_contract import profile, selection

from cosmas_os.adapters import portal_services as runtime
from cosmas_os.adapters.portal_services import PortalServiceProfile, PortalServices
from cosmas_os.application.portal_setup import Installation, installation_mode


def settings(**changes):
    return SimpleNamespace(
        workspace_available=True,
        workspace_authenticated_enabled=True,
        auth_mode="clerk_jwt",
        cosmas_env="early_adopter_beta",
        portal_work_enabled=True,
        portal_io_enabled=False,
        **changes,
    )


def no_database():
    raise AssertionError("Installation opened a database")


@pytest.mark.asyncio
async def test_adapter_cleanup_is_bounded_and_cannot_suppress_an_operation_failure(monkeypatch):
    monkeypatch.setattr(runtime, "ADAPTER_CLOSE_SECONDS", 0.01)

    class Resource:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_error):
            return True

    with pytest.raises(ValueError, match="operation"):
        async with runtime.owned_adapter(Resource()):
            raise ValueError("operation")

    class SlowResource(Resource):
        async def __aexit__(self, *_error):
            await asyncio.sleep(1)

    with pytest.raises(TimeoutError):
        async with runtime.owned_adapter(SlowResource()):
            pass


def installed():
    named = profile().model_copy(
        update={"portal_id": "example_portal", "origins": ("https://portal.example.com",)}
    )
    return Installation(
        selection().model_copy(update={"environment": "production"}), named, "Example provider"
    )


def test_real_provider_requires_explicit_host_opt_in_and_supported_deployment():
    item = installed()
    with pytest.raises(ValueError):
        PortalServices(settings(), PortalServiceProfile(installations=(item,)), no_database)
    local = settings()
    local.cosmas_env = "synth_os"
    with pytest.raises(ValueError):
        PortalServices(
            local,
            PortalServiceProfile(installations=(item,), allow_live_profiles=True),
            no_database,
        )
    services = PortalServices(
        settings(),
        PortalServiceProfile(installations=(item,), allow_live_profiles=True),
        no_database,
    )
    assert installation_mode(next(iter(services.catalog.installations.values()))) == "production"
    assert not services.has_execution


def test_catalog_only_installation_does_not_instantiate_an_adapter():
    called = []

    def adapter(_context):
        called.append(True)
        raise AssertionError("Adapter created during setup")

    item = installed()
    services = PortalServices(
        settings(),
        PortalServiceProfile(
            installations=(item,),
            adapters={item.profile.portal_id: adapter},
            allow_live_profiles=True,
        ),
        no_database,
    )
    assert services.catalog.require(
        str(item.selection.box_id),
        str(item.selection.owner_id),
        str(item.selection.connection_id),
        item.profile.commitment(),
        item.selection.configuration_sha256,
    )
    assert called == [] and not services.has_execution


def test_credential_configuration_requires_exact_named_adapters():
    item = installed()

    async def credentials(_selected):
        raise AssertionError("Credential read during setup")

    with pytest.raises(ValueError):
        PortalServices(
            settings(),
            PortalServiceProfile(
                installations=(item,), credentials=credentials, allow_live_profiles=True
            ),
            no_database,
        )
    with pytest.raises(ValueError):
        PortalServices(
            settings(),
            PortalServiceProfile(
                installations=(item,),
                adapters={"different": lambda _: None},
                allow_live_profiles=True,
            ),
            no_database,
        )


def test_a_synthetic_label_cannot_disguise_a_production_installation():
    item = Installation(
        selection().model_copy(update={"environment": "production"}), profile(), "Misclassified"
    )
    with pytest.raises(ValueError):
        PortalServices(
            settings(),
            PortalServiceProfile(installations=(item,), allow_live_profiles=True),
            no_database,
        )
