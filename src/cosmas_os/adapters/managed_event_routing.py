"""Exact installed-account event routes; lookup performs no I/O or activation."""

from dataclasses import dataclass, replace
from types import MappingProxyType
from uuid import UUID

from cosmas_os.adapters.vendor_connectors.transport import MAX_HEADER_BYTES
from cosmas_os.application import finance_settings, vendor_settings
from cosmas_os.application.finance_events import FinanceEventRoute
from cosmas_os.application.vendor_events import EventRoute
from cosmas_os.ports.vendor_connectors import ConnectionSelection


@dataclass(frozen=True, repr=False)
class ManagedEventProfile:
    vendor: tuple[EventRoute, ...] = ()
    finance: tuple[FinanceEventRoute, ...] = ()


def installed_selection(supplied, catalog):
    if not isinstance(supplied, ConnectionSelection):
        raise ValueError('Exact installed event selection required')
    selected = ConnectionSelection.model_validate(supplied.model_dump(mode='python'))
    matches = [item for item in catalog.installations.values()
        if item.selection.model_copy(update={'connection_id': selected.connection_id}) == selected]
    if len(matches) != 1 or matches[0].selection.connection_id == selected.connection_id:
        raise ValueError('Distinct reviewed event account version required')
    return selected, matches[0]


def route_id(value):
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError('Canonical event route identifier required')
    return value


def signing_secret(value):
    if type(value) is not bytes or not 1 <= len(value) <= MAX_HEADER_BYTES:
        raise ValueError('Explicit bounded signing secret required')
    return value


class ManagedEventRoutes:
    def __init__(self, profile: ManagedEventProfile, vendor: vendor_settings.Catalog, finance: finance_settings.Catalog):
        if (not isinstance(profile, ManagedEventProfile) or type(profile.vendor) is not tuple
                or type(profile.finance) is not tuple or len(profile.vendor) + len(profile.finance) > 1000):
            raise ValueError('Bounded explicit event routes required')
        delivery, payments = {}, {}
        for route in profile.vendor:
            if type(route) is not EventRoute:
                raise ValueError('Exact delivery event route required')
            selected, installed = installed_selection(route.expected_selection, vendor)
            rid = route_id(route.route_id)
            if (route.vendor != selected.vendor or route.connection_version_id != str(selected.connection_id)
                    or installed.routing.get('event_route_id') != rid or (route.vendor, rid) in delivery):
                raise ValueError('Delivery event account binding changed')
            if route.vendor == 'spruce':
                signing_secret(route.signing_secret)
            elif route.signing_secret is not None:
                raise ValueError('Unsigned fax notifications must remain hints')
            delivery[route.vendor, rid] = replace(route, expected_selection=selected)
        for route in profile.finance:
            if type(route) is not FinanceEventRoute:
                raise ValueError('Exact finance event route required')
            selected, _ = installed_selection(route.expected_selection, finance)
            rid = route_id(route.route_id)
            if route.connection_id != str(selected.connection_id) or rid in payments:
                raise ValueError('Finance event account binding changed')
            signing_secret(route.signing_secret)
            payments[rid] = replace(route, expected_selection=selected)
        self.delivery = MappingProxyType(delivery)
        self.payments = MappingProxyType(payments)

    def vendor(self, vendor: str, route: str) -> EventRoute | None:
        return self.delivery.get((vendor, route))

    def finance(self, route: str) -> FinanceEventRoute | None:
        return self.payments.get(route)
