"""Actual signed HTTP/PG callback journey; Clerk and Google I/O is synthetic."""
import base64
import json
import time
from contextlib import ExitStack
from contextvars import Context
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from tests.enrollment.test_native_practice_profile import invented_native_measurement
from tests.unit.test_personal_connection_failure import connection as connection
from tests.unit.test_personal_connection_failure import start as legacy_start

from cosmas_os.adapters.google_callback_broker import (
    HttpGoogleRegistrationPort,
    HttpGoogleRelayPort,
)
from cosmas_os.adapters.google_connection import (
    CALENDAR_SCOPE,
    FULL_MAIL_SCOPE,
    SCOPES,
    GooglePersonalConnection,
)
from cosmas_os.adapters.google_connection_runtime import google_connection_lifespan
from cosmas_os.api.auth import ClerkTokenVerifier, authenticate_request, native_clerk_origin
from cosmas_os.api.google_connection_routes import PATH, GoogleConnectionBoundary, router
from cosmas_os.enrollment.admission import derive_runtime_admission_key
from cosmas_os.enrollment.api import create_app
from cosmas_os.enrollment.auth import ClerkEnrollmentVerifier
from cosmas_os.enrollment.domain import BAA_DOC_ID, BAA_SHA256, BAA_VERSION, HumanIdentity, now_utc
from cosmas_os.enrollment.migration import upgrade
from cosmas_os.enrollment.models import Command, Practice
from cosmas_os.enrollment.service import EnrollmentService
from cosmas_os.enrollment.synthetic import SyntheticCommerce, synthetic_settings
from cosmas_os.enrollment.workspace import (
    NativeWorkspaceProof,
    NativeWorkspaceProofRegistry,
    NativeWorkspaceScope,
)
from cosmas_os.models import BoxContext, ExternalIdentity, Principal
from cosmas_os.ports.google_callback_broker import (
    BROKER_HEADER,
    RELAY_PATH,
    Relay,
    broker_key,
    encoded,
    signed,
)

BROKER = "https://enrollment-api.staging.cosmas.ai"


