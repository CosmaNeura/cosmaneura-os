"""Owned PostgreSQL and actual ASGI routes with invented signed Clerk contracts.

No real Clerk account or endpoint is used. The existing standalone qualification
database marker is required; this never touches the retained offline app database.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.integration import test_standalone_practice as owned

from cosmas_os.api import app as api
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.application.standalone_practice import (
    StandalonePracticeManifest,
    reserve_standalone_practice,
    seed_standalone_practice,
)
from cosmas_os.models import CoreCaptureAccount, ExternalIdentity, Principal, Ticket

case = owned.case


@pytest.mark.parametrize("policy", ["audience", "shared_staging"])
@pytest.mark.parametrize("origin", ["https://workspace.invented-cosmabot.test", "capacitor://localhost", "app://cosmas"])
def test_selected_clerk_policy_owns_new_practice_and_notebook_without_external_io(case, monkeypatch, policy, origin):
    c = case
    issuer = ("https://identity.invented-cosmabot.test" if policy == "audience"
              else "https://invented-cosmabot.clerk.accounts.dev")
    origins = "https://workspace.invented-cosmabot.test" + ("," + origin if origin.startswith(("app:", "capacitor:")) else "")
    c.config = c.config.model_copy(update={
        "cosmas_env": "standalone_clerk_synthetic", "standalone_jwks_path": "",
        "standalone_clerk_issuer_allowlist": issuer, "workspace_hosted_enabled": True,
        "workspace_apple_hosted_transport_enabled": origin == "capacitor://localhost",
        "workspace_desktop_hosted_transport_enabled": origin == "app://cosmas",
        "clerk_issuer": issuer, "clerk_jwks_url": issuer + "/.well-known/jwks.json",
        "clerk_session_policy": policy,
        "clerk_audience": "invented-practice-app-api" if policy == "audience" else "",
        "clerk_organization_id": "org_invented_clerk_practice",
        "clerk_authorized_parties": origins, "cors_allowed_origins": origins,
    })
    c.config.validate_runtime_configuration()
    manifest = c.manifest.model_dump(mode="json")
    manifest["identity"].update(clerk_issuer=issuer, clerk_organization_id=c.config.clerk_organization_id)
    c.manifest = StandalonePracticeManifest.model_validate(manifest)
    first = reserve_standalone_practice(c.session, c.config, c.manifest)
    assert first["phase"] == "reserved"
    assert c.session.scalar(select(func.count()).select_from(Principal)) == 0

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_keys(self, **_):
            return [SimpleNamespace(key_id="invented-clerk-key", key=private.public_key())]

    class Borrowed:
        def __enter__(self):
            return c.session

        def __exit__(self, *_):
            pass

    def session_dependency():
        yield c.session

    def token(subject):
        now = datetime.now(UTC)
        claims = {"iss": issuer, "sub": subject, "org_id": c.config.clerk_organization_id,
            "sid": "sess_invented_clerk_practice", "iat": now, "nbf": now,
            "exp": now + timedelta(minutes=5), "email": "invented-same-address@example.invalid"}
        if policy == "audience":
            claims["aud"] = c.config.clerk_audience
        if origin.startswith("https:"):
            claims["azp"] = origin
        return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "invented-clerk-key"})

    monkeypatch.setattr(api, "settings", c.config)
    monkeypatch.setattr(api, "new_capture_session", lambda *_: Borrowed())
    monkeypatch.setattr(api, "_clerk_verifier", lambda native_origin=None: ClerkTokenVerifier(
        c.config, jwks_client=Keys(), start_background_refresh=False, native_origin=native_origin))
    previous = api.app.dependency_overrides.copy()
    api.app.dependency_overrides[api.get_session] = session_dependency
    headers = {"Authorization": "Bearer " + token(c.manifest.identity.clerk_subject), "Origin": origin,
        "X-Cosmas-Workspace-Protocol": "1", "X-Cosmas-Draft-Recovery": "2",
        "X-Cosmas-Practice-Access-Contract": "1", "X-Cosmas-Team-Contract": "2"}
    client = TestClient(api.app)
    try:
        compatible = client.get("/practice-access/compatibility", headers=headers)
        assert compatible.status_code == 200 and compatible.json()["requests_require_protocol"]
        command = {"idempotency_key": str(uuid4()), "practice_name": c.manifest.identity.clinic_display_name,
                   "display_name": c.manifest.identity.owner_display_name, "confirm": True}
        wrong = client.post("/practice-access/setup/complete", json=command,
            headers={**headers, "Authorization": "Bearer " + token("user_invented_wrong_owner")})
        assert wrong.status_code == 403
        assert c.session.scalar(select(func.count()).select_from(ExternalIdentity)) == 0
        setup = client.post("/practice-access/setup/complete", json=command, headers=headers)
        assert setup.status_code == 200 and setup.json()["state"] == "owner_ready"
        seed_standalone_practice(c.session, c.config, c.manifest)
        identity = client.get("/provider-team/identity", headers=headers)
        assert identity.status_code == 200 and identity.json()["box_id"] == str(c.manifest.identity.box_id)
        catalog = client.get("/workspaces", headers=headers)
        assert catalog.status_code == 200 and len(catalog.json()) == 2
        opened = client.post("/workspaces", headers=headers, json={
            "appointment_id": str(c.manifest.appointments[0].id), "idempotency_key": "clerk-owned-visit"})
        assert opened.status_code == 200 and opened.json()["entries"] == []
        path = "/workspaces/" + opened.json()["id"]
        saved = client.post(path + "/entries", headers=headers, json={"expected_revision": 1,
            "idempotency_key": "clerk-owned-draft", "kind": "conversation", "content": "Invented own-practice draft"})
        assert saved.status_code == 200
        assert client.get(path, headers=headers).json()["entries"] == saved.json()["workspace"]["entries"]
        assert client.post("/chase/open", headers=headers, json={}).status_code == 403
        assert client.post("/practice-access/invitations", headers=headers, json={}).status_code == 403
        assert c.session.scalar(select(func.count()).select_from(CoreCaptureAccount)) == 0
        assert c.session.scalar(select(func.count()).select_from(Ticket)) == 0
        assert c.calls == []
    finally:
        client.close()
        api.app.dependency_overrides = previous
