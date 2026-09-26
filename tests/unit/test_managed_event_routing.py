"""Pure configuration checks preserve exact private callback scope and gates."""

from dataclasses import replace
from uuid import uuid4

import pytest
from tests.unit.test_managed_services import no_session, profile
from tests.unit.test_scheduling_runtime import configuration as configuration

from cosmas_os.adapters.managed_event_routing import ManagedEventProfile, ManagedEventRoutes
from cosmas_os.adapters.managed_services import ManagedServices
from cosmas_os.application import vendor_settings
from cosmas_os.application.finance_events import FinanceEventRoute
from cosmas_os.application.vendor_events import EventRoute


def configured():
    original = profile()
    installed, routes = [], []
    for item in original.vendor_catalog.installations.values():
        rid = str(uuid4())
        installed.append(replace(item, routing={**item.routing, 'event_route_id': rid}))
        selected = item.selection.model_copy(update={'connection_id': uuid4()})
        routes.append(EventRoute(rid, str(selected.connection_id), selected.vendor,
            b'invented-secret' if selected.vendor == 'spruce' else None, selected))
    selected = next(iter(original.finance_catalog.installations.values())).selection.model_copy(update={'connection_id': uuid4()})
    finance = FinanceEventRoute(str(uuid4()), str(selected.connection_id), b'invented-finance-secret', selected)
    return replace(original, vendor_catalog=vendor_settings.Catalog(installed), events=ManagedEventProfile(tuple(routes), (finance,)))


def test_event_configuration_and_lookup_do_not_open_database_or_enable_work(configuration):
    config = configured()
    assert config.events is not None
    managed = ManagedServices(configuration, config, no_session)
    before = configuration.model_dump()
    for route in config.events.vendor:
        assert managed.vendor_event(route.vendor, route.route_id) is None
    assert managed.finance_event(config.events.finance[0].route_id) is None
    assert configuration.model_dump() == before
    configuration.vendor_events_enabled = configuration.finance_events_enabled = True
    assert not configuration.vendor_io_enabled and not configuration.finance_io_enabled
    for route in config.events.vendor:
        actual = managed.vendor_event(route.vendor, route.route_id)
        assert actual == route and actual is not route
        assert managed.vendor_event('other', route.route_id) is None
    assert managed.finance_event(config.events.finance[0].route_id) == config.events.finance[0]
    managed.close()
    assert managed.vendor_event('spruce', config.events.vendor[0].route_id) is None
    assert managed.finance_event(config.events.finance[0].route_id) is None


@pytest.mark.parametrize('change', ['missing_selection', 'owner', 'box', 'credential', 'native_id', 'route_id', 'duplicate', 'secret', 'vendor'])
def test_invalid_delivery_event_binding_fails_before_resources(configuration, change):
    config = configured()
    assert config.events is not None
    route = config.events.vendor[0]
    assert route.expected_selection is not None
    changes = {'missing_selection': {'expected_selection': None}, 'native_id': {'connection_version_id': str(uuid4())},
        'route_id': {'route_id': str(uuid4())}, 'secret': {'signing_secret': b''}, 'vendor': {'vendor': 'stripe'}}
    if change in {'owner', 'box', 'credential'}:
        field = {'owner': 'owner_id', 'box': 'box_id', 'credential': 'credential_ref'}[change]
        route = replace(route, expected_selection=route.expected_selection.model_copy(update={field: uuid4()}))
    else:
        route = replace(route, **changes.get(change, {}))
    events = ManagedEventProfile((route, route) if change == 'duplicate' else (route,), ())
    with pytest.raises(ValueError):
        ManagedServices(configuration, replace(config, events=events), no_session)


@pytest.mark.parametrize('change', ['missing_selection', 'native_id', 'duplicate', 'secret'])
def test_invalid_finance_event_binding_fails_before_resources(configuration, change):
    config = configured()
    assert config.events is not None
    route = config.events.finance[0]
    changes = {'missing_selection': {'expected_selection': None}, 'native_id': {'connection_id': str(uuid4())}, 'secret': {'signing_secret': b''}}
    route = replace(route, **changes.get(change, {}))
    events = ManagedEventProfile((), (route, route) if change == 'duplicate' else (route,))
    with pytest.raises(ValueError):
        ManagedServices(configuration, replace(config, events=events), no_session)


def test_unsigned_fax_route_cannot_gain_signature_authority(configuration):
    config = configured()
    assert config.events is not None
    fax = config.events.vendor[1]
    with pytest.raises(ValueError):
        ManagedEventRoutes(ManagedEventProfile((replace(fax, signing_secret=b'claimed-signature'),), ()), config.vendor_catalog, config.finance_catalog)


def test_installation_id_is_never_accepted_as_a_reviewed_event_version(configuration):
    config = configured()
    assert config.events is not None
    route = config.events.finance[0]
    selected = next(iter(config.finance_catalog.installations.values())).selection
    route = replace(route, expected_selection=selected, connection_id=str(selected.connection_id))
    with pytest.raises(ValueError):
        ManagedServices(configuration, replace(config, events=ManagedEventProfile((), (route,))), no_session)
