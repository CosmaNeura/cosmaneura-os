"""Normal callback startup with actual account rows, signatures and late evidence."""

import base64
import hmac
import json
import time
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration import test_finance_settings as finance_fixture
from tests.integration import test_vendor_settings as vendor_fixture
from tests.integration.test_managed_services import managed_case as managed_case
from tests.integration.test_vendor_events import raw_event

from cosmas_os.adapters.managed_event_routing import ManagedEventProfile
from cosmas_os.adapters.vendor_connectors.transport import STRIPE_VERSION
from cosmas_os.api import finance_setup_schemas
from cosmas_os.application import finance_events, vendor_events, vendor_settings
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.config import settings
from cosmas_os.finance_models import FinanceConnectionVersion, FinanceEventCandidate
from cosmas_os.models import Operation
from cosmas_os.ports.vendor_connectors import ConnectionSelection
from cosmas_os.vendor_models import (
    VendorConnectionVersion,
    VendorEventCandidate,
    VendorProviderObservation,
)

SECRET = b'invented-managed-event-secret'


@pytest.fixture(params=['spruce', 'stripe'])
def event_case(managed_case, monkeypatch, request):
    case, vendor = managed_case, request.param
    rid = str(uuid4())
    config = case.profile
    if vendor == 'spruce':
        items = [replace(item, routing={**item.routing, 'event_route_id': rid}) if item.selection.vendor == vendor else item
            for item in config.vendor_catalog.installations.values()]
        catalog = vendor_settings.Catalog(items)
        case.vendor['installed'] = catalog
        config = replace(config, vendor_catalog=catalog)
        with Session(case.engine, expire_on_commit=False) as s:
            account = vendor_fixture.account(s, case.vendor)
            detail = vendor_fixture.view(s, case.vendor, account)
            native = s.get(VendorConnectionVersion, detail['review']['connection_version_id'])
            assert native is not None
            selected = ConnectionSelection.model_validate(native.private_selection)
        route = vendor_events.EventRoute(rid, str(selected.connection_id), vendor, SECRET, selected)
        events = ManagedEventProfile((route,), ())
        body = raw_event()
        headers = {'X-Spruce-Signature': base64.b64encode(hmac.digest(SECRET, body, 'sha256')).decode()}
        path = '/vendor-events/spruce/' + rid
    else:
        with Session(case.engine, expire_on_commit=False) as s:
            account = finance_fixture.account(s, case.finance)
            native = s.get(FinanceConnectionVersion, account['review']['connection_version_id'])
            assert native is not None
            selected = ConnectionSelection.model_validate(native.private_selection)
        route = finance_events.FinanceEventRoute(rid, str(selected.connection_id), SECRET, selected)
        events = ManagedEventProfile((), (route,))
        body = json.dumps({'id': 'evt_ManagedInvented', 'object': 'event', 'type': 'payment_intent.succeeded',
            'api_version': STRIPE_VERSION, 'livemode': False,
            'data': {'object': {'object': 'payment_intent', 'id': 'pi_ManagedInvented', 'livemode': False, 'client_secret': 'PRIVATE'}}}).encode()
        timestamp = str(int(time.time()))
        headers = {'Stripe-Signature': 't=' + timestamp + ',v1=' + hmac.digest(SECRET, timestamp.encode() + b'.' + body, 'sha256').hex()}
        path = '/finance-events/stripe/' + rid
    config = replace(config, events=events)
    monkeypatch.setattr(settings, 'vendor_events_enabled', True)
    monkeypatch.setattr(settings, 'finance_events_enabled', True)
    for name in ['vendor_io_enabled', 'finance_io_enabled', 'vendor_work_enabled', 'finance_work_enabled']:
        monkeypatch.setattr(settings, name, False)
    return case, vendor, config, route, account, body, headers, path


def counts(case, vendor, connection):
    model = VendorEventCandidate if vendor == 'spruce' else FinanceEventCandidate
    with Session(case.engine) as s:
        candidate = s.scalar(select(func.count()).select_from(model).where(model.connection_version_id == connection))
        operations = s.scalar(select(func.count()).select_from(Operation).where(Operation.box_id == case.vendor['box']))
        observations = s.scalar(select(func.count()).select_from(VendorProviderObservation).where(VendorProviderObservation.box_id == case.vendor['box']))
    return candidate, operations, observations


def test_normal_callbacks_verify_raw_signature_deduplicate_and_survive_restart(event_case, monkeypatch):
    case, vendor, config, route, _, body, headers, path = event_case
    connection = str(route.expected_selection.connection_id)
    with case.start(config) as client:
        assert client.post(path, content=body + b' ', headers=headers).status_code == 400
        assert client.post(path.rsplit('/', 1)[0] + '/' + str(uuid4()), content=body, headers=headers).status_code == 404
        result = client.post(path, content=body, headers=headers)
        assert result.status_code == 200 and result.json() == {'received': True}
        assert 'PRIVATE' not in result.text
    with case.start(config) as client:
        assert client.post(path, content=body, headers=headers).status_code == 200
        monkeypatch.setattr(settings, 'vendor_events_enabled' if vendor == 'spruce' else 'finance_events_enabled', False)
        assert client.post(path, content=body, headers=headers).status_code == 404
    assert counts(case, vendor, connection) == (1, 0, 0)
    assert not case.calls and not case.wire


def test_disabled_account_and_human_do_not_erase_signed_late_evidence(event_case):
    case, vendor, config, route, account, body, headers, path = event_case
    with Session(case.engine) as s:
        if vendor == 'spruce':
            vendor_fixture.command(s, case.vendor, account, 'disable')
        else:
            value = finance_setup_schemas.Disable(**finance_fixture.bound(account), confirm_disable=True)
            finance_fixture.command(s, case.finance, 'disable', value)
        from cosmas_os.models import ExternalIdentity
        identity = s.get(ExternalIdentity, case.owner_binding)
        assert identity is not None
        identity.active = False
        s.commit()
    with case.start(config) as client:
        response = client.post(path, content=body, headers=headers)
        assert response.status_code == 200 and response.json() == {'received': True}
    assert counts(case, vendor, str(route.expected_selection.connection_id)) == (1, 0, 0)
    assert not case.calls and not case.wire


def test_receiver_refuses_configured_selection_that_differs_from_actual_account(event_case):
    case, vendor, _, route, _, body, headers, _ = event_case
    changed = route.expected_selection.model_copy(update={'owner_id': uuid4()})
    wrong = replace(route, expected_selection=changed)
    with Session(case.engine) as s, pytest.raises(WorkspaceError) as error:
        if vendor == 'spruce':
            vendor_events.ingest(s, wrong, body, signature=headers['X-Spruce-Signature'])
        else:
            from cosmas_os.application.finance_work import FinancePolicy
            finance_events.ingest(s, wrong, body, headers['Stripe-Signature'], policy=FinancePolicy(events_enabled=True))
    assert error.value.status == 404
    assert counts(case, vendor, str(route.expected_selection.connection_id)) == (0, 0, 0)