@pytest.fixture
def journey(engine):
    stack = ExitStack()
    schema = "broker_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(text('CREATE SCHEMA "' + schema + '"'))
    registry = create_engine(engine.url, connect_args={"options": "-csearch_path=" + schema}, hide_parameters=True)
    upgrade(registry)
    settings = synthetic_settings()
    settings.clerk_issuer = "https://broker-fixture.clerk.accounts.dev"
    settings.clerk_publishable_key = "pk_test_" + base64.b64encode(b"broker-fixture.clerk.accounts.dev$").decode()
    settings.native_account_enabled = True
    settings.native_authorized_origins = ["capacitor://localhost", "app://cosmas"]
    settings.workspace_allocation_enabled = True
    settings.google_callback_broker_enabled = True
    settings.google_callback_broker_origin = BROKER
    settings.google_callback_client_id = "invented.apps.googleusercontent.com"
    factory = sessionmaker(registry, expire_on_commit=False)
    commerce = SyntheticCommerce(settings)
    enrollment = EnrollmentService(factory, settings, commerce)
    human = HumanIdentity(settings.clerk_issuer, "user_broker1", "sess_broker1", "owner@example.invalid", "Invented Owner")
    enrollment.profile(human, str(uuid4()), {"expected_revision": 0, "display_name": human.display_name, "title": "Owner"})
    enrollment.practice(human, str(uuid4()), {"expected_revision": enrollment.status(human)["revision"],
        "legal_name": "Invented Broker Practice LLC", "display_name": "Invented Practice", "address_line1": "123 Invented Street",
        "address_line2": "", "city": "Invented City", "region": "NY", "postal_code": "10001", "country": "US",
        "administrative_email": "office@example.invalid", "human_seats": 1, "covered_entity": True})
    enrollment.accept(human, str(uuid4()), {"expected_revision": enrollment.status(human)["revision"], "doc_id": BAA_DOC_ID,
        "version": BAA_VERSION, "sha256": BAA_SHA256, "signature_name": human.display_name, "signature_title": "Owner",
        "accepted": True, "authority_confirmed": True})
    practice = enrollment.status(human)["practice"]["id"]
    box, owner, account = (str(uuid4()) for _ in range(3))
    org = "org_broker1"
    web, api = "https://" + practice + ".staging.cosmas.ai", "https://api." + practice + ".staging.cosmas.ai"
    enrollment.record_workspace(practice, box_id=box, organization_id=org, url=web + "/chief", proof_sha256="1" * 64,
        workspace_api_origin=api, source_commit="2" * 40, image_sha256="3" * 64)
    with factory.begin() as session:
        saved = session.get(Practice, practice)
        saved.subscription_status, saved.stripe_subscription_id = "trialing", "sub_invented"
        saved.billing_verified_at, saved.trial_ends_at = now_utc(), now_utc() + timedelta(days=14)
    box_factory = sessionmaker(engine, expire_on_commit=False)
    with box_factory.begin() as session:
        session.add(BoxContext(id=box, display_name="Invented Practice"))
        session.flush()
        session.add(Principal(id=owner, box_id=box, principal_type="human", display_name=human.display_name))
        session.flush()
        session.add(ExternalIdentity(id=account, box_id=box, principal_id=owner, issuer=human.issuer, subject=human.subject,
            organization_id=org, active=True, reviewed_by="invented", evidence_ref="synthetic:broker"))
    evidence = {"active": True, "member": True, "session_id": human.session_id}
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    class Keys:
        def get_signing_keys(self, refresh):
            return [SimpleNamespace(key_id="broker-key", key=rsa_key.public_key())]
    def clerk(request):
        if "/sessions/" in request.url.path:
            requested_sid = request.url.path.rsplit("/",1)[1]
            return httpx.Response(200, json={"id": requested_sid, "user_id": human.subject,
                "status": "active" if evidence["active"] and requested_sid == evidence["session_id"] else "revoked"})
        if "/memberships" in request.url.path:
            return httpx.Response(200, json={"data": [{"public_user_data": {"user_id": human.subject},
                "organization": {"id": org}}] if evidence["member"] else []})
        return httpx.Response(200, json={"id": human.subject, "primary_email_address_id": "email1",
            "email_addresses": [{"id": "email1", "email_address": human.email, "verification": {"status": "verified"}}]})
    verifier = ClerkEnrollmentVerifier(settings, client=httpx.Client(transport=httpx.MockTransport(clerk)), jwks_client=Keys())
    proofs = []
    for origin in settings.native_authorized_origins:
        scope = NativeWorkspaceScope(practice, box, org, api, web + "/chief", "2" * 40, "3" * 64, human.issuer, origin)
        proofs.append(NativeWorkspaceProof.from_measurement(scope, invented_native_measurement(scope)))
    cases = {}
    case = SimpleNamespace(factory=factory, box_factory=box_factory, practice=practice, box=box, org=org, human=human,
        settings=settings, evidence=evidence, calls=[], relay_calls=[], lost_reply=False, full=False, bad_scope=False,
        registration_status=None, registration_error=None, callback_error=None, relay_status=None,revoke_at=None)
    def token(native=True, **changes):
        now = int(time.time())
        claims = {"iss": human.issuer, "sub": human.subject, "sid": evidence["session_id"], "org_id": org,
            "iat": now, "nbf": now, "exp": now + 300, **({} if native else {"azp": web}), **changes}
        return jwt.encode(claims, rsa_key, algorithm="RS256", headers={"kid": "broker-key"})
    def relay_transport(request):
        case.relay_calls.append(request)
        assert request.url.host == urlsplit(api).hostname
        # HTTP crosses an ownership boundary: capture ContextVars are never sent
        # over the wire. Retain each receiving app's real middleware/fences.
        response = Context().run(cases["box"].request, request.method, request.url.path,
            content=request.content, headers=dict(request.headers))
        case.relay_status = response.status_code
        if case.lost_reply:
            raise httpx.ReadTimeout("synthetic_PRIVATE_lost_reply")
        return httpx.Response(response.status_code, content=response.content, headers=dict(response.headers))
    relay = HttpGoogleRelayPort(client=httpx.Client(transport=httpx.MockTransport(relay_transport)))
    app = create_app(settings, engine=registry, verifier=verifier, commerce=commerce,
        native_workspace_authority=NativeWorkspaceProofRegistry(proofs), google_relay_port=relay)
    central = stack.enter_context(TestClient(app))
    original_register = app.state.google_callback_broker.register
    def inspected_register(*args):
        try:
            return original_register(*args)
        except Exception as error:
            # Test-only, bounded classification; never exception text or inputs.
            case.registration_error = type(error).__name__
            if hasattr(error,"errors"):
                case.registration_error += ":" + str([(item["loc"],item["type"]) for item in error.errors()])
            raise
    app.state.google_callback_broker.register = inspected_register
    original_callback = app.state.google_callback_broker.callback
    def inspected_callback(*args):
        try:
            return original_callback(*args)
        except Exception as error:
            case.callback_error = type(error).__name__
            raise
    app.state.google_callback_broker.callback = inspected_callback
    def registration_transport(request):
        response = Context().run(central.request, request.method, request.url.path,
            content=request.content, headers=dict(request.headers))
        case.registration_status = response.status_code
        return httpx.Response(response.status_code, content=response.content, headers=dict(response.headers))
    runtime = SimpleNamespace(workspace_available=True, workspace_authenticated_enabled=True, auth_mode="clerk_jwt",
        workspace_google_connection_enabled=True, workspace_google_message_enabled=True, workspace_google_calendar_enabled=True,
        workspace_google_message_available=True, workspace_enrollment_managed=True,
        google_connection_broker_enabled=True, google_connection_broker_origin=BROKER, workspace_enrollment_api_origin=BROKER,
        google_connection_client_id=settings.google_callback_client_id, google_connection_client_secret=SecretStr("synthetic_PRIVATE_client"),
        google_connection_encryption_key=SecretStr(base64.urlsafe_b64encode(b"q" * 32).decode()),
        google_connection_callback_uri=BROKER + "/connections/google/callback", google_connection_return_origin=web,
        workspace_enrollment_practice_id=practice, workspace_release_source_commit="2" * 40, workspace_release_image_sha256="3" * 64,
        workspace_enrollment_admission_secret=SecretStr(derive_runtime_admission_key(settings.runtime_admission_secret.get_secret_value(), practice, box, org)),
        cosmas_env="early_adopter_beta", workspace_enabled=True, workspace_hosted_enabled=True,
        workspace_apple_hosted_transport_enabled=True, workspace_desktop_hosted_transport_enabled=True,
        allowed_origins=[web,"capacitor://localhost","app://cosmas"], authorized_parties=[web,"capacitor://localhost","app://cosmas"],
        clerk_issuer=human.issuer, clerk_jwks_url=human.issuer+"/.well-known/jwks.json", clerk_organization_id=org,
        clerk_session_policy="enrollment_default", clerk_audience="", clerk_session_configuration_errors=lambda: [], beta_box_id=box)
    def google(request):
        case.calls.append(request)
        if case.revoke_at == (request.method,"session"):
            evidence["active"] = False
        if case.revoke_at == (request.method,"membership"):
            evidence["member"] = False
        if request.method == "POST":
            grant = SCOPES + " " + CALENDAR_SCOPE + (" " + FULL_MAIL_SCOPE if case.full else "")
            if case.bad_scope:
                grant += " https://www.googleapis.com/auth/gmail.send"
            payload = {"access_token": "synthetic_PRIVATE_access", "refresh_token": "synthetic_PRIVATE_refresh",
                "expires_in": 3600, "token_type": "Bearer", "scope": grant}
        else:
            payload = {"sub": "invented_google", "email": "mail@example.invalid", "email_verified": True}
        return httpx.Response(200, headers={"content-type":"application/json"},
            stream=httpx.ByteStream(json.dumps(payload).encode()))
    box_app = FastAPI()
    registration = HttpGoogleRegistrationPort(runtime, client=httpx.Client(transport=httpx.MockTransport(registration_transport)))
    stack.enter_context(google_connection_lifespan(box_app, runtime, box_factory,
        registration_port=registration, transport=httpx.MockTransport(google)))
    service = box_app.state.google_connection
    box_app.add_middleware(GoogleConnectionBoundary)
    # Isolated Box auth exercises the real RS256/SID/local-binding verifier;
    # the installed central registration enforces actual enrollment admission.
    auth_runtime = SimpleNamespace(**{**vars(runtime), "workspace_enrollment_managed":False})
    jwt_verifiers = {origin:ClerkTokenVerifier(auth_runtime, jwks_client=Keys(), start_background_refresh=False,
        native_origin=origin) for origin in (None,"capacitor://localhost")}
    def request_identity(request: Request):
        origin = native_clerk_origin(runtime,request.headers.getlist("origin"))
        with box_factory() as session:
            return authenticate_request(session,auth_runtime,authorization=request.headers.get("authorization"),
                box_header=None,actor_header=None,verifier=jwt_verifiers[origin])
    box_app.include_router(router(runtime=lambda: service, identity_dependency=request_identity, workspace_gate=lambda: None))
    box_client = stack.enter_context(TestClient(box_app))
    cases["box"] = box_client
    case.central, case.box_client, case.service, case.token = central, box_client, service, token
    case.account = account
    case.broker = app.state.google_callback_broker
    try:
        yield case
    finally:
        stack.close()
        registry.dispose()
        with engine.begin() as connection:
            connection.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))


