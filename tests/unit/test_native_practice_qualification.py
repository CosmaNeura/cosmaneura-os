"""Actual signed HTTP/local-binding proof; no service, credential or patient data."""

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.api.practice_access_routes import register
from cosmas_os.config import Settings
from cosmas_os.db import Base
from cosmas_os.models import BoxContext, ExternalIdentity, Principal
from cosmas_os.practice_setup_models import PracticeSetupProfile


@pytest.fixture
def native_case(engine):
    # Retain the normal PostgreSQL engine and isolate committed HTTP sessions
    # in a private schema. CaptureBudget deliberately rejects SQLite.
    schema = "native_qualification_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(text('CREATE SCHEMA "' + schema + '"'))
    isolated = create_engine(engine.url, connect_args={"options": "-c search_path=" + schema})
    try:
        yield _native_case(isolated)
    finally:
        isolated.dispose()
        with engine.begin() as connection:
            connection.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))


def _native_case(engine):
    Base.metadata.create_all(engine, tables=[BoxContext.__table__, Principal.__table__,
                                           ExternalIdentity.__table__, PracticeSetupProfile.__table__])
    factory = sessionmaker(engine, autoflush=False)
    values = json.loads((Path(__file__).parents[1] / "fixtures/hosted-workspace-settings.json").read_text())
    values.update(beta_box_id=str(uuid4()), workspace_apple_hosted_transport_enabled=True,
                  cors_allowed_origins="https://workspace.example.invalid,capacitor://localhost",
                  clerk_authorized_parties="https://workspace.example.invalid,capacitor://localhost",
                  workspace_release_source_commit="a" * 40, workspace_release_image_sha256="b" * 64)
    config = Settings(_env_file=None, **values)
    config.validate_runtime_configuration()
    owner_id = str(uuid4())
    with factory() as s:
        s.add(BoxContext(id=config.beta_box_id, display_name="Invented native practice"))
        s.flush()
        s.add(Principal(id=owner_id, box_id=config.beta_box_id, display_name="Invented native owner",
                        principal_type="human", state="active", is_owner=True))
        s.flush()
        s.add(ExternalIdentity(box_id=config.beta_box_id, principal_id=owner_id, provider="clerk",
                              issuer=config.clerk_issuer, organization_id=config.clerk_organization_id,
                              subject="user_native_invented", active=True, reviewed_by="invented",
                              evidence_ref="invented:local-only"))
        s.add(PracticeSetupProfile(box_id=config.beta_box_id, owner_id=owner_id,
                                  display_name="Invented native practice", owner_display_name="Invented owner",
                                  request_key=str(uuid4()), request_sha256="c" * 64))
        s.commit()
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_keys(self, **_):
            return [SimpleNamespace(key_id="native-invented", key=private.public_key())]

    def token(**changes):
        now = int(time.time())
        claims = {"iss": config.clerk_issuer, "sub": "user_native_invented", "org_id": config.clerk_organization_id,
                  "aud": config.clerk_audience, "iat": now, "nbf": now, "exp": now + 120,
                  "sid": "sess_native_invented", **changes}
        return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "native-invented"})

    calls = []
    def unavailable_admission():
        calls.append("central admission")
        raise RuntimeError("invented unavailable central service")

    def verifier(origins):
        return ClerkTokenVerifier(config, jwks_client=Keys(), start_background_refresh=False,
                                  native_origin="capacitor://localhost" if origins == ["capacitor://localhost"] else None)

    app = FastAPI()
    register(app, runtime=lambda: config, verifier=verifier, session_factory=factory,
             admission_adapter=lambda: unavailable_admission() if config.workspace_enrollment_managed else None)
    return SimpleNamespace(app=app, config=config, factory=factory, token=token, calls=calls)


def get(c, path="/practice-access/native-qualification", *, token=None, headers=None):
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=c.app), base_url="http://local") as client:
            h = {"Authorization": "Bearer " + (token or c.token()), "Origin": "capacitor://localhost",
                 "X-Cosmas-Practice-Access-Contract": "1"}
            h.update(headers or {})
            return await client.get(path, headers=h)
    return asyncio.run(exercise())


def test_native_qualification_measures_scoped_session_and_binding_without_admission(native_case):
    c = native_case
    # This is explicitly synthetic derived-key input, never a deployed secret.
    c.config.workspace_enrollment_managed = True
    c.config.workspace_enrollment_practice_id = str(uuid4())
    c.config.workspace_enrollment_api_origin = "https://enrollment.example.invalid"
    c.config.workspace_enrollment_origin_allowlist = "https://enrollment.example.invalid"
    c.config.workspace_enrollment_admission_secret = SecretStr("0" * 64)
    c.config.validate_runtime_configuration()
    response = get(c)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-cosmas-workspace-protocol"] == "1"
    assert response.json() == {"contract_version": 1, "state": "connected", "role": "owner",
        "box_id": c.config.beta_box_id, "organization_id": c.config.clerk_organization_id,
        "issuer": c.config.clerk_issuer, "subject": "user_native_invented",
        "source_commit": "a" * 40, "image_sha256": "b" * 64,
        "native_origin": "capacitor://localhost", "session_id": "sess_native_invented",
        "initial_setup_complete": True}
    assert "enrollment_admission" not in response.json() and c.calls == []


@pytest.mark.parametrize("changes,status", [
    ({"org_id": "org_other"}, 403), ({"sub": "user_unbound"}, 403),
    ({"azp": "https://workspace.example.invalid"}, 401), ({"sid": "bad"}, 401),
    ({"iss": "https://another.example.invalid"}, 401),
])
def test_native_qualification_rejects_wrong_signed_identity(native_case, changes, status):
    c = native_case
    assert get(c, token=c.token(**changes)).status_code == status
    assert c.calls == []


@pytest.mark.parametrize("origin", ["https://workspace.example.invalid", "app://cosmas", "null", ""])
def test_native_qualification_requires_exact_enabled_native_transport(native_case, origin):
    assert get(native_case, headers={"Origin": origin}).status_code == 404


@pytest.mark.parametrize("mutation", ["revoked", "missing_setup", "missing_release", "disabled"])
def test_native_qualification_cannot_create_or_repair_authority(native_case, mutation):
    c = native_case
    if mutation == "disabled":
        c.config.workspace_apple_hosted_transport_enabled = False
    elif mutation == "missing_release":
        c.config.workspace_release_source_commit = ""
    else:
        with c.factory() as s:
            if mutation == "revoked":
                s.scalar(select(ExternalIdentity)).active = False
            else:
                s.delete(s.get(PracticeSetupProfile, c.config.beta_box_id))
            s.commit()
    assert get(c).status_code == (404 if mutation in {"disabled", "missing_release"} else 403)
    assert c.calls == []


def test_browser_qualification_wire_contract_remains_unchanged(native_case):
    c = native_case
    response = get(c, "/practice-access/enrollment-qualification",
                   token=c.token(azp="https://workspace.example.invalid"),
                   headers={"Origin": "https://workspace.example.invalid"})
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"contract_version", "state", "role", "box_id", "organization_id",
                                  "issuer", "subject", "source_commit", "image_sha256"}
    assert "x-cosmas-workspace-protocol" not in response.headers
    assert c.calls == []
