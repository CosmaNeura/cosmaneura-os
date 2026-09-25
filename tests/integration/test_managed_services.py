"""Ordinary managed startup, real PostgreSQL authority and signed HTTP requests."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration import test_finance_settings as finance_fixture
from tests.integration import test_vendor_settings as vendor_fixture
from tests.integration.test_vendor_work import bound, proposal, vendor_case

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.adapters.managed_services import (
    ManagedServiceProfile,
    configure_managed_services,
    managed_services,
)
from cosmas_os.adapters.vendor_artifacts import LocalVendorArtifactStore
from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.api import app as api
from cosmas_os.api import vendor_setup_schemas as vendor_schema
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.application import services
from cosmas_os.config import settings
from cosmas_os.db import make_session_factory
from cosmas_os.finance_models import FinanceSubmitClaim
from cosmas_os.models import ExternalIdentity, Operation, Principal
from cosmas_os.vendor_models import VendorSubmitClaim


@pytest.fixture
def managed_case(engine, tmp_path, monkeypatch):
    # Every case commits a new invented practice, so asynchronous execution uses
    # real independent transactions; no existing account or operation is reused.
    monkeypatch.setattr(settings, 'workspace_enabled', True)
    monkeypatch.setattr(settings, 'vendor_work_enabled', True)
    subjects = {name: name + '_' + uuid4().hex for name in ('owner', 'peer')}
    def unwrap(fixture, *args):
        make = getattr(fixture, '__wrapped__', None)
        assert callable(make)
        value = make(*args)
        assert isinstance(value, dict)
        return value
    with Session(engine, expire_on_commit=False) as s:
        seed = services.provision_box(services.Container(s, blob=LocalBlobAdapter(tmp_path / 'seed')), 'Invented managed startup')
        c = unwrap(vendor_case, s, seed)
        vendor = unwrap(vendor_fixture.setup_case, c)
        finance = unwrap(finance_fixture.case, s, c)
        peer = Principal(box_id=c['box'], principal_type='human', display_name='Invented peer', state='active', is_owner=True)
        s.add(peer)
        s.flush()
        identities = []
        for actor, subject in [(c['actor'], 'owner'), (peer.id, 'peer')]:
            binding = ExternalIdentity(box_id=c['box'], principal_id=actor, provider='clerk', issuer='https://clerk.example.invalid',
                subject=subjects[subject], organization_id='org_invented', reviewed_by='Invented review', evidence_ref='test:w39-managed')
            s.add(binding)
            identities.append(binding)
        s.commit()
        owner_binding = identities[0].id
    for name, value in dict(workspace_authenticated_enabled=True, auth_mode='clerk_jwt', synth_seed=False,
            workspace_routines_enabled=False, workspace_llm_backend='disabled', vendor_setup_enabled=True,
            vendor_io_enabled=True, vendor_events_enabled=False, finance_setup_enabled=True,
            finance_work_enabled=True, finance_io_enabled=True, finance_events_enabled=False,
            clerk_issuer='https://clerk.example.invalid', clerk_jwks_url='https://clerk.example.invalid/.well-known/jwks.json',
            clerk_audience='cosmas-workspace-local', clerk_organization_id='org_invented',
            clerk_authorized_parties='http://localhost:5173', cors_allowed_origins='http://localhost:5173', beta_box_id=c['box']).items():
        monkeypatch.setattr(settings, name, value)
    assert settings.runtime_configuration_errors() == []
    monkeypatch.setattr(api, 'SessionLocal', make_session_factory(engine))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_keys(self, *, refresh):
            return [SimpleNamespace(key_id='invented-managed', key=key.public_key())]

    verifier = ClerkTokenVerifier(settings, jwks_client=Keys(), start_background_refresh=False)
    monkeypatch.setattr(api, '_clerk_verifier', lambda: verifier)
    calls, wire, hooks, runtimes = [], [], {}, []

    async def credentials(selected):
        calls.append(selected.commitment())
        if 'credential' in hooks:
            hooks['credential']()
        secret = 'sk_test_PRIVATE_invented' if selected.vendor == 'stripe' else 'PRIVATE-invented'
        return Credential(selection_sha256=selected.commitment(), credential_ref=str(selected.credential_ref), secret=SecretStr(secret))

    async def receiver(request):
        assert request.url.scheme == 'https' and request.method == 'POST'
        wire.append((request.url.host, request.url.path))
        if request.url.host == 'api.sprucehealth.com':
            return httpx.Response(200, json={'requestId': 'asyncRequest_w39invented'})
        assert request.url.host == 'api.stripe.com' and request.url.path == '/v1/payment_intents'
        from urllib.parse import parse_qs
        body = parse_qs(request.content.decode())
        return httpx.Response(200, json={'object': 'payment_intent', 'id': 'pi_W39Invented', 'customer': body['customer'][0],
            'amount': int(body['amount'][0]), 'currency': 'usd', 'amount_received': 0, 'livemode': False,
            'status': 'requires_payment_method', 'client_secret': 'PRIVATE-provider'})

    profile = ManagedServiceProfile(vendor['installed'], finance['installed'], credentials,
        LocalVendorArtifactStore(tmp_path / 'private-artifacts'), lambda: httpx.MockTransport(receiver))

    def start(profile_override=None):
        app = FastAPI(lifespan=api.lifespan, middleware=list(api.app.user_middleware))
        app.exception_handlers.update(api.app.exception_handlers)
        # Reuse exact registered routes without merging a second lifespan.
        app.router.routes.extend(api.app.router.routes)
        configure_managed_services(app, profile if profile_override is None else profile_override)
        runtimes.append(app)
        assert not app.dependency_overrides
        return TestClient(app)

    def headers(family, subject='owner'):
        now = datetime.now(UTC)
        token = jwt.encode(dict(sub=subjects[subject], iss=settings.clerk_issuer, aud=settings.clerk_audience,
            sid='session_w39managed', azp='http://localhost:5173', org_id='org_invented',
            iat=now, nbf=now, exp=now + timedelta(minutes=5)), key, algorithm='RS256', headers={'kid': 'invented-managed'})
        return {'Authorization': 'Bearer ' + token, 'X-Cosmas-Draft-Recovery': '2', f'X-Cosmas-{family}-Contract': '1'}

    yield SimpleNamespace(vendor=vendor, finance=finance, start=start, headers=headers, calls=calls, wire=wire,
        hooks=hooks, engine=engine, owner_binding=owner_binding, runtimes=runtimes, output=tmp_path, profile=profile)
    assert all(managed_services(app) is None for app in runtimes)


def ok(response):
    assert response.status_code == 200, response.text
    assert 'PRIVATE' not in response.text and 'credential_ref' not in response.text
    return response.json()


def prepare(case, client, vendor):
    if vendor == 'stripe':
        with Session(case.engine, expire_on_commit=False) as s:
            a, m = finance_fixture.ready(s, case.finance)
            _, tid, detail = finance_fixture.approved_payment(s, case.finance, a, m)
        return f"/workspaces/{case.finance['wid']}/finance-work/{tid}", detail, case.headers('Finance')
    c, h = case.vendor, case.headers('Vendor-Setup')
    req = vendor_fixture.account_request(c)
    receipt = ok(client.post('/vendor-settings/propose_account', headers=h, json=req.public()))
    activation = vendor_schema.Activation(**vendor_fixture.binding(receipt), idempotency_key=str(uuid4()),
        reviewed_account=True, reviewed_environment=True, reviewed_sender=True, reviewed_capabilities=True, confirm_local_activation=True)
    account = ok(client.post('/vendor-settings/activate', headers=h, json=activation.public()))
    recipient = vendor_fixture.recipient_request(c, account)
    receipt = ok(client.post('/vendor-settings/propose_recipient', headers=h, json=recipient.public()))
    activation = vendor_schema.Activation(**vendor_fixture.binding(receipt), idempotency_key=str(uuid4()),
        reviewed_account=True, reviewed_environment=True, reviewed_sender=True, reviewed_capabilities=True,
        confirm_local_activation=True, reviewed_patient=True, reviewed_recipient=True, reviewed_permission=True)
    ok(client.post('/vendor-settings/activate', headers=h, json=activation.public()))
    detail = ok(client.get('/vendor-settings/' + req.setup_id, headers=h))
    h = case.headers('Vendor')
    root = f"/workspaces/{c['wid']}/vendor-work"
    options = ok(client.get(root + '/options', headers=h))
    connection = next(x for x in options['connections'] if x['id'] == detail['review']['connection_version_id'])
    correspondence = next(x for x in options['correspondences'] if x['connection_id'] == connection['id'])
    request = proposal(c).public()
    request['connection'] = {k: connection[k] for k in ('id', 'revision', 'public_sha256')}
    request['correspondence'] = {k: correspondence[k] for k in ('id', 'revision', 'public_sha256')}
    receipt = ok(client.post(root, headers=h, json=request))
    path = root + '/' + receipt['effect']['ticket_id']
    detail = ok(client.get(path, headers=h))
    ok(client.post(path + '/decide', headers=h, json=bound(detail, review_sha256=detail['review_sha256'], choice='approve')))
    return path, ok(client.get(path, headers=h)), h


@pytest.mark.parametrize('vendor', ['spruce', 'stripe'])
def test_normal_signed_startup_keeps_pending_account_private_across_restart(managed_case, vendor):
    case = managed_case
    family = 'Vendor-Setup' if vendor == 'spruce' else 'Finance-Setup'
    root = '/vendor-settings' if vendor == 'spruce' else '/finance-setup'
    req = vendor_fixture.account_request(case.vendor) if vendor == 'spruce' else case.finance['account_request']
    with case.start() as client:
        page = ok(client.get(root, headers=case.headers(family)))
        assert len(page['installed_accounts']) == (3 if vendor == 'spruce' else 1)
        ok(client.post(root + '/propose_account', headers=case.headers(family), json=req.public()))
        saved = ok(client.get(root + '/' + req.setup_id, headers=case.headers(family)))
        assert saved['summary']['usable_locally'] is False
    with case.start() as client:
        assert ok(client.get(root + '/' + req.setup_id, headers=case.headers(family))) == saved
        assert client.get(root + '/' + req.setup_id, headers=case.headers(family, 'peer')).status_code == 404
    assert not case.calls and not case.wire


@pytest.mark.parametrize('vendor', ['spruce', 'stripe'])
def test_normal_signed_submission_and_saved_result_survive_restart(managed_case, vendor):
    case = managed_case
    with case.start() as client:
        path, detail, headers = prepare(case, client, vendor)
        ok(client.post(path + '/submit', headers=headers, json=bound(detail)))
        saved = ok(client.get(path, headers=headers))
    assert len(case.calls) == len(case.wire) == 1
    with case.start() as client:
        restored = ok(client.get(path, headers=headers))
        if vendor == 'spruce':
            assert datetime.fromisoformat(restored['observed_at']) >= datetime.fromisoformat(saved['observed_at'])
            assert {k: v for k, v in restored.items() if k != 'observed_at'} == {k: v for k, v in saved.items() if k != 'observed_at'}
        else:
            assert restored == saved
        assert client.get(path, headers=case.headers('Finance' if vendor == 'stripe' else 'Vendor', 'peer')).status_code == 404
    with Session(case.engine) as s:
        op = s.get(Operation, detail['summary']['operation_id'])
        assert op is not None and op.attempt_count == 1
        claim = FinanceSubmitClaim if vendor == 'stripe' else VendorSubmitClaim
        assert s.get(claim, op.id) is not None
    assert len(case.calls) == len(case.wire) == 1
    (case.output / 'managed-result.json').write_text(json.dumps({'vendor': vendor, 'saved': saved,
        'credential_acquisitions': len(case.calls), 'wire_calls': case.wire, 'route_overrides': 0}, indent=2))


@pytest.mark.parametrize('vendor', ['spruce', 'stripe'])
@pytest.mark.parametrize('fault', ['disable', 'identity'])
def test_current_authority_loss_during_acquisition_never_dispatches(managed_case, monkeypatch, vendor, fault):
    case = managed_case
    with case.start() as client:
        path, detail, headers = prepare(case, client, vendor)
        def revoke():
            if fault == 'disable':
                monkeypatch.setattr(settings, 'finance_io_enabled' if vendor == 'stripe' else 'vendor_io_enabled', False)
            else:
                with Session(case.engine) as s:
                    identity = s.get(ExternalIdentity, case.owner_binding)
                    assert identity is not None
                    identity.active = False
                    s.commit()
        case.hooks['credential'] = revoke
        response = client.post(path + '/submit', headers=headers, json=bound(detail))
        assert response.status_code in {200, 403, 409} and 'PRIVATE' not in response.text
    assert len(case.calls) == 1 and not case.wire
    with Session(case.engine) as s:
        op = s.scalar(select(Operation).where(Operation.id == detail['summary']['operation_id']))
        assert op is not None and op.attempt_count == 1 and op.status != 'succeeded'