def start(case, native=True, full=False, **claims):
    case.full = full
    headers = {"Authorization": "Bearer " + case.token(native, **claims), "X-Cosmas-Google-Connection": "1"}
    if native:
        headers["Origin"] = "capacitor://localhost"
    response = case.box_client.post(PATH, json={"action": "start_full_mail" if full else "start"}, headers=headers)
    assert response.status_code == 200, (response.text,case.registration_status,case.registration_error)
    fields = parse_qs(urlsplit(response.json()["authorization_url"]).query)
    assert fields["redirect_uri"] == [BROKER + "/connections/google/callback"]
    return fields["state"][0]


def callback(case, state, code="synthetic_PRIVATE_code"):
    return case.central.get("/connections/google/callback", params={"state": state, "code": code})


@pytest.mark.parametrize("native,full", [(False,False), (True,False), (True,True)])
def test_actual_registered_browser_and_native_consent_uses_box_pkce_and_custody(journey, native, full, caplog):
    c = journey
    state = start(c, native, full)
    response = callback(c, state)
    assert "connection complete" in response.text, (c.callback_error,c.relay_status,[r.method for r in c.calls])
    status = c.box_client.post(PATH, json={"action":"status","include_capabilities":True},
        headers={"X-Cosmas-Google-Connection":"1", "Authorization":"Bearer "+c.token(),"Origin":"capacitor://localhost"})
    assert status.status_code == 200 and status.json()["state"] == "connected"
    assert status.json()["capabilities"] == {"mail":True,"calendar":True}
    assert [r.method for r in c.calls] == ["POST", "GET"]
    fields = parse_qs(c.calls[0].content.decode())
    assert fields["redirect_uri"] == [BROKER + "/connections/google/callback"]
    assert len(fields["code_verifier"][0]) >= 43
    with c.factory() as session:
        row = session.scalar(select(Command).where(Command.operation == "google_callback"))
        saved = json.dumps(row.response)
        assert row.response["phase"] == "complete"
        assert state not in saved and "PRIVATE" not in saved and "verifier" not in saved
    assert "PRIVATE" not in response.text + caplog.text
    assert response.headers["cache-control"] == "no-store" and response.headers["referrer-policy"] == "no-referrer"


