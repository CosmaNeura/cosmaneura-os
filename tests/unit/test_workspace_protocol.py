"""Actual middleware and signed handshake; no database, vendor or identity network I/O."""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from starlette.middleware import Middleware

from cosmas_os.api import app as api
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.api.workspace_protocol import (
    CALLBACKS,
    CONTRACTS,
    WORKSPACE_ROOTS,
    WorkspaceProtocolBoundary,
)
from cosmas_os.config import Settings


@pytest.fixture
def connected(monkeypatch):
    fixture = Path(__file__).parents[1] / "fixtures/hosted-workspace-settings.json"
    config = Settings(_env_file=None, **json.loads(fixture.read_text()))
    config.validate_runtime_configuration()
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_keys(self, **_):
            return [SimpleNamespace(key_id="w84", key=private.public_key())]

    monkeypatch.setattr(api, "settings", config)
    monkeypatch.setattr(api, "_clerk_verifier", lambda native_origin=None: ClerkTokenVerifier(
        config, jwks_client=Keys(), start_background_refresh=False, native_origin=native_origin))
    opened = []

    class NoDatabase:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    def session(_):
        opened.append(True)
        return NoDatabase()

    monkeypatch.setattr(api, "new_capture_session", session)
    middleware = [Middleware(item.cls, *item.args, **{
        **item.kwargs, **({"allow_origins": [config.authorized_parties[0]]} if item.cls is CORSMiddleware else {})
    }) for item in api.app.user_middleware]
    app = FastAPI(middleware=middleware)
    app.exception_handlers.update(api.app.exception_handlers)
    app.include_router(api.app.router)

    @asynccontextmanager
    async def no_service_startup(_app):
        yield

    app.router.lifespan_context = no_service_startup
    dispatched = []

    @app.post("/workspaces/protocol-probe")
    async def probe(request: Request):
        dispatched.append(await request.body())
        return {"observed": True}

    def headers(*, omit=(), **changes):
        now = int(time.time())
        claims = {"iss": config.clerk_issuer, "sub": "user_w84invited", "org_id": config.clerk_organization_id,
                  "aud": config.clerk_audience, "azp": config.authorized_parties[0],
                  "sid": "sess_w84invented", "iat": now, "nbf": now, "exp": now + 120, **changes}
        for claim in omit:
            claims.pop(claim, None)
        return {"Authorization": "Bearer " + jwt.encode(claims, private, algorithm="RS256", headers={"kid": "w84"}),
                "Origin": config.authorized_parties[0], "X-Cosmas-Practice-Access-Contract": "1",
                "X-Cosmas-Draft-Recovery": "2", "X-Cosmas-Workspace-Protocol": "1"}

    with TestClient(app) as client:
        yield SimpleNamespace(client=client, config=config, headers=headers, opened=opened, dispatched=dispatched)


def test_actual_signed_handshake_for_invited_account_without_database_io(connected):
    c = connected
    result = c.client.get("/practice-access/compatibility", headers=c.headers())
    assert result.status_code == 200
    assert result.json() == {"contract_version": 1, "workspace_protocol": 1,
                             "requests_require_protocol": True, "contracts": CONTRACTS}
    assert result.headers["x-cosmas-workspace-protocol"] == "1"
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["access-control-allow-origin"] == c.config.authorized_parties[0]
    assert "X-Cosmas-Workspace-Protocol" in result.headers["access-control-expose-headers"]
    assert c.opened == [True]  # The context was opened; no method is available for database I/O.
    if destination := os.environ.get("W84_HANDSHAKE_RESULT"):
        Path(destination).write_text(json.dumps(result.json(), indent=2) + "\n")