def test_lost_relay_reply_is_recovered_without_second_google_exchange(journey):
    c = journey
    state = start(c)
    c.lost_reply = True
    callback(c, state)
    assert len(c.calls) == 2
    c.lost_reply = False
    with c.factory.begin() as session:
        row = session.scalar(select(Command).where(Command.operation == "google_callback"))
        row.response = {**row.response, "lease_until": 0}
    assert "connection complete" in callback(c, state).text
    assert len(c.calls) == 2 and len(c.relay_calls) == 2
    callback(c, state, "synthetic_PRIVATE_swapped_code")
    assert len(c.calls) == 2 and len(c.relay_calls) == 2


@pytest.mark.parametrize("change", ["session", "membership", "destination", "expired", "box", "config", "callback"])
def test_changed_authority_or_scope_blocks_callback_before_box_exchange(journey, change):
    c = journey
    state = start(c)
    if change == "session":
        c.evidence["active"] = False
    elif change == "membership":
        c.evidence["member"] = False
    elif change == "destination":
        with c.factory.begin() as session:
            session.get(Practice,c.practice).workspace_api_origin = "https://app.cosmaneura.com"
    elif change == "expired":
        c.broker.now = lambda: time.time() + 601
    elif change == "box":
        with c.factory.begin() as session:
            session.get(Practice,c.practice).box_id = str(uuid4())
    elif change == "config":
        c.service.settings.google_connection_client_secret = SecretStr("synthetic_PRIVATE_changed")
    else:
        c.settings.google_callback_broker_origin = "https://foreign.example.invalid"
    callback(c, state)
    assert c.calls == []
    assert len(c.relay_calls) == (1 if change == "config" else 0)


def test_disconnect_and_public_box_callback_cannot_bypass_registered_session(journey):
    c = journey
    state = start(c)
    direct = c.box_client.get("/connections/google/callback", params={"state": state, "code": "synthetic_PRIVATE_code"})
    assert direct.status_code == 404 and c.calls == []
    response = c.box_client.post(PATH,json={"action":"disconnect"},
        headers={"X-Cosmas-Google-Connection":"1", "Authorization":"Bearer "+c.token(),"Origin":"capacitor://localhost"})
    assert response.status_code == 200
    callback(c,state)
    assert c.calls == []


def test_write_grants_are_still_rejected_before_google_account_read(journey):
    c = journey
    state = start(c)
    c.bad_scope = True
    assert "connection complete" not in callback(c,state).text
    assert [r.method for r in c.calls] == ["POST"]
    with c.box_factory() as session:
        assert session.get(c.service.Credential,c.account) is None


@pytest.mark.parametrize("change", ["signature", "box_id", "practice_id", "callback_uri"])
def test_valid_shape_swapped_or_unsigned_relay_never_exchanges_google_code(journey, change):
    c = journey
    state = start(c)
    with c.box_factory() as session:
        attempt = session.scalar(select(c.service.Attempt).where(c.service.Attempt.account_id==c.account))
        private = c.service._open(attempt.sealed,"attempt",c.account,attempt.binding_digest,attempt.id)
        data = private["broker"]
    data = {**data,"contract_version":"cosmas-google-relay.v1","nonce":str(uuid4()),"issued_at":int(time.time()),
        "state":state,"code":"synthetic_PRIVATE_code","denied":False}
    if change in {"box_id","practice_id"}:
        data[change] = str(uuid4())
    elif change == "callback_uri":
        data[change] = "https://foreign.example.invalid/connections/google/callback"
    value = Relay.model_validate(data)
    raw = encoded(value)
    key = broker_key(c.service.settings.workspace_enrollment_admission_secret.get_secret_value())
    signature = "0"*64 if change=="signature" else signed(key,raw,"relay",value.nonce)
    response = c.box_client.post(RELAY_PATH,content=raw,headers={"Content-Type":"application/json",BROKER_HEADER:signature})
    assert response.status_code!=200 and c.calls==[]