@pytest.mark.parametrize("origin", ["app://cosmas", "capacitor://localhost"])
def test_actual_native_handshake_accepts_session_without_azp_only_for_enabled_origin(connected, origin):
    c = connected
    native_headers = {**c.headers(omit=("azp",)), "Origin": origin}
    assert c.client.get("/practice-access/compatibility", headers=native_headers).status_code == 401
    c.config.workspace_desktop_hosted_transport_enabled = origin == "app://cosmas"
    c.config.workspace_apple_hosted_transport_enabled = origin == "capacitor://localhost"
    c.config.cors_allowed_origins += "," + origin
    c.config.clerk_authorized_parties += "," + origin
    result = c.client.get("/practice-access/compatibility", headers=native_headers)
    assert result.status_code == 200
    assert result.json()["workspace_protocol"] == 1
    for invalid in [{**native_headers, "Origin": c.config.authorized_parties[0]},
        {**native_headers, "Origin": "null"},
        {key: value for key, value in native_headers.items() if key != "Origin"},
        {**c.headers(azp=c.config.authorized_parties[0]), "Origin": origin}]:
        assert c.client.get("/practice-access/compatibility", headers=invalid).status_code == 401
    duplicate = [*native_headers.items(), ("Origin", origin)]
    assert c.client.get("/practice-access/compatibility", headers=duplicate).status_code == 401


def test_handshake_retains_authentication_and_closed_request_contract(connected):
    c = connected
    for claims in [{"exp": int(time.time()) - 60}, {"org_id": "org_elsewhere"}]:
        assert c.client.get("/practice-access/compatibility", headers=c.headers(**claims)).status_code in {401, 403}
    assert c.client.get("/practice-access/compatibility?subject=user_elsewhere", headers=c.headers()).status_code == 422
    assert c.client.post("/practice-access/compatibility", headers=c.headers(), json={}).status_code == 405
    assert c.opened == []


def test_missing_duplicate_and_future_protocols_stop_real_stack_before_dispatch(connected):
    c = connected
    for protocol in [None, "0", "2", "1, 1"]:
        headers = c.headers()
        if protocol is None:
            del headers["X-Cosmas-Workspace-Protocol"]
        else:
            headers["X-Cosmas-Workspace-Protocol"] = protocol
        reply = c.client.post("/workspaces/protocol-probe", headers=headers, content=b"unread")
        assert reply.status_code == 426
        assert reply.json() == {"detail": "workspace_protocol_required"}
        assert reply.headers["access-control-allow-origin"] == c.config.authorized_parties[0]
    assert c.dispatched == [] and c.opened == []
    assert c.client.post("/workspaces/protocol-probe", headers=c.headers(), content=b"current").status_code == 200
    assert c.dispatched == [b"current"]


def test_every_workspace_family_is_fenced_without_consuming_request_body():
    called = []

    async def inner(*_):
        called.append(True)

    async def receive():
        pytest.fail("Protocol refusal must precede request body reads")

    async def check():
        for root in WORKSPACE_ROOTS:
            for suffix in ["", "/child"]:
                messages = []

                async def send(message, output=messages):
                    output.append(message)

                scope = {"type": "http", "path": "/" + root + suffix, "method": "POST", "headers": []}
                await WorkspaceProtocolBoundary(inner, lambda: SimpleNamespace(
                    workspace_hosted_enabled=True, workspace_draft_recovery_required=True))(scope, receive, send)
                assert messages[0]["status"] == 426
        assert not called
    asyncio.run(check())


def test_callbacks_health_and_legacy_profiles_retain_their_contracts(connected):
    c = connected
    assert c.client.get("/health").status_code == 200
    for callback in CALLBACKS:
        assert c.client.get(callback).status_code == 404  # Provider is not installed in this test app.
        assert c.client.post(callback, json={}).status_code == 426
    for event in ["/vendor-events/documo/00000000-0000-4000-8000-000000000084", "/finance-events/stripe/00000000-0000-4000-8000-000000000084"]:
        assert c.client.post(event, json={}).status_code != 426
    c.config.workspace_draft_recovery_required = False
    assert c.client.post("/workspaces/protocol-probe", content=b"legacy").status_code == 200
    assert c.dispatched == [b"legacy"]


def test_operational_preflight_admits_protocol_header(connected):
    c = connected
    reply = c.client.options("/practice-access/compatibility", headers={
        "Origin": c.config.authorized_parties[0], "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "Authorization,X-Cosmas-Practice-Access-Contract,X-Cosmas-Workspace-Protocol",
    })
    assert reply.status_code == 200
    assert "x-cosmas-workspace-protocol" in reply.headers["access-control-allow-headers"].lower()
    assert not c.opened and not c.dispatched