def test_registration_rejects_replaced_session_before_exposing_consent(journey):
    c = journey
    response = c.box_client.post(PATH,json={"action":"start"},headers={"X-Cosmas-Google-Connection":"1",
        "Authorization":"Bearer "+c.token(sid="sess_other"),"Origin":"capacitor://localhost"})
    assert response.status_code == 503 and "authorization_url" not in response.json()
    assert c.calls == c.relay_calls == []
    with c.factory() as session:
        assert session.scalar(select(Command).where(Command.operation=="google_callback")) is None


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
def test_beta_off_installed_direct_callback_keeps_its_original_redirect(connection):
    c = connection
    app = FastAPI()
    app.add_middleware(GoogleConnectionBoundary)
    app.include_router(router(runtime=lambda:c.service,identity_dependency=lambda:c.identity,workspace_gate=lambda:None))
    state = legacy_start(c)
    with TestClient(app) as client:
        response = client.get("/connections/google/callback",params={"state":state,"code":"synthetic_PRIVATE_code"},
            follow_redirects=False)
        relay = client.post(RELAY_PATH,json={})
    assert response.status_code == 303
    assert response.headers["location"] == c.service.return_origin + "/#google-connected"
    assert response.headers["cache-control"] == "no-store" and c.calls == ["POST","GET"]
    assert relay.status_code == 404 and c.service.broker_enabled is False


def test_exchanging_relay_retry_stays_pending_without_another_token_exchange(journey):
    c = journey
    state = start(c)
    with c.box_factory.begin() as session:
        attempt = session.scalar(select(c.service.Attempt).where(c.service.Attempt.account_id==c.account))
        attempt.status = "exchanging"
    assert "connection complete" not in callback(c,state).text
    with c.factory.begin() as session:
        row = session.scalar(select(Command).where(Command.operation=="google_callback"))
        assert row.response["phase"] == "relaying"
        row.response = {**row.response,"lease_until":0}
    assert "connection complete" not in callback(c,state).text
    assert c.calls == [] and len(c.relay_calls) == 2


def test_sign_out_and_new_verified_session_returns_fresh_consent_without_waiting(journey):
    c = journey
    assert "connection complete" in callback(c,start(c)).text
    with c.box_factory() as session:
        old_credential = session.get(c.service.Credential,c.account).sealed
    stale_state = start(c)
    c.evidence["session_id"] = "sess_reconnected"
    new_state = start(c)
    assert new_state != stale_state
    assert start(c) == new_state  # Same-SID lost-registration-reply retry is stable.
    with c.box_factory() as session:
        assert session.get(c.service.Credential,c.account).sealed == old_credential
    assert "connection complete" not in callback(c,stale_state).text
    assert len(c.calls) == 2
    assert "connection complete" in callback(c,new_state).text
    assert len(c.calls) == 4


@pytest.mark.parametrize("method,authority,expected",[("POST","session",["POST"]),
    ("GET","membership",["POST","GET"])])
def test_authority_revocation_during_provider_io_rejects_before_custody(journey,method,authority,expected):
    c = journey
    state = start(c)
    c.revoke_at = (method,authority)
    assert "connection complete" not in callback(c,state).text
    assert [r.method for r in c.calls] == expected
    with c.box_factory() as session:
        assert session.get(c.service.Credential,c.account) is None
    c.evidence["active"] = c.evidence["member"] = True
    assert "connection complete" not in callback(c,state).text
    assert [r.method for r in c.calls] == expected
